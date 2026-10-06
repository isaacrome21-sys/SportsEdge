import pytest

from sportsedge.mlb_pitcher_k_composite_candidate import AUTHORITY
from sportsedge.mlb_pitcher_k_skill_binding import (
    PitcherKSkillBindingError,
    bind_statcast_skill,
)


def _candidate():
    return {
        "schema": "MLB_PITCHER_K_COMPOSITE_CANDIDATE_V1",
        "authority": AUTHORITY,
        "market": "PITCHER_K",
        "start_count": 5,
        "components": {
            "workload_leash": {"schema": "MLB_PITCHER_K_WORKLOAD_CANDIDATE_V1", "summary": {}},
            "opponent_k": {"validated_in": "#1509"},
            "lineup_k": {"validated_in": "#1540"},
        },
        "missing_components": [
            "pitcher_whiff_chase_pit_source",
            "pitcher_handedness_pit_source",
        ],
        "evaluation_ready": False,
        "deployment": False,
        "model_p_eligible": False,
        "probability_formula": None,
        "fit_parameters": None,
    }


def _context():
    return {
        "entity_id": "501",
        "swings": 200,
        "whiffs": 60,
        "whiff_rate": 0.30,
        "out_of_zone_pitches": 180,
        "chases": 54,
        "chase_rate": 0.30,
        "pitcher_hand": "R",
        "window_start": "2026-09-07",
        "window_end": "2026-10-06",
    }


def _provenance():
    return {
        "schema": "SPORTSEDGE_STATCAST_MAIN_PROVENANCE_V1",
        "run_id": "999001",
        "event_name": "push",
        "ref": "refs/heads/main",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "eligible_for_forward_evaluation": True,
    }


def test_main_provenance_skill_binding_completes_sources_but_not_evaluation():
    got = bind_statcast_skill(_candidate(), pitcher_context=_context(), provenance=_provenance())
    assert got["schema"] == "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
    assert got["source_complete"] is True
    assert got["missing_components"] == []
    assert got["components"]["pitcher_skill"]["whiff_rate"] == 0.30
    assert got["components"]["pitcher_skill"]["chase_rate"] == 0.30
    assert got["components"]["pitcher_skill"]["pitcher_hand"] == "R"
    assert got["evaluation_ready"] is False
    assert got["deployment"] is False
    assert got["model_p_eligible"] is False
    assert got["probability_formula"] is None
    assert "UNTOUCHED_EVALUATION_PROTOCOL" in got["evaluation_blocker"]


def test_feature_branch_provenance_is_rejected():
    proof = _provenance()
    proof["ref"] = "refs/heads/research/foo"
    proof["head_branch"] = "research/foo"
    with pytest.raises(PitcherKSkillBindingError, match="not captured from main"):
        bind_statcast_skill(_candidate(), pitcher_context=_context(), provenance=proof)


def test_rates_must_match_counts():
    ctx = _context()
    ctx["whiff_rate"] = 0.31
    with pytest.raises(PitcherKSkillBindingError, match="does not match counts"):
        bind_statcast_skill(_candidate(), pitcher_context=ctx, provenance=_provenance())


def test_zero_or_missing_denominators_fail_closed():
    ctx = _context()
    ctx["swings"] = 0
    with pytest.raises(PitcherKSkillBindingError, match="swings must be positive"):
        bind_statcast_skill(_candidate(), pitcher_context=ctx, provenance=_provenance())


def test_candidate_never_becomes_model_eligible_via_binding():
    candidate = _candidate()
    candidate["model_p_eligible"] = True
    with pytest.raises(PitcherKSkillBindingError, match="cannot already be deployed"):
        bind_statcast_skill(candidate, pitcher_context=_context(), provenance=_provenance())
