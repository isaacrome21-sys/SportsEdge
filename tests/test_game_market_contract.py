import pytest

from sportsedge.game_market_contract import (
    canonical_game_market,
    game_market_policy,
    recognized_game_markets,
    require_official_eligibility,
)


def test_aliases_are_canonicalized():
    assert canonical_game_market("moneyline") == "ML"
    assert canonical_game_market("run line") == "RL"
    assert canonical_game_market("totals") == "TOTAL"
    assert canonical_game_market("nrfi") == "NRFI"
    assert canonical_game_market("yrfi") == "YRFI"


def test_requested_game_market_families_are_recognized():
    assert recognized_game_markets() == {"ML", "RL", "TOTAL", "NRFI", "YRFI"}


def test_ml_and_first_inning_are_registry_eligible():
    assert require_official_eligibility("ML").validation_status == "PASS_BETA"
    assert require_official_eligibility("NRFI").validation_status == "PASS_GATED"
    assert require_official_eligibility("YRFI").validation_status == "PASS_GATED"


def test_run_line_stays_blocked():
    p = game_market_policy("RL")
    assert p.official_eligible is False
    assert p.validation_status == "BLOCKED_DEPLOYMENT_PARITY"
    with pytest.raises(ValueError, match="MARKET_VALIDATION_BLOCK"):
        require_official_eligibility("RL")


def test_full_game_total_stays_blocked():
    p = game_market_policy("TOTAL")
    assert p.official_eligible is False
    assert p.validation_status == "BLOCKED_FRESH_CALIBRATION"
    with pytest.raises(ValueError, match="MARKET_VALIDATION_BLOCK"):
        require_official_eligibility("TOTAL")


def test_unknown_market_fails_closed():
    with pytest.raises(ValueError, match="UNSUPPORTED_GAME_MARKET"):
        game_market_policy("made_up_market")
