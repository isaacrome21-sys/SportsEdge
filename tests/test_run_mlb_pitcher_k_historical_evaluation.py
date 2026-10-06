from datetime import date
import json
from pathlib import Path

import pytest

from scripts import run_mlb_pitcher_k_historical_evaluation as R


def _plan():
    return {
        "schema": R.PLAN_SCHEMA,
        "status": "FROZEN_BEFORE_FIRST_HISTORICAL_ROW_MATERIALIZATION",
        "candidate_family": "RIDGE_LOGIT_K_RATE_BETA_BINOMIAL_V1",
        "seasons": {"training": 2023, "validation": 2024, "candidate_test": 2025},
        "sampling": {
            "months": [6, 7, 8, 9],
            "days_of_month": [1, 6, 11, 16, 21, 26],
            "game_type": "R",
        },
        "evaluation": {"candidate_test_one_look": True},
        "authority": {"model_p": False},
    }


def test_sample_dates_are_frozen_outcome_blind_grid():
    dates = R.sample_dates(_plan())
    assert len(dates) == 72
    assert len(set(dates)) == 72
    assert dates[0] == date(2023, 6, 1)
    assert dates[-1] == date(2025, 9, 26)
    assert all(d.month in {6, 7, 8, 9} for d in dates)
    assert all(d.day in {1, 6, 11, 16, 21, 26} for d in dates)


def test_statcast_context_is_target_date_exclusive_and_zero_authority():
    snapshot = {
        "source": "BASEBALL_SAVANT_STATCAST",
        "window_start": "2025-05-03",
        "window_end": "2025-06-01",
        "retrieved_at": "2026-10-06T18:00:00+00:00",
        "raw_pitch_rows": 12345,
        "pitcher_rows": [{
            "entity_id": "501",
            "swings": 200,
            "whiffs": 60,
            "whiff_rate": 0.30,
            "out_of_zone_pitches": 180,
            "chases": 54,
            "chase_rate": 0.30,
            "pitcher_hand": "R",
        }],
    }
    context, receipt = R.statcast_context(snapshot, pitcher_id=501, target_date=date(2025, 6, 1))
    assert context["whiff_rate"] == 0.30
    assert context["chase_rate"] == 0.30
    assert receipt["query_end_exclusive"] == "2025-06-01"
    assert receipt["same_day_rows_included"] is False
    assert receipt["future_rows_included"] is False
    assert receipt["forward_evidence_eligible"] is False
    assert receipt["promotion_authority"] is False


def test_statcast_context_rejects_wrong_target_window():
    snapshot = {
        "window_start": "2025-05-04",
        "window_end": "2025-06-02",
        "pitcher_rows": [],
    }
    with pytest.raises(R.HistoricalEvalError, match="target date exclusive"):
        R.statcast_context(snapshot, pitcher_id=501, target_date=date(2025, 6, 1))


def test_starter_uses_first_boxscore_pitcher_and_realized_k_bf():
    box = {
        "teams": {
            "away": {
                "pitchers": [501, 502],
                "players": {
                    "ID501": {
                        "stats": {"pitching": {"strikeOuts": 7, "battersFaced": 25}}
                    }
                },
            }
        }
    }
    assert R._starter(box, "away") == (501, 7, 25)


def test_load_plan_fails_if_one_look_or_authority_contract_changes(tmp_path: Path):
    plan = _plan()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert R.load_plan(path)["seasons"]["candidate_test"] == 2025

    plan["evaluation"]["candidate_test_one_look"] = False
    path.write_text(json.dumps(plan))
    with pytest.raises(R.HistoricalEvalError, match="one-look"):
        R.load_plan(path)

    plan = _plan()
    plan["authority"]["model_p"] = True
    path.write_text(json.dumps(plan))
    with pytest.raises(R.HistoricalEvalError, match="Model_P"):
        R.load_plan(path)


def test_run_requires_explicit_candidate_test_consumption(tmp_path: Path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_plan()))
    with pytest.raises(R.HistoricalEvalError, match="consume-candidate-test"):
        R.run(
            path,
            cache_dir=tmp_path / "cache",
            out_dir=tmp_path / "out",
            consume_candidate_test=False,
        )
