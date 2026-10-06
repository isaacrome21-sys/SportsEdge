from __future__ import annotations

import copy

import pytest

from sportsedge.nfl_lines_intake import parse_nfl_lines, tickets_to_dict
from sportsedge.nfl_unified_phone import build_unified_phone_card
from scripts.run_nfl_unified_lines_card import (
    _adapt_signed_yardage_for_nonnegative_v1,
    _apply_prop_board_safety,
    _name_alias_match,
    _normalize_ticket_prop_players,
)


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

def test_runner_alias_normalization_accepts_suffix_and_first_name_expansion():
    assert _name_alias_match("Kyle Pitts Sr.", "Kyle Pitts")
    assert _name_alias_match("Zachariah Branch", "Zach Branch")

    board = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "Kyle Pitts", "market": "receptions"},
                {"player": "Zach Branch", "market": "receiving_yards"},
            ],
        }]
    }
    rows = [
        {"team": "ATL", "player_name": "Kyle Pitts Sr."},
        {"team": "ATL", "player_name": "Zachariah Branch"},
        {"team": "NO", "player_name": "Chris Olave"},
    ]
    normalized, bindings = _normalize_ticket_prop_players(board, rows)
    props = normalized["games"][0]["markets"]
    assert props[0]["player"] == "Kyle Pitts Sr."
    assert props[0]["team"] == "ATL"
    assert props[1]["player"] == "Zachariah Branch"
    assert props[1]["team"] == "ATL"
    assert len(bindings) == 2


def test_runner_safety_voids_entire_two_team_prop_board_when_one_team_has_no_valid_rows():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "ATL WR", "market": "receiving_yards"},
                {"player": "NO WR", "market": "receiving_yards"},
            ],
        }]
    }
    payload = {
        "games": [{
            "rows": [
                {
                    "input_index": 0, "market": "receiving_yards", "team": "away",
                    "status": "PRICED", "selected": True, "estimate_p": 0.70, "score_0_100": 88,
                },
                {
                    "input_index": 1, "market": "receiving_yards", "team": "home",
                    "status": "NO_MODEL", "selected": False,
                    "reason": "ROLE_VALUE_INVALID:receiving_yards_per_reception",
                },
            ],
            "engine": {},
            "status": "PRICED_RESEARCH_PROPS_GAME_EDGE_DISABLED",
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [{"input_index": 0}],
    }
    out = _apply_prop_board_safety(payload, ticket)
    game = out["games"][0]
    assert game["role_status"] == "NO_MODEL"
    assert game["prop_status"] == "NO_MODEL_PROP_BOARD_INCOMPLETE"
    assert game["status"] == "PRICED_RESEARCH_PROPS_GAME_EDGE_DISABLED"
    assert game["engine"]["prop_board_status"] == "NO_MODEL"
    assert game["engine"]["prop_board_error"].startswith("GAME_PROP_SIMULATION_INCOMPLETE:NO=")
    assert out["selected_rows"] == []
    assert all(row["status"] == "NO_MODEL" for row in game["rows"])
    assert all(row["selected"] is False for row in game["rows"])
    assert all("score_0_100" not in row for row in game["rows"])


def test_runner_safety_keeps_two_team_board_when_both_requested_teams_price():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "ATL WR", "market": "receiving_yards"},
                {"player": "NO WR", "market": "receiving_yards"},
            ],
        }]
    }
    payload = {
        "games": [{
            "rows": [
                {"input_index": 0, "team": "away", "status": "PRICED", "selected": True},
                {"input_index": 1, "team": "home", "status": "PRICED", "selected": False},
            ],
            "engine": {},
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    game = out["games"][0]
    assert game["engine"]["prop_board_status"] == "AVAILABLE"
    assert game["role_status"] == "AVAILABLE"
    assert len(out["selected_rows"]) == 1


def test_runner_graphic_contract_uses_artifact_native_fields():
    out = _apply_prop_board_safety({"games": [], "rows": [], "selected_rows": []}, {"games": []})
    policy = out["presentation_policy"]
    assert policy["market_probability_field"] == "market_no_vig_p"
    assert policy["model_probability_field"] == "estimate_p"
    assert policy["score_field"] == "score_0_100"
    assert policy["score_label_field"] == "score_label"
    assert policy["kickoff_field"] == "games[].kickoff"
    assert policy["team_records"] == "OMIT_UNLESS_EXPLICITLY_SOURCED"

def test_runner_safety_does_not_void_game_for_individual_player_match_failure():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "ATL WR", "market": "receiving_yards"},
                {"player": "NO Mystery", "market": "receiving_yards"},
            ],
        }]
    }
    payload = {
        "games": [{
            "rows": [
                {
                    "input_index": 0, "team": "away", "status": "PRICED",
                    "selected": True, "estimate_p": 0.61, "score_0_100": 88,
                },
                {
                    "input_index": 1, "team": "home", "status": "NO_MODEL",
                    "selected": False,
                    "reason": "PROP_PLAYER_EXACT_MATCH_REQUIRED:NO Mystery:matches=0",
                },
            ],
            "engine": {},
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    game = out["games"][0]
    assert game["role_status"] == "AVAILABLE"
    assert game["engine"]["prop_board_status"] == "AVAILABLE"
    assert game["engine"]["failed_requested_teams"] == []
    assert "NO" in game["engine"]["degraded_requested_teams"]
    assert out["selected_rows"][0]["input_index"] == 0
    assert out["selected_rows"][0]["score_0_100"] == 88


def test_runner_safety_does_not_void_game_for_market_specific_td_prior_gap():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "ATL WR", "market": "receiving_yards"},
                {"player": "NO TE", "market": "anytime_td"},
            ],
        }]
    }
    payload = {
        "games": [{
            "rows": [
                {"input_index": 0, "team": "away", "status": "PRICED", "selected": True},
                {
                    "input_index": 1, "team": "home", "status": "NO_MODEL",
                    "selected": False,
                    "reason": "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS",
                },
            ],
            "engine": {},
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    assert out["games"][0]["role_status"] == "AVAILABLE"
    assert out["games"][0]["engine"]["prop_board_status"] == "AVAILABLE"
    assert len(out["selected_rows"]) == 1


def test_runner_safety_allows_single_team_quoted_prop_board():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "ATL WR", "market": "receiving_yards"},
            ],
        }]
    }
    payload = {
        "games": [{
            "rows": [
                {"input_index": 0, "team": "away", "status": "PRICED", "selected": True},
            ],
            "engine": {},
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    assert out["games"][0]["role_status"] == "AVAILABLE"
    assert len(out["selected_rows"]) == 1
    assert out["prop_board_safety_policy"]["single_team_quote_board_allowed"] is True

def test_runner_safety_still_catches_team_crash_when_same_team_has_a_local_alias_miss():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "ATL WR", "market": "receiving_yards"},
                {"player": "NO WR", "market": "receiving_yards"},
                {"player": "NO Mystery", "market": "receptions"},
            ],
        }]
    }
    payload = {
        "games": [{
            "rows": [
                {"input_index": 0, "team": "away", "status": "PRICED", "selected": True},
                {
                    "input_index": 1, "team": "home", "status": "NO_MODEL",
                    "selected": False, "reason": "ROLE_VALUE_INVALID:receiving_yards_per_reception",
                },
                {
                    "input_index": 2, "team": "home", "status": "NO_MODEL",
                    "selected": False,
                    "reason": "PROP_PLAYER_EXACT_MATCH_REQUIRED:NO Mystery:matches=0",
                },
            ],
            "engine": {},
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    game = out["games"][0]
    assert game["role_status"] == "NO_MODEL"
    assert game["engine"]["prop_board_error"].startswith(
        "GAME_PROP_SIMULATION_INCOMPLETE:NO=ROLE_VALUE_INVALID:"
    )
    assert out["selected_rows"] == []

def test_selection_concentration_is_flagged_but_never_rebalanced():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": f"ATL {i}", "market": "receiving_yards"}
                for i in range(6)
            ] + [
                {"player": "NO 1", "market": "receiving_yards"},
            ],
        }]
    }
    rows = []
    for i in range(6):
        rows.append({
            "input_index": i,
            "team": "away",
            "status": "PRICED",
            "selected": True,
            "selection": f"ATL {i} Under",
        })
    rows.append({
        "input_index": 6,
        "team": "home",
        "status": "PRICED",
        "selected": False,
        "selection": "NO 1 Over",
    })
    payload = {
        "games": [{
            "rows": rows,
            "engine": {},
            "status": "PRICED_RESEARCH_PROPS_GAME_EDGE_DISABLED",
            "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [],
        "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    diag = out["games"][0]["prop_selection_diagnostics"]
    assert "ALL_SELECTED_PROPS_ONE_TEAM_WITH_TWO_TEAM_PRICING" in diag["alerts"]
    assert "SELECTED_PROP_DIRECTION_CONCENTRATED_UNDER" in diag["alerts"]
    assert diag["selection_changed_by_diagnostic"] is False
    assert diag["review_required"] is True
    assert out["prop_card_review_required"] is True
    assert out["games"][0]["prop_selection_policy"]["forces_team_balance"] is False
    assert out["games"][0]["prop_selection_policy"]["forces_over_under_balance"] is False
    assert len(out["selected_rows"]) == 6

def test_correlation_policy_keeps_only_strongest_same_player_pass_volume_expression():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "Michael Penix Jr.", "market": "pass_attempts"},
                {"player": "Michael Penix Jr.", "market": "completions"},
                {"player": "Michael Penix Jr.", "market": "passing_yards"},
            ],
        }]
    }
    rows = [
        {
            "input_index": 0, "team": "away", "player": "Michael Penix Jr.",
            "market": "pass_attempts", "status": "PRICED", "selected": True,
            "selection": "Michael Penix Jr. Under", "ev_per_dollar": 0.08,
            "edge_probability_points": 0.08, "score_0_100": 88,
        },
        {
            "input_index": 1, "team": "away", "player": "Michael Penix Jr.",
            "market": "completions", "status": "PRICED", "selected": True,
            "selection": "Michael Penix Jr. Under", "ev_per_dollar": 0.12,
            "edge_probability_points": 0.10, "score_0_100": 88,
        },
        {
            "input_index": 2, "team": "away", "player": "Michael Penix Jr.",
            "market": "passing_yards", "status": "PRICED", "selected": True,
            "selection": "Michael Penix Jr. Under", "ev_per_dollar": 0.18,
            "edge_probability_points": 0.15, "score_0_100": 88,
        },
    ]
    payload = {
        "games": [{
            "rows": rows, "engine": {}, "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [], "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    selected = out["selected_rows"]
    assert len(selected) == 1
    assert selected[0]["market"] == "passing_yards"
    suppressed = [row for row in out["rows"] if not row.get("selected")]
    assert {row["selection_suppressed_reason"] for row in suppressed} == {
        "CORRELATED_PLAYER_FAMILY"
    }
    policy = out["games"][0]["prop_selection_policy"]
    assert policy["candidate_pair_selections"] == 3
    assert policy["served_prop_selections"] == 1


def test_correlation_policy_has_no_arbitrary_global_prop_count_cap():
    specs = [
        ("P0", "passing_yards"),
        ("P1", "receiving_yards"),
        ("P2", "rushing_yards"),
        ("P3", "rush_attempts"),
        ("P4", "pass_tds"),
        ("P5", "anytime_tds"),
        ("P6", "interceptions"),
    ]
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": player, "market": market}
                for player, market in specs
            ],
        }]
    }
    rows = [
        {
            "input_index": i, "team": "away", "player": player,
            "market": market, "status": "PRICED", "selected": True,
            "selection": f"{player} Under",
            "ev_per_dollar": 0.20 - i * 0.01,
            "edge_probability_points": 0.20 - i * 0.01,
            "score_0_100": 88,
        }
        for i, (player, market) in enumerate(specs)
    ]
    payload = {
        "games": [{
            "rows": rows, "engine": {}, "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [], "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    assert len(out["selected_rows"]) == 7
    policy = out["games"][0]["prop_selection_policy"]
    assert policy["global_prop_count_cap"] is None
    assert policy["served_prop_selections"] == 7
    assert policy["suppressed"] == []


def test_correlation_policy_never_forces_opposite_team_or_opposite_direction():
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": f"ATL {i}", "market": "receiving_yards"}
                for i in range(4)
            ] + [
                {"player": "NO 1", "market": "receiving_yards"},
            ],
        }]
    }
    rows = [
        {
            "input_index": i, "team": "away", "player": f"ATL {i}",
            "market": "receiving_yards", "status": "PRICED", "selected": True,
            "selection": f"ATL {i} Under", "ev_per_dollar": 0.10 + i * 0.01,
            "edge_probability_points": 0.08 + i * 0.01, "score_0_100": 88,
        }
        for i in range(4)
    ]
    rows.append({
        "input_index": 4, "team": "home", "player": "NO 1",
        "market": "receiving_yards", "status": "PRICED", "selected": False,
        "selection": "NO 1 Over", "ev_per_dollar": -0.04,
        "edge_probability_points": -0.03, "score_0_100": 88,
    })
    payload = {
        "games": [{
            "rows": rows, "engine": {}, "role_status": "AVAILABLE",
            "role_error": None,
        }],
        "rows": [], "selected_rows": [],
    }
    out = _apply_prop_board_safety(payload, ticket)
    assert len(out["selected_rows"]) == 2
    assert all(row["team"] == "away" for row in out["selected_rows"])
    assert all(str(row["selection"]).endswith("Under") for row in out["selected_rows"])
    suppressed = [
        row for row in out["rows"]
        if row.get("selection_suppressed_reason") == "CORRELATED_TEAM_OFFENSE_CLUSTER"
    ]
    assert len(suppressed) == 2
    policy = out["games"][0]["prop_selection_policy"]
    assert policy["forces_team_balance"] is False
    assert policy["forces_over_under_balance"] is False

def test_runner_signed_yardage_compatibility_copy_is_narrow_and_audited():
    source = [
        {
            "player_id": "cj",
            "player_name": "CJ Donaldson",
            "season": "2026",
            "week": "3",
            "recent_team": "NO",
            "receptions": "1",
            "receiving_yards": "-2",
            "rushing_yards": "11",
            "passing_yards": "0",
        },
        {
            "player_id": "ok",
            "player_name": "Healthy",
            "season": "2026",
            "week": "3",
            "recent_team": "ATL",
            "receiving_yards": "22",
        },
    ]
    adapted, receipts = _adapt_signed_yardage_for_nonnegative_v1(source)
    assert source[0]["receiving_yards"] == "-2"
    assert adapted[0]["receiving_yards"] == 0.0
    assert adapted[0]["rushing_yards"] == "11"
    assert adapted[1]["receiving_yards"] == "22"
    assert receipts == [{
        "player_id": "cj",
        "player_name": "CJ Donaldson",
        "season": "2026",
        "week": "3",
        "team": "NO",
        "field": "receiving_yards",
        "source_value": -2.0,
        "model_input_value": 0.0,
        "reason": "FROZEN_V1_NONNEGATIVE_EFFICIENCY_COMPATIBILITY",
    }]

