import json
import unittest
from datetime import datetime, timezone, date, timedelta

from sportsedge.auto_native_odds import run_auto_mlb_native_odds

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)


class Resp:
    def __init__(self, obj): self.raw = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


def schedule():
    return {"dates": [{"date": "2026-08-11", "games": [{
        "gamePk": 777,
        "gameDate": "2026-08-11T23:00:00Z",
        "officialDate": "2026-08-11",
        "gameNumber": 1,
        "doubleHeader": "N",
        "venue": {"id": 3313},
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "teams": {
            "away": {"team": {"id": 1, "name": "Chicago Cubs"}, "probablePitcher": {"id": 11, "fullName": "Away Pitcher"}},
            "home": {"team": {"id": 2, "name": "New York Yankees"}, "probablePitcher": {"id": 22, "fullName": "Home Pitcher"}},
        },
    }]}]}


def boxscore():
    def players(start, prefix):
        return {f"ID{start+i}": {"person": {"id": start+i, "fullName": f"{prefix} {i+1}"}, "battingOrder": str((i+1)*100)} for i in range(9)}
    return {"teams": {"away": {"players": players(100, "Cubs Batter")}, "home": {"players": players(200, "Yankees Batter")}}}


def features():
    def fact(k, v, sid): return {"source_id": sid, "fact_key": k, "value": v, "provider": "MLB", "event_time": "2026-08-11T14:50:00Z", "retrieved_at": "2026-08-11T14:58:00Z"}
    return [{
        "game_pk": 777,
        "player_id": 100,
        "team_id": 1,
        "market": "HITS",
        "feature_fact_keys": {"b_rate": "b", "p_rate": "p", "pa_pool": "pa"},
        "ttl_by_feature": {"b_rate": 3600, "p_rate": 3600, "pa_pool": 3600},
        "sources": [fact("b", .25, "b1"), fact("p", .23, "p1"), fact("pa", [4,4,5,3], "pa1")],
    }]


def events():
    return [{"id": "provider-event", "commence_time": "2026-08-11T23:00:00Z", "away_team": "Chicago Cubs", "home_team": "New York Yankees"}]


def event_odds(player="Cubs Batter 1", market="batter_hits"):
    return {
        "id": "provider-event",
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "2026-08-11T14:59:00Z",
            "markets": [{
                "key": market,
                "outcomes": [
                    {"name": "Over", "description": player, "point": 0.5, "price": -110, "sid": "over-1"},
                    {"name": "Under", "description": player, "point": 0.5, "price": -110, "sid": "under-1"},
                ],
            }],
        }],
    }


def stat_payload(rows): return {"stats": [{"splits": rows}]}
def hrow(day, pk, h, pa, d=0, t=0, hr=0): return {"date": day, "game": {"gamePk": pk}, "stat": {"hits": h, "doubles": d, "triples": t, "homeRuns": hr, "plateAppearances": pa}}
def frow(day, pk, started, pos="1B"): return {"date": day, "game": {"gamePk": pk}, "position": {"abbreviation": pos}, "stat": {"gamesStarted": started, "innings": "0.0" if pos == "DH" else "9.0"}}
def prow(day, pk, h, bfp, started=1, hr=1): return {"date": day, "game": {"gamePk": pk}, "stat": {"hits": h, "homeRuns": hr, "battersFaced": bfp, "gamesStarted": started}}


def batter_history():
    start = date(2026, 4, 1)
    rows = []
    for i in range(25):
        day = (start + timedelta(days=i)).isoformat()
        rows.append(hrow(day, 500+i, 2, 5, d=1 if i % 4 == 0 else 0, t=1 if i == 3 else 0, hr=1 if i % 7 == 0 else 0))
    return rows


def fielding_history():
    start = date(2026, 4, 1)
    return [frow((start + timedelta(days=i)).isoformat(), 500+i, 1, "DH" if i % 6 == 0 else "1B") for i in range(25)]


def pitching_history():
    start = date(2026, 4, 1)
    return [prow((start + timedelta(days=7*i)).isoformat(), 600+i, 5, 25, hr=1) for i in range(5)]


class AutoNativeOddsTests(unittest.TestCase):
    def opener(self, req, timeout=15, *, player="Cubs Batter 1", market="batter_hits"):
        url = req if isinstance(req, str) else req.full_url
        if "statsapi.mlb.com/api/v1/schedule?" in url: return Resp(schedule())
        if "statsapi.mlb.com/api/v1/game/777/boxscore" in url: return Resp(boxscore())
        if url == "https://features": return Resp(features())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events?" in url: return Resp(events())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events/provider-event/odds?" in url: return Resp(event_odds(player, market))
        raise AssertionError(url)

    def native_opener(self, req, timeout=15, *, market="batter_hits", venue_unmapped=False):
        url = req if isinstance(req, str) else req.full_url
        if "statsapi.mlb.com/api/v1/schedule?" in url:
            value = schedule()
            if venue_unmapped:
                value["dates"][0]["games"][0]["venue"]["id"] = 2529
            return Resp(value)
        if "statsapi.mlb.com/api/v1/game/777/boxscore" in url: return Resp(boxscore())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events?" in url: return Resp(events())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events/provider-event/odds?" in url: return Resp(event_odds(market=market))
        if "/people/" in url and any(f"season={year}" in url for year in range(2021, 2026)):
            return Resp(stat_payload([]))
        if "/people/100/stats?" in url and "group=hitting" in url and "season=2026" in url: return Resp(stat_payload(batter_history()))
        if "/people/100/stats?" in url and "group=fielding" in url and "season=2026" in url: return Resp(stat_payload(fielding_history()))
        if "/people/22/stats?" in url and "group=pitching" in url and "season=2026" in url: return Resp(stat_payload(pitching_history()))
        raise AssertionError(url)

    def test_native_odds_path_binds_provider_player_to_exact_mlb_id(self):
        report = run_auto_mlb_native_odds(odds_api_key="secret", feature_url="https://features", now=NOW, opener=self.opener)
        self.assertEqual(report.slate_date_ct, "2026-08-11")
        self.assertEqual(len(report.results), 2)
        self.assertEqual({r.entity_id for r in report.results}, {"100"})
        self.assertEqual({r.market for r in report.results}, {"HITS"})
        self.assertTrue(all(r.bet_status != "OFFICIAL_BET" for r in report.results))

    def test_native_auto_fetches_provider_event_list_once_per_key_attempt(self):
        calls = {"events": 0}

        def op(req, timeout=15):
            url = req if isinstance(req, str) else req.full_url
            if "api.the-odds-api.com/v4/sports/baseball_mlb/events?" in url:
                calls["events"] += 1
            return self.opener(req, timeout)

        run_auto_mlb_native_odds(
            odds_api_key="secret",
            feature_url="https://features",
            now=NOW,
            opener=op,
        )
        self.assertEqual(calls["events"], 1)


    def test_unknown_provider_player_is_not_guessed(self):
        def op(req, timeout=15): return self.opener(req, timeout, player="Someone Else")
        report = run_auto_mlb_native_odds(odds_api_key="secret", feature_url="https://features", now=NOW, opener=op)
        self.assertEqual(report.results, ())
        self.assertEqual(report.run_status, "DEGRADED")
        self.assertTrue(any("ODDS_PLAYER_ID_UNRESOLVED" in str(x) for x in report.source_failures))

    def test_no_feature_url_builds_hits_features_from_official_history(self):
        report = run_auto_mlb_native_odds(odds_api_key="secret", feature_url=None, now=NOW, opener=self.native_opener)
        self.assertEqual(len(report.results), 2)
        self.assertEqual({r.market for r in report.results}, {"HITS"})
        self.assertTrue(all(r.bet_status == "BLOCKED" for r in report.results))
        self.assertTrue(all("feature snapshot missing" not in r.reason.lower() for r in report.results))
        self.assertTrue(all("deployment" in r.reason.lower() or "eligible" in r.reason.lower() for r in report.results))
        self.assertFalse(any(x.get("stage") == "MLB_HITS_FEATURE" for x in report.source_failures))

    def test_no_feature_url_builds_total_bases_features_from_official_history(self):
        def op(req, timeout=15): return self.native_opener(req, timeout, market="batter_total_bases")
        report = run_auto_mlb_native_odds(odds_api_key="secret", feature_url=None, now=NOW, opener=op)
        self.assertEqual(len(report.results), 2)
        self.assertEqual({r.market for r in report.results}, {"TOTAL_BASES"})
        self.assertTrue(all(r.bet_status == "BLOCKED" for r in report.results))
        self.assertTrue(all("feature snapshot missing" not in r.reason.lower() for r in report.results))
        self.assertTrue(all("deployment" in r.reason.lower() or "eligible" in r.reason.lower() for r in report.results))
        self.assertFalse(any(x.get("stage") == "MLB_TOTAL_BASES_FEATURE" for x in report.source_failures))

    def test_unmapped_venue_blocks_total_bases_instead_of_using_neutral_park(self):
        def op(req, timeout=15): return self.native_opener(req, timeout, market="batter_total_bases", venue_unmapped=True)
        report = run_auto_mlb_native_odds(odds_api_key="secret", feature_url=None, now=NOW, opener=op)
        self.assertEqual(len(report.results), 2)
        self.assertTrue(all(r.bet_status == "BLOCKED" for r in report.results))
        self.assertTrue(any("VENUE_UNMAPPED" in str(x) for x in report.source_failures))


if __name__ == "__main__": unittest.main()
