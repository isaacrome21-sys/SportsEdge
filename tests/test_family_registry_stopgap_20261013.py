"""Independent family policy contract; does not override existing exclusion gates."""
import pytest
from sportsedge.family_market_registry import family_market_decision
from sportsedge.canonical_coverage import coverage_summary, blocked_row_for

@pytest.mark.parametrize("sport", ["NBA", "CBB"])
@pytest.mark.parametrize("market", ["ML", "MONEYLINE", "SPREAD", "TOTAL", "TOTALS"])
def test_family_stopgap_blocks_game_markets(sport, market):
    result = family_market_decision(sport, market)
    assert result["state"] == "BLOCKED"
    assert result["blocker"] == "NO_VALIDATION"
    assert result["validation_status"] == "UNVALIDATED"
    assert result["official_authority"] is False
    assert result["model_p_authority"] is False
    assert result["staking_authority"] is False


@pytest.mark.parametrize("market", ["ML", "MONEYLINE", "SPREAD", "TOTAL", "TOTALS"])
def test_cfb_game_markets_registered_research_only(market):
    # Owner ruling 2026-10-20 (decision packet Option B): the CFB game
    # families register research-only; they are not validated and carry
    # no authority, and per-fixture pricing still requires satisfied
    # Form 2 identity at the runtime gate.
    result = family_market_decision("CFB", market)
    assert result["state"] == "REGISTERED_RESEARCH_ONLY"
    assert result["blocker"] == "NO_VALIDATION"
    assert result["validation_status"] == "NOT_VALIDATED"
    assert result["eligible"] is False and result["promotable"] is False
    assert result["official_authority"] is False
    assert result["model_p_authority"] is False
    assert result["staking_authority"] is False

@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["UNLISTED_MARKET", ""])
def test_unknown_family_market_fails_closed(sport, market):
    result = family_market_decision(sport, market)
    assert result["state"] == "BLOCKED"
    assert result["blocker"] == "NO_ENGINE"
    assert result["staking_authority"] is False


@pytest.mark.parametrize("sport", ["CFB", "CBB"])
def test_player_points_unknown_outside_nba(sport):
    # PLAYER_POINTS became a registered NBA family on 2026-10-20
    # ("Build the engines"); for CFB/CBB it remains unregistered and
    # fails closed exactly as before. The NBA registration itself is
    # asserted in tests/test_nba_prop_engines_20261020.py.
    result = family_market_decision(sport, "PLAYER_POINTS")
    assert result["state"] == "BLOCKED"
    assert result["blocker"] == "NO_ENGINE"
    assert result["staking_authority"] is False


def test_player_passing_yards_registered_for_cfb_only():
    # Registered NOT_VALIDATED for CFB on 2026-10-14 (wiring completion);
    # still an unknown market for NBA/CBB, where it keeps failing closed.
    result = family_market_decision("CFB", "PLAYER_PASSING_YARDS")
    assert result["state"] == "BLOCKED"
    assert result["blocker"] == "NO_VALIDATION"
    assert result["validation_status"] == "UNVALIDATED"
    assert result["staking_authority"] is False
    for sport in ("NBA", "CBB"):
        other = family_market_decision(sport, "PLAYER_PASSING_YARDS")
        assert other["state"] == "BLOCKED"
        assert other["blocker"] == "NO_ENGINE"
        assert other["staking_authority"] is False


def test_phase_one_coverage_unchanged_and_il_exclusions_not_shadowed():
    assert coverage_summary()["markets_total"] == 89
    assert blocked_row_for("NBA", "PLAYER_POINTS", {"market": "X"}) is None
    assert family_market_decision("MLB", "MONEYLINE") is None
