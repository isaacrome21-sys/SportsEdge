from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.shared_first_inning_engine import (
    FIRST_INNING_EMPIRICAL_VERSION,
    build_shared_first_inning_engine_session,
)


def _features(value):
    runs = [value] * 10
    return {
        "away_first_inning_runs_for": list(runs),
        "away_first_inning_runs_against": list(runs),
        "home_first_inning_runs_for": list(runs),
        "home_first_inning_runs_against": list(runs),
    }


def _row(market="NRFI", side="YES", value=0):
    return {
        "game_id": "g1",
        "market": market,
        "entity_id": "g1",
        "line": 0.5,
        "side": side,
        "feature_source_hash": "a" * 64,
        "features": _features(value),
    }


def test_zero_run_history_is_stabilized_below_one():
    engine = build_shared_first_inning_engine_session()
    out = engine(_row(value=0))
    assert 0.90 < out["model_p"] < 1.0
    assert out["engine_version"] == FIRST_INNING_EMPIRICAL_VERSION


def test_all_scoring_history_is_stabilized_above_zero():
    engine = build_shared_first_inning_engine_session()
    nrfi = engine(_row(value=1))
    yrfi = engine(_row(market="YRFI", value=1))
    assert 0.0 < nrfi["model_p"] < 0.01
    assert nrfi["model_p"] + yrfi["model_p"] == 1.0


def test_yes_no_and_nrfi_yrfi_are_exact_complements():
    engine = build_shared_first_inning_engine_session()
    nrfi_yes = engine(_row(market="NRFI", side="YES", value=0))["model_p"]
    nrfi_no = engine(_row(market="NRFI", side="NO", value=0))["model_p"]
    yrfi_yes = engine(_row(market="YRFI", side="YES", value=0))["model_p"]
    assert abs(nrfi_yes + nrfi_no - 1.0) < 1e-12
    assert nrfi_no == yrfi_yes


def test_generic_game_adapter_uses_first_inning_features_not_full_game_means():
    out = generic_market_engine_adapter(_row(value=0))
    assert out["engine_version"] == FIRST_INNING_EMPIRICAL_VERSION
    assert out["model_p"] > 0.90
