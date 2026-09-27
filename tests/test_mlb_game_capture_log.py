import pytest
from sportsedge.mlb_game_capture_log import MLBCaptureLogError, record_capture, regime_for

def test_intake_and_close_stay_in_separate_fields():
    row=record_capture({
        "game_id":"2026-10-03-NYY-BOS","market":"MONEYLINE","selection":"NYY",
        "official_date":"2026-10-03","season_type":"P",
        "intake_line":None,"intake_american":-140,"intake_retrieved_at":"2026-10-03T16:00:00Z",
        "close_line":None,"close_american":-155,"close_retrieved_at":"2026-10-03T23:05:00Z",
        "estimate_p":0.57,"model_reliability":0.0,
    })
    assert row.intake_american==-140 and row.close_american==-155
    assert row.intake_retrieved_at != row.close_retrieved_at
    assert row.regime=="POSTSEASON"
    assert row.model_reliability==0.0
    assert "NOT Model_P" in row.authority_footer

def test_model_p_label_is_rejected_on_the_capture_log():
    with pytest.raises(MLBCaptureLogError, match="ESTIMATE_P"):
        record_capture({
            "game_id":"g","market":"TOTAL","selection":"OVER",
            "official_date":"2026-09-20",
            "retrieved_at":"2026-09-20T16:00:00Z","model_p":0.55,
        })

def test_october_2026_defaults_to_postseason_regime():
    assert regime_for(official_date="2026-10-03")=="POSTSEASON"
    assert regime_for(official_date="2026-09-20")=="REGULAR"
