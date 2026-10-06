import json
from pathlib import Path

PREREG = Path("config/research/nfl_market_context_prop_v2_recency_prereg_2026-10-05.json")


def test_v2_recency_candidate_is_frozen_market_blind_and_no_authority():
    x = json.loads(PREREG.read_text(encoding="utf-8"))
    assert x["status"] == "FROZEN_BEFORE_2026_WEEK5_FORWARD_EVIDENCE"
    assert x["candidate_family"] == "NFL_MARKET_CONTEXT_PROP_V2_RECENCY"
    rule = x["role_recency_rule"]
    assert rule["strictly_prior_rows_only"] is True
    assert rule["target_season_regular_games_required"] == 4
    assert rule["older_anchor_games"] == 1
    assert rule["market_blind"] is True
    assert x["selection_safety"]["forced_team_balance"] is False
    assert x["selection_safety"]["forced_over_under_balance"] is False
    assert x["selection_safety"]["one_team_or_direction_concentration_is_diagnostic_only"] is True
    roster = x["roster_residual_rule"]
    assert roster["latest_depth_snapshot_at_or_before_observed_at_required"] is True
    assert roster["out_or_inactive_excluded_from_active_depth_set"] is True
    assert roster["current_team_history_for_players_not_on_active_depth_snapshot"] == "REMOVE_BEFORE_ROLE_BUILD"
    assert roster["former_team_history_for_current_active_player"] == "PRESERVE_FOR_PLAYER_ROLE_ESTIMATION"
    assert roster["market_blind"] is True
    assert x["forward_window"]["backfill_allowed"] is False
    assert x["validation"]["no_parameter_retuning_after_first_forward_readout"] is True
    assert not any(
        value for key, value in x["authority"].items()
        if key != "research_only"
    )
