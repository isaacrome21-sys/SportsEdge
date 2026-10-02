"""Research batch routing for NFL prop readouts; never a runtime activation."""
from sportsedge.core.simulate.player_markets import derive_player_stat_market
from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market
from math import isfinite
from sportsedge.core.simulate.defense_markets import derive_defender_stat_market, derive_team_defense_stat_market
from sportsedge.sports.nfl.touchdown_readouts import derive_touchdown_readouts


OFFENSE = {
    "player_pass_attempts": "pass_attempts", "player_pass_completions": "completions",
    "player_pass_yds": "passing_yards", "player_pass_tds": "passing_tds",
    "player_pass_interceptions": "interceptions", "player_pass_longest_completion": "longest_completion",
    "player_pass_rush_yds": "pass_plus_rush_yards", "player_rush_attempts": "rush_attempts",
    "player_rush_yds": "rushing_yards", "player_rush_tds": "rushing_tds",
    "player_rush_longest": "longest_rush", "player_receptions": "receptions",
    "player_reception_yds": "receiving_yards", "player_reception_tds": "receiving_tds",
    "player_reception_longest": "longest_reception", "player_rush_reception_yds": "rush_plus_receiving_yards",
    "player_rush_reception_tds": "touchdowns", "player_targets": "targets",
}
KICKER = {"player_field_goals": "fg_made", "player_kicking_points": "kicking_points",
          "player_pats": "xp_made", "player_longest_field_goal": "longest_fg"}
DEFENSE = {"player_sacks": "sacks", "player_solo_tackles": "solo_tackles",
           "player_tackles_assists": "tackles_assists", "player_defensive_interceptions": "interceptions"}


def derive_prop_batch(requests, *, offensive_paths=(), kicker_paths=(), defensive_paths=(), scorer_paths=()):
    """Resolve every request or retain an explicit per-request blocker.

    Paths are materialized once, so generators cannot silently empty on the
    second market. No joint/parlay distribution is inferred across engine sets.
    Generic scorer markets require the complete TD path API, not offense-only TDs.
    """
    inputs = {"offense": list(offensive_paths), "kicker": list(kicker_paths), "defense": list(defensive_paths)}
    complete_scorers = list(scorer_paths)
    for group in inputs.values():
        identities = [(p.base_path.game_id, p.base_path.simulation_id) for p in group]
        if len(set(identities)) != len(identities):
            raise ValueError("NFL_PROP_DUPLICATE_SIMULATION")
        if len({game for game, _ in identities}) > 1:
            raise ValueError("NFL_PROP_MIXED_GAMES")
    rows = []
    for index, request in enumerate(requests):
        row = {"request_index": index, "status": "BLOCKED", "model_p": None,
               "official_authority": False, "staking_authority": False}
        try:
            market = request["market"]
            row["market"] = market
            line = request.get("line")
            if market in set(OFFENSE) | set(KICKER) | set(DEFENSE) | {"team_sacks", "team_turnovers"}:
                if isinstance(line, bool) or not isinstance(line, (int, float)) or not isfinite(line):
                    raise ValueError("NFL_PROP_FINITE_NUMERIC_LINE_REQUIRED")
            if market in OFFENSE:
                probabilities = derive_player_stat_market(inputs["offense"], player_id=request["player_id"],
                    stat=OFFENSE[market], line=request["line"], target_settlement_provider=request.get("settlement_provider"))
            elif market in KICKER:
                probabilities = derive_kicker_stat_market(inputs["kicker"], kicker_id=request["player_id"],
                    stat=KICKER[market], line=request["line"])
            elif market in DEFENSE:
                probabilities = derive_defender_stat_market(inputs["defense"], player_id=request["player_id"],
                    stat=DEFENSE[market], line=request["line"], tackle_settlement_provider=request.get("settlement_provider"))
            elif market in {"team_sacks", "team_turnovers"}:
                probabilities = derive_team_defense_stat_market(inputs["defense"], team=request["team"],
                    stat=market, line=request["line"])
            elif market in {"player_anytime_td", "player_tds_over", "player_first_td", "player_last_td", "player_two_plus_td", "player_three_plus_td"}:
                if not complete_scorers:
                    raise ValueError("COMPLETE_SCORER_PATH_REQUIRED")
                readout = derive_touchdown_readouts(complete_scorers, player_id=request["player_id"],
                    player_team=request["team"], td_line=request["line"] if market == "player_tds_over" else .5)
                if market == "player_tds_over":
                    probabilities = readout["td_total"]
                else:
                    key = {"player_anytime_td": "anytime_td", "player_first_td": "first_td",
                           "player_last_td": "last_td", "player_two_plus_td": "two_plus_td",
                           "player_three_plus_td": "three_plus_td"}[market]
                    probabilities = {"yes": readout[key], "no": 1 - readout[key]}
                row["no_touchdown"] = readout["no_touchdown"]
            else:
                raise ValueError("NFL_PROP_MARKET_UNSUPPORTED")
            row.update(status="RESEARCH_READOUT_NOT_MODEL_P", research_probabilities=probabilities,
                       reason="INDEPENDENT_ENGINE_VALIDATION_AND_PROMOTION_REQUIRED")
        except (KeyError, ValueError, TypeError) as exc:
            row["reason"] = str(exc)
        rows.append(row)
    return {"status": "RESEARCH_ONLY", "rows": rows, "official_count": 0,
            "promotion_authority": False, "joint_parlay_authority": False}
