from __future__ import annotations

from sportsedge.dfs.draftkings import DraftKingsClient
from sportsedge.dfs.optimizer import _mlb_conflict
from sportsedge.dfs.scoring import projection_from_stats
from sportsedge.dfs.types import DKPlayer


def test_sp_and_rp_are_pitchers_for_roster_conflicts_and_scoring() -> None:
    sp = DKPlayer("sp", "Starter", "AAA", "BBB", ("SP",), 9000)
    hitter = DKPlayer("h", "Hitter", "BBB", "AAA", ("OF",), 5000)
    assert sp.is_pitcher
    assert sp.eligible_for("P")
    assert _mlb_conflict([sp], hitter)
    proj = projection_from_stats(
        sp,
        "MLB",
        {"outs": 18, "strikeouts": 7, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2, "win_probability": 0.55},
        source="TEST",
    )
    assert proj.mean > 20.0


def test_live_named_roster_slots_override_generic_position() -> None:
    payload = {
        "draftables": [{
            "draftableId": 1,
            "playerDkId": 44,
            "displayName": "CFB Quarterback",
            "position": "QB",
            "rosterSlots": ["QB", "S-FLEX"],
            "salary": 8000,
            "teamAbbreviation": "AAA",
            "competition": {"competitionId": 2, "name": "AAA @ BBB", "startTime": "2026-09-18T23:30:00Z"},
        }]
    }
    player = DraftKingsClient(getter=lambda _: payload).fetch_draftables(123)[0]
    assert player.roster_slots == ("QB", "SUPERFLEX")
    assert player.eligible_for("QB")
    assert player.eligible_for("SUPERFLEX")
    assert not player.eligible_for("FLEX")


def test_salary_csv_roster_position_is_authoritative(tmp_path) -> None:
    path = tmp_path / "DKSalaries.csv"
    path.write_text(
        "Position,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame\n"
        "QB,Quarter Back,44,QB/S-FLEX,8000,AAA@BBB 09/18/2026 07:30PM ET,AAA,22.5\n",
        encoding="utf-8",
    )
    player = DraftKingsClient(getter=lambda _: {}).load_salary_csv(path)[0]
    assert player.roster_slots == ("QB", "SUPERFLEX")
    assert player.eligible_for("SUPERFLEX")
