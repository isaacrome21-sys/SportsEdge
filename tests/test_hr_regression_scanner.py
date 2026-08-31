import pytest

from sportsedge.hr_regression_scanner import (
    HRRegressionScannerError,
    scan_hr_regression_candidate,
    shortlist_hr_regression_candidates,
)


def base_row():
    return {
        "player_id": "player-1",
        "game_id": "game-1",
        "as_of": "2026-08-30T21:00:00Z",
        "first_pitch": "2026-08-30T23:20:00Z",
        "recent_bbe": 24,
        "recent_hr": 1,
        "barrel_pct": 14.0,
        "hard_hit_pct": 51.0,
        "avg_ev": 92.1,
        "xslg": 0.520,
    }


def test_strong_contact_candidate_is_flagged_without_price_data():
    out = scan_hr_regression_candidate(base_row()).as_dict()
    assert out["score"] >= 5.0
    assert "contact_quality_exceeds_recent_hr_results" in out["reasons"]
    assert out["governance"] == "CANDIDATE_GENERATION_ONLY_NOT_MODEL_P"


def test_market_data_leakage_fails_closed():
    row = base_row()
    row["american_odds"] = 350
    with pytest.raises(HRRegressionScannerError, match="market_data_in_contact_features"):
        scan_hr_regression_candidate(row)


def test_public_betting_leakage_fails_closed():
    row = base_row()
    row["handle_pct"] = 72
    with pytest.raises(HRRegressionScannerError, match="market_data_in_contact_features"):
        scan_hr_regression_candidate(row)


def test_post_start_contact_data_fails_closed():
    row = base_row()
    row["as_of"] = row["first_pitch"]
    with pytest.raises(HRRegressionScannerError, match="CONTACT_DATA_NOT_PREGAME"):
        scan_hr_regression_candidate(row)


def test_recent_hr_scarcity_does_not_create_candidate_by_itself():
    row = base_row()
    row.update({
        "recent_bbe": 20,
        "recent_hr": 0,
        "barrel_pct": 3.0,
        "hard_hit_pct": 28.0,
        "avg_ev": 86.0,
        "xslg": 0.320,
    })
    out = scan_hr_regression_candidate(row)
    assert out.score < 5.0
    assert "contact_quality_exceeds_recent_hr_results" not in out.reasons


def test_shortlist_is_deterministic_and_ranked():
    strong = base_row()
    medium = base_row()
    medium["player_id"] = "player-2"
    medium["barrel_pct"] = 10.0
    medium["hard_hit_pct"] = 44.0
    medium["avg_ev"] = 89.0
    medium["xslg"] = 0.460
    weak = base_row()
    weak["player_id"] = "player-3"
    weak.update({"barrel_pct": 2.0, "hard_hit_pct": 25.0, "avg_ev": 84.0, "xslg": 0.300})

    out = shortlist_hr_regression_candidates([weak, medium, strong], min_score=5.0)
    assert [r["player_id"] for r in out] == ["player-1", "player-2"]
