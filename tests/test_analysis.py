import pytest

from flakelens.analysis import Status, analyze, compute_stats
from flakelens.models import HistoryRow, Outcome

_LETTERS = {"p": Outcome.PASSED, "f": Outcome.FAILED, "e": Outcome.ERROR, "s": Outcome.SKIPPED}


def history(sequence: str, test_id: str = "t", commits: str | None = None) -> list[HistoryRow]:
    """Build a history from a string like "ppfp" (one letter per run).

    ``commits`` optionally gives one commit label per run, e.g. "aabb".
    """
    return [
        HistoryRow(
            test_id=test_id,
            run_id=index + 1,
            outcome=_LETTERS[letter],
            duration=0.1,
            message=None,
            commit=commits[index] if commits else None,
            branch=None,
            imported_at="2026-01-01T00:00:00+00:00",
        )
        for index, letter in enumerate(sequence)
    ]


def stats_for(sequence: str, **kwargs):
    commits = kwargs.pop("commits", None)
    return compute_stats("t", history(sequence, commits=commits), **kwargs)


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("pppp", Status.STABLE),
        ("ffff", Status.BROKEN),
        ("pppf", Status.BROKEN),  # one flip: a regression, not flakiness
        ("ffpp", Status.STABLE),  # one flip: the test was fixed
        ("pfpp", Status.FLAKY),  # two flips
        ("pfpfpf", Status.FLAKY),
        ("pf", Status.INSUFFICIENT_DATA),  # below the default min_runs of 3
        ("ssss", Status.SKIPPED),
        ("pspsfsp", Status.FLAKY),  # skips are ignored: p p f p -> two flips
    ],
)
def test_classification(sequence, expected):
    assert stats_for(sequence).status is expected


def test_errors_count_as_failures():
    stats = stats_for("pepe")
    assert stats.failures == 2
    assert stats.flips == 3
    assert stats.status is Status.FLAKY


def test_rates():
    stats = stats_for("ppfpsp")  # executed: p p f p p
    assert stats.executed == 5
    assert stats.skips == 1
    assert stats.fail_rate == pytest.approx(0.2)
    assert stats.flip_rate == pytest.approx(2 / 4)


def test_rates_with_no_data_are_zero():
    stats = stats_for("s")
    assert stats.fail_rate == 0.0
    assert stats.flip_rate == 0.0
    assert stats.last_outcome is None


def test_same_commit_conflict_is_flaky_even_with_few_runs():
    # Same commit "a" both passed and failed: the code did not change, the result did.
    stats = stats_for("pf", commits="aa")
    assert stats.same_code_conflicts == 1
    assert stats.status is Status.FLAKY


def test_different_commits_with_one_flip_are_not_flaky():
    stats = stats_for("ppff", commits="aabb")
    assert stats.same_code_conflicts == 0
    assert stats.status is Status.BROKEN


def test_conflict_inside_a_single_run_is_flaky():
    # E.g. a retry plugin reported the same test twice in one report.
    rows = history("pf")
    rows[1] = HistoryRow(**{**rows[1].__dict__, "run_id": 1})
    assert compute_stats("t", rows).status is Status.FLAKY


def test_min_runs_is_configurable():
    assert stats_for("pf", min_runs=2).status is Status.BROKEN
    assert stats_for("pfpf", min_runs=10).status is Status.INSUFFICIENT_DATA


def test_analyze_groups_by_test_and_sorts_most_actionable_first():
    rows = (
        history("pppp", test_id="stable")
        + history("pfpfpf", test_id="very_flaky")
        + history("ffff", test_id="broken")
        + history("pfpp", test_id="a_bit_flaky")
    )
    result = analyze(rows)
    assert [s.test_id for s in result] == ["very_flaky", "a_bit_flaky", "broken", "stable"]


def test_analyze_rejects_invalid_min_runs():
    with pytest.raises(ValueError):
        analyze([], min_runs=0)


def test_to_dict_is_json_friendly():
    data = stats_for("pfp").to_dict()
    assert data["status"] == "flaky"
    assert data["last_outcome"] == "passed"
    assert data["flip_rate"] == 1.0
