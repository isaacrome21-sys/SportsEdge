import json
import unittest
from datetime import datetime, timezone

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


def event_odds(player="Cubs Batter 1"):
    return {
        "id": "provider-event",
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "2026-08-11T14:59:00Z",
            "markets": [{
                "key": "batter_hits",
                "outcomes": [
                    {"name": "Over", "description": player, "point": 0.5, "price": -110, "sid": "over-1"},
                    {"name": "Under", "description": player, "point": 0.5, "price": -110, "sid": "under-1"},
                ],
            }],
        }],
    }


class AutoNativeOddsTests(unittest.TestCase):
    def opener(self, req, timeout=15, *, player="Cubs Batter 1"):
        url = req if isinstance(req, str) else req.full_url
        if "statsapi.mlb.com/api/v1/schedule?" in url: return Resp(schedule())
        if "statsapi.mlb.com/api/v1/game/777/boxscore" in url: return Resp(boxscore())
        if url == "https://features": return Resp(features())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events?" in url: return Resp(events())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events/provider-event/odds?" in url: return Resp(event_odds(player))
        raise AssertionError(url)

    def test_native_odds_path_binds_provider_player_to_exact_mlb_id(self):
        report = run_auto_mlb_native_odds(
            odds_api_key="secret",
            feature_url="https://features",
            now=NOW,
            opener=self.opener,
        )
        self.assertEqual(report.slate_date_ct, "2026-08-11")
        self.assertEqual(len(report.results), 2)
        self.assertEqual({r.entity_id for r in report.results}, {"100"})
        self.assertEqual({r.market for r in report.results}, {"HITS"})
        self.assertTrue(all(r.bet_status != "OFFICIAL_BET" for r in report.results))

    def test_unknown_provider_player_is_not_guessed(self):
        def op(req, timeout=15): return self.opener(req, timeout, player="Someone Else")
        report = run_auto_mlb_native_odds(
            odds_api_key="secret",
            feature_url="https://features",
            now=NOW,
            opener=op,
        )
        self.assertEqual(report.results, ())
        self.assertEqual(report.run_status, "NO_QUOTES")
        self.assertTrue(any("ODDS_PLAYER_ID_UNRESOLVED" in str(x) for x in report.source_failures))


if __name__ == "__main__": unittest.main()
