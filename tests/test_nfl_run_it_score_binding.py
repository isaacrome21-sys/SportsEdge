import pytest

from sportsedge.nfl_run_it_score_binding import (
    NflRunItScoreBindingError,
    bind_score_b,
    score_b_by_identity,
)


def _snapshot(**updates):
    row = {
        "game_id": "g1", "market": "spread", "selection": "GB",
        "captured_at": "2026-09-24T23:30:00Z", "kickoff_at": "2026-09-25T00:15:00Z",
        "source_version": "nfl-features-v1", "feature_digest": "abc123",
        "model_ready": True, "pit_safe": True, "role_stable": True,
        "usage_supported": True, "matchup_supported": True,
        "injury_context_ready": True, "shared_simulation_ready": True,
        "market_binding_ready": True,
    }
    row.update(updates)
    return row


def test_all_ready_scores_100_without_market_economics():
    scores = score_b_by_identity([_snapshot()])
    assert scores[("g1", "spread", "GB")] == 100


def test_score_changes_only_with_qualification_flags():
    scores = score_b_by_identity([_snapshot(matchup_supported=False, injury_context_ready=False)])
    assert scores[("g1", "spread", "GB")] == 75


def test_binding_preserves_ev_edge_and_order():
    rows = [
        {"game_id":"g1","market":"spread","selection":"GB","ev_per_dollar":.08,"edge_probability_points":.04},
        {"game_id":"g2","market":"total","selection":"OVER","ev_per_dollar":.03,"edge_probability_points":.02},
    ]
    second = _snapshot(game_id="g2", market="total", selection="OVER", role_stable=False)
    out = bind_score_b(rows, [_snapshot(), second])
    assert [r["game_id"] for r in out] == ["g1", "g2"]
    assert [r["ev_per_dollar"] for r in out] == [.08, .03]
    assert [r["edge_probability_points"] for r in out] == [.04, .02]
    assert [r["score_0_100"] for r in out] == [100, 88]


def test_missing_or_conflicting_snapshot_fails_closed():
    with pytest.raises(NflRunItScoreBindingError, match="REQUIRED_FOR_ROW"):
        bind_score_b([{"game_id":"g2","market":"total","selection":"OVER"}], [_snapshot()])
    with pytest.raises(NflRunItScoreBindingError, match="CONFLICTING"):
        score_b_by_identity([_snapshot(), _snapshot(role_stable=False)])


def test_market_price_cannot_enter_score_snapshot():
    with pytest.raises(Exception, match="MARKET_INPUT_FORBIDDEN"):
        score_b_by_identity([_snapshot(ev_per_dollar=.20)])
