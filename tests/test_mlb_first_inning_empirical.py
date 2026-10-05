from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.shared_first_inning_engine import (
    FIRST_INNING_EMPIRICAL_VERSION,
    build_shared_first_inning_engine_session,
)


def _features(value, league_zero=0.72):
    runs = [value] * 10
    return {
        "away_first_inning_runs_for": list(runs),
        "away_first_inning_runs_against": list(runs),
        "home_first_inning_runs_for": list(runs),
        "home_first_inning_runs_against": list(runs),
        "league_first_inning_zero_rate": league_zero,
        "league_half_innings": 400,
        "league_prior_strength": 30,
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


def test_zero_run_history_is_shrunk_toward_league_prior():
    engine = build_shared_first_inning_engine_session()
    out = engine(_row(value=0))
    zero_component = (10.0 + 0.5 + 30.0 * 0.72) / 41.0
    assert abs(out["model_p"] - zero_component ** 2) < 1e-12
    assert 0.0 < out["model_p"] < 1.0
    assert out["engine_version"] == FIRST_INNING_EMPIRICAL_VERSION


def test_all_scoring_history_is_shrunk_away_from_zero():
    engine = build_shared_first_inning_engine_session()
    nrfi = engine(_row(value=1))
    yrfi = engine(_row(market="YRFI", value=1))
    zero_component = (0.5 + 30.0 * 0.72) / 41.0
    assert abs(nrfi["model_p"] - zero_component ** 2) < 1e-12
    assert 0.0 < nrfi["model_p"] < 1.0
    assert nrfi["model_p"] + yrfi["model_p"] == 1.0


def test_missing_or_wrong_league_prior_fails_closed():
    engine = build_shared_first_inning_engine_session()
    row = _row(value=0)
    del row["features"]["league_first_inning_zero_rate"]
    try:
        engine(row)
    except Exception as exc:
        assert "league_first_inning_zero_rate" in str(exc)
    else:
        raise AssertionError("missing league prior should fail closed")

    row = _row(value=0)
    row["features"]["league_prior_strength"] = 15
    try:
        engine(row)
    except Exception as exc:
        assert "league_prior_strength" in str(exc)
    else:
        raise AssertionError("wrong held-out strength should fail closed")


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
    assert 0.0 < out["model_p"] < 1.0
