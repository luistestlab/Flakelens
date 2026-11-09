"""Command-line interface.

    flakelens import REPORT... [--commit SHA] [--branch NAME]
    flakelens report [--min-runs N] [--status ...] [--format table|json] [--fail-on-flaky]
    flakelens history TEST
    flakelens runs
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from flakelens import __version__
from flakelens.analysis import DEFAULT_MIN_RUNS, FlakeStats, Status, analyze
from flakelens.parser import ReportParseError, parse_junit_bytes
from flakelens.storage import Database

DEFAULT_DB_PATH = Path(".flakelens") / "flakelens.db"
DB_ENV_VAR = "FLAKELENS_DB"

EXIT_OK = 0
EXIT_FLAKY_FOUND = 1
EXIT_USAGE_ERROR = 2

MAX_TEST_ID_WIDTH = 70

_STATUS_FILTERS = {
    "problems": {Status.FLAKY, Status.BROKEN},
    "all": set(Status),
    **{status.value: {status} for status in Status},
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    db_path = args.db or os.environ.get(DB_ENV_VAR) or DEFAULT_DB_PATH
    with Database(db_path) as db:
        return args.handler(args, db)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flakelens",
        description="Find flaky tests by analyzing the history of your JUnit XML reports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--db",
        help=f"path to the SQLite database (default: ${DB_ENV_VAR} or {DEFAULT_DB_PATH})",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_import = sub.add_parser("import", help="import one or more JUnit XML reports")
    p_import.add_argument(
        "reports",
        nargs="+",
        help="report files, directories (all *.xml inside) or glob patterns",
    )
    p_import.add_argument("--commit", help="commit SHA the reports were produced from")
    p_import.add_argument("--branch", help="branch the reports were produced from")
    p_import.set_defaults(handler=_cmd_import)

    p_report = sub.add_parser("report", help="show flaky and broken tests")
    p_report.add_argument(
        "--min-runs",
        type=_positive_int,
        default=DEFAULT_MIN_RUNS,
        help=f"runs needed before judging a test (default: {DEFAULT_MIN_RUNS})",
    )
    p_report.add_argument(
        "--status",
        choices=sorted(_STATUS_FILTERS),
        default="problems",
        help="which tests to list (default: problems = flaky + broken)",
    )
    p_report.add_argument("--branch", help="only consider runs from this branch")
    p_report.add_argument("--limit", type=_positive_int, help="show at most N tests")
    p_report.add_argument("--format", choices=["table", "json"], default="table")
    p_report.add_argument(
        "--fail-on-flaky",
        action="store_true",
        help=f"exit with code {EXIT_FLAKY_FOUND} if any flaky test is found (for CI)",
    )
    p_report.set_defaults(handler=_cmd_report)

    p_history = sub.add_parser("history", help="show every recorded result of one test")
    p_history.add_argument("test", help="full test id, or a unique part of it")
    p_history.set_defaults(handler=_cmd_history)

    p_runs = sub.add_parser("runs", help="list imported runs")
    p_runs.set_defaults(handler=_cmd_runs)

    return parser


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {raw!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


# --------------------------------------------------------------------------- import


def _cmd_import(args: argparse.Namespace, db: Database) -> int:
    paths, missing = _expand_report_paths(args.reports)
    exit_code = EXIT_OK
    for pattern in missing:
        _error(f"no report found matching {pattern!r}")
        exit_code = EXIT_USAGE_ERROR

    imported = skipped = 0
    for path in paths:
        try:
            data = path.read_bytes()
            results = parse_junit_bytes(data, source=str(path))
        except OSError as exc:
            _error(f"{path}: cannot read file ({exc.strerror})")
            exit_code = EXIT_USAGE_ERROR
            continue
        except ReportParseError as exc:
            _error(str(exc))
            exit_code = EXIT_USAGE_ERROR
            continue

        run_id = db.add_run(
            results,
            source=str(path),
            content_hash=hashlib.sha256(data).hexdigest(),
            commit=args.commit,
            branch=args.branch,
        )
        if run_id is None:
            print(f"skipped  {path} (already imported)")
            skipped += 1
        else:
            print(f"imported {path} as run #{run_id} ({len(results)} tests)")
            imported += 1

    print(f"\n{imported} report(s) imported, {skipped} skipped as duplicates.")
    return exit_code


def _expand_report_paths(patterns: Sequence[str]) -> tuple[list[Path], list[str]]:
    """Turn files, directories and glob patterns into a list of report paths.

    Globs are expanded here because Windows shells do not expand them.
    """
    found: list[Path] = []
    missing: list[str] = []
    for pattern in patterns:
        path = Path(pattern)
        if path.is_dir():
            matches = sorted(p for p in path.glob("*.xml") if p.is_file())
        elif path.is_file():
            matches = [path]
        else:
            matches = sorted(Path(p) for p in glob.glob(pattern) if Path(p).is_file())
        if matches:
            found.extend(matches)
        else:
            missing.append(pattern)
    return found, missing


# --------------------------------------------------------------------------- report


def _cmd_report(args: argparse.Namespace, db: Database) -> int:
    all_stats = analyze(db.history(branch=args.branch), min_runs=args.min_runs)
    wanted = _STATUS_FILTERS[args.status]
    selected = [s for s in all_stats if s.status in wanted]
    if args.limit:
        selected = selected[: args.limit]

    if args.format == "json":
        print(json.dumps([s.to_dict() for s in selected], indent=2))
    else:
        _print_report_table(all_stats, selected)

    has_flaky = any(s.status is Status.FLAKY for s in all_stats)
    return EXIT_FLAKY_FOUND if args.fail_on_flaky and has_flaky else EXIT_OK


def _print_report_table(all_stats: list[FlakeStats], selected: list[FlakeStats]) -> None:
    if not all_stats:
        print("No test results yet. Import reports first: flakelens import <report.xml>")
        return

    counts = Counter(s.status for s in all_stats)
    summary = ", ".join(f"{counts[status]} {status.value}" for status in Status if counts[status])
    print(f"{len(all_stats)} tests analyzed: {summary}\n")

    if not selected:
        print("No tests match the selected status.")
        return

    rows = [
        [
            s.status.value.upper(),
            f"{s.flip_rate:.0%}",
            f"{s.fail_rate:.0%}",
            f"{s.failures}/{s.executed}",
            _truncate(s.test_id, MAX_TEST_ID_WIDTH),
        ]
        for s in selected
    ]
    _print_table(["STATUS", "FLIP", "FAIL", "FAILED/RUNS", "TEST"], rows)


# --------------------------------------------------------------------------- history


def _cmd_history(args: argparse.Namespace, db: Database) -> int:
    test_id = _resolve_test_id(db, args.test)
    if test_id is None:
        return EXIT_USAGE_ERROR

    rows = db.history(test_id=test_id)
    print(f"History of {test_id}\n")
    _print_table(
        ["RUN", "IMPORTED AT", "COMMIT", "OUTCOME", "TIME", "MESSAGE"],
        [
            [
                f"#{row.run_id}",
                row.imported_at,
                (row.commit or "-")[:10],
                row.outcome.value,
                f"{row.duration:.2f}s",
                _truncate(row.message or "", 60),
            ]
            for row in rows
        ],
    )
    return EXIT_OK


def _resolve_test_id(db: Database, query: str) -> str | None:
    """Accept either an exact test id or a fragment matching exactly one test."""
    candidates = db.find_test_ids(query)
    if query in candidates:
        return query
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        _error(f"no test matches {query!r}")
    else:
        _error(f"{query!r} matches {len(candidates)} tests, be more specific:")
        for candidate in candidates[:10]:
            print(f"  {candidate}", file=sys.stderr)
    return None


# --------------------------------------------------------------------------- runs


def _cmd_runs(args: argparse.Namespace, db: Database) -> int:
    runs = db.list_runs()
    if not runs:
        print("No runs imported yet.")
        return EXIT_OK
    _print_table(
        ["RUN", "IMPORTED AT", "COMMIT", "BRANCH", "TESTS", "FAILED", "SOURCE"],
        [
            [
                f"#{run.id}",
                run.imported_at,
                (run.commit or "-")[:10],
                run.branch or "-",
                str(run.total),
                str(run.failures),
                run.source,
            ]
            for run in runs
        ],
    )
    return EXIT_OK


# --------------------------------------------------------------------------- helpers


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(cell) for cell in column) for column in zip(headers, *rows)]

    def fmt(cells: list[str]) -> str:
        return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()

    print(fmt(headers))
    print(fmt(["-" * width for width in widths]))
    for row in rows:
        print(fmt(row))


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
