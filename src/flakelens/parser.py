"""Parse JUnit XML reports into :class:`CaseResult` objects.

JUnit XML is the de-facto interchange format for test results: pytest
(``--junitxml``), Jest (jest-junit), Cypress, Playwright, Maven Surefire,
Gradle and most CI systems can produce it. There is no single official
schema, so this parser is deliberately tolerant:

* the root element may be ``<testsuites>`` or a single ``<testsuite>``;
* suites may be nested;
* ``classname`` and ``time`` are optional.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from flakelens.models import CaseResult, Outcome

MAX_MESSAGE_LENGTH = 500

_FAILURE_TAGS = {"failure": Outcome.FAILED, "error": Outcome.ERROR}


class ReportParseError(Exception):
    """Raised when a file is not a usable JUnit XML report."""


def parse_junit_file(path: str | Path) -> list[CaseResult]:
    """Parse the JUnit XML report stored at ``path``."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReportParseError(f"{path}: cannot read file ({exc.strerror})") from exc
    return parse_junit_bytes(data, source=str(path))


def parse_junit_bytes(data: bytes, source: str = "<report>") -> list[CaseResult]:
    """Parse a JUnit XML report from raw bytes.

    ``source`` is only used to produce helpful error messages.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ReportParseError(f"{source}: invalid XML ({exc})") from exc

    if root.tag not in ("testsuites", "testsuite"):
        raise ReportParseError(
            f"{source}: expected <testsuites> or <testsuite> as root element, "
            f"found <{root.tag}>"
        )

    return [_parse_case(case, source) for case in root.iter("testcase")]


def _parse_case(case: ET.Element, source: str) -> CaseResult:
    name = (case.get("name") or "").strip()
    if not name:
        raise ReportParseError(f"{source}: found a <testcase> without a name")

    classname = (case.get("classname") or "").strip()
    test_id = f"{classname}::{name}" if classname else name

    outcome = Outcome.PASSED
    message: str | None = None
    for child in case:
        if child.tag in _FAILURE_TAGS:
            # A failure/error always wins, even if a <skipped> was also present.
            outcome = _FAILURE_TAGS[child.tag]
            message = _extract_message(child)
            break
        if child.tag == "skipped":
            outcome = Outcome.SKIPPED
            message = _extract_message(child)

    return CaseResult(
        test_id=test_id,
        outcome=outcome,
        duration=_parse_duration(case.get("time")),
        message=message,
    )


def _extract_message(element: ET.Element) -> str | None:
    """Return a short, single-line description of a failure or skip."""
    text = element.get("message") or element.text or ""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    first_line = lines[0]
    if len(first_line) > MAX_MESSAGE_LENGTH:
        first_line = first_line[: MAX_MESSAGE_LENGTH - 3] + "..."
    return first_line


def _parse_duration(raw: str | None) -> float:
    """Parse the ``time`` attribute (seconds). Bad or missing values become 0."""
    if not raw:
        return 0.0
    try:
        # Some reporters format large numbers with thousands separators.
        value = float(raw.replace(",", ""))
    except ValueError:
        return 0.0
    return max(value, 0.0)
