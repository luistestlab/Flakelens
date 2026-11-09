"""End-to-end tests: drive the CLI exactly like a user would."""

import json

import pytest

from flakelens.cli import EXIT_FLAKY_FOUND, EXIT_OK, EXIT_USAGE_ERROR, main


@pytest.fixture
def run(tmp_path, capsys):
    db_path = tmp_path / "cli.db"

    def _run(*args: str) -> tuple[int, str, str]:
        code = main(["--db", str(db_path), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def flaky_history(write_report):
    """Five runs: one stable, one flaky and one broken test."""
    outcomes = {
        "tests.test_cart::test_add": "ppppp",
        "tests.test_pay::test_timeout": "pfpfp",
        "tests.test_promo::test_code": "fffff",
    }
    return [
        write_report({test: seq[i] for test, seq in outcomes.items()}) for i in range(5)
    ]


def test_import_report_and_runs(run, flaky_history):
    code, out, _ = run("import", *map(str, flaky_history))
    assert code == EXIT_OK
    assert "imported" in out and "as run #5 (3 tests)" in out

    code, out, _ = run("runs")
    assert code == EXIT_OK
    assert "#5" in out


def test_import_directory_and_glob(run, flaky_history):
    directory = flaky_history[0].parent
    code, out, _ = run("import", str(directory))
    assert code == EXIT_OK
    assert "5 report(s) imported" in out

    code, out, _ = run("import", str(directory / "run-*.xml"))
    assert code == EXIT_OK
    assert "0 report(s) imported, 5 skipped as duplicates" in out


def test_import_reports_bad_and_missing_files_but_keeps_going(run, write_report, tmp_path):
    good = write_report({"a::b": "p"})
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml", encoding="utf-8")

    code, out, err = run("import", str(bad), str(tmp_path / "nope*.xml"), str(good))
    assert code == EXIT_USAGE_ERROR
    assert "invalid XML" in err
    assert "no report found" in err
    assert "1 report(s) imported" in out


def test_report_table(run, flaky_history):
    run("import", *map(str, flaky_history))
    code, out, _ = run("report")
    assert code == EXIT_OK
    assert "3 tests analyzed: 1 flaky, 1 broken, 1 stable" in out
    lines = out.splitlines()
    flaky_line = next(line for line in lines if "test_timeout" in line)
    assert flaky_line.startswith("FLAKY")
    assert "test_add" not in out  # stable tests are hidden by default


def test_report_json_and_status_filter(run, flaky_history):
    run("import", *map(str, flaky_history))
    code, out, _ = run("report", "--format", "json", "--status", "all")
    assert code == EXIT_OK
    data = json.loads(out)
    assert [item["status"] for item in data] == ["flaky", "broken", "stable"]
    assert data[0]["flips"] == 4


def test_fail_on_flaky_sets_exit_code(run, flaky_history):
    run("import", *map(str, flaky_history))
    code, _, _ = run("report", "--fail-on-flaky")
    assert code == EXIT_FLAKY_FOUND


def test_fail_on_flaky_passes_when_suite_is_healthy(run, write_report):
    reports = [write_report({"a::stable": "p"}) for _ in range(3)]
    run("import", *map(str, reports))
    code, _, _ = run("report", "--fail-on-flaky")
    assert code == EXIT_OK


def test_commit_flag_enables_same_commit_detection(run, write_report):
    first = write_report({"a::t": "p"})
    second = write_report({"a::t": "f"})
    run("import", str(first), "--commit", "abc123")
    run("import", str(second), "--commit", "abc123")
    _, out, _ = run("report", "--format", "json")
    (item,) = json.loads(out)
    assert item["status"] == "flaky"
    assert item["same_code_conflicts"] == 1


def test_report_on_empty_database(run):
    code, out, _ = run("report")
    assert code == EXIT_OK
    assert "No test results yet" in out


def test_history_by_fragment(run, flaky_history):
    run("import", *map(str, flaky_history))
    code, out, _ = run("history", "timeout")
    assert code == EXIT_OK
    assert "History of tests.test_pay::test_timeout" in out
    assert out.count("failed") == 2


def test_history_ambiguous_or_unknown(run, flaky_history):
    run("import", *map(str, flaky_history))
    code, _, err = run("history", "tests.")
    assert code == EXIT_USAGE_ERROR
    assert "matches 3 tests" in err

    code, _, err = run("history", "does-not-exist")
    assert code == EXIT_USAGE_ERROR
    assert "no test matches" in err


def test_invalid_min_runs_is_rejected(run):
    with pytest.raises(SystemExit) as excinfo:
        run("report", "--min-runs", "0")
    assert excinfo.value.code == 2
