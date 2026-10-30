"""NFL market probability capability audit.

This is deliberately an audit, not a promotion registry. PRESENT read-out code is
not equivalent to a validated Model_P engine and cannot grant Truth-Gate authority.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SURFACE=ROOT/"config/football_market_surface.json"

# Read-outs already present on main or this branch. Predictive validation may still
# be absent; callers must preserve that distinction.
READOUTS={
"moneyline":"sportsedge.core.simulate.markets:derive_game_markets",
"spread":"sportsedge.core.simulate.markets:derive_game_markets",
"total":"sportsedge.core.simulate.markets:derive_game_markets",
"team_total":"sportsedge.core.simulate.markets:derive_game_markets",
"first_half_moneyline":"sportsedge.core.simulate.markets:derive_period_markets",
"first_half_spread":"sportsedge.core.simulate.markets:derive_period_markets",
"first_half_total":"sportsedge.core.simulate.markets:derive_period_markets",
"second_half_moneyline":"sportsedge.core.simulate.markets:derive_period_markets",
"second_half_spread":"sportsedge.core.simulate.markets:derive_period_markets",
"second_half_total":"sportsedge.core.simulate.markets:derive_period_markets",
"quarter_moneyline":"sportsedge.core.simulate.markets:derive_period_markets",
"quarter_spread":"sportsedge.core.simulate.markets:derive_period_markets",
"quarter_total":"sportsedge.core.simulate.markets:derive_period_markets",
"alternate_spread":"sportsedge.core.simulate.markets:derive_alternate_markets",
"alternate_total":"sportsedge.core.simulate.markets:derive_alternate_markets",
"passing_yards":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"completions":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"attempts":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"passing_tds":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"interceptions":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"rush_yards":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"longest_completion":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"pass_plus_rush_yards":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"rushing_yards":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"receiving_yards":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"receptions":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"rush_attempts":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"targets":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"rush_plus_rec_yards":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"longest_reception":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"longest_rush":"sportsedge.core.simulate.player_markets:derive_player_stat_market",
"anytime_td":"sportsedge.core.simulate.nfl_probability_markets:derive_anytime_touchdown_probability",
"two_plus_td":"sportsedge.core.simulate.nfl_probability_markets:derive_two_plus_touchdown_probability",
"safety":"sportsedge.core.simulate.nfl_probability_markets:derive_safety_probability",
"fg_made":"sportsedge.core.simulate.kicker_markets:derive_kicker_stat_market",
"kicking_points":"sportsedge.core.simulate.kicker_markets:derive_kicker_stat_market",
"xp_made":"sportsedge.core.simulate.kicker_markets:derive_kicker_stat_market",
"player_sacks":"sportsedge.core.simulate.defense_markets:derive_defender_stat_market",
"tackles_assists":"sportsedge.core.simulate.defense_markets:derive_defender_stat_market",
"player_interceptions":"sportsedge.core.simulate.defense_markets:derive_defender_stat_market",
"team_sacks":"sportsedge.core.simulate.defense_markets:derive_team_defense_stat_market",
"team_turnovers":"sportsedge.core.simulate.defense_markets:derive_team_defense_stat_market",
}

def audit()->dict:
    surface=json.loads(SURFACE.read_text())
    rows=[]
    for item in surface["markets"]:
        market=item["market"]
        rows.append({
            "family":item["family"],"market":market,
            "declared_runtime_state":item["engine_state_by_sport"]["NFL"],
            "probability_readout_present":market in READOUTS,
            "entrypoint":READOUTS.get(market),
            "authority":"NONE_AUDIT_ONLY",
        })
    return {"schema":"NFL_MARKET_PROBABILITY_CAPABILITY_AUDIT_V1","markets":rows}

if __name__=="__main__":
    print(json.dumps(audit(),indent=2,sort_keys=True))
