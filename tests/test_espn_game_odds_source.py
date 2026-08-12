from datetime import date, datetime, timedelta, timezone
import json
import unittest
from urllib.parse import parse_qs, urlparse

from sportsedge.espn_game_odds_source import (
    DEFAULT_TTL_SECONDS, EspnGameOddsError, bind_espn_event,
    fetch_espn_draftkings_game_quotes, parse_espn_event_odds,
)
from sportsedge.mlb_source import GameSnapshot
from sportsedge.price_ttl import PriceFreshnessError, double_ttl_gate
from sportsedge.quote_bridge import validate_canonical_quote

NOW = datetime(2026, 8, 12, 13, 2, 10, tzinfo=timezone.utc)


def game(pk=100, status="Preview", start="2026-08-12T17:40:00+00:00"):
    return GameSnapshot(
        pk, start, status, 110, "Baltimore Orioles", 142, "Minnesota Twins",
        1, "Away Starter", 2, "Home Starter", NOW.isoformat(),
        official_date="2026-08-12",
    )


def event(status="pre", provider="DraftKings"):
    return {
        "id": "401816500", "name": "Baltimore Orioles at Minnesota Twins",
        "date": "2026-08-12T17:40:00Z", "status": status,
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"displayName": "Baltimore Orioles"}},
            {"homeAway": "home", "team": {"displayName": "Minnesota Twins"}},
        ]}],
        "odds": {
            "provider": {"name": provider},
            "home": {"moneyLine": -105}, "away": {"moneyLine": -102},
            "overUnder": 9.0, "overOdds": -102, "underOdds": -119,
            "pointSpread": {
                "home": {"open": {"line": "+1.5", "odds": "-199"},
                         "close": {"line": "+1.5", "odds": "-184"}},
                "away": {"open": {"line": "-1.5", "odds": "+163"},
                         "close": {"line": "-1.5", "odds": "+151"}},
            },
        },
    }


class Response:
    def __init__(self, payload): self.raw = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class TestEspnGameOddsSource(unittest.TestCase):
    def test_parses_exact_six_full_game_quotes(self):
        snap = parse_espn_event_odds(event(), game=game(), retrieved_at=NOW)
        self.assertEqual(len(snap.quotes), 6)
        self.assertEqual(snap.failures, ())
        self.assertEqual({q["market"] for q in snap.quotes}, {"MONEYLINE", "RUN_LINE", "TOTALS"})
        self.assertNotIn("NRFI", {q["market"] for q in snap.quotes})
        self.assertNotIn("YRFI", {q["market"] for q in snap.quotes})
        home_ml = next(q for q in snap.quotes if q["market"] == "MONEYLINE" and q["side"] == "HOME")
        away_rl = next(q for q in snap.quotes if q["market"] == "RUN_LINE" and q["side"] == "AWAY")
        over = next(q for q in snap.quotes if q["market"] == "TOTALS" and q["side"] == "OVER")
        self.assertEqual(home_ml["american_odds"], -105)
        self.assertEqual(away_rl["line"], -1.5)
        self.assertEqual(away_rl["american_odds"], 151)
        self.assertEqual(over["line"], 9.0)
        self.assertEqual(over["american_odds"], -102)
        self.assertTrue(all(q["sportsbook"] == "DraftKings" for q in snap.quotes))
        self.assertTrue(all(q["retrieved_at"] == NOW for q in snap.quotes))
        self.assertTrue(all(q["ttl_seconds"] == DEFAULT_TTL_SECONDS for q in snap.quotes))

    def test_every_emitted_quote_passes_canonical_bridge_and_double_ttl(self):
        snap = parse_espn_event_odds(event(), game=game(), retrieved_at=NOW)
        for raw in snap.quotes:
            q = validate_canonical_quote(raw)
            ingest, final = double_ttl_gate(q, NOW + timedelta(seconds=10), NOW + timedelta(seconds=50))
            self.assertEqual(ingest, 10)
            self.assertEqual(final, 50)
            with self.assertRaises(PriceFreshnessError):
                double_ttl_gate(q, NOW + timedelta(seconds=10), NOW + timedelta(seconds=61))

    def test_provider_must_be_draftkings(self):
        with self.assertRaisesRegex(EspnGameOddsError, "ESPN_PROVIDER_NOT_DRAFTKINGS"):
            parse_espn_event_odds(event(provider="ESPN BET"), game=game(), retrieved_at=NOW)

    def test_postgame_cannot_be_priced(self):
        with self.assertRaisesRegex(EspnGameOddsError, "ESPN_EVENT_NOT_PREGAME"):
            parse_espn_event_odds(event(status="post"), game=game(), retrieved_at=NOW)
        with self.assertRaisesRegex(EspnGameOddsError, "ESPN_EVENT_NOT_PREGAME"):
            bind_espn_event(event(status="post"), [game()])

    def test_runline_off_or_missing_does_not_fall_back_to_open(self):
        e = event()
        e["odds"]["pointSpread"]["home"]["close"] = {"line": "OFF", "odds": "OFF"}
        snap = parse_espn_event_odds(e, game=game(), retrieved_at=NOW)
        self.assertEqual(len(snap.quotes), 5)
        self.assertFalse(any(q["market"] == "RUN_LINE" and q["side"] == "HOME" for q in snap.quotes))
        self.assertTrue(any("ESPN_LINE_UNAVAILABLE" in f["reason"] for f in snap.failures))

    def test_unique_team_and_time_binding_required(self):
        self.assertEqual(bind_espn_event(event(), [game()]).game_pk, 100)
        with self.assertRaisesRegex(EspnGameOddsError, "AMBIGUOUS"):
            bind_espn_event(event(), [game(100), game(101)])
        with self.assertRaisesRegex(EspnGameOddsError, "NOT_FOUND"):
            bind_espn_event(event(), [game(100, start="2026-08-12T22:40:00+00:00")])

    def test_fetch_uses_explicit_slate_date_and_fetch_time(self):
        payload = {"sports": [{"leagues": [{"slug": "mlb", "events": [event()]}]}]}
        seen = []
        def opener(req, timeout=15):
            seen.append(req.full_url)
            return Response(payload)
        snap = fetch_espn_draftkings_game_quotes(
            slate_date=date(2026, 8, 12), schedule=[game()], retrieved_at=NOW, opener=opener,
        )
        self.assertEqual(len(snap.quotes), 6)
        qs = parse_qs(urlparse(seen[0]).query)
        self.assertEqual(qs["dates"], ["20260812"])
        self.assertEqual(qs["league"], ["mlb"])
        self.assertTrue(all(q["retrieved_at"] == NOW for q in snap.quotes))

    def test_fallback_ttl_cannot_be_relaxed_past_sixty_seconds(self):
        with self.assertRaisesRegex(EspnGameOddsError, "ESPN_FALLBACK_TTL_INVALID"):
            parse_espn_event_odds(event(), game=game(), retrieved_at=NOW, ttl_seconds=61)


if __name__ == "__main__":
    unittest.main()
