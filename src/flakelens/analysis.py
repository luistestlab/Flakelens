"""Classify tests as flaky, broken or stable based on their run history.

The heuristic, in order:

1. **Same-code conflict** - the test both passed and failed for the same
   commit (or inside the same run, e.g. after a retry). The code did not
   change, so the test is flaky. This is the strongest signal and needs no
   minimum number of runs.
2. **Not enough data** - fewer than ``min_runs`` executed (non-skipped) runs.
3. **Flips** - a "flip" is a change between pass and fail in consecutive
   runs. One flip is just a regression (pass -> fail) or a fix
   (fail -> pass). Two or more flips (pass -> fail -> pass ...) mean the
   test keeps changing its mind: flaky.
4. Otherwise the test is **broken** if its latest executed run failed, and
   **stable** if it passed.

Skipped runs are ignored for every rule above.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from flakelens.models import HistoryRow, Outcome

DEFAULT_MIN_RUNS = 3
FLAKY_FLIP_THRESHOLD = 2


class Status(str, Enum):
    FLAKY = "flaky"
    BROKEN = "broken"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient"
    SKIPPED = "skipped"


# Order used when sorting a report: most actionable first.
_STATUS_PRIORITY = {
    Status.FLAKY: 0,
    Status.BROKEN: 1,
    Status.INSUFFICIENT_DATA: 2,
    Status.STABLE: 3,
    Status.SKIPPED: 4,
}


@dataclass(frozen=True)
class FlakeStats:
    test_id: str
    status: Status
    executed: int  # runs where the test actually ran (not skipped)
    passes: int
    failures: int
    skips: int
    flips: int
    same_code_conflicts: int
    last_outcome: Outcome | None

    @property
    def fail_rate(self) -> float:
        return self.failures / self.executed if self.executed else 0.0

    @property
    def flip_rate(self) -> float:
        """Share of consecutive run pairs where the outcome changed (0..1)."""
        return self.flips / (self.executed - 1) if self.executed > 1 else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "status": self.status.value,
            "executed": self.executed,
            "passes": self.passes,
            "failures": self.failures,
            "skips": self.skips,
            "flips": self.flips,
            "same_code_conflicts": self.same_code_conflicts,
            "fail_rate": round(self.fail_rate, 4),
            "flip_rate": round(self.flip_rate, 4),
            "last_outcome": self.last_outcome.value if self.last_outcome else None,
        }


def compute_stats(
    test_id: str, rows: Sequence[HistoryRow], min_runs: int = DEFAULT_MIN_RUNS
) -> FlakeStats:
    """Compute statistics for one test. ``rows`` must be in chronological order."""
    executed = [row for row in rows if row.outcome is not Outcome.SKIPPED]
    failures = sum(1 for row in executed if row.outcome.is_failure)
    passes = len(executed) - failures

    flips = sum(
        1
        for previous, current in zip(executed, executed[1:])
        if previous.outcome.is_failure != current.outcome.is_failure
    )

    # Group outcomes by "same code": the commit if known, otherwise the run.
    outcomes_by_code: dict[tuple[str, object], set[bool]] = {}
    for row in executed:
        key = ("commit", row.commit) if row.commit else ("run", row.run_id)
        outcomes_by_code.setdefault(key, set()).add(row.outcome.is_failure)
    same_code_conflicts = sum(1 for seen in outcomes_by_code.values() if len(seen) == 2)

    last_outcome = executed[-1].outcome if executed else None

    if not executed:
        status = Status.SKIPPED
    elif same_code_conflicts > 0:
        status = Status.FLAKY
    elif len(executed) < min_runs:
        status = Status.INSUFFICIENT_DATA
    elif flips >= FLAKY_FLIP_THRESHOLD:
        status = Status.FLAKY
    elif last_outcome is not None and last_outcome.is_failure:
        status = Status.BROKEN
    else:
        status = Status.STABLE

    return FlakeStats(
        test_id=test_id,
        status=status,
        executed=len(executed),
        passes=passes,
        failures=failures,
        skips=len(rows) - len(executed),
        flips=flips,
        same_code_conflicts=same_code_conflicts,
        last_outcome=last_outcome,
    )


def analyze(
    rows: Iterable[HistoryRow], min_runs: int = DEFAULT_MIN_RUNS
) -> list[FlakeStats]:
    """Analyze every test in ``rows`` and return them most-actionable first.

    ``rows`` must be ordered chronologically within each test (this is what
    :meth:`flakelens.storage.Database.history` returns).
    """
    if min_runs < 1:
        raise ValueError("min_runs must be at least 1")

    by_test: dict[str, list[HistoryRow]] = {}
    for row in rows:
        by_test.setdefault(row.test_id, []).append(row)

    stats = [compute_stats(test_id, history, min_runs) for test_id, history in by_test.items()]
    stats.sort(
        key=lambda s: (_STATUS_PRIORITY[s.status], -s.flip_rate, -s.fail_rate, s.test_id)
    )
    return stats
