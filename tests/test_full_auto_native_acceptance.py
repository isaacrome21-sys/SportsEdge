import json
import unittest
from datetime import date, datetime, timedelta, timezone

from sportsedge.auto_native_odds import run_auto_mlb_native_odds

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)


class Resp:
    def __init__(self, value): self.raw = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


def schedule():
    return {"dates": [{"date": "2026-08-11", "games": [{"gamePk": 777, "gameDate": "2026-08-11T23:00:00Z", "officialDate": "2026-08-11","gameNumber": 1, "doubleHeader": "N", "venue": {"id": 3313},"status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},"teams": {"away": {"team": {"id": 1, "name": "Chicago Cubs"}, "probablePitcher": {"id": 11, "fullName": "Away Pitcher"}},"home": {"team": {"id": 2, "name": "New York Yankees"}, "probablePitcher": {"id": 22, "fullName": "Home Pitcher"}}}}]}]}


def boxscore():
    def players(start, prefix): return {f"ID{start+i}": {"person": {"id": start+i, "fullName": f"{prefix} {i+1}"}, "battingOrder": str((i+1)*100)} for i in range(9)}
    return {"teams": {"away": {"players": players(100, "Cubs Batter")}, "home": {"players": players(200, "Yankees Batter")}}}

def events(): return [{"id": "provider-event", "commence_time": "2026-08-11T23:00:00Z", "away_team": "Chicago Cubs", "home_team": "New York Yankees"}]
def event_odds():
    def outcomes(prefix): return [{"name": "Over", "description": "Cubs Batter 1", "point": 0.5, "price": -110, "sid": f"{prefix}-over"},{"name": "Under", "description": "Cubs Batter 1", "point": 0.5, "price": -110, "sid": f"{prefix}-under"}]
    return {"id": "provider-event", "bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": "2026-08-11T14:59:00Z","markets": [{"key": "batter_hits", "outcomes": outcomes("hits")},{"key": "batter_total_bases", "outcomes": outcomes("tb")}]}]}
def stat_payload(rows): return {"stats": [{"splits": rows}]}
def batting_rows():
    start = date(2026, 4, 1); out = []
    for i in range(25):
        d = (start + timedelta(days=i)).isoformat(); hr = 1 if i % 7 == 0 else 0; doubles = 1 if i % 4 == 0 else 0; triples = 1 if i == 3 else 0
        out.append({"date": d, "game": {"gamePk": 500+i}, "stat": {"hits": 2, "doubles": doubles, "triples": triples, "homeRuns": hr, "plateAppearances": 5}})
    return out
def fielding_rows():
    start = date(2026, 4, 1); return [{"date": (start + timedelta(days=i)).isoformat(), "game": {"gamePk": 500+i},"position": {"abbreviation": "DH" if i % 6 == 0 else "1B"},"stat": {"gamesStarted": 1, "innings": "0.0" if i % 6 == 0 else "9.0"}} for i in range(25)]
def pitching_rows():
    start = date(2026, 4, 1); return [{"date": (start + timedelta(days=7*i)).isoformat(), "game": {"gamePk": 600+i},"stat": {"hits": 5, "homeRuns": 1, "battersFaced": 25, "gamesStarted": 1}} for i in range(5)]


class FullAutoNativeAcceptance(unittest.TestCase):
    def opener(self, req, timeout=15):
        url = req if isinstance(req, str) else req.full_url
        if "statsapi.mlb.com/api/v1/schedule?" in url: return Resp(schedule())
        if "statsapi.mlb.com/api/v1/game/777/boxscore" in url: return Resp(boxscore())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events?" in url: return Resp(events())
        if "api.the-odds-api.com/v4/sports/baseball_mlb/events/provider-event/odds?" in url: return Resp(event_odds())
        if "/people/" in url and any(f"season={y}" in url for y in range(2021, 2026)): return Resp(stat_payload([]))
        if "/people/100/stats?" in url and "group=hitting" in url and "season=2026" in url: return Resp(stat_payload(batting_rows()))
        if "/people/100/stats?" in url and "group=fielding" in url and "season=2026" in url: return Resp(stat_payload(fielding_rows()))
        if "/people/22/stats?" in url and "group=pitching" in url and "season=2026" in url: return Resp(stat_payload(pitching_rows()))
        raise AssertionError(url)

    def test_hits_and_total_bases_run_without_manual_quote_or_feature_snapshots(self):
        report = run_auto_mlb_native_odds(odds_api_key="synthetic-key", feature_url=None, projected_lineups_url=None, now=NOW, opener=self.opener)
        self.assertEqual(report.slate_date_ct, "2026-08-11"); self.assertEqual(len(report.results), 4); self.assertEqual({r.market for r in report.results}, {"HITS", "TOTAL_BASES"}); self.assertEqual({r.entity_id for r in report.results}, {"100"}); self.assertEqual({r.side for r in report.results}, {"OVER", "UNDER"})
        self.assertTrue(all(r.bet_status == "MODEL_CANDIDATE" for r in report.results))
        self.assertTrue(all(r.model_p is not None for r in report.results))
        self.assertTrue(all("feature" not in r.reason.lower() for r in report.results)); self.assertTrue(all("quote" not in r.reason.lower() for r in report.results)); self.assertTrue(all("official_blocked" in r.reason.lower() for r in report.results))
        self.assertFalse(any(x.get("stage") in {"MLB_HITS_FEATURE", "MLB_TOTAL_BASES_FEATURE", "ODDS_API"} for x in report.source_failures if isinstance(x, dict) and x.get("stage")))


if __name__ == "__main__":
    unittest.main()
