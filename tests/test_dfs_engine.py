from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sportsedge.dfs.draftkings import DraftKingsClient, resolve_slate
from sportsedge.dfs.optimizer import optimize_single_entry
from sportsedge.dfs.projections import validate_projection_freshness
from sportsedge.dfs.rules import get_rules
from sportsedge.dfs.scoring import football_expected_dk_points, mlb_hitter_expected_dk_points
from sportsedge.dfs.types import DKPlayer, DKSlate, Projection


def p(pid: str, name: str, team: str, opp: str, pos: str, salary: int, mean: float) -> tuple[DKPlayer, Projection]:
    player = DKPlayer(pid, name, team, opp, (pos,), salary)
    proj = Projection(pid, mean, mean * 1.55, ownership=0.12, source="TEST")
    return player, proj


def test_scoring_contracts() -> None:
    assert football_expected_dk_points({"pass_yards": 300, "pass_tds": 2, "interceptions": 1, "p_pass_300": 1}) == 22.0
    assert mlb_hitter_expected_dk_points({"home_runs": 1, "rbi": 2, "runs": 1, "walks": 1}) == 18.0


def test_dk_lobby_and_draftables_normalization() -> None:
    lobby = {
        "DraftGroups": [{"DraftGroupId": 123, "StartDate": "2026-09-18T23:30:00Z", "GameCount": 5, "GameTypeId": 1}],
        "Contests": [{"id": 7, "dg": 123, "n": "CFB Main", "po": 150000}],
    }
    draftables = {
        "draftables": [{
            "draftableId": 999,
            "playerDkId": 44,
            "displayName": "Quarter Back",
            "position": "QB",
            "salary": 8000,
            "teamAbbreviation": "AAA",
            "competition": {"competitionId": 2, "name": "AAA @ BBB", "startTime": "2026-09-18T23:30:00Z"},
            "draftStatAttributes": [{"id": 90, "value": 22.5}],
        }]
    }

    def getter(url: str):
        return draftables if "draftgroups" in url else lobby

    client = DraftKingsClient(getter=getter)
    slates = client.discover_slates("CFB")
    assert slates[0].draft_group_id == 123
    players = client.fetch_draftables(123)
    assert players[0].salary == 8000
    assert players[0].opponent == "BBB"
    assert players[0].dk_fppg == 22.5


def test_resolve_slate_by_lock_time() -> None:
    slates = [
        DKSlate("MLB", 1, datetime(2026, 9, 18, 23, 5, tzinfo=timezone.utc), game_count=4),
        DKSlate("MLB", 2, datetime(2026, 9, 18, 23, 10, tzinfo=timezone.utc), game_count=8),
    ]
    selected = resolve_slate(slates, requested_start=datetime(2026, 9, 18, 23, 10, tzinfo=timezone.utc))
    assert selected.draft_group_id == 2


def test_nfl_optimizer_builds_qb_stack_and_valid_roster() -> None:
    rows = [
        p("qb1", "QB A", "A", "B", "QB", 6500, 23),
        p("qb2", "QB B", "B", "A", "QB", 6100, 19),
        p("rb1", "RB A", "A", "B", "RB", 7000, 19),
        p("rb2", "RB B", "B", "A", "RB", 6500, 18),
        p("rb3", "RB C", "C", "D", "RB", 5800, 16),
        p("wr1", "WR A1", "A", "B", "WR", 7200, 21),
        p("wr2", "WR A2", "A", "B", "WR", 5200, 15),
        p("wr3", "WR B1", "B", "A", "WR", 6000, 17),
        p("wr4", "WR C1", "C", "D", "WR", 4800, 14),
        p("te1", "TE A", "A", "B", "TE", 4200, 12),
        p("te2", "TE B", "B", "A", "TE", 3800, 10),
        p("dst1", "DST C", "C", "D", "DST", 3000, 8),
        p("dst2", "DST D", "D", "C", "DST", 2800, 7),
    ]
    players = [x[0] for x in rows]
    projections = {x[0].player_id: x[1] for x in rows}
    lineup = optimize_single_entry("NFL", get_rules("NFL"), players, projections, beam_width=5000, per_slot_limit=30)
    assert len(lineup.entries) == 9
    assert lineup.salary <= 50000
    qbs = [e.player for e in lineup.entries if e.slot == "QB"]
    qb = qbs[0]
    assert any(e.player.team == qb.team and set(e.player.positions) & {"WR", "TE"} for e in lineup.entries)


def test_mlb_optimizer_avoids_batters_against_selected_pitchers() -> None:
    rows = [
        p("p1", "P A", "A", "B", "P", 9000, 23),
        p("p2", "P C", "C", "D", "P", 8500, 21),
        p("p3", "P E", "E", "F", "P", 7000, 16),
        p("c1", "C A", "A", "B", "C", 3800, 9),
        p("c2", "C B", "B", "A", "C", 3600, 13),
        p("1b", "1B A", "A", "B", "1B", 4300, 12),
        p("2b", "2B C", "C", "D", "2B", 4100, 11),
        p("3b", "3B E", "E", "F", "3B", 4000, 10),
        p("ss", "SS A", "A", "B", "SS", 4200, 11),
        p("of1", "OF A", "A", "B", "OF", 4500, 13),
        p("of2", "OF C", "C", "D", "OF", 4400, 12),
        p("of3", "OF E", "E", "F", "OF", 3900, 10),
        p("of4", "OF G", "G", "H", "OF", 3500, 9),
    ]
    players = [x[0] for x in rows]
    projections = {x[0].player_id: x[1] for x in rows}
    lineup = optimize_single_entry("MLB", get_rules("MLB"), players, projections, beam_width=8000, per_slot_limit=30)
    selected = [e.player for e in lineup.entries]
    for pitcher in [x for x in selected if "P" in x.positions]:
        assert not any("P" not in h.positions and h.team == pitcher.opponent for h in selected)


def test_projection_freshness_is_pit_safe() -> None:
    player, proj = p("x", "Player X", "A", "B", "WR", 5000, 10)
    lock = datetime(2026, 9, 18, 23, 30, tzinfo=timezone.utc)
    good = Projection(**{**proj.__dict__, "updated_at": lock - timedelta(hours=2)})
    report = validate_projection_freshness([player], {player.player_id: good}, slate_start=lock, max_age=timedelta(hours=6))
    assert report["freshness_state"] == "PASS"
    future = Projection(**{**proj.__dict__, "updated_at": lock + timedelta(minutes=1)})
    try:
        validate_projection_freshness([player], {player.player_id: future}, slate_start=lock, max_age=timedelta(hours=6))
    except ValueError as exc:
        assert "DFS_PROJECTION_AFTER_LOCK" in str(exc)
    else:
        raise AssertionError("future projection should fail")


def test_cfb_optimizer_supports_superflex_and_qb_stacks() -> None:
    rows = [
        p("qa", "QB A", "A", "B", "QB", 9000, 28),
        p("qb", "QB B", "B", "A", "QB", 8200, 25),
        p("qc", "QB C", "C", "D", "QB", 7000, 20),
        p("ra", "RB A", "A", "B", "RB", 6500, 18),
        p("rb", "RB B", "B", "A", "RB", 6100, 17),
        p("rc", "RB C", "C", "D", "RB", 5200, 14),
        p("wa", "WR A", "A", "B", "WR", 6200, 19),
        p("wb", "WR B", "B", "A", "WR", 5700, 17),
        p("wc", "WR C", "C", "D", "WR", 4800, 14),
        p("wd", "WR D", "D", "C", "WR", 4200, 12),
        p("we", "WR A2", "A", "B", "WR", 3900, 11),
        p("wf", "WR B2", "B", "A", "WR", 3600, 10),
        p("ta", "TE A", "A", "B", "TE", 3300, 9),
    ]
    players = [x[0] for x in rows]
    projections = {x[0].player_id: x[1] for x in rows}
    lineup = optimize_single_entry("CFB", get_rules("CFB"), players, projections, beam_width=10000, per_slot_limit=30)
    assert len(lineup.entries) == 8
    assert lineup.salary <= 50000
    assert any(e.slot == "SUPERFLEX" for e in lineup.entries)
    for qb in [e.player for e in lineup.entries if "QB" in e.player.positions]:
        assert any(
            e.player.player_id != qb.player_id
            and e.player.team == qb.team
            and set(e.player.positions) & {"WR", "TE"}
            for e in lineup.entries
        )
