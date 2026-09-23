from datetime import datetime, timezone

import pytest

from sportsedge.nfl_run_it_scored import run_it_scored
from sportsedge.nfl_run_it_score_binding import NflRunItScoreBindingError

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
        "captured_at":"2026-09-23T07:55:00Z","commence_time":"2026-09-25T00:15:00Z",
        "source_version":"nfl-v1","feature_digest":"abc123",
        "model_ready":ready,"pit_safe":ready,"role_stable":ready,
        "usage_supported":ready,"matchup_supported":ready,
        "injury_context_ready":ready,"shared_simulation_ready":ready,
        "market_binding_ready":ready,
    }


def test_game_run_it_gets_score_b_without_changing_economics_or_rank():
    base = run_it_scored(_quotes(), _estimates(), [_snapshot()], as_of=NOW, edge_floor=0.0)
    assert len(base.picks) == 1
    pick = base.picks[0]
    assert pick.selection == "GB"
    assert pick.rank == 1
    assert pick.score_0_100 == 100
    assert pick.ev_per_dollar > 0
    assert pick.edge_probability_points > 0


def test_score_changes_with_qualification_not_market_economics():
    strong = run_it_scored(_quotes(), _estimates(), [_snapshot(ready=True)], as_of=NOW, edge_floor=0.0)
    weak = run_it_scored(_quotes(), _estimates(), [_snapshot(ready=False)], as_of=NOW, edge_floor=0.0)
    assert strong.picks[0].score_0_100 == 100
    assert weak.picks[0].score_0_100 == 0
    assert strong.picks[0].ev_per_dollar == weak.picks[0].ev_per_dollar
    assert strong.picks[0].edge_probability_points == weak.picks[0].edge_probability_points
    assert strong.picks[0].rank == weak.picks[0].rank == 1


def test_missing_qualification_for_surviving_row_fails_closed():
    with pytest.raises(NflRunItScoreBindingError, match="QUALIFICATION_SNAPSHOT_REQUIRED_FOR_ROW"):
        run_it_scored(_quotes(), _estimates(), [], as_of=NOW, edge_floor=0.0)
