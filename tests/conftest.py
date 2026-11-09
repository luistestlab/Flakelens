from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

# Outcome shorthand used by the helpers: "p" passed, "f" failed, "e" error, "s" skipped.
_CASE_BODY = {
    "p": "",
    "f": '<failure message="assert 1 == 2">Traceback...</failure>',
    "e": '<error message="ConnectionError: timeout">Traceback...</error>',
    "s": '<skipped message="not supported"/>',
}


def junit_xml(cases: dict[str, str], suite: str = "suite") -> str:
    """Build a small JUnit XML report.

    ``cases`` maps ``"classname::name"`` to an outcome letter (p/f/e/s).
    """
    body = []
    for test_id, outcome in cases.items():
        classname, _, name = test_id.rpartition("::")
        body.append(
            f'<testcase classname="{classname}" name="{name}" time="0.1">'
            f"{_CASE_BODY[outcome]}</testcase>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites><testsuite name="{suite}">{"".join(body)}</testsuite></testsuites>'
    )


@pytest.fixture
def write_report(tmp_path: Path) -> Callable[..., Path]:
    """Write a JUnit report into tmp_path and return its path."""
    counter = iter(range(1, 10_000))

    def _write(cases: dict[str, str], name: str | None = None) -> Path:
        path = tmp_path / "reports" / (name or f"run-{next(counter):03d}.xml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(junit_xml(cases, suite=path.stem), encoding="utf-8")
        return path

    return _write
