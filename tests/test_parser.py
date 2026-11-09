import pytest

from flakelens.models import Outcome
from flakelens.parser import ReportParseError, parse_junit_bytes, parse_junit_file


def parse(xml: str):
    return parse_junit_bytes(xml.encode("utf-8"))


def test_parses_all_outcomes():
    results = parse(
        """
        <testsuites>
          <testsuite name="s">
            <testcase classname="tests.test_a" name="test_pass" time="0.5"/>
            <testcase classname="tests.test_a" name="test_fail" time="1.0">
              <failure message="assert False">trace</failure>
            </testcase>
            <testcase classname="tests.test_a" name="test_error">
              <error>RuntimeError: boom
              more trace</error>
            </testcase>
            <testcase classname="tests.test_a" name="test_skip">
              <skipped message="flaky on windows"/>
            </testcase>
          </testsuite>
        </testsuites>
        """
    )
    assert [(r.test_id, r.outcome) for r in results] == [
        ("tests.test_a::test_pass", Outcome.PASSED),
        ("tests.test_a::test_fail", Outcome.FAILED),
        ("tests.test_a::test_error", Outcome.ERROR),
        ("tests.test_a::test_skip", Outcome.SKIPPED),
    ]
    assert results[0].duration == 0.5
    assert results[1].message == "assert False"
    # Without a message attribute, the first line of the element text is used.
    assert results[2].message == "RuntimeError: boom"
    assert results[3].message == "flaky on windows"


def test_accepts_single_testsuite_root_and_nested_suites():
    results = parse(
        """
        <testsuite name="outer">
          <testcase classname="a" name="one"/>
          <testsuite name="inner">
            <testcase classname="b" name="two"/>
          </testsuite>
        </testsuite>
        """
    )
    assert [r.test_id for r in results] == ["a::one", "b::two"]


def test_test_id_without_classname_is_just_the_name():
    (result,) = parse('<testsuite><testcase name="lonely test"/></testsuite>')
    assert result.test_id == "lonely test"


def test_failure_wins_over_skipped():
    (result,) = parse(
        '<testsuite><testcase name="t"><skipped/><failure message="x"/></testcase></testsuite>'
    )
    assert result.outcome is Outcome.FAILED


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.25", 1.25), ("1,234.5", 1234.5), ("", 0.0), ("abc", 0.0), ("-3", 0.0)],
)
def test_duration_parsing_is_tolerant(raw, expected):
    (result,) = parse(f'<testsuite><testcase name="t" time="{raw}"/></testsuite>')
    assert result.duration == expected


def test_long_messages_are_truncated():
    long_message = "x" * 2000
    (result,) = parse(
        f'<testsuite><testcase name="t"><failure message="{long_message}"/></testcase></testsuite>'
    )
    assert len(result.message) == 500
    assert result.message.endswith("...")


def test_empty_report_returns_no_results():
    assert parse("<testsuites/>") == []


def test_invalid_xml_raises_clear_error():
    with pytest.raises(ReportParseError, match="invalid XML"):
        parse("<testsuites><testcase></testsuites>")


def test_wrong_root_element_raises():
    with pytest.raises(ReportParseError, match="found <html>"):
        parse("<html><body/></html>")


def test_testcase_without_name_raises():
    with pytest.raises(ReportParseError, match="without a name"):
        parse('<testsuite><testcase classname="a"/></testsuite>')


def test_parse_file_reports_missing_file(tmp_path):
    with pytest.raises(ReportParseError, match="cannot read file"):
        parse_junit_file(tmp_path / "missing.xml")
