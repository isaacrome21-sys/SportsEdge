import pytest
from sportsedge.nfl_prop_shared_sim import (
    estimate_prop,
    simulate_player,
    simulate_game,
    stabilized_role,
    NflPropSimulationError,
    DEFAULT_TD_PRIOR_STRENGTH,
    DEFAULT_VOLUME_PRIOR_STRENGTH,
)


def player():
    return {
        "role_prior": {
            "pass_attempts": 35,
            "completion_rate": 0.66,
            "pass_yards_per_completion": 11.5,
            "pass_td_rate": 0.055,
            "interception_rate": 0.025,
            "rush_attempts": 4,
            "rush_yards_per_attempt": 4.2,
            "targets": 1,
            "catch_rate": 0.7,
            "receiving_yards_per_reception": 8,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {
            "volume_multiplier": 1,
            "pass_multiplier": 1,
            "rush_multiplier": 1,
            "target_multiplier": 1,
            "efficiency_multiplier": 1,
            "pass_efficiency_multiplier": 1,
            "rush_efficiency_multiplier": 1,
            "receiving_efficiency_multiplier": 1,
            "shared_workload_sigma": 0.1,
        },
    }


def receiver():
    p = player()
    p["role_prior"] = {
        **p["role_prior"],
        "pass_attempts": 0,
        "pass_td_rate": 0.0,
        "interception_rate": 0.0,
        "rush_attempts": 1,
        "targets": 9,
        "catch_rate": 0.65,
        "receiving_yards_per_reception": 12.0,
    }
    return p


def test_deterministic_and_coherent_shared_draws():
    a = simulate_player(player(), n_sims=200, seed=9)
    b = simulate_player(player(), n_sims=200, seed=9)
    assert a == b
    assert all(r["completions"] <= r["pass_attempts"] for r in a)
    assert all(r["pass_tds"] <= r["completions"] for r in a)
    assert all(r["rush_receiving_yards"] == r["rushing_yards"] + r["receiving_yards"] for r in a)


def test_integer_push_mass_and_board_shape():
    draws = [{"pass_tds": 1}, {"pass_tds": 2}, {"pass_tds": 3}, {"pass_tds": 2}]
    row = estimate_prop(draws, game_id="g", player="QB", market="pass_tds", line=2, selection="OVER")
    assert row["estimate_p"] == 0.25 and row["push_p"] == 0.5
    assert "price_american" not in row and "ev_per_dollar" not in row


def test_market_inputs_cannot_enter_probability_generator():
    p = player()
    p["price_american"] = -110
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_player(p, n_sims=5)


def test_nested_market_and_implied_total_are_rejected():
    p = player()
    p["context"]["price_american"] = -110
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_player(p, n_sims=5)
    p = player()
    p["trailing"]["implied_team_total"] = 24.5
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_player(p, n_sims=5)
    p = player()
    p["context"]["volume_multiplier"] = 24.5  # numeric multiplier is allowed
    simulate_player(p, n_sims=3)
    p = player()
    p["context"]["implied_volume_multiplier"] = 1.2
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_player(p, n_sims=5)


def test_td_rate_uses_heavier_shrinkage_than_volume():
    p = player()
    p["sample_size"] = 2
    p["trailing"] = {**p["role_prior"], "pass_td_rate": 0.20, "pass_attempts": 50}
    role = stabilized_role(p)
    # 2 games of 20% TD rate should barely move a 5.5% prior with strength 40.
    assert abs(role["pass_td_rate"] - 0.055) < abs(role["pass_attempts"] - 35)
    assert DEFAULT_TD_PRIOR_STRENGTH > DEFAULT_VOLUME_PRIOR_STRENGTH
    expected_td = (40 * 0.055 + 2 * 0.20) / 42
    assert abs(role["pass_td_rate"] - expected_td) < 1e-12


def test_rushing_yards_can_be_negative():
    p = player()
    p["role_prior"]["rush_attempts"] = 18
    p["role_prior"]["rush_yards_per_attempt"] = 0.4
    draws = simulate_player(p, n_sims=4000, seed=3)
    assert any(r["rushing_yards"] < 0 for r in draws)


def test_same_game_players_share_one_latent():
    qb = player()
    wr = receiver()
    games = simulate_game([qb, wr], n_sims=80, seed=11)
    assert len(games) == 80
    assert all(len(g) == 2 for g in games)
    assert all(g[0]["pass_tds"] <= g[0]["completions"] for g in games)
