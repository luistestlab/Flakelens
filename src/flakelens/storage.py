"""SQLite persistence for imported test runs.

Each imported report becomes one row in ``runs`` and one row per test case
in ``results``. Runs are ordered by their auto-increment id, i.e. by import
order, which the analysis treats as chronological order.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from flakelens.models import CaseResult, HistoryRow, Outcome, RunInfo

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at  TEXT NOT NULL,
    source       TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    commit_sha   TEXT,
    branch       TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    test_id  TEXT NOT NULL,
    outcome  TEXT NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    message  TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_test_id ON results(test_id);
CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id);
"""


class Database:
    """Thin wrapper around a SQLite connection.

    Use it as a context manager so the connection is always closed::

        with Database("flakelens.db") as db:
            db.add_run(results, source="report.xml", content_hash="...")
    """

    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def add_run(
        self,
        results: Iterable[CaseResult],
        *,
        source: str,
        content_hash: str,
        commit: str | None = None,
        branch: str | None = None,
        imported_at: str | None = None,
    ) -> int | None:
        """Store one run and its results.

        Returns the new run id, or ``None`` if a report with the same content
        hash was already imported (importing the same file twice would
        silently inflate the statistics).
        """
        imported_at = imported_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        try:
            with self._conn:  # one transaction: all or nothing
                cursor = self._conn.execute(
                    "INSERT INTO runs (imported_at, source, content_hash, commit_sha, branch) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (imported_at, source, content_hash, commit, branch),
                )
                run_id = cursor.lastrowid
                self._conn.executemany(
                    "INSERT INTO results (run_id, test_id, outcome, duration, message) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (run_id, r.test_id, r.outcome.value, r.duration, r.message)
                        for r in results
                    ],
                )
        except sqlite3.IntegrityError:
            if self._hash_exists(content_hash):
                return None
            raise
        return run_id

    def _hash_exists(self, content_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM runs WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return row is not None

    def list_runs(self) -> list[RunInfo]:
        rows = self._conn.execute(
            """
            SELECT runs.id, runs.imported_at, runs.source, runs.commit_sha, runs.branch,
                   COUNT(results.id) AS total,
                   COALESCE(SUM(CASE WHEN results.outcome IN ('failed', 'error')
                                     THEN 1 ELSE 0 END), 0) AS failures
            FROM runs
            LEFT JOIN results ON results.run_id = runs.id
            GROUP BY runs.id
            ORDER BY runs.id
            """
        ).fetchall()
        return [
            RunInfo(
                id=row["id"],
                imported_at=row["imported_at"],
                source=row["source"],
                commit=row["commit_sha"],
                branch=row["branch"],
                total=row["total"],
                failures=row["failures"],
            )
            for row in rows
        ]

    def history(
        self, *, test_id: str | None = None, branch: str | None = None
    ) -> list[HistoryRow]:
        """Return stored results ordered by test, then chronologically."""
        conditions: list[str] = []
        params: list[str] = []
        if test_id is not None:
            conditions.append("results.test_id = ?")
            params.append(test_id)
        if branch is not None:
            conditions.append("runs.branch = ?")
            params.append(branch)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self._conn.execute(
            f"""
            SELECT results.test_id, results.run_id, results.outcome, results.duration,
                   results.message, runs.commit_sha, runs.branch, runs.imported_at
            FROM results
            JOIN runs ON runs.id = results.run_id
            {where}
            ORDER BY results.test_id, results.run_id, results.id
            """,
            params,
        ).fetchall()
        return [
            HistoryRow(
                test_id=row["test_id"],
                run_id=row["run_id"],
                outcome=Outcome(row["outcome"]),
                duration=row["duration"],
                message=row["message"],
                commit=row["commit_sha"],
                branch=row["branch"],
                imported_at=row["imported_at"],
            )
            for row in rows
        ]

    def find_test_ids(self, fragment: str) -> list[str]:
        """Return distinct test ids containing ``fragment`` (case-insensitive)."""
        rows = self._conn.execute(
            "SELECT DISTINCT test_id FROM results WHERE test_id LIKE ? ESCAPE '\\' "
            "ORDER BY test_id",
            (f"%{_escape_like(fragment)}%",),
        ).fetchall()
        return [row["test_id"] for row in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
