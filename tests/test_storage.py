import pytest

from flakelens.models import CaseResult, Outcome
from flakelens.storage import Database


@pytest.fixture
def db(tmp_path):
    with Database(tmp_path / "nested" / "dir" / "test.db") as database:
        yield database


def results(*outcomes: Outcome) -> list[CaseResult]:
    return [CaseResult(test_id=f"t{i}", outcome=o) for i, o in enumerate(outcomes)]


def test_creates_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "c.db"
    Database(path).close()
    assert path.exists()


def test_add_run_and_read_history(db):
    run_id = db.add_run(
        results(Outcome.PASSED, Outcome.FAILED),
        source="r1.xml",
        content_hash="h1",
        commit="abc",
        branch="main",
    )
    assert run_id == 1

    rows = db.history()
    assert [(r.test_id, r.outcome, r.commit, r.branch) for r in rows] == [
        ("t0", Outcome.PASSED, "abc", "main"),
        ("t1", Outcome.FAILED, "abc", "main"),
    ]


def test_duplicate_content_hash_is_skipped(db):
    assert db.add_run(results(Outcome.PASSED), source="a.xml", content_hash="same") == 1
    assert db.add_run(results(Outcome.PASSED), source="b.xml", content_hash="same") is None
    assert len(db.list_runs()) == 1
    assert len(db.history()) == 1  # the duplicate's results were rolled back


def test_history_is_chronological_per_test(db):
    db.add_run([CaseResult("x", Outcome.PASSED)], source="1", content_hash="1")
    db.add_run([CaseResult("x", Outcome.FAILED)], source="2", content_hash="2")
    db.add_run([CaseResult("x", Outcome.PASSED)], source="3", content_hash="3")
    assert [r.outcome for r in db.history(test_id="x")] == [
        Outcome.PASSED,
        Outcome.FAILED,
        Outcome.PASSED,
    ]


def test_history_filters_by_branch(db):
    db.add_run(results(Outcome.PASSED), source="1", content_hash="1", branch="main")
    db.add_run(results(Outcome.FAILED), source="2", content_hash="2", branch="feature")
    rows = db.history(branch="main")
    assert [r.outcome for r in rows] == [Outcome.PASSED]


def test_list_runs_counts_failures(db):
    db.add_run(
        results(Outcome.PASSED, Outcome.FAILED, Outcome.ERROR, Outcome.SKIPPED),
        source="r.xml",
        content_hash="h",
    )
    db.add_run([], source="empty.xml", content_hash="h2")
    first, empty = db.list_runs()
    assert (first.total, first.failures) == (4, 2)
    assert (empty.total, empty.failures) == (0, 0)


def test_find_test_ids_treats_wildcards_literally(db):
    db.add_run(
        [
            CaseResult("tests::test_100_percent", Outcome.PASSED),
            CaseResult("tests::test_login", Outcome.PASSED),
        ],
        source="r",
        content_hash="h",
    )
    assert db.find_test_ids("LOGIN") == ["tests::test_login"]
    assert db.find_test_ids("%") == []
    assert db.find_test_ids("_100_") == ["tests::test_100_percent"]


def test_data_persists_between_connections(tmp_path):
    path = tmp_path / "persist.db"
    with Database(path) as first:
        first.add_run(results(Outcome.PASSED), source="r", content_hash="h")
    with Database(path) as second:
        assert len(second.list_runs()) == 1
