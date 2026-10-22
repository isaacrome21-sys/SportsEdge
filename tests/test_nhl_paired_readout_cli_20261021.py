"""NHL two-sided operator quotes in the local CLI remain unverified research."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.run_cfb_nhl_research_readout import run_payload


NOW = datetime(2026, 10, 21, 17, 0, tzinfo=timezone.utc)


def fixture(market="MONEYLINE", line=None):
    if market == "TOTAL":
        sides = ("OVER", "UNDER")
    else:
        sides = ("AWAY", "HOME")
    return {
        "as_of": NOW.isoformat(), "nhl_games": [{
            "away": "Flyers", "home": "Sabres", "event_id": "evt-a",
            "fixture_source_ref": "operator-nhl-fixture",
            "event_start": (NOW + timedelta(hours=5)).isoformat(),
            "paired_markets": [{
                "market": market, "capture_id": "C123",
                "quote_source_ref": "operator-dk-receipt",
                "quote_rows": [
                    {"side": sides[0], "odds": +120,
                     "line": line, "capture_id": "C123",
                     "captured_at": (NOW-timedelta(seconds=20)).isoformat()},
                    {"side": sides[1], "odds": -140,
                     "line": -line if market=="PUCK_LINE" else line,
                     "capture_id": "C123",
                     "captured_at": (NOW-timedelta(seconds=23)).isoformat()}
                ]
            }]
        }]
    }


@pytest.mark.parametrize("market,line", [
    ("MONEYLINE",None),("TOTAL",6.5),("PUCK_LINE",1.5)])
def test_nhl_cli_opt_in_diagnostics_research_only(market,line):
    report=run_payload(fixture(market,line))
    assert report["count"]==1
    diagnostic=report["items"][0]["paired_market_diagnostics"][0]
    assert diagnostic["market"]==market
    assert diagnostic["gap_is_not_edge"] is True
    assert diagnostic["play_authority"] is False
    assert report["book_quote_authentication"]=="NONE"


def test_nhl_cli_stale_quote_refused_not_retimed():
    p=fixture("TOTAL",6.5)
    p["nhl_games"][0]["paired_markets"][0]["quote_rows"][0]["captured_at"]=(
        NOW-timedelta(seconds=200)).isoformat()
    with pytest.raises(ValueError,match="NHL_QUOTE_STALE"):
        run_payload(p)


def test_nhl_cli_never_fills_unoffered_opposite_side():
    p=fixture()
    p["nhl_games"][0]["paired_markets"][0]["quote_rows"].pop()
    with pytest.raises(ValueError,match="NHL_MARKET_TWO_SIDED_REQUIRED"):
        run_payload(p)


def test_nhl_cli_duplicate_market_pair_fails_closed():
    p=fixture()
    p["nhl_games"][0]["paired_markets"].append(
        dict(p["nhl_games"][0]["paired_markets"][0]))
    with pytest.raises(ValueError,match="NHL_DUPLICATE_MARKET_PAIR"):
        run_payload(p)
