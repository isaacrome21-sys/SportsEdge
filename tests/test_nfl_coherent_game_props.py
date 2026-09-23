import pytest

from sportsedge.nfl_coherent_game_props import game_script_multipliers, simulate_player_on_game_paths
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError


def payload():
    prior={
      "pass_attempts":34,"completion_rate":.66,"pass_yards_per_completion":11.5,
      "pass_td_rate":.05,"interception_rate":.025,"rush_attempts":8,
      "rush_yards_per_attempt":4.5,"targets":7,"catch_rate":.68,
      "receiving_yards_per_reception":10.5,
    }
    return {"role_prior":prior,"trailing":prior,"sample_size":20,"context":{"shared_workload_sigma":0}}


def test_game_script_direction_is_football_coherent():
    trailing=game_script_multipliers({"team_margin":-14,"pace_multiplier":1})
    leading=game_script_multipliers({"team_margin":14,"pace_multiplier":1})
    assert trailing["pass_multiplier"] > leading["pass_multiplier"]
    assert trailing["target_multiplier"] > leading["target_multiplier"]
    assert trailing["rush_multiplier"] < leading["rush_multiplier"]


def test_shared_game_path_adapter_is_deterministic_and_one_to_one():
    states=[{"team_margin":-7,"pace_multiplier":1.05},{"team_margin":10,"pace_multiplier":.94}]
    a=simulate_player_on_game_paths(payload(),states,seed=9)
    b=simulate_player_on_game_paths(payload(),states,seed=9)
    assert a==b and len(a)==len(states)
    assert all(x["completions"]<=x["pass_attempts"] for x in a)
    assert all(x["rush_receiving_yards"]==x["rushing_yards"]+x["receiving_yards"] for x in a)


def test_market_inputs_fail_closed():
    with pytest.raises(NflPropSimulationError,match="MARKET_INPUT_FORBIDDEN"):
        game_script_multipliers({"team_margin":0,"price_american":-110})
    bad=payload(); bad["odds"]=-110
    with pytest.raises(NflPropSimulationError,match="MARKET_INPUT_FORBIDDEN"):
        simulate_player_on_game_paths(bad,[{"team_margin":0}],seed=1)
