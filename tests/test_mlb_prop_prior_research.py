from __future__ import annotations

import pytest

from sportsedge.mlb_prop_prior_research import (
    PropPriorResearchError,
    evaluate_heldout_rows,
    long_window_posterior_settlement_mass,
)


def test_long_window_prior_pulls_ten_for_ten_tail_toward_older_base_rate():
    result = long_window_posterior_settlement_mass(
        recent_mass={"over": 1.0, "under": 0.0, "push": 0.0},
        recent_effective_n=10.0,
        prior_mass={"over": 0.5, "under": 0.5, "push": 0.0},
        prior_effective_n=60.0,
        has_push=False,
        prior_strength_cap=20.0,
    )

    assert result["prior_strength"] == 20.0
    assert result["p_over"] == pytest.approx(20.5 / 31.0)
    assert result["p_under"] == pytest.approx(10.5 / 31.0)
    assert result["p_over"] < 0.90
    assert result["authority"] == "RESEARCH_ONLY_NOT_MODEL_P_NOT_OFFICIAL"


def test_prior_strength_cannot_exceed_observed_older_effective_sample():
    result = long_window_posterior_settlement_mass(
        recent_mass={"over": 0.6, "under": 0.4, "push": 0.0},
        recent_effective_n=10.0,
        prior_mass={"over": 0.4, "under": 0.6, "push": 0.0},
        prior_effective_n=7.0,
        has_push=False,
        prior_strength_cap=20.0,
    )

    assert result["prior_strength"] == 7.0


def test_candidate_never_invents_mass_on_infeasible_settlement():
    result = long_window_posterior_settlement_mass(
        recent_mass={"over": 1.0, "under": 0.0, "push": 0.0},
        recent_effective_n=10.0,
        prior_mass={"over": 1.0, "under": 0.0, "push": 0.0},
        prior_effective_n=20.0,
        has_push=False,
        prior_strength_cap=10.0,
        feasible={"over": True, "under": False},
    )

    assert result["p_over"] == 1.0
    assert result["p_under"] == 0.0


def test_candidate_rejects_observed_mass_on_infeasible_settlement():
    with pytest.raises(PropPriorResearchError, match="inactive settlement"):
        long_window_posterior_settlement_mass(
            recent_mass={"over": 0.9, "under": 0.1, "push": 0.0},
            recent_effective_n=10.0,
            prior_mass={"over": 1.0, "under": 0.0, "push": 0.0},
            prior_effective_n=20.0,
            has_push=False,
            prior_strength_cap=10.0,
            feasible={"over": True, "under": False},
        )


def test_heldout_gate_fails_closed_on_non_prior_timestamp():
    rows = [
        {
            "target_at_utc": "2026-09-30T18:00:00Z",
            "prior_max_at_utc": "2026-09-30T18:00:00Z",
            "baseline_p": 0.80,
            "candidate_p": 0.65,
            "outcome": 1,
        }
    ]

    with pytest.raises(PropPriorResearchError, match="strict-prior chronology"):
        evaluate_heldout_rows(rows)


def test_heldout_gate_requires_noninferior_overall_and_tail_brier():
    rows = [
        {
            "target_at_utc": "2026-09-30T18:00:00Z",
            "prior_max_at_utc": "2026-09-29T18:00:00Z",
            "baseline_p": 0.95,
            "candidate_p": 0.70,
            "outcome": 0,
        },
        {
            "target_at_utc": "2026-09-30T19:00:00Z",
            "prior_max_at_utc": "2026-09-29T19:00:00Z",
            "baseline_p": 0.60,
            "candidate_p": 0.55,
            "outcome": 1,
        },
    ]

    result = evaluate_heldout_rows(rows)

    assert result["candidate_brier"] < result["baseline_brier"]
    assert result["tail_n"] == 1
    assert result["tail_candidate_brier"] < result["tail_baseline_brier"]
    assert result["passes_research_gate"] is True
    assert result["authority"] == "RESEARCH_ONLY_NOT_MODEL_P_NOT_OFFICIAL"


def test_heldout_gate_does_not_pass_candidate_that_only_improves_tail():
    rows = [
        {
            "target_at_utc": "2026-09-30T18:00:00Z",
            "prior_max_at_utc": "2026-09-29T18:00:00Z",
            "baseline_p": 0.95,
            "candidate_p": 0.80,
            "outcome": 0,
        },
        {
            "target_at_utc": "2026-09-30T19:00:00Z",
            "prior_max_at_utc": "2026-09-29T19:00:00Z",
            "baseline_p": 0.50,
            "candidate_p": 0.89,
            "outcome": 1,
        },
        {
            "target_at_utc": "2026-09-30T20:00:00Z",
            "prior_max_at_utc": "2026-09-29T20:00:00Z",
            "baseline_p": 0.50,
            "candidate_p": 0.89,
            "outcome": 0,
        },
    ]

    result = evaluate_heldout_rows(rows)

    assert result["tail_n"] == 1
    assert result["tail_candidate_brier"] < result["tail_baseline_brier"]
    assert result["candidate_brier"] > result["baseline_brier"]
    assert result["passes_research_gate"] is False
