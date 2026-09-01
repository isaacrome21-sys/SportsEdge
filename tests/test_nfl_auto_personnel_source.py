from datetime import datetime, timezone

from sportsedge.sports.nfl.auto_personnel_source import build_depth_chart_personnel_provider
from sportsedge.sports.nfl.run_it_context import build_run_it_context


_SOURCE_URI = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2026.csv"
_SOURCE_SHA = "a" * 64


def _row(team, pos, slot, *, rank=1, dt="2026-09-10T15:00:00+00:00", player=None):
    return {
        "dt": dt,
        "team": team,
        "gsis_id": player or f"{team}-{pos}-{slot}-{rank}",
        "pos_abb": pos,
        "pos_slot": slot,
        "pos_rank": rank,
    }


def _complete_snapshot(team):
    rows = []
    for slot, pos in enumerate(("LT", "LG", "C", "RG", "RT"), start=1):
        rows.append(_row(team, pos, slot))
    for slot, pos in enumerate(("CB", "CB", "FS", "SS"), start=20):
        rows.append(_row(team, pos, slot))
    rows.append(_row(team, "WR", 30, rank=2))
    return rows


def test_depth_chart_personnel_uses_latest_snapshot_at_or_before_pit_only():
    as_of = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    rows = _complete_snapshot("BUF") + _complete_snapshot("PIT")
    # A future snapshot must not replace the complete PIT-safe one.
    rows += [
        _row("BUF", "LT", 1, dt="2026-09-10T17:00:00+00:00", player="FUTURE"),
        _row("PIT", "CB", 20, dt="2026-09-10T17:00:00+00:00", player="FUTURE2"),
    ]
    provider = build_depth_chart_personnel_provider(
        game_id="2026_01_PIT_BUF",
        team_ids=("BUF", "PIT"),
        as_of=as_of,
        source_uri=_SOURCE_URI,
        source_sha256=_SOURCE_SHA,
        rows=rows,
    )
    assert provider is not None
    assert provider["status"] == "AVAILABLE"
    payload = provider["payload"]
    by_team = {row["team_id"]: row for row in payload["teams"]}
    assert by_team["BUF"]["projected_ol_starters_known"] is True
    assert by_team["BUF"]["starting_secondary_known"] is True
    assert by_team["PIT"]["projected_ol_starters_known"] is True
    assert by_team["PIT"]["starting_secondary_known"] is True
    assert payload["depth_snapshot_asof_by_team"] == {
        "BUF": "2026-09-10T15:00:00+00:00",
        "PIT": "2026-09-10T15:00:00+00:00",
    }
    for row in payload["teams"]:
        assert row["eleven_personnel_rate"] is None
        assert row["nickel_rate"] is None
        assert row["ol_continuity_starts"] is None


def test_depth_chart_personnel_refuses_untimestamped_rows_for_auto_pit():
    provider = build_depth_chart_personnel_provider(
        game_id="2026_01_PIT_BUF",
        team_ids=("BUF",),
        as_of=datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc),
        source_uri=_SOURCE_URI,
        source_sha256=_SOURCE_SHA,
        rows=[{"team": "BUF", "gsis_id": "x", "pos_abb": "LT", "pos_slot": 1, "pos_rank": 1}],
    )
    assert provider is None


def test_auto_context_registry_accepts_source_derived_personnel_without_promotion():
    as_of = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    provider = build_depth_chart_personnel_provider(
        game_id="2026_01_PIT_BUF",
        team_ids=("BUF",),
        as_of=as_of,
        source_uri=_SOURCE_URI,
        source_sha256=_SOURCE_SHA,
        rows=_complete_snapshot("BUF"),
    )
    bundle = build_run_it_context(
        mode="AUTO",
        game={"game_id": "2026_01_PIT_BUF", "auto_personnel_provider": provider},
        as_of=as_of,
    )
    assert bundle["observations"]["personnel_packages"]["status"] == "AVAILABLE"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
