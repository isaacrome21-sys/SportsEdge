import pytest
from sportsedge.nfl_coherent_game_tds import estimate_anytime_td_from_game_paths,simulate_anytime_td_on_game_paths
from sportsedge.nfl_td_role_model import NflTdRoleError


def payload():
 return {"rush_share":.45,"target_share":.12,"goal_line_carry_share":.70,"close_target_share":.18,"team_rush_td_mix":.55,"context":{"availability_multiplier":1,"matchup_multiplier":1}}


def test_td_allocation_is_deterministic_and_one_to_one_with_game_paths():
 states=[{"team_tds":0},{"team_tds":2},{"team_tds":4},{"team_tds":1}]
 a=simulate_anytime_td_on_game_paths(payload(),states,seed=9)
 b=simulate_anytime_td_on_game_paths(payload(),states,seed=9)
 assert a==b and len(a)==len(states)
 assert a[0]==0 and set(a)<={0,1}
 assert estimate_anytime_td_from_game_paths(payload(),states,seed=9)==sum(a)/len(a)


def test_more_team_tds_cannot_reduce_same_path_hit_with_same_seed():
 low=simulate_anytime_td_on_game_paths(payload(),[{"team_tds":1}],seed=17)[0]
 high=simulate_anytime_td_on_game_paths(payload(),[{"team_tds":5}],seed=17)[0]
 assert high>=low


def test_market_inputs_fail_closed():
 bad=payload();bad["price_american"]=-110
 with pytest.raises(NflTdRoleError,match="MARKET_INPUT_FORBIDDEN"):
  simulate_anytime_td_on_game_paths(bad,[{"team_tds":2}],seed=1)
 with pytest.raises(NflTdRoleError,match="MARKET_INPUT_FORBIDDEN"):
  simulate_anytime_td_on_game_paths(payload(),[{"team_tds":2,"odds":120}],seed=1)
