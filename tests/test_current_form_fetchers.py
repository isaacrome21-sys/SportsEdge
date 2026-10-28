"""Offline contract tests for sportsedge.current_form (no network).

Every fetcher is exercised through an injected opener serving pinned
fixtures, mirroring the live-verified schemas recorded in
research/analytics_current_form_20261027/. The tests pin the layer's
invariants: fail-closed reason codes, point-in-time week cutoffs,
week-0 aggregate exclusion (nflverse NGS), Sports Reference table
extraction, and the factoring-spec adjustment caps.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest

from sportsedge.current_form import (
    bbr_per_game,
    build_context_block,
    capped_adjustment,
    current_form_ngs,
    expected_statistics,
    pfr_team_stats,
    player_advanced_stats,
    snap_share_form,
    target_share_form,
    team_epa_form,
    team_form_from_scoreboards,
)
from sportsedge.current_form.common import fetch_bytes


def opener_for(mapping):
    def _opener(request, timeout):
        url = request.full_url
        for needle, body in mapping.items():
            if needle in url:
                return body
        raise HTTPError(url, 404, "not found", None, None)

    return _opener


def gz(text: str) -> bytes:
    return gzip.compress(text.encode())


NGS_PASSING = "\n".join(
    [
        "season,season_type,week,player_display_name,player_position,team_abbr,attempts,"
        "completion_percentage_above_expectation,avg_time_to_throw,avg_intended_air_yards,"
        "avg_air_yards_to_sticks,aggressiveness,passer_rating",
        # week 0 = nflverse season aggregate row; must never enter windows
        "2026,REG,0,Test QB,QB,AAA,999,99.0,9.9,99.0,99.0,99.0,158.3",
        "2026,REG,1,Test QB,QB,AAA,10,1.0,2.5,8.0,1.0,10.0,90.0",
        "2026,REG,2,Test QB,QB,AAA,10,2.0,2.5,8.0,1.0,10.0,90.0",
        "2026,REG,3,Test QB,QB,AAA,10,3.0,2.5,8.0,1.0,10.0,90.0",
        "2026,REG,4,Test QB,QB,AAA,10,50.0,2.5,8.0,1.0,10.0,90.0",
    ]
)


def test_ngs_window_excludes_week0_and_future_weeks():
    out = current_form_ngs(
        "passing", season=2026, through_week=3, opener=opener_for({"ngs_passing": gz(NGS_PASSING)})
    )
    assert out["status"] == "OK"
    player = out["players"]["Test QB"]
    assert player["weeks"] == [1, 2, 3]
    assert player["season"]["completion_percentage_above_expectation"] == 2.0
    assert out["label"] == "RESEARCH_CONTEXT_ONLY"


def test_ngs_through_week_beyond_file_fails_closed():
    out = current_form_ngs(
        "passing", season=2026, through_week=9, opener=opener_for({"ngs_passing": gz(NGS_PASSING)})
    )
    assert out["status"] == "MISSING"
    assert out["reason"] == "NGS_THROUGH_WEEK_BEYOND_FILE"
    assert out["file_max_week"] == 4


def test_fetch_bytes_http_error_fails_closed():
    out = fetch_bytes("https://example.invalid/x", opener=opener_for({}))
    assert out == {
        "status": "MISSING",
        "reason": "FETCH_HTTP_ERROR",
        "url": "https://example.invalid/x",
    }


SNAPS = "\n".join(
    [
        "game_id,pfr_game_id,season,game_type,week,player,pfr_player_id,position,team,opponent,"
        "offense_snaps,offense_pct,defense_snaps,defense_pct,st_snaps,st_pct",
        "g1,,2026,REG,1,Runner One,,RB,AAA,BBB,30,0.5,0,0.0,0,0.0",
        "g2,,2026,REG,2,Runner One,,RB,AAA,CCC,60,1.0,0,0.0,0,0.0",
        "g3,,2026,REG,3,Runner One,,RB,AAA,DDD,60,1.0,0,0.0,0,0.0",
    ]
)


def test_snap_share_form_windows():
    out = snap_share_form(
        season=2026, through_week=2, last_n=1, opener=opener_for({"snap_counts_2026": SNAPS.encode()})
    )
    assert out["status"] == "OK"
    player = out["players"]["Runner One"]
    assert player["games"] == 2
    assert player["offense_pct_season"] == 0.75
    assert player["offense_pct_last_n"] == 1.0


WEEK_STATS = "\n".join(
    [
        "player_id,player_display_name,position,team,headshot_url,season,week,season_type,"
        "completions,attempts,passing_yards,passing_tds,passing_interceptions,sacks,sack_yards,"
        "sack_fumbles,sack_fumbles_lost,passing_air_yards,passing_yards_after_catch,"
        "passing_first_downs,passing_epa,passing_2pt_conversions,pacr,dakota,carries,rushing_yards,"
        "rushing_tds,rushing_fumbles,rushing_fumbles_lost,rushing_first_downs,rushing_epa,"
        "rushing_2pt_conversions,receptions,targets,receiving_yards,receiving_tds,"
        "receiving_fumbles,receiving_fumbles_lost,receiving_air_yards,receiving_yards_after_catch,"
        "receiving_first_downs,receiving_epa,receiving_2pt_conversions,racr,target_share,air_yards_share,"
        "wopr_x,wopr_y,fantasy_points,fantasy_points_ppr",
        "p1,Receiver A,WR,AAA,,2026,1,REG,0,0,0,0,0,0,0,0,0,0,0,0,0.0,0,0,0,0,0,0,0,0,0,0,0,"
        "8,10,80,1,0,0,50,30,4,2.5,0,0,0,0,0,0",
        "p2,Receiver B,WR,AAA,,2026,1,REG,0,0,0,0,0,0,0,0,0,0,0,0,0.0,0,0,0,0,0,0,0,0,0,0,0,"
        "24,30,240,2,0,0,150,90,12,7.5,0,0,0,0,0,0",
    ]
)


def test_target_share_and_epa_sums():
    out = target_share_form(
        season=2026,
        through_week=1,
        opener=opener_for({"stats_player_week_2026": WEEK_STATS.encode()}),
    )
    assert out["status"] == "OK"
    season = out["players_season"]
    assert season["Receiver A"]["target_share"] == 0.25
    assert season["Receiver B"]["target_share"] == 0.75
    assert season["Receiver B"]["receiving_epa"] == 7.5


PBP = "\n".join(
    [
        "game_id,week,posteam,defteam,play_type,epa,success,pass,rush",
        "g1,1,AAA,BBB,pass,0.5,1,1,0",
        "g1,1,AAA,BBB,rush,-0.5,0,0,1",
        "g1,1,BBB,AAA,pass,1.0,1,1,0",
        "g2,2,AAA,CCC,pass,0.25,1,1,0",
    ]
)


def test_team_epa_splits():
    out = team_epa_form(
        season=2026, through_week=2, opener=opener_for({"play_by_play_2026": gz(PBP)})
    )
    assert out["status"] == "OK"
    aaa = out["offense_season"]["AAA"]
    assert aaa["plays"] == 3
    assert aaa["epa_per_play"] == round(0.25 / 3, 4)
    assert aaa["pass_epa_per_play"] == 0.375
    assert out["defense_season"]["AAA"]["epa_per_play"] == 1.0


SCOREBOARD = {
    "events": [
        {
            "date": "2026-10-20T00:00:00Z",
            "status": {"type": {"completed": True}},
            "competitions": [
                {
                    "competitors": [
                        {"team": {"abbreviation": "AAA"}, "score": "110", "winner": True},
                        {"team": {"abbreviation": "BBB"}, "score": "100", "winner": False},
                    ]
                }
            ],
        },
        {
            "date": "2026-10-25T00:00:00Z",
            "status": {"type": {"completed": False}},
            "competitions": [
                {
                    "competitors": [
                        {"team": {"abbreviation": "AAA"}, "score": "0", "winner": False},
                        {"team": {"abbreviation": "CCC"}, "score": "0", "winner": False},
                    ]
                }
            ],
        },
    ]
}


def test_espn_form_counts_only_finals_before_as_of():
    body = json.dumps(SCOREBOARD).encode()
    out = team_form_from_scoreboards(
        "nba",
        as_of=datetime(2026, 10, 21, tzinfo=timezone.utc),
        dates=["20261020"],
        opener=opener_for({"scoreboard": body}),
    )
    assert out["status"] == "OK"
    assert out["teams"]["AAA"] == {
        "games": 1,
        "wins": 1,
        "losses": 0,
        "avg_margin": 10.0,
        "dates": ["20261020"],
    }
    assert "CCC" not in out["teams"]


SAVANT = (
    '\ufeff"last_name, first_name","player_id","year","pa","bip","ba","est_ba",'
    '"est_ba_minus_ba_diff","slg","est_slg","est_slg_minus_slg_diff","woba","est_woba",'
    '"est_woba_minus_woba_diff"\r\n'
    '"Hitter, One","123",2026,100,60,0.250,0.280,0.030,0.400,0.450,0.050,0.320,0.350,0.030\r\n'
)


def test_savant_expected_statistics_parse():
    out = expected_statistics(
        entity="batter", season=2026, opener=opener_for({"expected_statistics": SAVANT.encode()})
    )
    assert out["status"] == "OK"
    row = out["players"]["123"]
    assert row["name"] == "Hitter, One"
    assert row["est_woba_minus_woba"] == 0.03


TORVIK_ROW = ",".join(
    ["Player One", "Team A", "B10", "30", "80.1", "110.5", "25.0", "52.0", "55.0", "8.0",
     "20.0", "15.0", "12.0", "40", "50", "0.80", "20", "40", "0.50", "10", "30", "0.333",
     "1.0", "1.5", "40.0", "Jr", "6-5", "3", "5.25", "112.0", "x", "y", "2027"]
)


def test_torvik_positional_parse_and_drift_guard():
    out = player_advanced_stats(season=2027, opener=opener_for({"getadvstats": TORVIK_ROW.encode()}))
    assert out["status"] == "OK"
    player = out["players"][0]
    assert player["player"] == "Player One"
    assert player["offensive_rating"] == 110.5
    assert player["porpag"] == 5.25
    bad = player_advanced_stats(
        season=2027, opener=opener_for({"getadvstats": b"only,three,fields"})
    )
    assert bad["status"] == "MISSING"
    assert bad["reason"] == "SCHEMA_DRIFT"


PFR_HTML = """
<table id="team_stats"><thead><tr>
<th data-stat="team">Team</th><th data-stat="g">G</th><th data-stat="points">PF</th>
</tr></thead><tbody>
<tr><th data-stat="team">Team A</th><td data-stat="g">7</td><td data-stat="points">180</td></tr>
<tr><th data-stat="team">Team</th><td data-stat="g">G</td><td data-stat="points">PF</td></tr>
<tr><th data-stat="team">Team B</th><td data-stat="g">7</td><td data-stat="points">150</td></tr>
</tbody></table>
"""

BBR_HTML = """
<table id="per_game_stats"><thead><tr>
<th data-stat="name_display">Player</th><th data-stat="team_name_abbr">Tm</th><th data-stat="pts_per_g">PTS</th>
</tr></thead><tbody>
<tr><th data-stat="name_display">Star One</th><td data-stat="team_name_abbr">AAA</td><td data-stat="pts_per_g">30.5</td></tr>
</tbody></table>
"""


def test_sports_reference_table_extraction():
    out = pfr_team_stats(season=2026, opener=opener_for({"pro-football-reference": PFR_HTML.encode()}))
    assert out["status"] == "OK"
    assert out["teams"]["Team A"]["points"] == 180.0
    assert out["teams"]["Team A"]["games"] == 7
    assert "Team" not in out["teams"]  # repeated header row dropped
    out = bbr_per_game(season_end_year=2027, opener=opener_for({"basketball-reference": BBR_HTML.encode()}))
    assert out["status"] == "OK"
    assert out["players"][0]["player"] == "Star One"
    assert out["players"][0]["pts_per_g"] == 30.5


def test_adjustment_caps_are_enforced():
    adj = capped_adjustment("points", 0.9, signal="form", source="test")
    assert adj["applied_value"] == 0.5
    assert adj["capped"] is True
    adj = capped_adjustment("probability", 0.05, signal="form", source="test")
    assert adj["applied_value"] == 0.02
    block = build_context_block(
        [{"status": "MISSING", "reason": "FETCH_HTTP_ERROR"}],
        adjustments=[
            capped_adjustment("points", 0.5, signal="a", source="s"),
            capped_adjustment("points", 0.5, signal="b", source="s"),
            capped_adjustment("points", 0.5, signal="c", source="s"),
        ],
    )
    applied = [a["applied_value"] for a in block["current_form_context"]["suggested_adjustments"]]
    assert applied == [0.5, 0.5, 0.0]
    assert block["current_form_context"]["label"] == "RESEARCH_CONTEXT_ONLY"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
