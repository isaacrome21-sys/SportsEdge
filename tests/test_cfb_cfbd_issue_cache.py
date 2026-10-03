from types import SimpleNamespace

from sportsedge.sports.cfb import cfbd_issue_cache as cc


def test_roundtrip_and_untrusted_ignored():
    body = cc.encode_item("talent_2021", {"Alabama": 1000.5})
    assert cc.decode_bodies([body, "noise\nCFBCACHE bad_2020 !!!"]) == {"talent_2021": {"Alabama": 1000.5}}
    out = "\n".join([
        '{"u": "github-actions[bot]", "b": %s}' % __import__("json").dumps(body),
        '{"u": "stranger", "b": %s}' % __import__("json").dumps(cc.encode_item("sp_2020", {"X": 1})),
    ])
    runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr="")
    assert cc.load_cache(1475, runner=runner) == {"talent_2021": {"Alabama": 1000.5}}


def test_normalize_lines_prefers_consensus():
    data = [{"id": 7, "week": 3, "homeTeam": "A", "awayTeam": "B", "homeScore": 21, "awayScore": 14,
             "lines": [{"provider": "Bovada", "spread": -3, "overUnder": 50},
                       {"provider": "consensus", "spread": -3.5, "overUnder": 51.5, "spreadOpen": -2.5}]}]
    got = cc.normalize_lines(data)["7"]
    assert got["spread"] == -3.5 and got["total"] == 51.5 and got["spread_open"] == -2.5
    assert got["week"] == 3 and got["home_pts"] == 21.0


def test_ensure_fetches_missing_only_and_stops_on_429():
    calls, saved = [], []

    def fetch(path, params, key):
        calls.append((path, params))
        if path == "/player/returning":
            raise cc.RateLimited("429")
        return [{"team": "A", "talent": 900.0}]

    cache = cc.ensure(["talent_2020", "talent_2021", "returning_2021", "sp_2020"], "k",
                      cache={"talent_2020": {"A": 1.0}}, fetch=fetch,
                      save=lambda n, d: saved.append(n), sleep=lambda s: None)
    assert [c[0] for c in calls] == ["/talent", "/player/returning"]
    assert saved == ["talent_2021"] and "sp_2020" not in cache


def test_ensure_respects_budget():
    def fetch(path, params, key):
        if path == "/lines":
            return [{"id": 1, "homeTeam": "A", "awayTeam": "B", "lines": [{"provider": "consensus", "spread": -1}]}]
        return [{"team": "A", "talent": 1, "percentPPA": 1, "rating": 1}]

    cache = cc.ensure(cc.history_names(), "k", cache={}, budget=2, fetch=fetch,
                      save=lambda n, d: None, sleep=lambda s: None)
    assert len(cache) == 2


def test_live_week_bundle_name_roundtrip():
    payload = {"schema": "CFB_LIVE_WEEK_CACHE_V1", "season": 2026, "week": 5, "games": [], "snapshots": {}}
    body = cc.encode_item("live_2026_w5", payload)
    assert cc.decode_bodies([body])["live_2026_w5"] == payload
