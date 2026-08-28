import pytest

from sportsedge.engine_registry import EngineDispatchError, resolve_manual_market_type


def test_explicit_nrfi_and_yrfi_still_resolve():
    assert resolve_manual_market_type("NRFI") == "NRFI"
    assert resolve_manual_market_type("YRFI") == "YRFI"


def test_generic_first_inning_total_fails_closed_instead_of_aliasing_to_yrfi():
    with pytest.raises(EngineDispatchError, match="NO_ENGINE_FOR_MARKET: FIRST_INNING_TOTAL"):
        resolve_manual_market_type("FIRST_INNING_TOTAL")
