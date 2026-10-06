from datetime import date

import pytest

from sportsedge.mlb_pitcher_k_historical_row import (
    PROVENANCE_SCHEMA,
    PitcherKHistoricalRowError,
    bind_historical_statcast_skill,
    build_historical_evaluation_row,
)


def _composite():
    return {
        "schema": "MLB_PITCHER_K_COMPOSITE_CANDIDATE_V1",
        "authority": "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED",
        "market": "PITCHER_K",
        "deployment": False,
        "model_p_eligible": False,
        "components": {
            "workload_leash": {
                "summary": {
                    "recent_mean_batters_faced": 24.0,
                    "recent_mean_k_per_batter_faced": 0.25,
                    "recent_mean_pitches_per_batter_faced": 3.9,
                }
            },
            "opponent_k": {
                "beta": 1.0,
                "target_rel": 1.05,
                "history_rel": [1.0, 0.98, 1.02, 1.01, 0.99],
                "validated_in": "#1509",
            },
            "lineup_k": None,
        },
        "missing_components": ["pitcher_whiff_chase_pit_source", "pitcher_handedness_pit_source"],
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
        "window_start": "2025-05-02",
        "window_end": "2025-06-01",
    }


def _receipt():
    return {
        "schema": PROVENANCE_SCHEMA,
        "source": "BASEBALL_SAVANT_STATCAST",
        "mode": "HISTORICAL_RECONSTRUCTION",
        "target_date": "2025-06-01",
        "window_start": "2025-05-02",
        "query_end_exclusive": "2025-06-01",
        "retrieved_at": "2026-10-06T17:00:00+00:00",
        "raw_pitch_rows": 50000,
        "same_day_rows_included": False,
        "future_rows_included": False,
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "evaluation_use": "CANDIDATE_SPECIFIC_HISTORICAL_TEST_ONLY",
    }


def _history():
    rows = []
    for i in range(5):
        rows.append(
            {
                "strikeouts": 5 + i,
                "outs": 18 + i,
                "earned_runs": 2 + (i % 2),
                "hits_allowed": 5 + (i % 3),
                "walks_allowed": 1 + (i % 2),
            }
        )
    return rows


def test_historical_binding_is_explicitly_not_forward_evidence():
    got = bind_historical_statcast_skill(
        _composite(), pitcher_context=_context(), provenance=_receipt(),
        target_date=date(2025, 6, 1),
    )
    assert got["schema"] == "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
    assert got["source_complete"] is True
    assert got["historical_reconstruction"] is True
    assert got["forward_evidence_eligible"] is False
    assert got["model_p_eligible"] is False
    assert got["components"]["pitcher_skill"]["provenance"]["backfill"] is True


def test_same_day_or_forward_claim_is_rejected():
    receipt = _receipt()
    receipt["forward_evidence_eligible"] = True
    with pytest.raises(PitcherKHistoricalRowError, match="cannot be forward evidence"):
        bind_historical_statcast_skill(
            _composite(), pitcher_context=_context(), provenance=receipt,
            target_date=date(2025, 6, 1),
        )


def test_target_date_exclusive_window_is_required():
    context = _context()
    context["window_end"] = "2025-06-02"
    with pytest.raises(PitcherKHistoricalRowError, match="target-date exclusive"):
        bind_historical_statcast_skill(
            _composite(), pitcher_context=context, provenance=_receipt(),
            target_date=date(2025, 6, 1),
        )


def test_row_prices_incumbent_with_shipped_engine_and_stays_research_only():
    candidate = bind_historical_statcast_skill(
        _composite(), pitcher_context=_context(), provenance=_receipt(),
        target_date=date(2025, 6, 1),
    )
    row = build_historical_evaluation_row(
        season=2025,
        target_date=date(2025, 6, 1),
        game_id=777001,
        pitcher_id=501,
        candidate=candidate,
        history_pool=_history(),
        realized_strikeouts=7,
        realized_batters_faced=25,
    )
    assert len(row["incumbent_p_over"]) == 20
    assert "5.5" in row["incumbent_p_over"]
    assert all(0.0 <= p <= 1.0 for p in row["incumbent_p_over"].values())
    assert row["forward_evidence_eligible"] is False
    assert row["promotion_authority"] is False
    assert "model_p" not in row
