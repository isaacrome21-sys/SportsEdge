"""NBA failed-family score integrity at the structured and phone-card boundary.

This does not change projections, line sidedness, frozen models or evaluation.
"""
from datetime import datetime, timezone

from artifacts import free_models
from scripts.free_models_phone_issue import render_card


NOW = datetime(2026, 10, 21, 17, 0, tzinfo=timezone.utc)


def _row(market="TOTAL", side="UNDER", line=240.5, *,
         captured_at="2026-10-21T17:00:00+00:00"):
    result = {
        "sport": "NBA", "away": "Minnesota Timberwolves",
        "home": "Miami Heat", "market": market, "side": side,
        "odds": -110, "quote_captured_at": captured_at,
        "commence_time": "2026-10-21T23:30:00+00:00",
    }
    if line is not None:
        result["line"] = line
    return result


def test_failed_total_preserves_projection_without_score():
    row = free_models.calculate(_row(), free_models.PublicContext(NOW),
                                NOW, auto_context=False)
    assert row["status"] == "WATCH_NBA_GAME_FAILED_VALIDATION"
    assert row["score"] is None and row["score_0_100"] is None
    assert row["score_authority"] is False
    assert row["score_status"] == "WITHHELD_FAILED_NBA_GAME_VALIDATION"
    assert row["independent_projection"]["projected_total"] > 0
    assert row["selection"] == "UNDER 240.5"
    assert row["line"] == 240.5


def test_failed_game_moneyline_and_spread_have_no_score():
    for market, side, line in (("ML", "HOME", None),
                               ("SPREAD", "AWAY", 2.5)):
        row = free_models.calculate(_row(market, side, line),
                                    free_models.PublicContext(NOW),
                                    NOW, auto_context=False)
        assert row["score"] is None and row["score_0_100"] is None
        assert row["score_authority"] is False
        assert row["model_validation"] == "FAILED_VALIDATION"


def test_stale_quote_stays_stale_and_cannot_gain_score():
    row = free_models.calculate(
        _row(captured_at="2026-10-20T17:00:00+00:00"),
        free_models.PublicContext(NOW), NOW, auto_context=False,
    )
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["score"] is None
    assert row["score_status"] == "WITHHELD_FAILED_NBA_GAME_VALIDATION"
    assert "QUOTE_NOT_FRESH" in row["reason"]


def test_all_under_diagnostics_are_visible_without_fake_99s():
    # Eleven raw directions remain eleven raw directions; neither inversion
    # nor cherry-picking can create a balanced bet shortlist.
    prices = [231.5, 234.5, 234.5, 237.5, 239.5, 240.5,
              239.5, 229.5, 242.5, 219.5, 227.5]
    rows = [_row(line=line) for line in prices]
    card = free_models.run(rows, now=NOW, auto_context=False, min_ev=-100)
    assert len(card["evaluated_rows"]) == 11
    assert all(row["score"] is None for row in card["evaluated_rows"])
    assert card["independent_candidates"] == []
    assert card["edges"] == []
    assert card["nba_game_card_integrity"]["numeric_quality_scores_allowed"] is False
    assert card["nba_game_card_integrity"]["score_policy"] == "WITHHELD_FAILED_NBA_GAME_VALIDATION"
    assert card["nba_game_card_integrity"]["under_rows"] == 11

    # The renderer must not trust an arbitrary score injected upstream.
    card["evaluated_rows"][0]["score"] = 99
    visible = render_card(card)
    assert "failed-model diagnostics, no 0–100 Score" in visible
    assert "11 UNDER / 0 OVER" in visible
    assert visible.count("WATCH_NBA_GAME_FAILED_VALIDATION") == 11
    assert "99/100" not in visible
    assert "| 99 |" not in visible
    assert "Raw diagnostic selection" in visible
    assert "projection, direction, quote and source receipt" in visible


def test_mixed_total_directions_are_preserved_not_forced_balanced():
    card = free_models.run(
        [_row(side="OVER", line=210.5), _row(side="UNDER", line=250.5)],
        now=NOW, auto_context=False, min_ev=-100,
    )
    visible = render_card(card)
    assert "OVER 210.5" in visible and "UNDER 250.5" in visible
    assert "1 UNDER / 1 OVER" in visible
