from sportsedge.research.historical_row_quality import validate_historical_row


BASE = dict(
    sport="MLB", market="ML", event_id="123", season=2025,
    event_start_ts="2025-07-01T19:00:00Z",
    decision_ts="2025-07-01T18:00:00Z",
    feature_asof_ts="2025-07-01T17:00:00Z",
    model_p=0.53, bookmaker="DK",
    offered_decimal=1.95, odds_captured_at="2025-07-01T17:50:00Z",
    benchmark_p=0.52, benchmark_source="contemporaneous_no_vig",
)


def test_valid_pit_row():
    assert validate_historical_row(BASE) == ()


def test_late_odds_fail():
    assert "ODDS_AFTER_DECISION" in validate_historical_row({
        **BASE, "odds_captured_at": "2025-07-01T18:01:00Z"})


def test_late_features_fail():
    assert "FEATURE_AFTER_DECISION" in validate_historical_row({
        **BASE, "feature_asof_ts": "2025-07-01T18:01:00Z"})


def test_missing_book_fails_when_offered():
    assert "OFFERED_ODDS_MISSING_BOOKMAKER" in validate_historical_row({
        **BASE, "bookmaker": None})


def test_unattributed_benchmark_fails():
    assert "BENCHMARK_SOURCE_MISSING" in validate_historical_row({
        **BASE, "benchmark_source": None})


def test_naive_time_fails():
    assert "INVALID_DECISION_TS" in validate_historical_row({
        **BASE, "decision_ts": "2025-07-01T18:00:00"})


def test_nan_model_probability_rejected():
    assert "INVALID_MODEL_P" in validate_historical_row({**BASE, "model_p": float("nan")})


def test_infinite_offered_price_rejected():
    assert "INVALID_OFFERED_DECIMAL" in validate_historical_row({**BASE, "offered_decimal": float("inf")})
