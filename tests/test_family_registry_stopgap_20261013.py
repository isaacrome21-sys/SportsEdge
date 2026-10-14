"""Fail-closed research family registry contract: no model promotion."""
from sportsedge.canonical_coverage import resolve_market, blocked_row_for, BLOCKED
import pytest

@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["ML", "MONEYLINE", "SPREAD", "TOTAL", "TOTALS"])
def test_family_stopgap_blocks_all_game_markets(sport, market):
    result = resolve_market(sport, market)
    assert result["state"] == BLOCKED
    assert result["blocker"] == "NO_VALIDATION"
    assert result["validation_status"] == "UNVALIDATED"
    row = blocked_row_for(sport, market, {"market": market, "side": "HOME"})
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["research_only"] is True
    assert row["official_authority"] is False
    assert row["model_p_authority"] is False
    assert row["staking_authority"] is False

@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["PLAYER_PASSING_YARDS", "PLAYER_POINTS", "UNLISTED_MARKET", ""])
def test_unregistered_family_market_fails_closed(sport, market):
    result = resolve_market(sport, market)
    assert result["state"] == BLOCKED
    assert result["blocker"] == "NO_ENGINE"
    row = blocked_row_for(sport, market, {"market": market})
    assert row["staking_authority"] is False
    assert row["model_p_authority"] is False
