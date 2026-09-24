import pytest
from sportsedge.nfl_prop_shared_sim import estimate_prop,simulate_player,NflPropSimulationError

def player():
 return {"role_prior":{"pass_attempts":35,"completion_rate":.66,"pass_yards_per_completion":11.5,"pass_td_rate":.055,"interception_rate":.025,"rush_attempts":4,"rush_yards_per_attempt":4.2,"targets":1,"catch_rate":.7,"receiving_yards_per_reception":8},"trailing":{},"sample_size":0,"context":{"volume_multiplier":1,"pass_multiplier":1,"rush_multiplier":1,"target_multiplier":1,"efficiency_multiplier":1,"pass_efficiency_multiplier":1,"rush_efficiency_multiplier":1,"receiving_efficiency_multiplier":1,"shared_workload_sigma":.1}}

def test_deterministic_and_coherent_shared_draws():
 a=simulate_player(player(),n_sims=200,seed=9); b=simulate_player(player(),n_sims=200,seed=9)
 assert a==b
 assert all(r["completions"]<=r["pass_attempts"] for r in a)
 assert all(r["rush_receiving_yards"]>=r["rushing_yards"] for r in a)

def test_integer_push_mass_and_board_shape():
 draws=[{"pass_tds":1},{"pass_tds":2},{"pass_tds":3},{"pass_tds":2}]
 row=estimate_prop(draws,game_id="g",player="QB",market="pass_tds",line=2,selection="OVER")
 assert row["estimate_p"]==.25 and row["push_p"]==.5
 assert "price_american" not in row and "ev_per_dollar" not in row

def test_market_inputs_cannot_enter_probability_generator():
 p=player(); p["price_american"]=-110
 with pytest.raises(NflPropSimulationError,match="MARKET_INPUT_FORBIDDEN"):
  simulate_player(p,n_sims=5)