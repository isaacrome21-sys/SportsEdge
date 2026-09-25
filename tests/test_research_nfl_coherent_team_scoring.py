import pytest

from sportsedge.nfl_coherent_team_scoring import simulate_coherent_team_scoring_paths
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError


def qb():
    return {
        "player": "QB",
        "rushing_td_share": 0.08,
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


def player(name, targets, catch_rate, ypr, rush_attempts, receiving_td_share, rushing_td_share):
    return {
        "player": name,
        "receiving_td_share": receiving_td_share,
        "rushing_td_share": rushing_td_share,
        "role_prior": {
            "pass_attempts": 0,
            "completion_rate": 0.0,
            "pass_yards_per_completion": 0.0,
            "pass_td_rate": 0.0,
            "interception_rate": 0.0,
            "rush_attempts": rush_attempts,
            "rush_yards_per_attempt": 4.2,
            "targets": targets,
            "catch_rate": catch_rate,
            "receiving_yards_per_reception": ypr,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": 0.0},
    }


def pool():
    return [
        player("RB1", 6, 0.72, 11.0, 13, 0.12, 0.45),
        player("WR1", 10, 0.68, 11.0, 1, 0.38, 0.02),
        player("WR2", 7, 0.65, 11.0, 1, 0.24, 0.01),
        player("OTHER", 6, 0.62, 11.0, 5, 0.10, 0.18),
    ]


def state(team_tds=3, pass_td_share=0.64, pass_multiplier=1.0, rush_multiplier=1.0):
    return {
        "script_source": "historical_play_by_play",
        "pass_multiplier": pass_multiplier,
        "rush_multiplier": rush_multiplier,
        "team_tds": team_tds,
        "pass_td_share": pass_td_share,
    }


def test_same_seed_is_identical_and_all_td_invariants_hold():
    states = [
        state(0, 0.64, 1.10, 0.90),
        state(2, 0.70, 1.15, 0.85),
        state(3, 0.60, 1.00, 1.00),
        state(4, 0.52, 0.90, 1.10),
    ] * 20

    a = simulate_coherent_team_scoring_paths(qb(), pool(), states, seed=41)
    b = simulate_coherent_team_scoring_paths(qb(), pool(), states, seed=41)
    assert a == b
    assert len(a) == len(states)

    for path in a:
        team = path["team"]
        q = path["qb"]
        players = path["players"]

        assert team["passing_tds"] + team["rushing_tds"] == team["team_tds"]
        assert q["pass_tds"] == team["passing_tds"]
        assert q["pass_tds"] <= q["completions"]
        assert sum(row["receiving_tds"] for row in players.values()) == q["pass_tds"]
        assert q["rushing_tds"] + sum(row["rushing_tds"] for row in players.values()) == team["rushing_tds"]
        assert sum(row["receiving_yards"] for row in players.values()) == q["passing_yards"]

        for row in players.values():
            assert row["receiving_tds"] <= row["receptions"]
            if row["receiving_tds"]:
                assert row["receptions"] > 0
            assert row["rushing_tds"] <= row["rush_attempts"]
            assert row["anytime_tds"] == row["receiving_tds"] + row["rushing_tds"]


def test_zero_catch_player_cannot_receive_passing_td_even_with_large_share():
    players = [
        player("NO_CATCH", 12, 0.0, 12.0, 0, 1.0, 0.0),
        player("OTHER", 20, 0.85, 11.0, 12, 0.20, 0.50),
    ]
    paths = simulate_coherent_team_scoring_paths(
        qb(),
        players,
        [state(team_tds=4, pass_td_share=0.90)] * 25,
        seed=9,
    )
    assert all(path["players"]["NO_CATCH"]["receiving_tds"] == 0 for path in paths)


def test_pass_td_share_is_required_and_bounded():
    missing = state()
    del missing["pass_td_share"]
    with pytest.raises(NflPropSimulationError, match="PASS_TD_SHARE_REQUIRED"):
        simulate_coherent_team_scoring_paths(qb(), pool(), [missing], seed=1)

    bad = state(pass_td_share=1.2)
    with pytest.raises(NflPropSimulationError, match="PASS_TD_SHARE_OUT_OF_RANGE"):
        simulate_coherent_team_scoring_paths(qb(), pool(), [bad], seed=1)


def test_player_td_shares_are_explicit_not_defaulted():
    players = pool()
    del players[0]["receiving_td_share"]
    with pytest.raises(NflPropSimulationError, match="RECEIVING_TD_SHARE_REQUIRED:RB1"):
        simulate_coherent_team_scoring_paths(qb(), players, [state()], seed=1)


def test_impossible_all_pass_share_fails_closed_when_completion_capacity_is_too_small():
    low_completion_qb = qb()
    low_completion_qb["role_prior"] = dict(low_completion_qb["role_prior"])
    low_completion_qb["role_prior"]["pass_attempts"] = 1
    low_completion_qb["role_prior"]["completion_rate"] = 0.0

    with pytest.raises(NflPropSimulationError, match="PASS_TD_CAPACITY_CONFLICT"):
        simulate_coherent_team_scoring_paths(
            low_completion_qb,
            pool(),
            [state(team_tds=2, pass_td_share=1.0)],
            seed=3,
        )
