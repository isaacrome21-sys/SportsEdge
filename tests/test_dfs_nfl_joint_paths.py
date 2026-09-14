from __future__ import annotations

from datetime import datetime, timezone

from sportsedge.dfs.football_joint import build_nfl_joint_path_snapshot
from sportsedge.dfs.sources.nfl_player_stats import build_prior_player_stat_history
from sportsedge.dfs.types import DKPlayer


def _stat(*, player_id: str, name: str, position: str, team: str, season: int, week: int,
          attempts: int = 0, pass_yards: int = 0, pass_tds: int = 0, interceptions: int = 0,
          carries: int = 0, rush_yards: int = 0, rush_tds: int = 0,
          targets: int = 0, receptions: int = 0, rec_yards: int = 0, rec_tds: int = 0,
          fumbles_lost: int = 0):
    return {
        "player_id": player_id,
        "player_display_name": name,
        "player_name": name,
        "position": position,
        "season": str(season),
        "week": str(week),
        "season_type": "REG",
        "team": team,
        "opponent_team": "BBB" if team == "AAA" else "AAA",
        "attempts": str(attempts),
        "passing_yards": str(pass_yards),
        "passing_tds": str(pass_tds),
        "interceptions": str(interceptions),
        "carries": str(carries),
        "rushing_yards": str(rush_yards),
        "rushing_tds": str(rush_tds),
        "targets": str(targets),
        "receptions": str(receptions),
        "receiving_yards": str(rec_yards),
        "receiving_tds": str(rec_tds),
        "fumbles_lost": str(fumbles_lost),
    }


def _history_rows(season: int, week: int):
    rows = []
    for team, prefix in (("AAA", "A"), ("BBB", "B")):
        rows.extend([
            _stat(player_id=f"{prefix}QB", name=f"{prefix} Quarterback", position="QB", team=team, season=season, week=week,
                  attempts=34, pass_yards=255, pass_tds=2, interceptions=1, carries=4, rush_yards=22),
            _stat(player_id=f"{prefix}RB", name=f"{prefix} Running Back", position="RB", team=team, season=season, week=week,
                  carries=17, rush_yards=76, rush_tds=1, targets=5, receptions=4, rec_yards=31),
            _stat(player_id=f"{prefix}WR", name=f"{prefix} Wide Receiver", position="WR", team=team, season=season, week=week,
                  carries=1, rush_yards=5, targets=10, receptions=7, rec_yards=94, rec_tds=1),
            _stat(player_id=f"{prefix}TE", name=f"{prefix} Tight End", position="TE", team=team, season=season, week=week,
                  targets=7, receptions=5, rec_yards=58, rec_tds=1),
            _stat(player_id=f"{prefix}WR2", name=f"{prefix} Wide Receiver Two", position="WR", team=team, season=season, week=week,
                  targets=7, receptions=4, rec_yards=72),
            _stat(player_id=f"{prefix}RB2", name=f"{prefix} Running Back Two", position="RB", team=team, season=season, week=week,
                  carries=8, rush_yards=35, targets=3, receptions=2, rec_yards=14),
        ])
    return rows


def _players():
    rows = []
    for team, opp, prefix in (("AAA", "BBB", "A"), ("BBB", "AAA", "B")):
        rows.extend([
            DKPlayer(f"dk-{prefix}QB", f"{prefix} Quarterback", team, opp, ("QB",), 7000),
            DKPlayer(f"dk-{prefix}RB", f"{prefix} Running Back", team, opp, ("RB",), 6500),
            DKPlayer(f"dk-{prefix}WR", f"{prefix} Wide Receiver", team, opp, ("WR",), 6200),
            DKPlayer(f"dk-{prefix}TE", f"{prefix} Tight End", team, opp, ("TE",), 4300),
            DKPlayer(f"dk-{prefix}DST", f"{team} DST", team, opp, ("DST",), 3000),
        ])
    return rows


def test_prior_history_excludes_target_week_and_future_rows() -> None:
    current = _history_rows(2026, 1) + _history_rows(2026, 2) + _history_rows(2026, 3)
    prior = _history_rows(2025, 18)
    payload = build_prior_player_stat_history(
        current_rows=current,
        prior_rows=prior,
        season=2026,
        target_week=3,
        team_ids=("AAA", "BBB"),
        current_source_uri="https://example.test/current.csv",
        current_source_sha256="a" * 64,
        prior_source_uri="https://example.test/prior.csv",
        prior_source_sha256="b" * 64,
    )
    assert payload["strictly_prior_week_only"] is True
    for player in payload["players"]:
        assert all(
            row["season"] == 2025 or (row["season"] == 2026 and row["week"] < 3)
            for row in player["games"]
        )


def test_joint_paths_are_aligned_and_preserve_passing_td_identity() -> None:
    current = _history_rows(2026, 1) + _history_rows(2026, 2)
    history = build_prior_player_stat_history(
        current_rows=current,
        season=2026,
        target_week=3,
        team_ids=("AAA", "BBB"),
        current_source_uri="https://example.test/current.csv",
        current_source_sha256="a" * 64,
    )
    snapshot = build_nfl_joint_path_snapshot(
        players=_players(),
        history_payload=history,
        as_of=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc),
        paths=1000,
        seed=42,
    )
    assert snapshot["path_count"] == 1000
    assert snapshot["status"].startswith("RESEARCH_ONLY")
    by_id = {row["player_id"]: row for row in snapshot["players"]}
    assert all(len(row["samples"]) == 1000 for row in by_id.values())
    for i in range(1000):
        for prefix in ("A", "B"):
            qb = by_id[f"dk-{prefix}QB"]["samples"][i]
            rec_tds = sum(
                by_id[f"dk-{prefix}{pos}"]["samples"][i]["rec_tds"]
                for pos in ("RB", "WR", "TE")
            )
            assert qb["pass_tds"] == rec_tds
    assert all("dk_points" in sample for sample in by_id["dk-ADST"]["samples"])


def test_joint_path_seed_is_replayable() -> None:
    history = build_prior_player_stat_history(
        current_rows=_history_rows(2026, 1),
        season=2026,
        target_week=2,
        team_ids=("AAA", "BBB"),
        current_source_uri="https://example.test/current.csv",
        current_source_sha256="c" * 64,
    )
    kwargs = dict(
        players=_players(), history_payload=history,
        as_of=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc), paths=1000, seed=9,
    )
    a = build_nfl_joint_path_snapshot(**kwargs)
    b = build_nfl_joint_path_snapshot(**kwargs)
    assert a["path_set_id"] == b["path_set_id"]
    assert a["players"][0]["samples"] == b["players"][0]["samples"]
