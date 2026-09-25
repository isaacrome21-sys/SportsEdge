import pytest
from sportsedge.nfl_prop_shared_sim import (
    estimate_prop,
    simulate_player,
    simulate_game,
    stabilized_role,
    NflPropSimulationError,
    DEFAULT_RARE_PRIOR_STRENGTH,
    DEFAULT_VOLUME_PRIOR_STRENGTH,
    MULTIPLIER_MAX,
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
            "source": "injury",
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


def test_deterministic_and_coherent_attempt_accounting():
    a = simulate_player(player(), n_sims=200, seed=9)
    b = simulate_player(player(), n_sims=200, seed=9)
    assert a == b
    assert all(r["completions"] <= r["pass_attempts"] for r in a)
    assert all(r["pass_tds"] <= r["completions"] for r in a)
    assert all(r["interceptions"] <= r["pass_attempts"] - r["completions"] for r in a)
    assert all(r["completions"] + r["interceptions"] <= r["pass_attempts"] for r in a)
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


def test_nested_market_keys_are_rejected_but_workload_names_are_not():
    p = player()
    p["context"]["price_american"] = -110
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_player(p, n_sims=5)
    p = player()
    p["trailing"]["implied_team_total"] = 24.5
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_player(p, n_sims=5)
    p = player()
    p["trailing"]["prev_week_targets"] = 9
    simulate_player(p, n_sims=3)


def test_volume_multiplier_cannot_smuggle_a_team_total():
    p = player()
    p["context"]["volume_multiplier"] = 24.5
    with pytest.raises(NflPropSimulationError, match="CONTEXT_MULTIPLIER_OUT_OF_RANGE"):
        simulate_player(p, n_sims=5)
    p = player()
    p["context"]["volume_multiplier"] = MULTIPLIER_MAX
    simulate_player(p, n_sims=3)
    p = player()
    p["context"]["source"] = "closing_total"
    with pytest.raises(NflPropSimulationError, match="CONTEXT_SOURCE_NOT_MARKET_BLIND"):
        simulate_player(p, n_sims=5)


def test_rare_rates_use_heavier_shrinkage_than_volume():
    p = player()
    p["sample_size"] = 2
    p["trailing"] = {**p["role_prior"], "pass_td_rate": 0.20, "interception_rate": 0.12, "pass_attempts": 50}
    role = stabilized_role(p)
    assert DEFAULT_RARE_PRIOR_STRENGTH > DEFAULT_VOLUME_PRIOR_STRENGTH
    expected_td = (40 * 0.055 + 2 * 0.20) / 42
    expected_int = (40 * 0.025 + 2 * 0.12) / 42
    assert abs(role["pass_td_rate"] - expected_td) < 1e-12
    assert abs(role["interception_rate"] - expected_int) < 1e-12


def test_rushing_yards_have_losses_and_a_right_tail():
    p = player()
    p["role_prior"]["rush_attempts"] = 18
    p["role_prior"]["rush_yards_per_attempt"] = 0.4
    stuffed = simulate_player(p, n_sims=4000, seed=3)
    assert any(r["rushing_yards"] < 0 for r in stuffed)
    p = player()
    p["role_prior"]["rush_attempts"] = 20
    p["role_prior"]["rush_yards_per_attempt"] = 4.3
    explosive = simulate_player(p, n_sims=4000, seed=7)
    assert any(r["rushing_yards"] >= 120 for r in explosive)


def test_simulate_game_is_shared_volume_placeholder_only():
    games = simulate_game([player(), receiver()], n_sims=80, seed=11)
    assert len(games) == 80
    assert all(len(g) == 2 for g in games)
    assert all(g[0]["pass_tds"] <= g[0]["completions"] for g in games)
    assert all(g[0]["interceptions"] <= g[0]["pass_attempts"] - g[0]["completions"] for g in games)
