import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.unified_auto_roles import (
    assemble_unified_team_models,
    build_unified_team_models_from_nflverse,
)
from sportsedge.sports.nfl.unified_run_it import run_unified_nfl_run_it_from_nflverse


def binding():
    return {
        "status": "BOUND",
        "provider": "nflverse-data-archives",
        "published_at": "2026-09-24T12:00:00+00:00",
        "source_uri": "https://github.com/nflverse/nflverse-data-archives/releases/download/archive-2026-09-24/player_stats.rds",
        "raw_sha256": "a" * 64,
    }


def player_rows():
    return [
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "chi_qb1", "player_name": "CHI QB1", "team": "CHI", "position": "QB",
            "attempts": 32, "completions": 21, "passing_yards": 245, "passing_tds": 2,
            "interceptions": 1, "carries": 4, "rushing_yards": 18, "rushing_tds": 1,
        },
        {
            "game_id": "old2", "season": 2026, "week": 2,
            "player_id": "chi_qb1", "player_name": "CHI QB1", "team": "CHI", "position": "QB",
            "attempts": 35, "completions": 24, "passing_yards": 270, "passing_tds": 1,
            "interceptions": 0, "carries": 5, "rushing_yards": 24,
        },
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "chi_qb2", "player_name": "CHI QB2", "team": "CHI", "position": "QB",
            "attempts": 2, "completions": 1, "passing_yards": 7,
        },
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "chi_wr1", "player_name": "CHI WR1", "team": "CHI", "position": "WR",
            "targets": 9, "receptions": 6, "receiving_yards": 78, "receiving_tds": 1,
        },
        {
            "game_id": "old2", "season": 2026, "week": 2,
            "player_id": "chi_wr1", "player_name": "CHI WR1", "team": "CHI", "position": "WR",
            "targets": 10, "receptions": 7, "receiving_yards": 91, "receiving_tds": 1,
        },
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "chi_rb1", "player_name": "CHI RB1", "team": "CHI", "position": "RB",
            "targets": 4, "receptions": 3, "receiving_yards": 24,
            "carries": 15, "rushing_yards": 63, "rushing_tds": 1,
        },
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "gb_qb1", "player_name": "GB QB1", "team": "GB", "position": "QB",
            "attempts": 31, "completions": 20, "passing_yards": 230, "passing_tds": 2,
            "interceptions": 1, "carries": 3, "rushing_yards": 12,
        },
        {
            "game_id": "old2", "season": 2026, "week": 2,
            "player_id": "gb_qb1", "player_name": "GB QB1", "team": "GB", "position": "QB",
            "attempts": 36, "completions": 25, "passing_yards": 289, "passing_tds": 2,
            "interceptions": 0, "carries": 4, "rushing_yards": 16,
        },
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "gb_wr1", "player_name": "GB WR1", "team": "GB", "position": "WR",
            "targets": 8, "receptions": 5, "receiving_yards": 65, "receiving_tds": 2,
        },
        {
            "game_id": "old1", "season": 2026, "week": 1,
            "player_id": "gb_rb1", "player_name": "GB RB1", "team": "GB", "position": "RB",
            "targets": 5, "receptions": 4, "receiving_yards": 31,
            "carries": 17, "rushing_yards": 72, "rushing_tds": 2,
        },
    ]


def depth_rows():
    return [
        {
            "dt": "2026-09-27T12:00:00Z", "team": "CHI", "gsis_id": "chi_qb1",
            "pos_abb": "QB", "pos_rank": 1,
        },
        {
            "dt": "2026-09-27T12:00:00Z", "team": "CHI", "gsis_id": "chi_qb2",
            "pos_abb": "QB", "pos_rank": 2,
        },
        {
            # Future snapshot must never replace the PIT starter.
            "dt": "2026-09-29T12:00:00Z", "team": "CHI", "gsis_id": "chi_qb2",
            "pos_abb": "QB", "pos_rank": 1,
        },
        {
            "dt": "2026-09-27T13:00:00Z", "team": "GB", "gsis_id": "gb_qb1",
            "pos_abb": "QB", "pos_rank": 1,
        },
    ]


def build(**overrides):
    args = dict(
        game_id="2026_03_GB_CHI",
        kickoff="2026-09-28T23:00:00Z",
        observed_at="2026-09-28T20:00:00Z",
        source_binding=binding(),
        player_rows=player_rows(),
        depth_rows=depth_rows(),
        depth_source_uri="https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2026.csv",
        depth_source_sha256="b" * 64,
        as_of="2026-09-28T20:30:00Z",
        home_team="CHI",
        away_team="GB",
    )
    args.update(overrides)
    return build_unified_team_models_from_nflverse(**args)


def test_builds_home_away_models_with_pit_depth_starters():
    out = build()
    assert out["status"] == "AVAILABLE"
    assert out["starter_qb_id_by_team"] == {"CHI": "chi_qb1", "GB": "gb_qb1"}
    assert out["home_model"]["qb"]["player_id"] == "chi_qb1"
    assert out["away_model"]["qb"]["player_id"] == "gb_qb1"
    assert {row["position"] for row in out["home_model"]["skill_players"]} == {"WR", "RB"}
    assert out["home_model"]["pass_td_share"] == pytest.approx(0.5)
    assert out["away_model"]["pass_td_share"] == pytest.approx(0.5)
    assert out["depth_snapshot_asof_by_team"]["CHI"] == "2026-09-27T12:00:00+00:00"
    assert out["provenance"]["role_source_raw_sha256"] == "a" * 64
    assert out["provenance"]["depth_source_sha256"] == "b" * 64


def test_missing_starter_role_row_fails_closed():
    rows = depth_rows()
    rows[0] = dict(rows[0], gsis_id="unknown_qb")
    with pytest.raises(NFLContextError, match="starter QB role row missing:CHI"):
        build(depth_rows=rows)


def test_two_rank_one_qbs_same_snapshot_fail_closed():
    rows = depth_rows()
    rows.append({
        "dt": "2026-09-27T12:00:00Z", "team": "CHI", "gsis_id": "chi_qb2",
        "pos_abb": "QB", "pos_rank": 1,
    })
    with pytest.raises(NFLContextError, match="starting QB identity not unique:CHI"):
        build(depth_rows=rows)


def test_future_depth_only_fails_closed():
    rows = [
        {
            "dt": "2026-09-29T12:00:00Z", "team": "CHI", "gsis_id": "chi_qb1",
            "pos_abb": "QB", "pos_rank": 1,
        },
        {
            "dt": "2026-09-29T12:00:00Z", "team": "GB", "gsis_id": "gb_qb1",
            "pos_abb": "QB", "pos_rank": 1,
        },
    ]
    with pytest.raises(NFLContextError, match="depth snapshot missing:CHI"):
        build(depth_rows=rows)


def test_role_bundle_cannot_be_newer_than_assembly_asof():
    role_bundle = {
        "status": "AVAILABLE",
        "observed_at": "2026-09-28T21:00:00Z",
        "players": [],
        "team_scoring": {},
    }
    with pytest.raises(NFLContextError, match="role bundle observed after assembly as_of"):
        assemble_unified_team_models(
            role_bundle=role_bundle,
            depth_rows=depth_rows(),
            depth_source_uri="https://example.com/depth.csv",
            depth_source_sha256="b" * 64,
            as_of="2026-09-28T20:30:00Z",
            home_team="CHI",
            away_team="GB",
        )


def test_invalid_depth_provenance_fails_closed():
    with pytest.raises(NFLContextError, match="depth source_sha256 invalid"):
        build(depth_source_sha256="not-a-sha")


def _qualification(market, selection):
    return {
        "game_id": "2026_03_GB_CHI",
        "market": market,
        "selection": selection,
        "captured_at": "2026-09-28T20:29:00Z",
        "kickoff_at": "2026-09-28T23:00:00Z",
        "source_version": "nfl-unified-auto-v1",
        "feature_digest": "abc123",
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": True,
        "matchup_supported": True,
        "injury_context_ready": True,
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }


def test_raw_nflverse_inputs_flow_into_game_and_qb_prop_boards():
    game_quotes = [
        {
            "game_id": "2026_03_GB_CHI", "home": "CHI", "away": "GB",
            "market": "moneyline", "selection": "CHI", "price_american": 120,
            "book": "draftkings", "retrieved_at": "2026-09-28T20:30:00Z",
        },
        {
            "game_id": "2026_03_GB_CHI", "home": "CHI", "away": "GB",
            "market": "moneyline", "selection": "GB", "price_american": -140,
            "book": "draftkings", "retrieved_at": "2026-09-28T20:30:00Z",
        },
    ]
    prop_quotes = []
    for book in ("draftkings", "fanduel", "betmgm"):
        prop_quotes.extend([
            {
                "game_id": "2026_03_GB_CHI", "player": "CHI QB1",
                "market": "passing_yards", "selection": "OVER", "line": 100.5,
                "book": book, "price_american": 110,
                "retrieved_at": "2026-09-28T20:30:00Z",
            },
            {
                "game_id": "2026_03_GB_CHI", "player": "CHI QB1",
                "market": "passing_yards", "selection": "UNDER", "line": 100.5,
                "book": book, "price_american": -130,
                "retrieved_at": "2026-09-28T20:30:00Z",
            },
        ])

    out = run_unified_nfl_run_it_from_nflverse(
        game_id="2026_03_GB_CHI",
        home_team="CHI",
        away_team="GB",
        kickoff="2026-09-28T23:00:00Z",
        observed_at="2026-09-28T20:00:00Z",
        source_binding=binding(),
        player_rows=player_rows(),
        depth_rows=depth_rows(),
        depth_source_uri="https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2026.csv",
        depth_source_sha256="b" * 64,
        attempt9_margin=6.0,
        attempt9_total=44.0,
        game_quotes=game_quotes,
        prop_quotes=prop_quotes,
        qualification_snapshots=[
            _qualification("moneyline", "CHI"),
            _qualification("moneyline", "GB"),
            _qualification("passing_yards", "CHI QB1"),
        ],
        as_of="2026-09-28T20:30:30Z",
        edge_floor=0.0,
        n_sims=400,
        seed=17,
    )

    assert out["auto_roles"]["status"] == "AVAILABLE"
    assert out["auto_roles"]["starter_qb_id_by_team"]["CHI"] == "chi_qb1"
    assert out["game_card"]["picks"]
    qb_rows = [
        row for row in out["prop_board"]
        if row["player"] == "CHI QB1" and row["market"] == "passing_yards"
    ]
    assert qb_rows
    assert qb_rows[0]["status"] == "OK"
    assert qb_rows[0]["score_0_100"] == 100
