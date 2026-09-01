from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.prop_opportunity_context import (
    PROP_FAMILY_FIELDS,
    build_prop_opportunity_provider,
    build_prop_opportunity_snapshot,
)
from sportsedge.sports.nfl.run_it_context import build_run_it_context


NOW = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def _row():
    return {
        "player_id": "p1",
        "team_id": "BUF",
        "position": "WR",
        "sample_games": 5,
        "snap_share": 0.82,
        "route_participation": 0.91,
        "target_share": 0.27,
        "targets_per_route_run": 0.24,
        "adot": 12.4,
        "air_yard_share": 0.31,
        "carry_share": None,
        "early_down_snap_share": 0.73,
        "third_down_snap_share": 0.68,
        "two_minute_snap_share": 0.88,
        "goal_line_carries": 0,
        "red_zone_targets": 4,
        "red_zone_snap_share": 0.76,
        "designed_qb_run_rate": None,
        "scramble_rate": None,
        "pass_attempt_share": None,
        "pass_rush_snap_share": None,
        "pressure_rate_allowed": 0.29,
        "run_block_success_rate": 0.54,
        "man_coverage_target_rate": 0.30,
        "zone_coverage_target_rate": 0.25,
        "explosive_target_rate": 0.18,
    }


def test_prop_family_map_contains_required_attack_groups():
    assert set(PROP_FAMILY_FIELDS) == {
        "QB_PASSING", "WR_TE_RECEIVING", "RB_RUSHING", "RB_RECEIVING",
        "ANYTIME_TD", "LONGEST_RECEPTION", "QB_RUSHING", "PASS_RUSH",
    }
    assert "targets_per_route_run" in PROP_FAMILY_FIELDS["WR_TE_RECEIVING"]
    assert "goal_line_carries" in PROP_FAMILY_FIELDS["ANYTIME_TD"]
    assert "designed_qb_run_rate" in PROP_FAMILY_FIELDS["QB_RUSHING"]


def test_missing_values_remain_none_and_zero_is_preserved_when_real():
    row = build_prop_opportunity_snapshot(_row())
    assert row.designed_qb_run_rate is None
    assert row.goal_line_carries == 0
    assert row.snap_share == 0.82


def test_rates_fail_closed_outside_probability_bounds():
    raw = _row()
    raw["route_participation"] = 1.01
    with pytest.raises(NFLContextError):
        build_prop_opportunity_snapshot(raw)


def test_prop_provider_remains_context_only_and_has_no_market_payload():
    result = build_prop_opportunity_provider(
        game_id="2026_01_BUF_NYJ",
        as_of=NOW,
        source_uri="https://example.com/pit-prop-features.json",
        source_sha256=SHA,
        rows=[_row()],
    )
    assert result["status"] == "AVAILABLE"
    assert result["payload"]["market_fields_in_payload"] is False
    assert result["payload"]["process"][-2:] == ["EV", "EXECUTION_GATE"]
    assert "sportsbook" not in result["payload"]
    assert "odds" not in result["payload"]


def test_run_it_registers_prop_opportunity_under_snap_usage_workload():
    game = {
        "game_id": "2026_01_BUF_NYJ",
        "prop_opportunity_inputs": [_row()],
        "prop_opportunity_source_uri": "https://example.com/pit-prop-features.json",
        "prop_opportunity_source_sha256": SHA,
    }
    bundle = build_run_it_context(mode="AUTO", game=game, as_of=NOW)
    row = bundle["observations"]["snap_usage_workload"]
    assert row["status"] == "AVAILABLE"
    assert row["model_p_eligible"] is False
    assert row["truth_gate_eligible"] is False
    assert row["payload"]["market_fields_in_payload"] is False
    assert row["payload"]["players"][0]["target_share"] == 0.27
