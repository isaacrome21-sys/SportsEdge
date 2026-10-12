"""No-leakage tests for chronological splitting."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.backtest.splits import (
    SplitError, fixed_split, walk_forward_splits,
)

BASE = datetime(2024, 9, 8, 17, 0, tzinfo=timezone.utc)


def fx(i, days=0, hours=0):
    kickoff = BASE + timedelta(days=days, hours=hours)
    return {
        "fixture_id": "g%d" % i,
        "kickoff": kickoff.isoformat(),
        "as_of": (kickoff - timedelta(hours=2)).isoformat(),
    }


def test_walk_forward_never_leaks_future_into_train():
    fixtures = [fx(i, days=i) for i in range(10)]
    for split in walk_forward_splits(fixtures, min_train=3, test_size=2):
        train_max = max(f["kickoff"] for f in split.train)
        test_min = min(f["kickoff"] for f in split.test)
        assert train_max < test_min
        assert len(split.train) >= 3
        assert len(split.test) == 2
        # train is expanding: later splits keep earlier fixtures
    splits = list(walk_forward_splits(fixtures, min_train=3, test_size=2))
    assert len(splits) == 6  # (10 - 3 - 2) / 1 + 1
    assert splits[0].train[0]["fixture_id"] == "g0"
    assert [f["fixture_id"] for f in splits[0].test] == ["g3", "g4"]
    assert len(splits[-1].train) == 8


def test_unsorted_fixtures_raise_instead_of_silently_reordering():
    fixtures = [fx(0, days=1), fx(1, days=0)]
    with pytest.raises(SplitError) as exc:
        list(walk_forward_splits(fixtures, min_train=1, test_size=1))
    assert "BACKTEST_CHRONOLOGY_UNSORTED" in str(exc.value)


def test_shared_kickoff_never_split_across_boundary():
    a = fx(0, days=0)
    b = fx(1, days=0)  # same kickoff as a
    c = fx(2, days=1)
    d = fx(3, days=2)
    splits = list(walk_forward_splits([a, b, c, d], min_train=2, test_size=1))
    assert splits, "expected at least one split"
    for split in splits:
        train_ids = {f["fixture_id"] for f in split.train}
        test_ids = {f["fixture_id"] for f in split.test}
        # a and b share a kickoff: they must land on the same side
        assert not (("g0" in train_ids) != ("g1" in train_ids))


def test_embargo_drops_too_close_splits():
    fixtures = [fx(i, days=d) for i, d in enumerate([0, 1, 2, 10, 11, 12])]
    no_embargo = list(walk_forward_splits(fixtures, min_train=2, test_size=2))
    embargoed = list(walk_forward_splits(fixtures, min_train=2, test_size=2,
                                         embargo_days=5))
    assert len(no_embargo) == 3
    assert len(embargoed) == 1  # only train ..day2 / test day10-11 clears 5d
    split = embargoed[0]
    assert split.train[-1]["kickoff"] < split.test[0]["kickoff"]


def test_fixed_split_cutoff_and_empty_sides_fail_closed():
    fixtures = [fx(i, days=i) for i in range(4)]
    cut = (BASE + timedelta(days=2)).isoformat()
    split = fixed_split(fixtures, cut)
    assert [f["fixture_id"] for f in split.train] == ["g0", "g1"]
    assert [f["fixture_id"] for f in split.test] == ["g2", "g3"]
    with pytest.raises(SplitError) as exc:
        fixed_split(fixtures, (BASE - timedelta(days=1)).isoformat())
    assert "BACKTEST_SPLIT_TRAIN_EMPTY" in str(exc.value)
    with pytest.raises(SplitError) as exc:
        fixed_split(fixtures, (BASE + timedelta(days=10)).isoformat())
    assert "BACKTEST_SPLIT_TEST_EMPTY" in str(exc.value)


def test_as_of_after_kickoff_is_rejected():
    bad = dict(fx(0))
    bad["as_of"] = (BASE + timedelta(hours=1)).isoformat()
    with pytest.raises(SplitError) as exc:
        list(walk_forward_splits([bad, fx(1, days=1)],
                                 min_train=1, test_size=1))
    assert "BACKTEST_AS_OF_AFTER_KICKOFF" in str(exc.value)


def test_duplicate_and_missing_ids_rejected():
    with pytest.raises(SplitError, match="BACKTEST_FIXTURE_ID_DUPLICATE"):
        list(walk_forward_splits([fx(0), fx(0, hours=1)],
                                 min_train=1, test_size=1))
    bad = dict(fx(0))
    del bad["fixture_id"]
    with pytest.raises(SplitError, match="BACKTEST_FIXTURE_ID_REQUIRED"):
        list(walk_forward_splits([bad, fx(1, days=1)],
                                 min_train=1, test_size=1))
