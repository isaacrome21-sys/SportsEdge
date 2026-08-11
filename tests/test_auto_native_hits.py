import json
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

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
        "venue": {"id": 10},
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "teams": {
            "away": {"team": {"id": 1, "name": "Chicago Cubs"}, "probablePitcher": {"id": 11, "fullName": "Away Pitcher"}},
            "home": {"team": {"id": 2, "name": "New York Yankees"}, "probablePitcher": {"id": 22, "fullName": "Home Pitcher"}},
        },
    }]}]}


def current_boxscore():
    def players(start, prefix):
        return {f"ID{start+i}": {
            "person": {"id": start+i, "fullName": f"{prefix} {i+1}"},
            "battingOrder": str((i+1)*100),
        } for i in range(9)}
    return {"teams": {"away": {"players": players(100, "Cubs Batter")}, "home": {"players": players(200, "Yankees Batter")}}}


def prior_boxscore(order):
    return {"teams": {"away": {"players": {"ID100": {"person": {"id": 100, "fullName": "Cubs Batter 1"}, "battingOrder": order}}}, "home": {"players": {}}}}


def log_payload(rows): return {"stats": [{"splits": rows}]}

def split(day, game_pk, stat): return {"date": day, "game": {"gamePk": game_pk}, "stat": stat}


def events():
    return [{"id": "provider-event", "commence_time": "2026-08-11T23:00:00Z", "away_team": "Chicago Cubs", "home_team": "New York Yankees"}]


def event_odds():
    return {"id": "provider-event", "bookmakers": [{
        "key": "draftkings", "title": "DraftKings", "last_update": "2026-08-11T14:59:00Z",
        "markets": [{"key": "batter_hits", "outcomes": [
            {"name": "Over", "description": "Cubs Batter 1", "point": 0.5, "price": -110, "sid": "hit-over"}
        ]}],
    }]}


class FullyNativeHitsTests(unittest.TestCase):
    batting = [
        split("2026-08-01", 1, {"hits": 1, "plateAppearances": 4}),
        split("2026-08-02", 2, {"hits": 2, "plateAppearances": 5}),
        split("2026-08-03", 3, {"hits": 0, "plateAppearances": 4}),
        split("2026-08-04", 4, {"hits": 1, "plateAppearances": 4}),
        split("2026-08-05", 5, {"hits": 1, "plateAppearances": 5}),
        split("2026-08-06", 6, {"hits": 1, "plateAppearances": 2}),
        split("2026-08-11", 7, {"hits": 4, "plateAppearances": 4}),
    ]
    pitching = [
        split("2026-08-01", 21, {"gamesStarted": 1, "hits": 4, "battersFaced": 22}),
        split("2026-08-03", 22, {"gamesStarted": 0, "hits": 3, "battersFaced": 9}),
        split("2026-08-07", 23, {"gamesStarted": 1, "hits": 5, "battersFaced": 25}),
        split("2026-08-11", 24, {"gamesStarted": 1, "hits": 10, "battersFaced": 30}),
    ]
    orders = {1: "100", 2: "200", 3: "300", 4: "400", 5: "500", 6: "101"}

    def opener(self, req, timeout=15):
        url = req if isinstance(req, str) else req.full_url
        if "statsapi.mlb.com/api/v1/schedule?" in url:
            return Resp(schedule())
        if "statsapi.mlb.com/api/v1/game/777/boxscore" in url:
            return Resp(current_boxscore())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events?" in url:
            return Resp(events())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events/provider-event/odds?" in url:
            return Resp(event_odds())

        parsed = urlparse(url)
        if "/people/" in parsed.path and parsed.path.endswith("/stats"):
            qs = parse_qs(parsed.query)
            season = int(qs["season"][0])
            group = qs["group"][0]
            if season != 2026:
                return Resp(log_payload([]))
            return Resp(log_payload(self.batting if group == "hitting" else self.pitching))
        if "/game/" in parsed.path and parsed.path.endswith("/boxscore"):
            game_pk = int(parsed.path.split("/")[-2])
            return Resp(prior_boxscore(self.orders[game_pk]))
        raise AssertionError(url)

    def test_native_odds_plus_native_hits_needs_no_feature_provider(self):
        report = run_auto_mlb_native_odds(
            odds_api_key="secret",
            feature_url=None,
            now=NOW,
            opener=self.opener,
            history_cache_dir=None,
        )
        self.assertEqual(report.slate_date_ct, "2026-08-11")
        self.assertEqual(len(report.results), 1)
        result = report.results[0]
        self.assertEqual(result.market, "HITS")
        self.assertEqual(result.entity_id, "100")
        # The native feature path reached the normal deployment gate; it did not
        # fail because an external feature snapshot was absent.
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertNotIn("FEATURE", result.reason.upper())
        self.assertNotIn("MISSING", result.reason.upper())

    def test_native_history_failure_is_reported_not_guessed(self):
        original = self.opener
        def op(req, timeout=15):
            url = req if isinstance(req, str) else req.full_url
            if "/people/22/stats" in url:
                return Resp(log_payload([]))
            return original(req, timeout)
        report = run_auto_mlb_native_odds(
            odds_api_key="secret", feature_url=None, now=NOW, opener=op, history_cache_dir=None,
        )
        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].bet_status, "BLOCKED")
        self.assertTrue(any(x.get("stage") == "NATIVE_HITS_FEATURES" and "STARTER_PRIOR_BFP_MISSING" in x.get("reason", "") for x in report.source_failures))


if __name__ == "__main__": unittest.main()
