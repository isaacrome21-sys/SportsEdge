"""Adversarial raw prop-candidate quarantine tests; no provider/model authority."""
from copy import deepcopy
from pathlib import Path

import pytest

from sportsedge.prop_candidate_quarantine import (
    CANDIDATE_STATUS, EXTREME_CLAIMED_EV_QUARANTINE,
    partition_prop_surfaces,
)


def row(ev, *, status=CANDIDATE_STATUS, index=0, **extra):
    return {"status": status, "ev_per_dollar": ev,
            "input_index": index, **extra}


@pytest.mark.parametrize("ev", [0.40, 0.4000001, 2.818, "0.40", 999])
def test_exact_and_above_owner_threshold_never_candidate(ev):
    candidates, watch, held = partition_prop_surfaces([row(ev)])
    assert EXTREME_CLAIMED_EV_QUARANTINE == 0.40
    assert candidates == watch == []
    assert len(held) == 1
    assert held[0]["reason"] == "EXTREME_CLAIMED_EV_QUARANTINE"
    assert held[0]["eligible_for_headline"] is False


def test_just_below_threshold_retains_research_only_candidate():
    original = row(.399999, index=9)
    candidates, watch, held = partition_prop_surfaces([original])
    assert candidates == [original] and not watch and not held
    assert candidates[0]["status"] == CANDIDATE_STATUS


@pytest.mark.parametrize("hidden", [
    {"independent_projection": {"ev_per_dollar": 2.818}},
    {"pricing_lanes": {"lane_a_independent": {"ev_per_dollar": .9},
                       "lane_b_anchored": {"ev_per_dollar": .05}}},
    {"pricing_lanes": {"lane_b_anchored": {"ev_per_dollar": .40}}},
    {"raw_ev_per_dollar": .58},
    {"reported_ev_per_dollar": .41},
])
def test_small_blended_claim_cannot_mask_raw_extreme(hidden):
    candidates, watch, held = partition_prop_surfaces([row(.02, **hidden)])
    assert not candidates and not watch
    assert held[0]["reason"] == "EXTREME_CLAIMED_EV_QUARANTINE"


def test_watchlist_extreme_is_quarantined_not_relabelled_as_watch():
    rows = [row(.60, status="WATCH_PRICE_CAP", index=1),
            row(.15, status="WATCH_QUOTE_NOT_CURRENT", index=2)]
    candidates, watch, held = partition_prop_surfaces(rows)
    assert not candidates
    assert watch == [rows[1]]
    assert [x["input_index"] for x in held] == [1]


@pytest.mark.parametrize("ev", [None, float("nan"), float("inf"),
                                float("-inf"), True, False, "281.8%", {}])
def test_invalid_visible_candidate_ev_fails_closed(ev):
    candidates, watch, held = partition_prop_surfaces([row(ev)])
    assert candidates == watch == []
    assert held[0]["reason"] == "PROP_EV_CLAIM_INVALID"


@pytest.mark.parametrize("hidden", [
    {"independent_projection": {"ev_per_dollar": "nan"}},
    {"independent_projection": "forged"},
    {"pricing_lanes": {"lane_a_independent": {"ev_per_dollar": True}}},
    {"pricing_lanes": {"lane_b_anchored": "forged"}},
    {"pricing_lanes": "forged"},
])
def test_invalid_hidden_claim_does_not_bypass_screen(hidden):
    candidates, watch, held = partition_prop_surfaces([row(.10, **hidden)])
    assert not candidates and not watch
    assert held[0]["reason"] == "PROP_EV_CLAIM_INVALID"


def test_quarantine_preserves_original_rows_and_input_indices():
    rows = [row(2.818, index=3),
            row(.22, index=4),
            row(.61, status="WATCH_QUOTE_NOT_CURRENT", index=5),
            row(.10, status="NO_MODEL_OR_MARKET", index=6)]
    before = deepcopy(rows)
    candidates, watch, held = partition_prop_surfaces(rows)
    assert rows == before
    assert candidates == [rows[1]]
    assert not watch
    assert [x["input_index"] for x in held] == [3, 5]
    assert len(candidates) + len(watch) + len(held) == 3
    assert len(rows) == 4  # NO_MODEL_OR_MARKET remains in evaluated_rows.


def test_under_threshold_candidates_keep_descending_ev_order():
    rows = [row(.12, index=1), row(.35, index=2), row(.21, index=3)]
    candidates, watch, held = partition_prop_surfaces(rows)
    assert [x["input_index"] for x in candidates] == [2, 3, 1]
    assert not watch and not held


def test_watch_without_ev_stays_watch_not_candidate():
    original = {"status": "WATCH_QUOTE_NOT_CURRENT", "input_index": 7}
    candidates, watch, held = partition_prop_surfaces([original])
    assert not candidates and not held and watch == [original]


def test_runner_canonical_output_is_wired_through_same_partition():
    # Static seam guard plus executed helper tests: a direct sorted(...)
    # assignment would silently reopen the alternate JSON output bypass.
    source = (Path(__file__).resolve().parents[1] /
              "artifacts" / "run_it_full.py").read_text(encoding="utf-8")
    assert "partition_prop_surfaces(modeled_props)" in source
    assert 'card["prop_candidates"], card["prop_watchlist"], card["prop_quarantined"]' in source


@pytest.mark.parametrize("hidden", [
    {"independent_projection": {"ev_per_dollar": 0.04,
                                "raw_ev_per_dollar": 2.818}},
    {"independent_projection": {"ev_per_dollar": 0.04,
                                "reported_ev_per_dollar": 0.40}},
    {"pricing_lanes": {"lane_a_independent": {
        "ev_per_dollar": 0.04, "raw_ev_per_dollar": 2.818}}},
    {"pricing_lanes": {"lane_b_anchored": {
        "ev_per_dollar": 0.04, "reported_ev_per_dollar": 0.41}}},
])
def test_nested_ev_alias_cannot_mask_extreme_from_raw_output(hidden):
    candidates, watch, held = partition_prop_surfaces([row(0.04, **hidden)])
    assert not candidates and not watch
    assert held[0]["reason"] == "EXTREME_CLAIMED_EV_QUARANTINE"


@pytest.mark.parametrize("hidden", [
    {"independent_projection": {"raw_ev_per_dollar": "nan"}},
    {"pricing_lanes": {"lane_a_independent": {
        "reported_ev_per_dollar": float("inf")}}},
])
def test_malformed_nested_alias_fails_closed_from_raw_output(hidden):
    candidates, watch, held = partition_prop_surfaces([row(0.04, **hidden)])
    assert not candidates and not watch
    assert held[0]["reason"] == "PROP_EV_CLAIM_INVALID"

@pytest.mark.parametrize("hidden", [
    {"estimate_p": 1.5},
    {"model_probability": -0.01},
    {"estimate_p": float("nan")},
    {"model_probability": float("inf")},
    {"estimate_p": True},
    {"independent_projection": {"estimate_p": 1.2, "ev_per_dollar": 0.04}},
    {"independent_projection": {"model_probability": "nan"}},
    {"pricing_lanes": {"lane_a_independent": {
        "model_probability": -0.1, "ev_per_dollar": 0.04}}},
    {"pricing_lanes": {"lane_b_anchored": {
        "estimate_p": False, "ev_per_dollar": 0.04}}},
])
def test_impossible_explicit_probability_never_reaches_raw_candidate(hidden):
    original = row(0.04, index=17, **hidden)
    before = deepcopy(original)
    candidates, watch, held = partition_prop_surfaces([original])
    assert candidates == watch == []
    assert len(held) == 1
    assert held[0]["reason"] == "PROP_PROBABILITY_CLAIM_INVALID"
    assert held[0]["input_index"] == 17
    assert held[0]["eligible_for_headline"] is False
    assert original == before  # Retain original evidence for grading.


def test_impossible_probability_in_watchlist_is_also_held():
    original = row(0.04, status="WATCH_QUOTE_NOT_CURRENT", estimate_p=1.5)
    candidates, watch, held = partition_prop_surfaces([original])
    assert not candidates and not watch
    assert held[0]["reason"] == "PROP_PROBABILITY_CLAIM_INVALID"


@pytest.mark.parametrize("p", [0, 0.5, 1, "0.25"])
def test_valid_explicit_probability_does_not_create_false_hold(p):
    original = row(0.04, estimate_p=p)
    candidates, watch, held = partition_prop_surfaces([original])
    assert candidates == [original]
    assert not watch and not held
