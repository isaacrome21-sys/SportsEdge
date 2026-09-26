import pytest

from sportsedge.nfl_coherent_team_props import (
    coherent_pass_yards_per_completion,
    scripted_role_means,
    simulate_anytime_td_board_on_game_paths,
    simulate_team_on_game_paths,
)
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError


def qb():
    return {
        "player": "QB",
        "role_prior": {
            "pass_attempts": 36,
            "completion_rate": 0.68,
            "pass_yards_per_completion": 11.0,
            "pass_td_rate": 0.055,
            "interception_rate": 0.02,
            "rush_attempts": 5,
            "rush_yards_per_attempt": 4.0,
            "targets": 0,
            "catch_rate": 0.0,
            "receiving_yards_per_reception": 0.0,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": 0.0},
    }


def receiver(name, targets, catch_rate, ypr):
    return {
        "player": name,
        "role_prior": {
            "pass_attempts": 0,
            "completion_rate": 0.0,
            "pass_yards_per_completion": 0.0,
            "pass_td_rate": 0.0,
            "interception_rate": 0.0,
            "rush_attempts": 1,
            "rush_yards_per_attempt": 4.0,
            "targets": targets,
            "catch_rate": catch_rate,
            "receiving_yards_per_reception": ypr,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": 0.0},
    }


def state(pass_multiplier=1.0, rush_multiplier=1.0, team_tds=3):
    return {
        "script_source": "historical_play_by_play",
        "pass_multiplier": pass_multiplier,
        "rush_multiplier": rush_multiplier,
        "team_tds": team_tds,
    }


def pool():
    # Realistic, separately fitted receiver YPRs that do NOT equal the QB's raw
    # fitted YPC (11.0).  The coherent path must derive one identity, not block.
    return [
        receiver("WR1", 10, 0.68, 12.0),
        receiver("WR2", 7, 0.65, 10.5),
        receiver("OTHER", 6, 0.62, 8.5),
    ]


def test_game_script_uses_explicit_inputs_and_moves_workload_directionally():
    trailing = scripted_role_means(qb(), state(pass_multiplier=1.20, rush_multiplier=0.80))
    leading = scripted_role_means(qb(), state(pass_multiplier=0.80, rush_multiplier=1.20))
    assert trailing["pass_attempts"] > leading["pass_attempts"]
    assert trailing["rush_attempts"] < leading["rush_attempts"]

    bad = state()
    del bad["pass_multiplier"]
    with pytest.raises(NflPropSimulationError, match="SCRIPT_MULTIPLIER_REQUIRED:pass_multiplier"):
        scripted_role_means(qb(), bad)


def test_context_pass_or_rush_multiplier_cannot_double_apply_game_script():
    bad_qb = qb()
    bad_qb["context"] = {
        "shared_workload_sigma": 0.0,
        "pass_multiplier": 1.20,
        "source": "role",
    }
    with pytest.raises(NflPropSimulationError, match="CONTEXT_SCRIPT_MULTIPLIER_CONFLICT"):
        scripted_role_means(bad_qb, state(pass_multiplier=1.20))

    bad_receiver = receiver("WR1", 8, 0.7, 11.0)
    bad_receiver["context"] = {
        "shared_workload_sigma": 0.0,
        "rush_multiplier": 1.15,
        "source": "role",
    }
    with pytest.raises(NflPropSimulationError, match="CONTEXT_SCRIPT_MULTIPLIER_CONFLICT"):
        simulate_team_on_game_paths(qb(), [bad_receiver], [state()], seed=3)


def test_team_paths_are_deterministic_and_conserve_qb_receiving_identity():
    states = [
        state(1.15, 0.85, 2),
        state(0.90, 1.10, 4),
        state(1.00, 1.00, 1),
    ] * 20
    a = simulate_team_on_game_paths(qb(), pool(), states, seed=41)
    b = simulate_team_on_game_paths(qb(), pool(), states, seed=41)
    assert a == b
    assert len(a) == len(states)

    for game in a:
        q = game["qb"]
        receivers = game["receivers"].values()
        assert sum(row["receptions"] for row in receivers) == q["completions"]
        assert sum(row["receiving_yards"] for row in receivers) == q["passing_yards"]
        assert all(
            row["rush_receiving_yards"] == row["rushing_yards"] + row["receiving_yards"]
            for row in game["receivers"].values()
        )


def _with_qb_ypc(value):
    out = qb()
    out["role_prior"] = dict(out["role_prior"])
    out["role_prior"]["pass_yards_per_completion"] = value
    return out


def test_disagreeing_qb_and_receiver_fits_derive_one_identity_instead_of_blocking():
    # Raw QB fit (7.5) deliberately disagrees with the receiver pool.
    states = [state(1.10, 0.90, 2), state(0.90, 1.10, 3)] * 15
    paths = simulate_team_on_game_paths(_with_qb_ypc(7.5), pool(), states, seed=5)
    assert len(paths) == len(states)
    for game in paths:
        q = game["qb"]
        rows = game["receivers"].values()
        assert sum(row["receptions"] for row in rows) == q["completions"]
        assert sum(row["receiving_yards"] for row in rows) == q["passing_yards"]

    weights = [10 * 0.68, 7 * 0.65, 6 * 0.62]
    expected = (weights[0] * 12.0 + weights[1] * 10.5 + weights[2] * 8.5) / sum(weights)
    assert coherent_pass_yards_per_completion(pool(), state()) == pytest.approx(expected)


def test_raw_qb_ypc_fit_has_no_effect_on_coherent_paths():
    states = [state(1.15, 0.85, 2), state(1.00, 1.00, 4)] * 10
    low = simulate_team_on_game_paths(_with_qb_ypc(7.5), pool(), states, seed=13)
    high = simulate_team_on_game_paths(_with_qb_ypc(15.0), pool(), states, seed=13)
    assert low == high


def test_receiver_efficiency_context_moves_derived_qb_yardage():
    boosted = pool()
    boosted[0]["context"] = {
        "shared_workload_sigma": 0.0,
        "receiving_efficiency_multiplier": 1.20,
        "source": "matchup",
    }
    assert coherent_pass_yards_per_completion(boosted, state()) > coherent_pass_yards_per_completion(
        pool(), state()
    )


def test_qb_pass_yardage_context_fails_closed_rather_than_being_discarded():
    for key in ("pass_efficiency_multiplier", "efficiency_multiplier"):
        bad_qb = qb()
        bad_qb["context"] = {"shared_workload_sigma": 0.0, key: 1.10, "source": "matchup"}
        with pytest.raises(NflPropSimulationError, match=f"QB_PASS_YARDAGE_CONTEXT_CONFLICT:{key}"):
            simulate_team_on_game_paths(bad_qb, pool(), [state()], seed=5)


def test_receiver_pool_with_catch_weight_but_no_yardage_fails_closed():
    zero_yardage = [receiver("WR1", 8, 0.7, 0.0), receiver("OTHER", 5, 0.6, 0.0)]
    with pytest.raises(NflPropSimulationError, match="RECEIVING_YARD_WEIGHT_REQUIRED"):
        simulate_team_on_game_paths(qb(), zero_yardage, [state()], seed=5)


def test_receiver_pool_requires_real_completion_weight():
    empty = [receiver("OTHER", 0, 0.0, 0.0)]
    with pytest.raises(NflPropSimulationError, match="RECEIVER_WEIGHT_REQUIRED"):
        simulate_team_on_game_paths(qb(), empty, [state(pass_multiplier=1.8)], seed=7)


def test_td_board_uses_explicit_shares_and_same_team_td_path():
    shares = [
        {"player": "RB1", "td_share": 0.35},
        {"player": "WR1", "td_share": 0.25},
        {"player": "TE1", "td_share": 0.15},
    ]
    states = [state(team_tds=0), state(team_tds=2), state(team_tds=5)]
    a = simulate_anytime_td_board_on_game_paths(shares, states, seed=9)
    b = simulate_anytime_td_board_on_game_paths(shares, states, seed=9)
    assert a == b
    assert a[0] == {"RB1": 0, "WR1": 0, "TE1": 0}
    assert all(set(row.values()) <= {0, 1} for row in a)


def test_more_team_tds_cannot_remove_a_same_seed_td_hit():
    shares = [{"player": "RB1", "td_share": 0.55}, {"player": "WR1", "td_share": 0.25}]
    low = simulate_anytime_td_board_on_game_paths(shares, [state(team_tds=1)], seed=17)[0]
    high = simulate_anytime_td_board_on_game_paths(shares, [state(team_tds=5)], seed=17)[0]
    assert all(high[player] >= low[player] for player in low)


def test_market_inputs_and_market_derived_script_sources_fail_closed():
    bad_state = state()
    bad_state["price_american"] = -110
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        simulate_team_on_game_paths(qb(), pool(), [bad_state], seed=3)

    bad_source = state()
    bad_source["script_source"] = "sportsbook_market_total"
    with pytest.raises(NflPropSimulationError, match="SCRIPT_SOURCE_NOT_MARKET_BLIND"):
        simulate_team_on_game_paths(qb(), pool(), [bad_source], seed=3)


def test_td_shares_cannot_smuggle_probability_mass_above_one():
    shares = [{"player": "A", "td_share": 0.7}, {"player": "B", "td_share": 0.5}]
    with pytest.raises(NflPropSimulationError, match="TD_SHARES_SUM_ABOVE_ONE"):
        simulate_anytime_td_board_on_game_paths(shares, [state(team_tds=2)], seed=1)
