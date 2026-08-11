import json
import unittest
from datetime import datetime, timezone

from sportsedge.auto_runner import run_auto_mlb

UTC = timezone.utc
NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)


class Resp:
    def __init__(self, obj): self.raw = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


def schedule(status="Preview"):
    return {"dates": [{"date": "2026-08-11", "games": [{"gamePk": 777, "gameDate": "2026-08-11T23:00:00Z", "officialDate": "2026-08-11", "gameNumber": 1, "doubleHeader": "N", "venue": {"id": 10}, "status": {"abstractGameState": status, "detailedState": "Scheduled"}, "teams": {"away": {"team": {"id": 1, "name": "Away"}, "probablePitcher": {"id": 11, "fullName": "AP"}}, "home": {"team": {"id": 2, "name": "Home"}, "probablePitcher": {"id": 22, "fullName": "HP"}}}}]}]}


def boxscore(confirmed=True):
    def players(start):
        if not confirmed: return {}
        return {f"ID{start+i}": {"person": {"id": start+i, "fullName": str(start+i)}, "battingOrder": str((i+1)*100)} for i in range(9)}
    return {"teams": {"away": {"players": players(100)}, "home": {"players": players(200)}}}


def quote():
    return [{"game_id": "777", "period": "FG", "market": "HITS", "entity_id": "100", "line": 0.5, "side": "OVER", "american_odds": -110, "book_key": "dk", "is_alternate": False, "raw_market_name": "Player Hits", "retrieved_at": "2026-08-11T14:59:00Z", "ttl_seconds": 300}]


def features(impossible=False):
    e = "2026-08-11T14:58:30Z" if impossible else "2026-08-11T14:50:00Z"
    r = "2026-08-11T14:58:00Z"
    def fact(k, v, sid): return {"source_id": sid, "fact_key": k, "value": v, "provider": "MLB", "event_time": e, "retrieved_at": r}
    return [{"game_pk": 777, "player_id": 100, "team_id": 1, "market": "HITS", "feature_fact_keys": {"b_rate": "b", "p_rate": "p", "pa_pool": "pa"}, "ttl_by_feature": {"b_rate": 3600, "p_rate": 3600, "pa_pool": 3600}, "sources": [fact("b", .25, "b1"), fact("p", .23, "p1"), fact("pa", [4,4,5,3], "pa1")]}]


def projected(stale=False):
    return [{"game_pk": 777, "team_id": 1, "side": "away", "retrieved_at": "2026-08-11T12:00:00Z" if stale else "2026-08-11T14:59:00Z", "ttl_seconds": 900, "rows": [{"player_id": 100+i, "slot": i+1, "sequence": 0} for i in range(9)]}, {"game_pk": 777, "team_id": 2, "side": "home", "retrieved_at": "2026-08-11T14:59:00Z", "ttl_seconds": 900, "rows": [{"player_id": 200+i, "slot": i+1, "sequence": 0} for i in range(9)]}]


class AutoRunnerTests(unittest.TestCase):
    def opener(self, req, timeout=15, *, confirmed=True, status="Preview", impossible=False, projected_rows=None):
        url = req if isinstance(req, str) else req.full_url
        if "schedule?" in url: return Resp(schedule(status))
        if "/boxscore" in url: return Resp(boxscore(confirmed))
        if url == "https://quotes": return Resp(quote())
        if url == "https://features": return Resp(features(impossible))
        if url == "https://projected": return Resp(projected_rows if projected_rows is not None else projected())
        raise AssertionError(url)

    def test_confirmed_lineup_full_auto_preserves_ct_date_and_no_forced_bet(self):
        report = run_auto_mlb(quote_url="https://quotes", feature_url="https://features", now=NOW, opener=self.opener)
        self.assertEqual(report.slate_date_ct, "2026-08-11")
        self.assertEqual(len(report.results), 1)
        self.assertNotEqual(report.results[0].bet_status, "OFFICIAL_BET")

    def test_projected_lineup_is_usable_but_not_relabelled_confirmed(self):
        def op(req, timeout=15): return self.opener(req, timeout, confirmed=False)
        report = run_auto_mlb(quote_url="https://quotes", feature_url="https://features", projected_lineups_url="https://projected", now=NOW, opener=op, require_confirmed_lineup=False)
        self.assertEqual(len(report.results), 1)
        self.assertNotIn("confirmed MLB batting order required", report.results[0].reason)

    def test_stale_projected_lineup_blocks(self):
        def op(req, timeout=15): return self.opener(req, timeout, confirmed=False, projected_rows=projected(stale=True))
        report = run_auto_mlb(quote_url="https://quotes", feature_url="https://features", projected_lineups_url="https://projected", now=NOW, opener=op)
        self.assertIn("PROJECTED_LINEUP_STALE", report.results[0].reason)

    def test_impossible_feature_chronology_blocks(self):
        def op(req, timeout=15): return self.opener(req, timeout, impossible=True)
        report = run_auto_mlb(quote_url="https://quotes", feature_url="https://features", now=NOW, opener=op)
        self.assertIn("IMPOSSIBLE_SOURCE_CHRONOLOGY", report.results[0].reason)

    def test_live_game_blocks_before_model(self):
        def op(req, timeout=15): return self.opener(req, timeout, status="Live")
        report = run_auto_mlb(quote_url="https://quotes", feature_url="https://features", now=NOW, opener=op)
        self.assertIn("GAME_NOT_PREGAME", report.results[0].reason)

    def test_malformed_quote_preserves_cardinality_as_block(self):
        def op(req, timeout=15):
            url = req if isinstance(req, str) else req.full_url
            if url == "https://quotes":
                bad = quote(); del bad[0]["book_key"]; return Resp(bad)
            return self.opener(req, timeout)
        report = run_auto_mlb(quote_url="https://quotes", feature_url="https://features", now=NOW, opener=op)
        self.assertEqual(len(report.results), 1)
        self.assertIn("QUOTE_IDENTITY_INCOMPLETE", report.results[0].reason)


if __name__ == "__main__": unittest.main()
