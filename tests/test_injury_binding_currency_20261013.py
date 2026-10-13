"""Injury-binding currency (Grok reimplementation, 2026-10-13).

Root cause: injury_rows() bound any team-ID-matched ESPN group as the
current report without looking at entry dates. The live CFB league feed
returns 3 groups with entries dated 2020-11-21 / 2022-11 (Florida WR 'Out'
2020), which were bound as STRUCTURE_VERIFIED and priced.
"""
from datetime import datetime, timezone

import pytest

from artifacts import free_models as fm
from artifacts.free_models import ESPN, PublicContext

NOW = datetime(2026, 10, 13, 22, 0, tzinfo=timezone.utc)


def _row(date, status="Out", pos="QB", aid="1"):
    r = {"status": status, "athlete": {"id": aid, "position": {"abbreviation": pos}}}
    if date is not None:
        r["date"] = date
    return r


def _ctx(sport, rows, team_id="57"):
    league = {"injuries": [{"id": team_id, "displayName": "T", "injuries": rows}]}
    path = fm.LEAGUES[sport]
    def get(url):
        if url == f"{ESPN}/{path}/injuries":
            return league
        raise OSError("no team endpoint")
    return PublicContext(NOW, get), {"id": team_id}


def test_live_shape_2020_entry_is_stale_unknown_not_healthy():
    ctx, team = _ctx("CFB", [_row("2020-11-21T18:31Z", pos="WR")])
    rows, status = ctx.injury_rows("CFB", team)
    assert rows is None and status == fm.INJURY_STALE_UNKNOWN
    assert ctx.injury_points("CFB", team) == (0.0, fm.INJURY_STALE_UNKNOWN)
    assert any(r.get("status") == fm.INJURY_STALE_UNKNOWN for r in ctx.receipts)


def test_current_cfb_rows_bind():
    ctx, team = _ctx("CFB", [_row("2026-10-10T15:00Z")])
    rows, status = ctx.injury_rows("CFB", team)
    assert status == "STRUCTURE_VERIFIED" and len(rows) == 1


@pytest.mark.parametrize("date,why", [
    (None, "UNDATED"), ("garbage", "UNDATED"), ("2026-10-10T15:00", "UNDATED"),
    ("2026-10-14T00:00Z", "AFTER_AS_OF"), ("2026-09-01T00:00Z", "OLDER_THAN_21D"),
    ("2022-11-26T22:30Z", "OLDER_THAN_21D")])
def test_any_bad_row_poisons_whole_team(date, why):
    ctx, team = _ctx("CFB", [_row("2026-10-10T15:00Z", aid="2"), _row(date)])
    rows, status = ctx.injury_rows("CFB", team)
    assert rows is None and status == fm.INJURY_STALE_UNKNOWN
    assert why in ctx.receipts[-1]["reason"]


@pytest.mark.parametrize("bad", [5, "x", None, []])
def test_non_dict_rows_are_undated(bad):
    ctx, team = _ctx("CFB", [bad])
    assert ctx.injury_rows("CFB", team) == (None, fm.INJURY_STALE_UNKNOWN)


def test_nfl_behavior_unchanged_for_old_ir_rows():
    ctx, team = _ctx("NFL", [_row("2026-08-01T00:00Z")])
    rows, status = ctx.injury_rows("NFL", team)
    assert status == "STRUCTURE_VERIFIED" and len(rows) == 1
    assert ctx.injury_points("NFL", team)[0] == -1.5


def test_currency_scope_is_cfb_only():
    assert "CFB" in fm.INJURY_CURRENCY_DAYS and "NFL" not in fm.INJURY_CURRENCY_DAYS
