from sportsedge.ml_dog_calibration import evaluate_ml_favorite_dog_calibration


def _row(game_id, generated, p=0.40, win=False, odds=120):
    return {
        "decision_id": f"d-{game_id}-{generated}",
        "game_id": str(game_id),
        "market": "MONEYLINE",
        "side": "AWAY",
        "generated_at_utc": generated,
        "first_pitch_utc": "2026-09-30T23:00:00+00:00",
        "american_odds": odds,
        "model_p": p,
        "outcome_win": win,
    }


def test_historical_rows_can_diagnose_but_never_validate_forward_gate():
    rows = [_row(i, "2026-08-13T17:00:00+00:00", win=(i % 5 < 2)) for i in range(200)]
    out = evaluate_ml_favorite_dog_calibration(rows)
    assert out["underdog_diagnostic_all_available"]["overall"]["n"] == 200
    assert out["underdog_forward_validation"]["overall"]["n"] == 0
    assert out["dog_calibration_validated"] is False
    assert "FORWARD_DOG_SAMPLE_LT_200" in out["dog_calibration_reasons"]


def test_repeated_snapshots_count_once_using_latest_pregame_row():
    rows = [
        _row(1, "2026-08-13T18:00:00+00:00", p=0.30, win=True),
        _row(1, "2026-08-13T19:00:00+00:00", p=0.40, win=True),
    ]
    out = evaluate_ml_favorite_dog_calibration(rows)
    assert out["deduped_moneyline_rows"] == 1
    assert out["underdog_forward_validation"]["overall"]["mean_model_p"] == 0.40


def test_perfectly_calibrated_200_game_forward_dog_sample_can_pass_general_gate():
    rows = []
    # Exactly 80 wins out of 200 at p=.40; all rows are genuinely after protocol commit.
    for i in range(200):
        rows.append(_row(i, "2026-08-14T18:00:00+00:00", p=0.40, win=(i < 80), odds=120))
    out = evaluate_ml_favorite_dog_calibration(rows)
    assert out["underdog_forward_validation"]["overall"]["n"] == 200
    assert out["dog_calibration_validated"] is True
    assert out["dog_calibration_reasons"] == []
    assert out["dog_175_plus_validated"] is False


def test_post_first_pitch_row_is_excluded():
    row = _row(1, "2026-10-01T00:00:00+00:00", p=0.40, win=True)
    out = evaluate_ml_favorite_dog_calibration([row])
    assert out["deduped_moneyline_rows"] == 0
