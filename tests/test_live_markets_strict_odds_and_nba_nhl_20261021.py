"""Adversarial tests for LiveMarketQuote strict odds, identity, and NBA/NHL registry."""

from datetime import datetime, timezone
import math
import pytest

from sportsedge.live_markets import LiveMarketError, LiveMarketQuote, SPORT_LIVE_MARKETS


def _valid_kwargs(**overrides):
    base = dict(
        sport="NBA",
        event_id="EVT1",
        book="DK",
        market="MONEYLINE",
        contract_key="ml",
        focal_selection="Home",
        opposite_selection="Away",
        focal_odds=-110,
        opposite_odds=-110,
        source_as_of=datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 10, 21, 20, 1, tzinfo=timezone.utc),
        active=True,
        provider="dk",
    )
    base.update(overrides)
    return base


def test_nba_and_nhl_registered():
    assert "NBA" in SPORT_LIVE_MARKETS
    assert "NHL" in SPORT_LIVE_MARKETS
    assert "MONEYLINE" in SPORT_LIVE_MARKETS["NBA"]
    assert "PUCK_LINE" in SPORT_LIVE_MARKETS["NHL"]


def test_valid_nba_quote_passes():
    q = LiveMarketQuote(**_valid_kwargs())
    assert q.governance_status == "PAIRED_QUOTE_READY"
    assert q.paired


@pytest.mark.parametrize("bad_odds", [True, False, "110", math.nan, math.inf, -math.inf, 50, -50, 0])
def test_invalid_odds_rejected(bad_odds):
    with pytest.raises(LiveMarketError):
        LiveMarketQuote(**_valid_kwargs(focal_odds=bad_odds)).validate()


def test_same_selection_rejected():
    with pytest.raises(LiveMarketError, match="distinct"):
        LiveMarketQuote(**_valid_kwargs(opposite_selection="  home  ")).validate()


def test_blank_identity_rejected():
    with pytest.raises(LiveMarketError):
        LiveMarketQuote(**_valid_kwargs(event_id="   ")).validate()


def test_naive_timestamp_rejected():
    with pytest.raises(LiveMarketError, match="timezone-aware"):
        LiveMarketQuote(**_valid_kwargs(source_as_of=datetime(2026, 10, 21, 20, 0))).validate()
