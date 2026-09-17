import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.capture_market_maker_fourc_line_history import FourCImportError, import_file, normalize_capsule

UTC = timezone.utc
SOURCE_CAPTURE_SHA = "a" * 64
CAPSULE_SHA = "b" * 64


def capsule():
    return {
        "schema_version": "FOURC_LINE_HISTORY_CAPSULE_V1",
        "source": "4codds",
        "source_url": "https://www.4codds.com/",
        "source_capture_sha256": SOURCE_CAPTURE_SHA,
        "event": {
            "source_event_key": "det-buf-2026",
            "sport_key": "americanfootball_nfl",
            "home_team": "Buffalo Bills",
            "away_team": "Detroit Lions",
            "commence_time": "2026-09-17T00:15:00Z",
        },
        "market": "h2h",
        "observations": [
            {"book": "Pinnacle", "designation": "home", "price_american": -205, "observed_at": "2026-09-15T23:00:00Z"},
            {"book": "DraftKings", "designation": "home", "price_american": -195, "observed_at": "2026-09-15T23:02:00Z"},
            {"book": "FanDuel", "designation": "home", "price_american": -200, "observed_at": "2026-09-15T23:03:00Z"},
        ],
    }


class FourCImportTests(unittest.TestCase):
    def test_namespaces_books_and_preserves_zero_authority(self):
        rows = normalize_capsule(
            capsule(),
            capsule_sha256=CAPSULE_SHA,
            ingested_at=datetime(2026, 9, 16, 1, 0, tzinfo=UTC),
        )
        self.assertEqual([row["book"] for row in rows], ["fourc_pinnacle", "fourc_draftkings", "fourc_fanduel"])
        self.assertTrue(all(row["event_id"].startswith("fourc:") for row in rows))
        self.assertTrue(all(row["book_last_update"] is None for row in rows))
        self.assertTrue(all(row["timestamp_source"] == "FOURC_DISPLAYED_MOVE_TIME" for row in rows))
        for row in rows:
            self.assertFalse(row["native_sportsbook_identity_authority"])
            self.assertFalse(row["draftkings_evidence_authority"])
            self.assertFalse(row["model_p_authority"])
            self.assertFalse(row["truth_gate_input"])
            self.assertFalse(row["promotion_authority"])
            self.assertFalse(row["eligibility_authority"])
            self.assertFalse(row["staking_authority"])
            self.assertFalse(row["official_authority"])
            self.assertFalse(row["evidence_clock_authority"])
            self.assertFalse(row["wager_placement_authority"])

    def test_capsule_hash_binds_exact_bytes(self):
        payload = capsule()
        raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capsule.json"
            path.write_bytes(raw)
            rows, digest = import_file(path, ingested_at=datetime(2026, 9, 16, 1, 0, tzinfo=UTC))
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertTrue(all(row["capsule_sha256"] == digest for row in rows))
        self.assertTrue(all(row["source_capture_sha256"] == SOURCE_CAPTURE_SHA for row in rows))

    def test_rejects_unsupported_book(self):
        payload = capsule()
        payload["observations"][0]["book"] = "UnknownBook"
        with self.assertRaisesRegex(FourCImportError, "FOURC_BOOK_UNSUPPORTED"):
            normalize_capsule(payload, capsule_sha256=CAPSULE_SHA, ingested_at=datetime.now(UTC))

    def test_rejects_missing_source_capture_hash(self):
        payload = capsule()
        payload["source_capture_sha256"] = ""
        with self.assertRaisesRegex(FourCImportError, "FOURC_SOURCE_CAPTURE_SHA256_INVALID"):
            normalize_capsule(payload, capsule_sha256=CAPSULE_SHA, ingested_at=datetime.now(UTC))

    def test_spread_requires_point_and_maps_team_outcome(self):
        payload = capsule()
        payload["market"] = "spreads"
        payload["observations"] = [
            {"book": "Pinnacle", "designation": "away", "point": 3.5, "price_american": -110, "observed_at": "2026-09-15T23:00:00Z"}
        ]
        rows = normalize_capsule(payload, capsule_sha256=CAPSULE_SHA, ingested_at=datetime.now(UTC))
        self.assertEqual(rows[0]["outcome"], "Detroit Lions")
        self.assertEqual(rows[0]["point"], 3.5)

    def test_duplicate_observation_fails_closed(self):
        payload = capsule()
        payload["observations"].append(dict(payload["observations"][0]))
        with self.assertRaisesRegex(FourCImportError, "FOURC_DUPLICATE_OBSERVATION"):
            normalize_capsule(payload, capsule_sha256=CAPSULE_SHA, ingested_at=datetime.now(UTC))

    def test_policy_keeps_fourc_separate_and_zero_authority(self):
        policy = json.loads(Path("config/market_maker_radar_v1.json").read_text())
        self.assertIn("fourc_pinnacle", policy["books"]["market_makers"])
        self.assertIn("fourc_draftkings", policy["books"]["soft_books"])
        self.assertIn("fourc_fanduel", policy["books"]["soft_books"])
        families = policy["grading"]["source_family_ids"]
        self.assertNotEqual(families["pinnacle_to_draftkings"], families["fourc_pinnacle_to_fourc_draftkings"])
        self.assertNotEqual(families["pinnacle_to_fanduel"], families["fourc_pinnacle_to_fourc_fanduel"])
        fourc = policy["external_line_history"]["fourc"]
        self.assertFalse(fourc["native_sportsbook_identity_authority"])
        self.assertFalse(fourc["draftkings_evidence_authority"])
        self.assertFalse(fourc["truth_gate_input"])
        self.assertFalse(fourc["promotion_authority"])
        self.assertFalse(fourc["official_authority"])
        self.assertTrue(fourc["never_blend_with_native_source_families"])


if __name__ == "__main__":
    unittest.main()
