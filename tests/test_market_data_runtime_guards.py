from datetime import datetime, timezone
from io import BytesIO
from urllib.error import HTTPError

import pytest

from sportsedge.market_data_contract import MarketQuote, PublicBettingSplit
from sportsedge.market_data_runtime import decide_market_runtime, public_split_context
from sportsedge.the_odds_api_live import TheOddsApiError, _get_json


UTC = timezone.utc


def _quote(*, in_play: bool) -> MarketQuote:
    now = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
    return MarketQuote(
        provider="THE_ODDS_API",
        book="draftkings",
        sport_key="americanfootball_nfl",
        provider_event_id="evt-1",
        market="spreads",
        selection="Example",
        american_odds=-110,
        captured_at=now,
        provider_updated_at=now,
        raw_payload_sha256="a" * 64,
        commence_time=now if in_play else datetime(2026, 9, 14, 4, 0, tzinfo=UTC),
        in_play=in_play,
    )


def test_live_quote_is_no_engine_zero_unit_paper_even_with_authorities():
    decision = decide_market_runtime(
        _quote(in_play=True), model_p_authority=True, staking_authority=True
    )
    assert decision.status == "NO_ENGINE"
    assert decision.live_engine_status == "NO_ENGINE"
    assert decision.card_stage == "PAPER"
    assert decision.stake_units == 0.0
    assert decision.model_p_authority is False
    assert decision.staking_authority is False


def test_pregame_model_without_staking_authority_is_zero_unit_paper():
    decision = decide_market_runtime(
        _quote(in_play=False), model_p_authority=True, staking_authority=False
    )
    assert decision.status == "MODEL_ONLY_NO_STAKING"
    assert decision.card_stage == "PAPER"
    assert decision.stake_units == 0.0


def test_public_split_is_single_source_unverified_and_scrape_failure_is_explicit():
    split = PublicBettingSplit(
        source="ACTION_NETWORK",
        sport_key="americanfootball_nfl",
        event_key="evt-1",
        market="SPREAD",
        selection="Example",
        ticket_percent=78.0,
        money_percent=54.0,
        captured_at=datetime(2026, 9, 14, 3, 0, tzinfo=UTC),
        raw_payload_sha256="b" * 64,
    )
    context = public_split_context(split, scrape_ok=False)
    assert context["source_scope"] == "SINGLE_SOURCE_UNVERIFIED"
    assert context["source_methodology"] == "UNDISCLOSED"
    assert context["scrape_health"] == "SCRAPE_FAILED_OR_LAYOUT_CHANGED"
    assert context["empty_means_no_signal"] is False
    assert context["model_p_input"] is False
    assert context["truth_gate_input"] is False
    assert context["confidence_vote"] is False


def test_401_is_machine_readable_and_api_key_is_redacted():
    secret = "super-secret-key"
    url = f"https://api.the-odds-api.com/v4/sports/x/odds?apiKey={secret}&regions=us"

    def opener(request_url, timeout=20):
        raise HTTPError(request_url, 401, "Unauthorized", hdrs=None, fp=BytesIO(b""))

    with pytest.raises(TheOddsApiError) as excinfo:
        _get_json(url, opener=opener)
    text = str(excinfo.value)
    assert text.startswith("PROVIDER_AUTH_FAILED_401:")
    assert secret not in text
    assert "REDACTED" in text
