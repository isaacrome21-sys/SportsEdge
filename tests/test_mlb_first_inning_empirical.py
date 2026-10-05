from scripts import research_mlb_f5_nrfi_tightening as RESEARCH
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
        "league_first_inning_scoreless_rate": league_zero,
        "league_prior_halves": 1000,
        "league_prior_strength": 30,
    }


def _row(market="NRFI", side="YES", value=0, league_zero=0.72):
    return {
        "game_id": "g1",
        "market": market,
        "entity_id": "g1",
        "line": 0.5,
        "side": side,
        "feature_source_hash": "a" * 64,
        "features": _features(value, league_zero=league_zero),
    }


def test_zero_run_history_is_stabilized_below_one():
    engine = build_shared_first_inning_engine_session()
    out = engine(_row(value=0, league_zero=0.95))
    assert 0.90 < out["model_p"] < 1.0
    assert out["engine_version"] == FIRST_INNING_EMPIRICAL_VERSION


def test_all_scoring_history_is_stabilized_above_zero():
    engine = build_shared_first_inning_engine_session()
    nrfi = engine(_row(value=1, league_zero=0.20))
    yrfi = engine(_row(market="YRFI", value=1, league_zero=0.20))
    assert 0.0 < nrfi["model_p"] < 0.05
    assert nrfi["model_p"] + yrfi["model_p"] == 1.0


def test_yes_no_and_nrfi_yrfi_are_exact_complements():
    engine = build_shared_first_inning_engine_session()
    nrfi_yes = engine(_row(market="NRFI", side="YES", value=0))["model_p"]
    nrfi_no = engine(_row(market="NRFI", side="NO", value=0))["model_p"]
    yrfi_yes = engine(_row(market="YRFI", side="YES", value=0))["model_p"]
    assert abs(nrfi_yes + nrfi_no - 1.0) < 1e-12
    assert nrfi_no == yrfi_yes


def test_generic_game_adapter_uses_first_inning_features_not_full_game_means():
    out = generic_market_engine_adapter(_row(value=0, league_zero=0.95))
    assert out["engine_version"] == FIRST_INNING_EMPIRICAL_VERSION
    assert out["model_p"] > 0.90


def test_m30_formula_matches_held_out_research_recipe():
    engine = build_shared_first_inning_engine_session()
    row = _row(value=0, league_zero=0.72)
    row["features"]["away_first_inning_runs_for"] = [0] * 7 + [1] * 3
    row["features"]["home_first_inning_runs_against"] = [0] * 6 + [1] * 4
    row["features"]["home_first_inning_runs_for"] = [0] * 6 + [1] * 4
    row["features"]["away_first_inning_runs_against"] = [0] * 8 + [1] * 2

    def zero_p(values):
        return (sum(int(v == 0) for v in values) + 0.5 + 30 * 0.72) / (len(values) + 31.0)

    away_zero = 0.5 * (
        zero_p(row["features"]["away_first_inning_runs_for"])
        + zero_p(row["features"]["home_first_inning_runs_against"])
    )
    home_zero = 0.5 * (
        zero_p(row["features"]["home_first_inning_runs_for"])
        + zero_p(row["features"]["away_first_inning_runs_against"])
    )
    expected = away_zero * home_zero
    out = engine(row)
    assert abs(out["model_p"] - expected) < 1e-12


def test_engine_matches_winning_research_direct_m30_recipe():
    row = _row(value=0, league_zero=0.72)
    features = row["features"]
    features["away_first_inning_runs_for"] = [0] * 7 + [1] * 3
    features["home_first_inning_runs_against"] = [0] * 6 + [1] * 4
    features["home_first_inning_runs_for"] = [0] * 6 + [1] * 4
    features["away_first_inning_runs_against"] = [0] * 8 + [1] * 2

    away = [
        {
            "i1_for": offense,
            "i1_against": allowed,
        }
        for offense, allowed in zip(
            features["away_first_inning_runs_for"],
            features["away_first_inning_runs_against"],
        )
    ]
    home = [
        {
            "i1_for": offense,
            "i1_against": allowed,
        }
        for offense, allowed in zip(
            features["home_first_inning_runs_for"],
            features["home_first_inning_runs_against"],
        )
    ]
    expected = RESEARCH.direct_nrfi(away, home, 0.72, 30)
    actual = build_shared_first_inning_engine_session()(row)["model_p"]
    assert abs(actual - expected) < 1e-12


def test_league_prior_contract_fails_closed():
    engine = build_shared_first_inning_engine_session()
    bad = _row()
    bad["features"]["league_prior_strength"] = 15
    try:
        engine(bad)
    except Exception as exc:
        assert "strength" in str(exc).lower()
    else:
        raise AssertionError("expected league prior strength drift to fail closed")
