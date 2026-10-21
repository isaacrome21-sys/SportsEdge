"""NHL paired quote market readout: no invented sides, time, or PLAY."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from sportsedge.research.nhl_paired_market_readout_v1 import nhl_paired_market_readout


NOW = datetime(2026, 10, 21, 17, 0, tzinfo=timezone.utc)
EVENT = NOW + timedelta(hours=5)


def case(market, *, line=None):
    sides = {"MONEYLINE": ("AWAY", "HOME"), "TOTAL": ("OVER", "UNDER"),
             "PUCK_LINE": ("AWAY", "HOME")}[market]
    return {
        "away": "Flyers", "home": "Sabres", "event_id": "evt-1",
        "fixture_source_ref": "fixture-operator-path",
        "quote_source_ref": "dk-operator-path",
        "capture_id": "capture-1", "as_of": NOW.isoformat(),
        "event_start": EVENT.isoformat(), "market": market,
        "quote_rows": [
            {"side": sides[0], "line": line, "odds": 120,
             "capture_id": "capture-1",
             "captured_at": (NOW-timedelta(seconds=20)).isoformat()},
            {"side": sides[1],
             "line": -line if market == "PUCK_LINE" else line,
             "odds": -140, "capture_id": "capture-1",
             "captured_at": (NOW-timedelta(seconds=22)).isoformat()}
        ],
    }


@pytest.mark.parametrize("market,line", [
    ("MONEYLINE", None), ("TOTAL", 6.5), ("PUCK_LINE", 1.5)])
def test_research_market_pairs_conserve_mass_and_never_authenticate(market, line):
    result = nhl_paired_market_readout(**case(market, line=line))
    assert abs(sum(result["rate_v1_model"].values())-1) < 1e-8
    assert abs(sum(result["same_book_no_vig"].values())-1) < 1e-8
    assert result["status"] == "UNVALIDATED_MARKET_DIAGNOSTIC"
    assert result["quote_authentication"].startswith("OPERATOR_DECLARATION")
    assert result["play_authority"] is False
    assert result["gap_is_not_edge"] is True


def test_refuse_single_side_missing_pair():
    kwargs = case("TOTAL", line=6.5)
    kwargs["quote_rows"].pop()
    with pytest.raises(ValueError, match="TWO_SIDED_REQUIRED"):
        nhl_paired_market_readout(**kwargs)


def test_refuse_stale_quote():
    kwargs = case("MONEYLINE")
    kwargs["quote_rows"][0]["captured_at"] = (NOW-timedelta(seconds=181)).isoformat()
    with pytest.raises(ValueError, match="QUOTE_STALE"):
        nhl_paired_market_readout(**kwargs)


def test_refuse_backdated_after_tip_and_future_capture():
    kwargs = case("MONEYLINE")
    kwargs["event_start"] = NOW.isoformat()
    with pytest.raises(ValueError, match="EVENT_STARTED"):
        nhl_paired_market_readout(**kwargs)
    kwargs = case("MONEYLINE")
    kwargs["quote_rows"][0]["captured_at"] = (NOW+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="IN_FUTURE"):
        nhl_paired_market_readout(**kwargs)


def test_refuse_mismatched_total_and_puck_lines():
    kwargs = case("TOTAL", line=6.5)
    kwargs["quote_rows"][1]["line"] = 5.5
    with pytest.raises(ValueError, match="TOTAL_PAIR_LINE_MISMATCH"):
        nhl_paired_market_readout(**kwargs)
    kwargs = case("PUCK_LINE", line=1.5)
    kwargs["quote_rows"][1]["line"] = 1.5
    with pytest.raises(ValueError, match="PUCK_LINE_PAIR_MISMATCH"):
        nhl_paired_market_readout(**kwargs)


def test_refuse_captured_from_different_batch_or_book():
    kwargs = case("MONEYLINE")
    kwargs["quote_rows"][1]["capture_id"] = "other"
    with pytest.raises(ValueError, match="CAPTURE_ID_MISMATCH"):
        nhl_paired_market_readout(**kwargs)
    kwargs = case("MONEYLINE")
    kwargs["book"] = "not-DK"
    with pytest.raises(ValueError, match="BOOK_NOT_DRAFTKINGS"):
        nhl_paired_market_readout(**kwargs)


def test_refuse_invalid_odds_and_naive_quote_time():
    kwargs = case("MONEYLINE")
    kwargs["quote_rows"][0]["odds"] = -99
    with pytest.raises(ValueError, match="ODDS_INVALID"):
        nhl_paired_market_readout(**kwargs)
    kwargs = case("MONEYLINE")
    kwargs["quote_rows"][0]["captured_at"] = "2026-10-21T17:00:00"
    with pytest.raises(ValueError, match="CAPTURE_TIME_NAIVE"):
        nhl_paired_market_readout(**kwargs)


def test_refuse_quote_pair_older_than_150_second_capture_span():
    kwargs = case("TOTAL", line=6.5)
    kwargs["quote_rows"][0]["captured_at"] = (NOW-timedelta(seconds=180)).isoformat()
    kwargs["quote_rows"][1]["captured_at"] = NOW.isoformat()
    with pytest.raises(ValueError, match="PAIR_CAPTURE_SPAN_EXCEEDED"):
        nhl_paired_market_readout(**kwargs)
