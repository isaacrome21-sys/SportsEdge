"""Saving or loading a rating history must preserve its recorded state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from sportsedge.ratings.elo import EloError, EloTracker
from sportsedge.ratings.provider import RatingError, RatingProvider


WHEN = datetime(2026, 9, 1, tzinfo=timezone.utc)


def tracker():
    value = EloTracker("NFL")
    value.record_game(date=WHEN, home="Chiefs", away="Ravens",
                      home_score=24, away_score=17, season="2026")
    return value


def test_exported_histories_are_independent_snapshots():
    original = tracker()
    exported = original.to_dict()
    rating = original.rating_at("Chiefs", WHEN + timedelta(days=1))
    exported["teams"]["chiefs"]["ratings"][0] = -1000
    exported["teams"]["chiefs"]["seasons"].clear()
    assert original.rating_at("Chiefs", WHEN + timedelta(days=1)) == rating
    # A later update still sees the original season and finite prior rating.
    original.record_game(date=WHEN + timedelta(days=2), home="Chiefs", away="Ravens",
                         home_score=24, away_score=17, season="2026")
    assert original.games_recorded == 2


@pytest.mark.parametrize("rating", [float("nan"), float("inf"), float("-inf"), True, "bad", None])
def test_loading_invalid_ratings_fails_closed(rating):
    data = tracker().to_dict()
    data["teams"]["chiefs"]["ratings"][0] = rating
    with pytest.raises(EloError, match="TRACKER_RATING"):
        EloTracker.from_dict(data)


def test_loading_duplicate_normalized_team_names_refuses_overwrite():
    data = tracker().to_dict()
    data["teams"]["Chiefs!"] = data["teams"]["chiefs"]
    with pytest.raises(EloError, match="TRACKER_TEAM"):
        EloTracker.from_dict(data)


@pytest.mark.parametrize("blob", [None, [], "not a history"])
def test_loading_invalid_team_history_is_a_domain_error(blob):
    data = tracker().to_dict()
    data["teams"]["chiefs"] = blob
    with pytest.raises(EloError, match="TRACKER_HISTORY"):
        EloTracker.from_dict(data)


def test_loading_a_valid_export_preserves_all_ratings_and_counts():
    original = tracker()
    restored = EloTracker.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    for team in original.teams():
        assert restored.rating_at(team, WHEN + timedelta(days=1)) == original.rating_at(
            team, WHEN + timedelta(days=1))


def test_provider_load_reports_corrupt_history_as_a_rating_error(tmp_path):
    data = tracker().to_dict()
    data["teams"]["chiefs"]["ratings"][0] = "nan"
    store = tmp_path / "ratings.json"
    store.write_text(json.dumps({"version": 1, "tracker": data}))
    with pytest.raises(RatingError, match="RATINGS_STORE_INVALID"):
        RatingProvider.load(store)
