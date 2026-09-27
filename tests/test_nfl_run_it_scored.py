from datetime import datetime, timezone

import pytest

from sportsedge.nfl_run_it import run_it
from sportsedge.nfl_run_it_scored import ScoredCardPick, run_it_scored
from sportsedge.nfl_run_it_score_binding import NflRunItScoreBindingError
from sportsedge.nfl_run_it_scoring import SCORE_LABEL

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)


def _quotes():
    stamp = "2026-09-23T07:59:00Z"
    return [
        {"game_id":"g1","home":"GB","away":"ATL","market":"moneyline","selection":"GB","price_american":110,"book":"draftkings","retrieved_at":stamp},
        {"game_id":"g1","home":"GB","away":"ATL","market":"moneyline","selection":"ATL","price_american":-130,"book":"draftkings","retrieved_at":stamp},
    ]


def _estimates():
    return [
        {"game_id":"g1","market":"moneyline","selection":"GB","estimate_p":0.55},
        {"game_id":"g1","market":"moneyline","selection":"ATL","estimate_p":0.45},
    ]


def _snapshot(selection="GB", ready=True):
    return {
        "game_id":"g1","market":"moneyline","selection":selection,
        "captured_at":"2026-09-23T07:55:00Z","kickoff_at":"2026-09-25T00:15:00Z",
        "source_version":"nfl-v1","feature_digest":"abc123",
        "model_ready":ready,"pit_safe":ready,"role_stable":ready,
        "usage_supported":ready,"matchup_supported":ready,
        "injury_context_ready":ready,"shared_simulation_ready":ready,
        "market_binding_ready":ready,
    }


def test_game_run_it_exposes_score_b_without_changing_economics_or_rank():
    base = run_it(_quotes(), _estimates(), as_of=NOW, edge_floor=0.0)
    scored = run_it_scored(_quotes(), _estimates(), [_snapshot()], as_of=NOW, edge_floor=0.0)

    assert len(base.picks) == len(scored.picks) == 1
    original = base.picks[0]
    pick = scored.picks[0]
    assert isinstance(pick, ScoredCardPick)
    assert pick.selection == original.selection == "GB"
    assert pick.rank == original.rank == 1
    assert pick.ev_per_dollar == original.ev_per_dollar
    assert pick.edge_probability_points == original.edge_probability_points
    assert pick.score_0_100 == 100
    assert pick.score_label == SCORE_LABEL

    payload = scored.to_dict()["picks"][0]
    assert payload["score_0_100"] == 100
    assert payload["score_label"] == SCORE_LABEL


def test_score_changes_only_with_qualification_not_market_economics():
    strong = run_it_scored(_quotes(), _estimates(), [_snapshot(ready=True)], as_of=NOW, edge_floor=0.0)
    weak = run_it_scored(_quotes(), _estimates(), [_snapshot(ready=False)], as_of=NOW, edge_floor=0.0)

    strong_pick = strong.picks[0]
    weak_pick = weak.picks[0]
    assert strong_pick.ev_per_dollar == weak_pick.ev_per_dollar
    assert strong_pick.edge_probability_points == weak_pick.edge_probability_points
    assert strong_pick.rank == weak_pick.rank == 1
    assert strong_pick.score_0_100 == 100
    assert weak_pick.score_0_100 == 0


def test_missing_qualification_for_surviving_row_fails_closed():
    with pytest.raises(NflRunItScoreBindingError, match="QUALIFICATION_SNAPSHOT_REQUIRED_FOR_ROW"):
        run_it_scored(_quotes(), _estimates(), [], as_of=NOW, edge_floor=0.0)
