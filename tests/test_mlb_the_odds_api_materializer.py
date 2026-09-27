import json
from hashlib import sha256
import unittest

from sportsedge.sports.mlb.the_odds_api_materializer import (
    MLBTheOddsAPIMaterializationError,
    materialize_persisted_snapshot,
)


def _raw_snapshot() -> tuple[bytes, str]:
    payload = {
        "timestamp": "2026-06-05T22:30:00Z",
        "data": [{
            "id": "game-1",
            "commence_time": "2026-06-06T00:10:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Home", "price": -120},
                        {"name": "Away", "price": 105},
                    ]},
                    {"key": "batter_hits", "outcomes": [
                        {"name": "Over", "description": "Player A", "price": -110, "point": 1.5},
                        {"name": "Under", "description": "Player A", "price": -120, "point": 1.5},
                        {"name": "Over", "description": "Player B", "price": 100, "point": 1.5},
                        {"name": "Under", "description": "Player B", "price": -130, "point": 1.5},
                    ]},
                    {"key": "pitcher_record_a_win", "outcomes": [
                        {"name": "Yes", "description": "Pitcher A", "price": 140},
                        {"name": "No", "description": "Pitcher A", "price": -170},
                    ]},
                    {"key": "spreads_1st_5_innings", "outcomes": [
                        {"name": "Home", "price": 120, "point": -0.5},
                        {"name": "Away", "price": -140, "point": 0.5},
                    ]},
                    {"key": "unsupported_vendor_market", "outcomes": [
                        {"name": "Whatever", "price": -110},
                    ]},
                ],
            }],
        }],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return raw, sha256(raw).hexdigest()


class MLBTheOddsAPIMaterializerTests(unittest.TestCase):
    def test_materializes_multiple_direct_market_families(self):
        raw, digest = _raw_snapshot()
        out = materialize_persisted_snapshot(raw, source_sha256=digest)
        self.assertEqual(out["status"], "MATERIALIZED")
        self.assertEqual(out["quote_count"], 10)
        self.assertEqual(out["quote_count_by_market"]["MONEYLINE"], 2)
        self.assertEqual(out["quote_count_by_market"]["HITS"], 4)
        self.assertEqual(out["quote_count_by_market"]["PITCHER_RECORD_WIN"], 2)
        self.assertEqual(out["quote_count_by_market"]["F5_RUN_LINE"], 2)
        self.assertEqual(out["ignored_provider_markets"], {"unsupported_vendor_market": 1})
        hit_entities = {q["entity_id"] for q in out["quotes"] if q["market"] == "HITS"}
        self.assertEqual(hit_entities, {"Player A", "Player B"})
        f5 = [q for q in out["quotes"] if q["market"] == "F5_RUN_LINE"]
        self.assertEqual({q["period"] for q in f5}, {"F5"})

    def test_snapshot_sha_is_binding(self):
        raw, digest = _raw_snapshot()
        with self.assertRaisesRegex(MLBTheOddsAPIMaterializationError, "SHA256_MISMATCH"):
            materialize_persisted_snapshot(raw + b" ", source_sha256=digest)

    def test_malformed_direct_market_blocks_snapshot(self):
        raw, _ = _raw_snapshot()
        payload = json.loads(raw)
        for market in payload["data"][0]["bookmakers"][0]["markets"]:
            if market["key"] == "batter_hits":
                market["outcomes"][0].pop("description")
                break
        broken = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        out = materialize_persisted_snapshot(broken, source_sha256=sha256(broken).hexdigest())
        self.assertEqual(out["status"], "BLOCKED_PROVIDER_SNAPSHOT")
        self.assertGreater(out["failure_count"], 0)
        self.assertTrue(any(f.get("market") == "HITS" for f in out["failures"]))


if __name__ == "__main__":
    unittest.main()
