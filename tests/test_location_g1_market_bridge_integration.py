"""Real-dependency G1 -> frozen score grid -> coherent game/prop research test."""
from __future__ import annotations

import pytest

from sportsedge.sports.nfl.location_g1_market_bridge import run_location_g1_research_market_bridge
from sportsedge.sports.nfl.location_symmetric_g1 import (
    CANDIDATE_FAMILY, MODEL_ID, MARGIN_DIFF_KEYS, MARGIN_FEATURE_NAMES,
    TOTAL_FEATURE_NAMES, TOTAL_SUM_KEYS, NFLSymmetricLocationG1,
)
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT


def _model():
    m, t = len(MARGIN_FEATURE_NAMES), len(TOTAL_FEATURE_NAMES)
    return NFLSymmetricLocationG1(
        model_id=MODEL_ID, candidate_family=CANDIDATE_FAMILY,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        margin_feature_names=MARGIN_FEATURE_NAMES,
        total_feature_names=TOTAL_FEATURE_NAMES,
        margin_feature_means=(0.0,) * m, margin_feature_scales=(1.0,) * m,
        margin_coefficients=(3.0,) + (0.0,) * m,
        total_feature_means=(0.0,) * t, total_feature_scales=(1.0,) * t,
        total_coefficients=(45.0,) + (0.0,) * t,
        margin_alpha=10.0, total_alpha=10.0, train_seasons=(2021, 2022),
    )


def _features():
    side = {key: 0.0 for key in set(MARGIN_DIFF_KEYS) | set(TOTAL_SUM_KEYS)}
    side.update({
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "feature_asof_ts": "2026-10-08T11:00:00Z",
        "wind_mph": 5.0, "roof_closed": 0.0, "prior_weight": 0.5,
    })
    return {"game_id": "2026_05_AWAY_HOME", "home_features": dict(side), "away_features": dict(side)}


def _player(name, position, **rates):
    role = {
        "pass_attempts": 0.0, "completion_rate": 0.0,
        "pass_yards_per_completion": 0.0, "pass_td_rate": 0.0,
        "interception_rate": 0.0, "rush_attempts": 0.0,
        "rush_yards_per_attempt": 0.0, "targets": 0.0,
        "catch_rate": 0.0, "receiving_yards_per_reception": 0.0,
    }
    role.update(rates)
    return {"player": name, "position": position, "role_prior": role,
            "trailing": {}, "sample_size": 0,
            "context": {"shared_workload_sigma": 0.06}}


def _team():
    return {
        "qb": _player("H_QB", "QB", pass_attempts=34.0,
                      completion_rate=0.65, pass_yards_per_completion=11.0,
                      pass_td_rate=0.05, interception_rate=0.025,
                      rush_attempts=4.0, rush_yards_per_attempt=4.5),
        "skill_players": [
            _player("H_WR", "WR", targets=9.0, catch_rate=0.65,
                    receiving_yards_per_reception=12.0),
            _player("H_RB", "RB", rush_attempts=14.0,
                    rush_yards_per_attempt=4.2, targets=4.0,
                    catch_rate=0.7, receiving_yards_per_reception=7.0),
        ],
    }


def _kwargs():
    return dict(
        model=_model(), game_features=_features(),
        observed_at="2026-10-08T12:00:00Z",
        game_start_ts="2026-10-08T17:00:00Z",
        game_id="2026_05_AWAY_HOME", home_team="HOME", away_team="AWAY",
        game_markets=[
            {"market": "moneyline", "selection": "home"},
            {"market": "spread", "selection": "home", "line": -3.5},
            {"market": "total", "selection": "under", "line": 45.5},
            {"market": "team_total", "team": "home", "selection": "over", "line": 23.5},
        ],
        prop_markets=[
            {"team": "home", "player": "H_QB", "market": "passing_yards",
             "selection": "over", "line": 220.5},
            {"team": "home", "player": "H_WR", "market": "receiving_yards",
             "selection": "over", "line": 65.5},
        ],
        home_model=_team(), n_sims=120, seed=27,
    )


def test_coherent_game_and_prop_research_market_prices():
    out = run_location_g1_research_market_bridge(**_kwargs())
    assert out["attempt9_raw"] is None
    assert out["score_means"] == {"mean_home": 24.0, "mean_away": 21.0}
    assert out["score_distribution"]["location_source"] == "LOCATION_SYMMETRIC_G1_RESEARCH"
    assert len(out["game_markets"]) == 4
    assert len(out["prop_markets"]) == 2
    for row in out["game_markets"] + out["prop_markets"]:
        assert row["status"] == "PRICED_RESEARCH", row
        assert row["estimate_p"] + row["loss_p"] + row["push_p"] == pytest.approx(1.0)
    assert out["location_g1_raw"]["training_lineage_verified"] is False
    assert out["authority"]["research_only"] is True
    assert all(not out["authority"][key] for key in (
        "creates_model_p", "official_authority", "promotion_authority", "staking_authority"))


def test_g1_coherent_paths_are_seed_deterministic():
    first = run_location_g1_research_market_bridge(**_kwargs())
    second = run_location_g1_research_market_bridge(**_kwargs())
    assert first["game_markets"] == second["game_markets"]
    assert first["prop_markets"] == second["prop_markets"]


@pytest.mark.parametrize("side", ["home", "away"])
def test_future_feature_fails_closed(side):
    kwargs = _kwargs()
    kwargs["game_features"][f"{side}_features"]["feature_asof_ts"] = "2026-10-08T12:01:00Z"
    with pytest.raises(ValueError, match="PIT_WINDOW_INVALID"):
        run_location_g1_research_market_bridge(**kwargs)


def test_market_derived_feature_fails_closed():
    kwargs = _kwargs()
    kwargs["game_features"]["home_features"]["sportsbook_odds"] = -110
    with pytest.raises(ValueError, match="MARKET_DATA_PROHIBITED"):
        run_location_g1_research_market_bridge(**kwargs)


def test_opaque_nested_mapping_fails_closed():
    from types import MappingProxyType
    kwargs = _kwargs()
    kwargs["game_features"]["home_features"]["hidden"] = MappingProxyType({"sportsbook_odds": -110})
    with pytest.raises(ValueError, match="OPAQUE_FEATURE_MAPPING_PROHIBITED"):
        run_location_g1_research_market_bridge(**kwargs)
