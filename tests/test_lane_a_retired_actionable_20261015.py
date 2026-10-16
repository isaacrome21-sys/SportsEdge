"""Owner ruling t207u: Lane A is retired from actionable cards pending a
rebuild and an independent backtest. Lane A output may appear only as a
labeled research diagnostic -- never a lean, candidate or position."""
from sportsedge.pricing_provenance import (
    LANE_A_RETIRED_PLAY_BLOCK, LANE_A_RETIRED_STATUS, apply_play_gate,
    is_play_eligible, provenance_for_game_result)


def _row(status="RESEARCH_POSITIVE_EV_UNVALIDATED"):
    return {"pricing_lane": "LANE_A_INDEPENDENT", "market": "TOTAL",
            "status": status, "estimate_p": 0.55, "ev_per_dollar": 0.04,
            "game_id": "g1", "selection": "Over 8.5"}


def test_lane_a_provenance_not_play_eligible():
    assert provenance_for_game_result({"pricing_lane": "LANE_A_INDEPENDENT"})[
        "play_eligible"] is False


def test_lane_a_row_never_play_eligible():
    assert is_play_eligible(_row()) is False


def test_gate_demotes_lane_a_to_labeled_diagnostic():
    for status in ("RESEARCH_POSITIVE_EV_UNVALIDATED",
                   "RESEARCH_CANDIDATE_NOT_VALIDATED", "RESEARCH_EDGE"):
        r = _row(status)
        apply_play_gate([r])
        assert r["status"] == LANE_A_RETIRED_STATUS
        assert r["research_only"] is True
        assert r["research_diagnostic"] == "LANE_A_RETIRED_DIAGNOSTIC"
        assert r["play_blocked_reason"] == LANE_A_RETIRED_PLAY_BLOCK
        assert r["estimate_p"] == 0.55  # diagnostic value kept, not invented


def test_lane_b_still_anchored_watch():
    r = _row(); r["pricing_lane"] = "LANE_B_ANCHORED"
    apply_play_gate([r])
    assert r["status"] == "WATCH_MARKET_ANCHORED_RESEARCH"


def test_priced_research_lane_a_keeps_status_but_is_labeled_diagnostic():
    r = _row("PRICED_RESEARCH")
    apply_play_gate([r])
    assert r["status"] == "PRICED_RESEARCH"
    assert r["research_diagnostic"] == "LANE_A_RETIRED_DIAGNOSTIC"
    assert r["play_blocked_reason"] == LANE_A_RETIRED_PLAY_BLOCK
    assert is_play_eligible(r) is False


def test_run_full_card_lists_lane_a_only_as_diagnostic_never_position():
    from test_anchored_lane_play_gate_20261012 import _run_full, _mlb_total_rows
    card = _run_full(_mlb_total_rows(), lane="A")
    under = next(r for r in card["evaluated_rows"]
                 if str(r.get("selection") or "").startswith("UNDER"))
    assert under["status"] == LANE_A_RETIRED_STATUS
    for surface in ("edges", "independent_candidates", "independent_watchlist"):
        assert under not in card.get(surface, [])
    assert under in card["lane_a_research_diagnostics"]
    assert card["summary"]["surfaced_positions"] == 0
