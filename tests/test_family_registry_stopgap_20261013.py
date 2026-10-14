"""Independent family policy contract; does not override existing exclusion gates."""
import pytest
from sportsedge.family_market_registry import family_market_decision
from sportsedge.canonical_coverage import coverage_summary, blocked_row_for

@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["ML", "MONEYLINE", "SPREAD", "TOTAL", "TOTALS"])
def test_family_stopgap_blocks_game_markets(sport, market):
    result = family_market_decision(sport, market)
    assert result["state"] == "BLOCKED"
    assert result["blocker"] == "NO_VALIDATION"
    assert result["validation_status"] == "UNVALIDATED"
    assert result["official_authority"] is False
    assert result["model_p_authority"] is False
    assert result["staking_authority"] is False

@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["PLAYER_PASSING_YARDS", "PLAYER_POINTS", "UNLISTED_MARKET", ""])
def test_unknown_family_market_fails_closed(sport, market):
    result = family_market_decision(sport, market)
    assert result["state"] == "BLOCKED"
    assert result["blocker"] == "NO_ENGINE"
    assert result["staking_authority"] is False


def test_phase_one_coverage_unchanged_and_il_exclusions_not_shadowed():
    assert coverage_summary()["markets_total"] == 89
    assert blocked_row_for("NBA", "PLAYER_POINTS", {"market": "X"}) is None
    assert family_market_decision("MLB", "MONEYLINE") is None
