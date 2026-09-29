from sportsedge.nfl_coherent_prop_runner import run_coherent_prop_estimates
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError
import pytest

ROLE={"pass_attempts":30,"completion_rate":.65,"pass_yards_per_completion":11,
"pass_td_rate":.04,"interception_rate":.02,"rush_attempts":4,
"rush_yards_per_attempt":4,"targets":6,"catch_rate":.65,
"receiving_yards_per_reception":11}

def payload(name, player_id=None, **extra):
    row={"player":name,"role_prior":dict(ROLE),"trailing":{},"sample_size":0,
         "context":{"source":"none"},**extra}
    if player_id is not None:
        row["player_id"]=player_id
    return row

def state():
    return {"script_source":"preregistered_fixture","pass_multiplier":1.0,
            "rush_multiplier":1.0,"team_tds":2,"pass_td_share":.5}

def teams():
    return [
      {"team":"PHI","qb":payload("QB1","gsis-qb1",rushing_td_share=.1),
       "skill_players":[payload("WR1","gsis-wr1",receiving_td_share=.5,rushing_td_share=.1),
                        payload("OTHER1","synthetic-phi-other",receiving_td_share=.5,rushing_td_share=.8)]},
      {"team":"CHI","qb":payload("QB2","gsis-qb2",rushing_td_share=.1),
       "skill_players":[payload("WR2","gsis-wr2",receiving_td_share=.5,rushing_td_share=.1),
                        payload("OTHER2","synthetic-chi-other",receiving_td_share=.5,rushing_td_share=.8)]},
    ]

def test_runner_is_deterministic_and_market_blind():
    states={"PHI":[state() for _ in range(200)],"CHI":[state() for _ in range(200)]}
    markets=[{"player_id":"gsis-qb1","market":"passing_yards","selection":"OVER","line":200.5},
             {"player_id":"gsis-wr1","market":"receiving_yards","selection":"UNDER","line":60.5},
             {"player_id":"gsis-wr2","market":"anytime_tds","selection":"OVER","line":0.5}]
    a=run_coherent_prop_estimates(game_id="g",teams=teams(),game_states_by_team=states,markets=markets)
    b=run_coherent_prop_estimates(game_id="g",teams=teams(),game_states_by_team=states,markets=markets)
    assert a==b
    assert [x["player_id"] for x in a]==["gsis-qb1","gsis-wr1","gsis-wr2"]
    assert all(0 <= x["estimate_p"] <= 1 and x["status"]=="RESEARCH_ONLY" for x in a)

def test_runner_keeps_legacy_player_name_lookup():
    states={"PHI":[state() for _ in range(20)],"CHI":[state() for _ in range(20)]}
    out=run_coherent_prop_estimates(game_id="g",teams=teams(),game_states_by_team=states,
        markets=[{"player":"QB1","market":"passing_yards","selection":"OVER","line":200.5}])
    assert out[0]["player_id"]=="gsis-qb1"
    assert out[0]["player"]=="QB1"

def test_runner_rejects_market_contamination():
    bad=teams()
    bad[0]["qb"]["context"]["odds"]=-110
    states={"PHI":[state()],"CHI":[state()]}
    with pytest.raises(NflPropSimulationError, match="MARKET_INPUT_FORBIDDEN"):
        run_coherent_prop_estimates(game_id="g",teams=bad,game_states_by_team=states,
            markets=[{"player_id":"gsis-qb1","market":"passing_yards","selection":"OVER","line":200.5}])

def test_runner_rejects_duplicate_stable_ids():
    bad=teams()
    bad[0]["skill_players"][0]["player_id"]="gsis-qb1"
    states={"PHI":[state()],"CHI":[state()]}
    with pytest.raises(NflPropSimulationError, match="PLAYER_IDENTITY_DUPLICATE"):
        run_coherent_prop_estimates(game_id="g",teams=bad,game_states_by_team=states,
            markets=[{"player_id":"gsis-qb1","market":"passing_yards","selection":"OVER","line":200.5}])
