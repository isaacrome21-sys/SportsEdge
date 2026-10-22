"""Known-failed NBA game families remain visible without false +EV authority.

These tests enforce presentation/routing only. They do NOT improve the
underlying rating forecast or grant a new historical market-screen verdict.
"""
from datetime import datetime, timezone
from artifacts import free_models


NOW = datetime(2026, 10, 21, 17, 0, tzinfo=timezone.utc)


def _row(market, side, line=None, price=-110, *, captured_at="2026-10-21T17:00:00+00:00"):
    row = {
        "sport": "NBA", "away": "Minnesota Timberwolves",
        "home": "Miami Heat", "market": market, "side": side,
        "odds": price, "quote_captured_at": captured_at,
        "commence_time": "2026-10-21T23:30:00+00:00",
    }
    if line is not None:
        row["line"] = line
    return row


def test_nba_total_failed_market_score_is_watch_not_candidate():
    row = _row("TOTAL", "UNDER", 243.5)
    result = free_models.calculate(row, free_models.PublicContext(NOW),
                                   NOW, auto_context=False)
    assert result["status"] == "WATCH_NBA_GAME_FAILED_VALIDATION"
    assert result["model_validation"] == "FAILED_VALIDATION"
    assert result["research_only"] is True
    assert result["validated_profitability"] is False
    assert result["independent_projection"]["projected_total"] > 0
    assert "NBA_GAME_MARKET_FAILED_ACCURACY_TEST" in result["reason"]


def test_nba_moneyline_and_spread_fail_in_same_way():
    for row in (_row("SPREAD", "HOME", -2.5),
                _row("ML", "HOME")):
        result = free_models.calculate(row, free_models.PublicContext(NOW),
                                       NOW, auto_context=False)
        assert result["status"] == "WATCH_NBA_GAME_FAILED_VALIDATION"
        assert result["model_validation"] == "FAILED_VALIDATION"


def test_stale_quote_reason_precedes_accuracy_watch_and_never_enters_candidates():
    row = _row("TOTAL", "UNDER", 243.5,
               captured_at="2026-10-20T17:00:00+00:00")
    result = free_models.calculate(row, free_models.PublicContext(NOW),
                                   NOW, auto_context=False)
    assert result["status"] == "WATCH_QUOTE_NOT_CURRENT"
    card = free_models.run([row], now=NOW, auto_context=False)
    assert card["independent_candidates"] == []
    assert card["edges"] == []
    assert card["nba_game_card_integrity"]["family_validation"] == "FAILED_VALIDATION"


def test_fresh_nba_failed_rows_visible_as_watch_not_picks():
    card = free_models.run([_row("TOTAL", "UNDER", 243.5),
                            _row("TOTAL", "UNDER", 235.5),
                            _row("TOTAL", "UNDER", 236.5)],
                           now=NOW, auto_context=False, min_ev=-100)
    assert card["independent_candidates"] == []
    assert card["edges"] == []
    assert len(card["independent_watchlist"]) == 3
    integrity = card["nba_game_card_integrity"]
    assert integrity["apparent_positive_gap_total_rows"] == 3
    assert integrity["under_rows"] == 3
    assert integrity["over_rows"] == 0
    assert integrity["same_direction_concentration"] is True
    assert integrity["positive_ev_candidate_authority"] is False
    assert len(card["evaluated_rows"]) == 3


def test_mixed_directions_not_false_all_under():
    rows = [_row("TOTAL", "UNDER", 243.5),
            _row("TOTAL", "OVER", 200.5),
            _row("TOTAL", "UNDER", 250.5)]
    card = free_models.run(rows, now=NOW, auto_context=False, min_ev=-100)
    integrity = card["nba_game_card_integrity"]
    assert integrity["under_rows"] == 2
    assert integrity["over_rows"] == 1
    assert integrity["same_direction_concentration"] is False
