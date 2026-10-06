from __future__ import annotations

import copy

import pytest

from sportsedge.nfl_lines_intake import parse_nfl_lines, tickets_to_dict
from sportsedge.nfl_unified_phone import build_unified_phone_card


def runtime():
    return {
        "runtime": {
            "targets": {
                "margin": {
                    "feature_mean": [0.0] * 6,
                    "feature_std": [1.0] * 6,
                    "coefficients": [0.0] * 6,
                    "intercept": 3.0,
                },
                "total": {
                    "feature_mean": [0.0] * 6,
                    "feature_std": [1.0] * 6,
                    "coefficients": [0.0] * 6,
                    "intercept": 46.0,
                },
            }
        }
    }


def history():
    rows = []
    for i in range(1, 7):
        rows.append({
            "id": f"KC{i}",
            "date": f"2026-09-{i:02d}",
            "home": "KC", "away": f"X{i}",
            "hs": 24 + i, "as": 17 + i,
        })
        rows.append({
            "id": f"BAL{i}",
            "date": f"2026-09-{i:02d}",
            "home": "BAL", "away": f"Y{i}",
            "hs": 27 + i, "as": 20 + i,
        })
    return rows


def schedule():
    return [{
        "game_id": "2026_04_KC_BAL",
        "away_team_id": "KC",
        "home_team_id": "BAL",
        "season": 2026,
        "week": 4,
        "kickoff_ts": "2026-10-04T17:00:00+00:00",
    }]


def depth():
    stamp = "2026-10-01T12:00:00Z"
    return [
        {"dt": stamp, "team": "BAL", "gsis_id": "lamar", "player_name": "Lamar Jackson", "pos_abb": "QB", "pos_rank": 1},
        {"dt": stamp, "team": "BAL", "gsis_id": "henry", "player_name": "Derrick Henry", "pos_abb": "RB", "pos_rank": 1},
        {"dt": stamp, "team": "BAL", "gsis_id": "flowers", "player_name": "Zay Flowers", "pos_abb": "WR", "pos_rank": 1},
        {"dt": stamp, "team": "BAL", "gsis_id": "andrews", "player_name": "Mark Andrews", "pos_abb": "TE", "pos_rank": 1},
        {"dt": stamp, "team": "KC", "gsis_id": "mahomes", "player_name": "Patrick Mahomes", "pos_abb": "QB", "pos_rank": 1},
        {"dt": stamp, "team": "KC", "gsis_id": "pacheco", "player_name": "Isiah Pacheco", "pos_abb": "RB", "pos_rank": 1},
        {"dt": stamp, "team": "KC", "gsis_id": "worthy", "player_name": "Xavier Worthy", "pos_abb": "WR", "pos_rank": 1},
        {"dt": stamp, "team": "KC", "gsis_id": "kelce", "player_name": "Travis Kelce", "pos_abb": "TE", "pos_rank": 1},
    ]


def stat(player_id, player_name, position, team, week, **kwargs):
    row = {
        "player_id": player_id,
        "player_name": player_name,
        "position": position,
        "recent_team": team,
        "season": 2026,
        "week": week,
        "season_type": "REG",
        "attempts": 0, "completions": 0, "passing_yards": 0,
        "passing_tds": 0, "interceptions": 0,
        "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
        "targets": 0, "receptions": 0, "receiving_yards": 0,
        "receiving_tds": 0,
    }
    row.update(kwargs)
    return row


def player_stats():
    rows = []
    for week in (1, 2, 3):
        rows += [
            stat("lamar", "Lamar Jackson", "QB", "BAL", week,
                 attempts=32 + week, completions=22 + week, passing_yards=245 + 8 * week,
                 passing_tds=2, interceptions=1, carries=7, rushing_yards=45, rushing_tds=1 if week == 2 else 0),
            stat("henry", "Derrick Henry", "RB", "BAL", week,
                 carries=18 + week, rushing_yards=90 + 4 * week, rushing_tds=1,
                 targets=2, receptions=2, receiving_yards=14),
            stat("flowers", "Zay Flowers", "WR", "BAL", week,
                 targets=8 + week, receptions=6, receiving_yards=75 + 3 * week,
                 receiving_tds=1 if week == 1 else 0),
            stat("andrews", "Mark Andrews", "TE", "BAL", week,
                 targets=6, receptions=4, receiving_yards=52, receiving_tds=1 if week == 2 else 0),
            stat("mahomes", "Patrick Mahomes", "QB", "KC", week,
                 attempts=35 + week, completions=24 + week, passing_yards=270 + 5 * week,
                 passing_tds=2, interceptions=1, carries=4, rushing_yards=20),
            stat("pacheco", "Isiah Pacheco", "RB", "KC", week,
                 carries=15 + week, rushing_yards=72 + 3 * week, rushing_tds=1 if week == 3 else 0,
                 targets=3, receptions=2, receiving_yards=15),
            stat("worthy", "Xavier Worthy", "WR", "KC", week,
                 targets=7, receptions=5, receiving_yards=68, receiving_tds=1 if week == 1 else 0),
            stat("kelce", "Travis Kelce", "TE", "KC", week,
                 targets=8, receptions=6, receiving_yards=70, receiving_tds=1 if week == 2 else 0),
        ]
    return rows


def ticket(body):
    parsed = parse_nfl_lines(body)
    return tickets_to_dict(parsed, observed_at="2026-10-01T18:00:00-05:00")


def full_board():
    return ticket(
        """
        Chiefs @ Ravens
        ML +135 -155
        Spread +3.5 -110 -110
        Total 47.5 -108 -112
        TeamTotal Ravens 25.5 -110 -110
        Prop "Lamar Jackson" PassYards 249.5 -110 -110
        Prop "Derrick Henry" RushYards 89.5 -115 -105
        Prop "Zay Flowers" RecYards 72.5 -110 -110
        Prop "Zay Flowers" Receptions 5.5 -120 +100
        """
    )


def test_intake_supports_full_game_team_total_and_player_prop_board():
    games = parse_nfl_lines(
        """
        Chiefs @ Ravens
        ML +135 -155
        Spread +3.5 -110 -110
        Total 47.5 -108 -112
        TeamTotal Baltimore Ravens 25.5 -110 -110
        Prop "Lamar Jackson" PassingYards 249.5 -110 -110
        Prop Derrick Henry RushYards 89.5 -115 -105
        """
    )
    rows = games[0].markets
    assert [row.market for row in rows] == [
        "moneyline", "spread", "total", "team_total", "passing_yards", "rushing_yards"
    ]
    assert rows[3].team == "BAL"
    assert rows[4].player == "Lamar Jackson"
    assert rows[5].player == "Derrick Henry"


def test_unified_phone_card_disables_game_edges_but_prices_qb_rb_wr_props():
    out = build_unified_phone_card(
        full_board(),
        history=history(),
        schedule_games=schedule(),
        depth_rows=depth(),
        player_rows=player_stats(),
        injury_source_ready=True,
        runtime=runtime(),
        n_sims=600,
        seed=44,
    )
    assert out["schema"] == "SPORTSEDGE_NFL_UNIFIED_PHONE_CARD_V1"
    assert len(out["games"]) == 1
    game = out["games"][0]
    assert game["forecast"]["margin"] == 3.5
    assert game["forecast"]["total"] == 47.5
    assert game["forecast"]["source"] == "SPORTSBOOK_MARKET_CENTER_CONTEXT_ONLY"
    assert game["market_context"]["home_spread"] == -3.5
    rows = game["rows"]
    assert len(rows) == 16
    assert {row["market"] for row in rows} == {
        "moneyline", "spread", "total", "team_total",
        "passing_yards", "rushing_yards", "receiving_yards", "receptions",
    }
    game_rows = [row for row in rows if row["market"] in {"moneyline", "spread", "total", "team_total"}]
    prop_rows = [row for row in rows if row["market"] not in {"moneyline", "spread", "total", "team_total"}]
    assert all(row["status"] == "NO_MODEL" for row in game_rows)
    assert all(row["reason"] == "V2K_DEVELOPMENT_BUDGET_EXHAUSTED_NO_PASS" for row in game_rows)
    assert all(row["selected"] is False for row in game_rows)
    assert all(row["status"] == "PRICED" for row in prop_rows)
    assert all(0.0 <= row["estimate_p"] <= 1.0 for row in prop_rows)
    assert all(0.0 <= row["push_p"] <= 1.0 for row in prop_rows)
    assert all(row["score_label"] == "SPORTSEDGE_QUALIFICATION_ROLE_SCORE_V1" for row in prop_rows)
    assert game["engine"]["game_market_edge_disabled"] is True
    assert game["engine"]["workload_coupling"]["lead_trail_pass_rush_adjustment"] is False
    assert out["pricing_policy"]["game_markets_disabled"] is True


def test_score_is_qualification_only_when_price_changes():
    base = full_board()
    shifted = copy.deepcopy(base)
    shifted["games"][0]["markets"][4]["away_or_over_price"] = +105
    shifted["games"][0]["markets"][4]["home_or_under_price"] = -125

    a = build_unified_phone_card(
        base, history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=runtime(), n_sims=300, seed=9,
    )
    b = build_unified_phone_card(
        shifted, history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=runtime(), n_sims=300, seed=9,
    )
    a_prop = [row for row in a["rows"] if row["market"] == "passing_yards"]
    b_prop = [row for row in b["rows"] if row["market"] == "passing_yards"]
    assert [row["score_0_100"] for row in a_prop] == [row["score_0_100"] for row in b_prop]
    assert [row["estimate_p"] for row in a_prop] == [row["estimate_p"] for row in b_prop]
    assert [row["ev_per_dollar"] for row in a_prop] != [row["ev_per_dollar"] for row in b_prop]


def test_price_ceiling_blocks_research_prop_card_but_preserves_probability():
    board = full_board()
    board["games"][0]["markets"][4]["away_or_over_price"] = -180
    board["games"][0]["markets"][4]["home_or_under_price"] = +150
    out = build_unified_phone_card(
        board, history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=runtime(), n_sims=300, seed=12,
    )
    passing_over = next(
        row for row in out["rows"]
        if row["market"] == "passing_yards" and row["side_index"] == 0
    )
    assert 0.0 <= passing_over["estimate_p"] <= 1.0
    assert passing_over["card_eligible"] is False
    assert passing_over["card_reason"] == "PRICE_ABOVE_STRAIGHT_CEILING"


def test_td_prop_is_explicit_no_model_until_scoring_prior_is_bound():
    board = ticket(
        """
        Chiefs @ Ravens
        Spread +3.5 -110 -110
        Total 47.5 -110 -110
        Prop "Derrick Henry" ATTD 0.5 -125 +105
        """
    )
    out = build_unified_phone_card(
        board, history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=runtime(), n_sims=250, seed=4,
    )
    props = [row for row in out["rows"] if row["market"] == "anytime_tds"]
    assert len(props) == 2
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert all("SCORING_COMPOSITION_PRIOR_REQUIRED" in row["reason"] for row in props)


def test_out_player_prop_fails_exact_player_match_without_poisoning_game_markets():
    injuries = [{
        "season": 2026, "week": 4, "team": "BAL", "gsis_id": "flowers",
        "report_status": "Out", "date_modified": "2026-10-01T20:00:00Z",
    }]
    board = ticket(
        """
        Chiefs @ Ravens
        Spread +3.5 -110 -110
        Total 47.5 -110 -110
        Prop "Zay Flowers" RecYards 72.5 -110 -110
        """
    )
    out = build_unified_phone_card(
        board, history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_rows=injuries, injury_source_ready=True, runtime=runtime(),
        n_sims=250, seed=8,
    )
    totals = [row for row in out["rows"] if row["market"] == "total"]
    props = [row for row in out["rows"] if row["market"] == "receiving_yards"]
    assert all(row["status"] == "NO_MODEL" for row in totals)
    assert all(row["reason"] == "V2K_DEVELOPMENT_BUDGET_EXHAUSTED_NO_PASS" for row in totals)
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert all("PROP_PLAYER_EXACT_MATCH_REQUIRED" in row["reason"] for row in props)


def test_live_prop_board_fails_closed_when_injury_source_is_not_ready():
    board = ticket(
        """
        Chiefs @ Ravens
        Spread +3.5 -110 -110
        Total 47.5 -110 -110
        Prop "Lamar Jackson" PassYards 249.5 -110 -110
        """
    )
    out = build_unified_phone_card(
        board, history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=False, runtime=runtime(),
        n_sims=200, seed=6,
    )
    totals = [row for row in out["rows"] if row["market"] == "total"]
    props = [row for row in out["rows"] if row["market"] == "passing_yards"]
    assert all(row["status"] == "NO_MODEL" for row in totals)
    assert all(row["reason"] == "V2K_DEVELOPMENT_BUDGET_EXHAUSTED_NO_PASS" for row in totals)
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert all(row["reason"] == "INJURY_SOURCE_REQUIRED_FOR_LIVE_PROPS" for row in props)


def test_market_context_phone_ignores_attempt9_runtime():
    a = build_unified_phone_card(
        full_board(), history=history(), schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=runtime(), n_sims=300, seed=33,
    )
    wild = runtime()
    wild["runtime"]["targets"]["margin"]["intercept"] = -99.0
    wild["runtime"]["targets"]["total"]["intercept"] = 180.0
    b = build_unified_phone_card(
        full_board(), history=[], schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=wild, n_sims=300, seed=33,
    )
    a_props = [(r["market"], r["selection"], r.get("estimate_p")) for r in a["rows"] if r["status"] == "PRICED"]
    b_props = [(r["market"], r["selection"], r.get("estimate_p")) for r in b["rows"] if r["status"] == "PRICED"]
    assert a_props == b_props
    assert a["games"][0]["forecast"]["margin"] == 3.5
    assert b["games"][0]["forecast"]["margin"] == 3.5


def test_prop_card_requires_posted_spread_and_total_context():
    board = ticket(
        """
        Chiefs @ Ravens
        Prop "Lamar Jackson" PassYards 249.5 -110 -110
        """
    )
    out = build_unified_phone_card(
        board, history=[], schedule_games=schedule(), depth_rows=depth(),
        player_rows=player_stats(), injury_source_ready=True, runtime=runtime(),
        n_sims=200, seed=2,
    )
    props = [row for row in out["rows"] if row["market"] == "passing_yards"]
    assert len(props) == 2
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert all(row["reason"] == "MARKET_CONTEXT_SPREAD_TOTAL_REQUIRED" for row in props)

def test_player_alias_normalization_accepts_generational_suffix_on_roster():
    board = ticket(
        """
        Chiefs @ Ravens
        Spread +3.5 -110 -110
        Total 47.5 -110 -110
        Prop "Travis Kelce" Receptions 5.5 -110 -110
        """
    )
    rows = copy.deepcopy(depth())
    for row in rows:
        if row.get("gsis_id") == "kelce":
            row["player_name"] = "Travis Kelce Sr."

    out = build_unified_phone_card(
        board,
        history=history(),
        schedule_games=schedule(),
        depth_rows=rows,
        player_rows=player_stats(),
        injury_source_ready=True,
        runtime=runtime(),
        n_sims=300,
        seed=61,
    )
    props = [row for row in out["rows"] if row["market"] == "receptions"]
    assert len(props) == 2
    assert all(row["status"] == "PRICED" for row in props)
    assert {row["player"] for row in props} == {"Travis Kelce Sr."}


def test_two_team_prop_board_fails_closed_if_either_team_simulation_fails():
    board = ticket(
        """
        Chiefs @ Ravens
        Spread +3.5 -110 -110
        Total 47.5 -110 -110
        Prop "Zay Flowers" RecYards 72.5 -110 -110
        Prop "Xavier Worthy" RecYards 65.5 -110 -110
        """
    )
    stats = copy.deepcopy(player_stats())
    for row in stats:
        if row.get("recent_team") == "BAL" and row.get("position") in {"RB", "WR", "TE"}:
            row["receiving_yards"] = 0

    out = build_unified_phone_card(
        board,
        history=history(),
        schedule_games=schedule(),
        depth_rows=depth(),
        player_rows=stats,
        injury_source_ready=True,
        runtime=runtime(),
        n_sims=300,
        seed=62,
    )
    props = [
        row for row in out["rows"]
        if row["market"] == "receiving_yards"
    ]
    assert len(props) == 4
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert out["selected_rows"] == []
    game = out["games"][0]
    assert game["role_status"] == "NO_MODEL"
    assert game["engine"]["prop_board_status"] == "NO_MODEL"
    assert game["engine"]["prop_board_error"].startswith(
        "GAME_PROP_SIMULATION_INCOMPLETE:home="
    )
    assert "home" in game["engine"]["team_simulation_errors"]


def test_phone_artifact_declares_graphic_field_contract():
    out = build_unified_phone_card(
        full_board(),
        history=history(),
        schedule_games=schedule(),
        depth_rows=depth(),
        player_rows=player_stats(),
        injury_source_ready=True,
        runtime=runtime(),
        n_sims=250,
        seed=63,
    )
    policy = out["presentation_policy"]
    assert policy["market_probability_field"] == "market_no_vig_p"
    assert policy["model_probability_field"] == "estimate_p"
    assert policy["score_field"] == "score_0_100"
    assert policy["score_label_field"] == "score_label"
    assert policy["kickoff_field"] == "games[].kickoff"
    assert policy["team_records"] == "OMIT_UNLESS_EXPLICITLY_SOURCED"

