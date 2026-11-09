"""Core data types shared by the parser, the storage layer and the analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Outcome(str, Enum):
    """Final outcome of a single test case in a single run."""

    PASSED = "passed"
    FAILED = "failed"  # an assertion failed
    ERROR = "error"  # the test crashed / raised an unexpected exception
    SKIPPED = "skipped"

    @property
    def is_failure(self) -> bool:
        """Failures and errors both mean "the test did not pass"."""
        return self in (Outcome.FAILED, Outcome.ERROR)


@dataclass(frozen=True)
class CaseResult:
    """One test case as it appeared in one report.

    ``test_id`` is a stable identifier built from the JUnit ``classname`` and
    ``name`` attributes, e.g. ``tests.test_cart::test_add_item``.
    """

    test_id: str
    outcome: Outcome
    duration: float = 0.0
    message: str | None = None


@dataclass(frozen=True)
class HistoryRow:
    """A stored result joined with information about the run it belongs to."""

    test_id: str
    run_id: int
    outcome: Outcome
    duration: float
    message: str | None
    commit: str | None
    branch: str | None
    imported_at: str


@dataclass(frozen=True)
class RunInfo:
    """Summary of one imported report."""

    id: int
    imported_at: str
    source: str
    commit: str | None
    branch: str | None
    total: int
    failures: int
