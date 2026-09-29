from __future__ import annotations

from scripts.run_nfl_coherent_props import run_payload


ROLE={"pass_attempts":28,"completion_rate":.65,"pass_yards_per_completion":11,
      "pass_td_rate":.04,"interception_rate":.02,"rush_attempts":4,
      "rush_yards_per_attempt":4,"targets":5,"catch_rate":.65,
      "receiving_yards_per_reception":11}


def _player(name, pid, **extra):
    return {"player":name,"player_id":pid,"role_prior":dict(ROLE),"trailing":{},
            "sample_size":0,"context":{"source":"none"},**extra}


def _state():
    return {"script_source":"preregistered_fixture","pass_multiplier":1.0,
            "rush_multiplier":1.0,"team_tds":2,"pass_td_share":.5}


def _payload():
    return {
        "game_id":"2026_03_PHI_CHI",
        "seed":21,
        "teams":[
            {"team":"PHI","qb":_player("QB1","qb1",rushing_td_share=.1),
             "skill_players":[_player("WR1","wr1",receiving_td_share=.5,rushing_td_share=.1),
                              _player("OTHER1","other1",receiving_td_share=.5,rushing_td_share=.8)]},
            {"team":"CHI","qb":_player("QB2","qb2",rushing_td_share=.1),
             "skill_players":[_player("WR2","wr2",receiving_td_share=.5,rushing_td_share=.1),
                              _player("OTHER2","other2",receiving_td_share=.5,rushing_td_share=.8)]},
        ],
        "game_states_by_team":{"PHI":[_state() for _ in range(25)],"CHI":[_state() for _ in range(25)]},
        "markets":[{"player_id":"qb1","market":"passing_yards","selection":"OVER","line":200.5}],
    }


def test_cli_payload_is_deterministic_and_hash_bound():
    payload=_payload()
    a=run_payload(payload)
    b=run_payload(payload)
    assert a==b
    assert len(a["input_sha256"])==64
    assert a["schema"]=="NFL_COHERENT_PROP_RESEARCH_RUN_V1"
    assert a["rows"][0]["player_id"]=="qb1"
    assert a["authority"]=="NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
