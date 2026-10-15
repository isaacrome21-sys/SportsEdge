"""MLB pitcher-K end-to-end sprint battery (Oct 14, 2026).

Covers the worked-example chain's pure links: frozen-fit integrity,
milestone-ladder conversion on the verbatim Oct 14 DK fixtures,
settlement EV arithmetic, candidate pricing invariants, fail-closed
behavior, and the validation analysis scorers on known answers.
Network links (StatsAPI/Savant) are exercised by the builder script
itself, not by this battery.
"""
import json
from pathlib import Path

import pytest

from sportsedge.mlb_pitcher_k_probability_candidate import (
    PitcherKProbabilityCandidateError,
    feature_vector,
    price_threshold,
)
from sportsedge.milestone_ladder_intake import expand_milestone_ladder_rows

import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_script("build_mlb_pitcher_k_example_20261014")
analysis = _load_script("analyze_mlb_pitcher_k_validation_20261014")

CAP = "2026-10-14T19:44:00Z"
GAME = {"sport": "MLB", "away": "Milwaukee Brewers",
        "home": "Los Angeles Dodgers", "kickoff": "2026-10-14T19:00:00-05:00",
        "book": "draftkings", "quote_captured_at": CAP}


def _ladder(player, rungs):
    row = dict(GAME, market="PITCHER_K", player_name=player)
    row["milestone_ladder"] = {
        "form": "X_PLUS",
        "rungs": [{"threshold": t, "odds": o} for t, o in rungs]}
    return row


def _synthetic_candidate():
    return {
        "schema": "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1",
        "authority": "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED",
        "source_complete": True, "missing_components": [],
        "deployment": False, "model_p_eligible": False,
        "components": {
            "workload_leash": {"summary": {
                "recent_mean_batters_faced": 23.0,
                "recent_mean_k_per_batter_faced": 0.27,
                "recent_mean_pitches_per_batter_faced": 3.9}},
            "opponent_k": {"target_rel": 1.02},
            "lineup_k": None,
            "pitcher_skill": {"whiff_rate": 0.29, "chase_rate": 0.31,
                              "pitcher_hand": "L"},
        },
    }


# ------------------------------------------------------------- frozen fit

def test_frozen_fit_digest_recomputes():
    fit, concentration, freeze = builder.load_frozen_fit(ROOT)
    assert fit.fit_sha256 == \
        "70a31ff9b995a2d54df87feb2d51e2518fa9cd8593bf6c047970e08557b6ecea"
    assert concentration == 100.0
    assert fit.ridge_alpha == 100.0
    assert fit.training_rows == 4721
    assert freeze["development_readout"]["passes_development_gate"] is True


# ------------------------------------------------------- ladder conversion

def test_snell_ladder_converts_with_provenance_and_no_invented_price():
    rungs = [(3, -2600), (4, -890), (5, -382), (6, -184), (7, 106),
             (8, 199), (9, 370), (10, 680), (11, 1240)]
    out = expand_milestone_ladder_rows([_ladder("Blake Snell", rungs)])
    assert [r["line"] for r in out] == [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5]
    assert all(r["side"] == "OVER" for r in out)
    assert all(r["source_quote_form"] == "MILESTONE_X_PLUS" for r in out)
    assert all(r["quote_captured_at"] == CAP for r in out)
    assert [r["odds"] for r in out] == [o for _, o in rungs]
    assert all("opposite_odds" not in r and "under_odds" not in r for r in out)


def test_gasser_ladder_lines():
    out = expand_milestone_ladder_rows(
        [_ladder("Robert Gasser", [(2, -730), (3, -229), (4, 105),
                                   (5, 239), (6, 537), (7, 1140)])])
    assert [r["line"] for r in out] == [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]


# ------------------------------------------------------------- EV arithmetic

def test_ev_known_answers():
    assert builder.ev_per_dollar(0.5, 100) == pytest.approx(0.0)
    assert builder.ev_per_dollar(0.6, -110) == pytest.approx(
        0.6 * (100 / 110) - 0.4)
    assert builder.ev_per_dollar(1.0, -2600) == pytest.approx(100 / 2600)
    assert builder.american_to_decimal(-182) == pytest.approx(1 + 100 / 182)


# -------------------------------------------------------- candidate pricing

def test_candidate_pricing_invariants():
    fit, concentration, _ = builder.load_frozen_fit(ROOT)
    cand = _synthetic_candidate()
    feats = feature_vector(cand)
    assert feats[4] == 1.0  # lineup fallback when component absent
    priced = price_threshold(cand, fit, concentration=concentration, line=6.5)
    assert priced["candidate_p_push"] == 0.0  # half line: no push mass
    total = (priced["candidate_p_over"] + priced["candidate_p_under"]
             + priced["candidate_p_push"])
    assert total == pytest.approx(1.0)
    assert priced["deployment"] is False and priced["model_p_eligible"] is False
    assert priced["projected_batters_faced"] == 23


def test_candidate_fails_closed_without_skill():
    cand = _synthetic_candidate()
    del cand["components"]["pitcher_skill"]
    with pytest.raises(PitcherKProbabilityCandidateError):
        feature_vector(cand)


def test_rung_probabilities_decrease_with_threshold():
    fit, concentration, _ = builder.load_frozen_fit(ROOT)
    cand = _synthetic_candidate()
    probs = [price_threshold(cand, fit, concentration=concentration,
                             line=x - 0.5)["candidate_p_over"]
             for x in range(3, 12)]
    assert all(a > b for a, b in zip(probs, probs[1:]))


# ------------------------------------------------------ validation scorers

def test_rps_known_answer():
    # Degenerate distribution concentrated at the realized count scores 0
    # only in the limit; instead check a fair-coin threshold directly:
    # p_over = 0.5 at every line, realized above all lines -> each term .25
    p_over = {f"{x + 0.5:.1f}": 0.5 for x in range(20)}
    assert analysis.rps_from_p_over(p_over, 25) == pytest.approx(0.25)
    assert analysis.rps_from_p_over(p_over, 0) == pytest.approx(0.25)


def test_count_log_score_matches_mass():
    import math

    from sportsedge.mlb_pitcher_k_probability_candidate import count_mass
    mass = count_mass(n_trials=20, k_rate=0.25, concentration=100.0)
    assert analysis.count_log_score(0.25, 20, 5) == pytest.approx(
        -math.log(mass[5]))
