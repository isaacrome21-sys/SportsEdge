from unittest.mock import patch
from datetime import datetime, timezone
import pytest
from sportsedge.mlb_phone_batter_pricing import phone_batter_rows
from sportsedge.mlb_phone_first_inning_pricing import phone_first_inning_rows
from tests.test_mlb_prop_exact_quote_and_degenerate_tail_20261014 import ExactPairPhoneBridgeTests, NOW
from tests.test_mlb_first_inning import _row, _schedule_getter, _history_games, _fixture_game

@pytest.mark.parametrize("stale", [False, True])
def test_batter_alias_prices_without_refreshing_capture(stale):
    case = ExactPairPhoneBridgeTests()
    case.setUp()
    rows = [case._row("OVER", .5), case._row("UNDER", .5)]
    for row in rows:
        row["captured_at"] = row.pop("quote_captured_at")
        if stale:
            row["captured_at"] = "2026-01-01T00:00:00Z"
    with patch("sportsedge.mlb_phone_batter_pricing.MLBBatterPublicSource.prior_games", return_value=case.verified):
        out, _ = phone_batter_rows(rows, now=NOW)
    assert all("ev_per_dollar" in r for r in out), out
    expected = "STALE_QUOTE" if stale else "RECENT_CAPTURED_QUOTE"
    assert all(r["quote_status"] == expected for r in out)


def test_first_inning_capture_alias_reaches_ev():
    rows = [_row(side="OVER", odds=105), _row(side="UNDER", odds=-140)]
    for row in rows:
        row["captured_at"] = row.pop("quote_captured_at")
    out, _ = phone_first_inning_rows(rows, now=datetime(2026,10,11,20,tzinfo=timezone.utc),
        getter=_schedule_getter(_history_games(), _fixture_game()))
    assert all("ev_per_dollar" in r for r in out), out


def test_pitcher_capture_alias_reaches_ev():
    from sportsedge.mlb_phone_pitcher_pricing import phone_pitcher_rows
    from tests.test_mlb_phone_pitcher_real_public_history import prop, getter, AS_OF
    rows = [prop(), prop(side="UNDER", odds=-114)]
    for row in rows:
        row["captured_at"] = row.pop("quote_captured_at")
    out, _ = phone_pitcher_rows(rows, now=AS_OF, getter=getter)
    assert all("ev_per_dollar" in r for r in out), out
    assert all(r["quote_status"] == "RECENT_CAPTURED_QUOTE" for r in out)
