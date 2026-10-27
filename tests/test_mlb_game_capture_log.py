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

@pytest.mark.parametrize("official_date", ["", "not-a-date", "2027-02-30"])
@pytest.mark.parametrize("flags", [{"season_type": "R"}, {"season_type": "P"}, {"postseason": True}, {"postseason": False}])
def test_explicit_flags_cannot_bypass_official_date_validation(official_date, flags):
    with pytest.raises(MLBCaptureLogError, match="OFFICIAL_DATE_INVALID"):
        regime_for(official_date=official_date, **flags)


@pytest.mark.parametrize("season_type,postseason", [("R", True), ("P", False), ("REGULAR", True), ("POSTSEASON", False)])
def test_conflicting_season_provenance_is_refused(season_type, postseason):
    with pytest.raises(MLBCaptureLogError, match="SEASON_FLAGS_CONFLICT"):
        regime_for(official_date="2027-04-01", season_type=season_type, postseason=postseason)


@pytest.mark.parametrize("season_type", ["X", "UNKNOWN", "S"])
def test_unknown_explicit_season_type_is_refused(season_type):
    with pytest.raises(MLBCaptureLogError, match="SEASON_TYPE_UNKNOWN"):
        regime_for(official_date="2027-04-01", season_type=season_type)


@pytest.mark.parametrize("postseason", ["False", 0, 1, "True"])
def test_nonboolean_postseason_flags_are_refused(postseason):
    with pytest.raises(MLBCaptureLogError, match="POSTSEASON_FLAG_INVALID"):
        regime_for(official_date="2027-04-01", postseason=postseason)


@pytest.mark.parametrize("field", ["intake_american", "close_american"])
@pytest.mark.parametrize("bad", [
    0, 99, -99, True, False, -115.9, 110.0, "-110.5",
    "nan", "++110", "--110", "+-110", "110foo", "", [], {},
])
def test_malformed_american_odds_never_become_priced_receipts(field, bad):
    payload = {
        "game_id": "g", "market": "MONEYLINE", "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": -110,
        "close_retrieved_at": "2027-04-01T16:05:00Z",
        "close_american": -115,
    }
    payload[field] = bad
    code = "INTAKE_AMERICAN_INVALID" if field == "intake_american" else "CLOSE_AMERICAN_INVALID"
    with pytest.raises(MLBCaptureLogError, match=code):
        record_capture(payload)


@pytest.mark.parametrize("intake,close", [
    ("-110", "+100"), ("+125", "-105"), (-110, 120),
])
def test_valid_integral_american_odds_are_preserved_without_rounding(intake, close):
    row = record_capture({
        "game_id": "g", "market": "MONEYLINE", "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": intake,
        "close_retrieved_at": "2027-04-01T16:05:00Z",
        "close_american": close,
    })
    assert row.intake_american == int(intake)
    assert row.close_american == int(close)


@pytest.mark.parametrize("field", ["intake_line", "close_line"])
@pytest.mark.parametrize("bad", [None, True, False, float("nan"), float("inf"),
                                  float("-inf"), "nan", "Infinity", "bad", [], {}])
def test_market_threshold_capture_refuses_nonfinite_boolean_or_missing_lines(field, bad):
    payload = {
        "game_id": "g-2027", "market": "TOTAL", "selection": "OVER",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_line": 8.5, "intake_american": -110,
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "close_line": 8.5, "close_american": -115,
        "close_retrieved_at": "2027-04-01T16:05:00Z",
    }
    payload[field] = bad
    reason = "INTAKE_LINE_INVALID" if field == "intake_line" else "CLOSE_LINE_INVALID"
    with pytest.raises(MLBCaptureLogError, match=reason):
        record_capture(payload)


def test_moneyline_remains_lineless_and_pending_close_is_allowed():
    basic = {
        "game_id": "g-2027", "market": "MONEYLINE", "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": "-110",
    }
    row = record_capture(basic)
    assert row.intake_line is None
    assert row.close_line is None
    assert row.close_american is None
    assert row.close_retrieved_at is None


@pytest.mark.parametrize("market", ["MONEYLINE", "ML", "H2H"])
@pytest.mark.parametrize("field", ["intake_line", "close_line", "line"])
def test_winner_moneyline_never_preserves_numeric_handicap(market, field):
    payload = {
        "game_id": "g-2027", "market": market, "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": -110,
        "close_retrieved_at": "2027-04-01T16:05:00Z",
        "close_american": -115,
    }
    payload[field] = 1.5
    with pytest.raises(MLBCaptureLogError, match="MONEYLINE_THRESHOLD_FORBIDDEN"):
        record_capture(payload)


@pytest.mark.parametrize("market", ["MONEYLINE", "ML", "H2H"])
def test_winner_moneyline_aliases_accept_two_priced_capture_times_without_lines(market):
    row = record_capture({
        "game_id": "g-2027", "market": market, "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "intake_american": -110,
        "close_retrieved_at": "2027-04-01T16:05:00Z",
        "close_american": -115,
    })
    assert row.intake_line is None and row.close_line is None
    assert row.regime == "REGULAR"


def test_valid_market_threshold_preserved_without_rounding():
    row = record_capture({
        "game_id": "g-2027", "market": "RUN_LINE", "selection": "HOME",
        "official_date": "2027-04-01", "season_type": "R",
        "intake_line": "-1.5", "intake_american": "+120",
        "intake_retrieved_at": "2027-04-01T16:00:00Z",
        "close_line": "-1.5", "close_american": "+125",
        "close_retrieved_at": "2027-04-01T16:05:00Z",
    })
    assert row.intake_line == -1.5 and row.close_line == -1.5
