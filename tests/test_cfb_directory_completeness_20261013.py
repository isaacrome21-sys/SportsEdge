"""Directory completeness (Grok reimplementation, 2026-10-13).

Root cause: PublicContext.teams() fetched ESPN ``teams?limit=500`` once.
ESPN truncates silently at ``limit`` (no count metadata); the live CFB
directory is 762 teams, so 262 schools could never resolve identity.
"""
from datetime import datetime, timezone

import pytest

from artifacts.free_models import ESPN, PublicContext

NOW = datetime(2026, 10, 13, 22, 0, tzinfo=timezone.utc)
BASE = f"{ESPN}/football/college-football/teams?limit=500"


def _page(start, n):
    return {"sports": [{"leagues": [{"teams": [
        {"team": {"id": str(i), "displayName": f"School {i}"}} for i in range(start, start + n)]}]}]}


def _getter(pages):
    calls = []
    def get(url):
        calls.append(url)
        if url not in pages:
            raise OSError("no fixture")
        return pages[url]
    get.calls = calls
    return get


def _ctx(get, floor=True):
    ctx = PublicContext(NOW, get)
    ctx.enforce_directory_floor = floor
    return ctx


def test_full_762_team_directory_paginates_to_completion():
    get = _getter({BASE: _page(1, 500), BASE + "&page=2": _page(501, 262)})
    teams, status = _ctx(get).team_directory("CFB")
    assert status == "COMPLETE"
    assert len(teams) == 762
    assert len({t["id"] for t in teams}) == 762
    assert get.calls == [BASE, BASE + "&page=2"]
    assert _ctx(get).identify("CFB", "School 762")["id"] == "762"


def test_old_truncated_view_is_refused_not_used():
    # A page-2 outage means the 500-team view is incomplete -> fail closed.
    get = _getter({BASE: _page(1, 500)})
    ctx = _ctx(get)
    teams, status = ctx.team_directory("CFB")
    assert teams == [] and status.startswith("DIRECTORY_INCOMPLETE:PAGE_2")
    assert ctx.identify("CFB", "School 1") is None
    assert any(r.get("status") == "DIRECTORY_INCOMPLETE" for r in ctx.receipts)


def test_below_live_floor_fails_closed():
    get = _getter({BASE: _page(1, 120)})
    teams, status = _ctx(get).team_directory("CFB")
    assert teams == [] and status == "DIRECTORY_INCOMPLETE:120_BELOW_FLOOR_700"


def test_repeated_page_fails_closed():
    get = _getter({BASE: _page(1, 500), BASE + "&page=2": _page(1, 500)})
    teams, status = _ctx(get).team_directory("CFB")
    assert teams == [] and "REPEATS_TEAM_IDS" in status


def test_endless_full_pages_hit_cap():
    pages = {BASE: _page(1, 500)}
    for p in range(2, 12):
        pages[f"{BASE}&page={p}"] = _page(p * 1000, 500)
    teams, status = _ctx(_getter(pages)).team_directory("CFB")
    assert teams == [] and "PAGE_CAP" in status


@pytest.mark.parametrize("bad", [{"sports": "x"}, {"sports": [1]},
                                 {"sports": [{"leagues": [{"teams": 5}]}]}, {}])
def test_malformed_page_fails_closed(bad):
    teams, status = _ctx(_getter({BASE: bad})).team_directory("CFB")
    assert teams == [] and "MALFORMED" in status


def test_fixture_getters_exempt_from_floor_only():
    ctx = PublicContext(NOW, _getter({BASE: _page(1, 3)}))
    assert ctx.enforce_directory_floor is False
    assert len(ctx.teams("CFB")) == 3
    assert PublicContext(NOW).enforce_directory_floor is True
