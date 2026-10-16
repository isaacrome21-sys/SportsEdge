"""Audit findings on the Lane A retirement (03750cf8): lane_b_watchlist
leak, case-insensitive lane spelling, phone-board ranking."""
import pytest
from sportsedge.pricing_provenance import (
    LANE_A_RETIRED_STATUS, apply_play_gate, is_lane_a_label, is_play_eligible,
    provenance_for_game_result)
from sportsedge.phone_display import _disposition


@pytest.mark.parametrize("spelling", ["lane_a_independent", " Lane_A_Independent ",
                                      "LANE_A_INDEPENDENT"])
def test_lane_a_spelling_normalised(spelling):
    assert is_lane_a_label(spelling)
    assert provenance_for_game_result({"pricing_lane": spelling})["play_eligible"] is False
    row = {"pricing_lane": spelling, "status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
           "estimate_p": 0.6, "ev_per_dollar": 0.05}
    apply_play_gate([row])
    assert row["status"] == LANE_A_RETIRED_STATUS
    assert row["pricing_lane"] == "LANE_A_INDEPENDENT"
    assert not is_play_eligible(row)


def test_phone_board_never_ranks_lane_a_diagnostic():
    row = {"pricing_lane": "LANE_A_INDEPENDENT", "status": LANE_A_RETIRED_STATUS,
           "estimate_p": 0.6, "ev_per_dollar": 0.20, "odds_american": 110,
           "pricing_provenance": {"lane": "INDEPENDENT", "engine_lane": "LANE_A_INDEPENDENT"},
           "quote_freshness": {"status": "FRESH"}}
    label, bucket, _ = _disposition(row, 0.02)
    assert label == "RESEARCH DIAGNOSTIC"
    assert bucket == "diagnostic"


def test_primary_lane_a_rows_excluded_from_lane_b_watchlist():
    from test_anchored_lane_play_gate_20261012 import _engine_card, _mlb_total_rows
    card = _engine_card(_mlb_total_rows(), lane="A")
    assert all(not is_lane_a_label(r.get("pricing_lane"))
               for r in card["lane_b_watchlist"])
