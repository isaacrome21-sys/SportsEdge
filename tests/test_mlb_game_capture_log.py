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

def test_2027_regular_games_never_inherit_2026_postseason_fallback():
    assert regime_for(official_date="2027-04-01") == "REGULAR"
    assert regime_for(official_date="2028-04-01") == "REGULAR"
    assert regime_for(official_date="2027-10-05", season_type="R") == "REGULAR"
    assert regime_for(official_date="2027-10-05", season_type="P") == "POSTSEASON"
    with pytest.raises(MLBCaptureLogError, match="FUTURE_LATE_SEASON_TYPE_REQUIRED"):
        regime_for(official_date="2027-10-05")
    with pytest.raises(MLBCaptureLogError, match="OFFICIAL_DATE_INVALID"):
        regime_for(official_date="2027-not-a-date")


@pytest.mark.parametrize("close_ts,close_price,reason", [
    ("2027-04-01T16:00:00Z", -115, "CLOSE_NOT_AFTER_INTAKE"),
    ("2027-04-01T15:59:59Z", -115, "CLOSE_NOT_AFTER_INTAKE"),
    ("2027-04-01T16:05:00Z", None, "CLOSE_PRICE_MISSING"),
    (None, -115, "CLOSE_TIMESTAMP_MISSING"),
])
def test_close_needs_separate_later_timestamp_and_price(close_ts, close_price, reason):
    row = {
        "game_id": "g-2027", "market": "MONEYLINE", "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": -110,
        "close_retrieved_at": close_ts,
        "close_american": close_price,
    }
    with pytest.raises(MLBCaptureLogError, match=reason):
        record_capture(row)


def test_2027_valid_two_capture_record_stays_research_only():
    row = record_capture({
        "game_id": "g-2027", "market": "MONEYLINE", "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": -110,
        "close_retrieved_at": "2027-04-01T16:05:00Z",
        "close_american": -115,
    })
    assert row.regime == "REGULAR"
    assert row.intake_retrieved_at < row.close_retrieved_at
    assert row.authority_footer == "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
