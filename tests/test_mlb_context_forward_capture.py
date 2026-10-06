from sportsedge.mlb_context_forward_capture import capture_training_row

def test_capture_requires_strict_pregame_time():
    b={"game_pk":1}
    try: capture_training_row(b,game_date="2026-10-07",first_pitch_utc="2026-10-07T18:00:00Z",captured_at_utc="2026-10-07T18:00:00Z")
    except ValueError: pass
    else: raise AssertionError("expected pregame rejection")

def test_capture_manifest_is_price_blind():
    b={"game_pk":1,"hybrid_dk":{"quotes":[{"american_odds":-110}]}}
    r=capture_training_row(b,game_date="2026-10-07",first_pitch_utc="2026-10-07T18:00:00Z",captured_at_utc="2026-10-07T17:00:00Z")
    assert r["pit_strict"] is True
    assert r["contains_sportsbook_prices"] is False
    assert "hybrid_dk" not in str(r)

