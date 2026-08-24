import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.draftkings_prop_source import COUNT_MARKETS


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_mlb_prop_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_mlb_prop_odds", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def _snapshot(*, retrieved_at: str, market: str = "PITCHER_OUTS"):
    return SimpleNamespace(
        quotes=(
            {
                "provider_event_id": "123",
                "market": market,
                "entity_name": "Player A",
                "entity_name_normalized": "playera",
                "side": "OVER",
                "selection": "Over",
                "line": 1.5 if market != "PITCHER_OUTS" else 17.5,
                "american_odds": -110,
                "sportsbook": "DraftKings",
                "book_key": "draftkings_direct",
                "retrieved_at": retrieved_at,
                "ttl_seconds": 120,
                "is_alternate": False,
                "raw_market_name": market,
                "provider": "DRAFTKINGS_WEB_RESEARCH",
            },
        ),
        failures=(),
        league_id=84240,
        base_url="https://example.invalid/",
    )


def _event():
    raw = {
        "id": 123,
        "name": "Away @ Home",
        "startDate": "2026-08-24T00:10:00Z",
        "participants": [
            {"name": "Away", "venueRole": "Away"},
            {"name": "Home", "venueRole": "Home"},
        ],
    }
    return {
        "provider_event_id": "123",
        "event_name": "Away @ Home",
        "first_pitch_at": "2026-08-24T00:10:00+00:00",
        "provider_event_sha256": mod._sha256_json(raw),
        "provider_event_snapshot": raw,
    }


class ArchiveMLBPropOddsTests(unittest.TestCase):
    def test_target_market_set_is_derived_from_live_dk_parser(self):
        self.assertEqual(mod.TARGET_MARKETS, frozenset(COUNT_MARKETS))
        self.assertIn("HITS", mod.TARGET_MARKETS)
        self.assertIn("EXTRA_BASE_HITS", mod.TARGET_MARKETS)
        self.assertIn("PITCHER_HITS_WALKS_ER", mod.TARGET_MARKETS)
        self.assertIn("EITHER_PITCHER_ER", mod.TARGET_MARKETS)
        self.assertNotIn("MONEYLINE", mod.TARGET_MARKETS)
        self.assertNotIn("FIRST_HOME_RUN", mod.TARGET_MARKETS)

    def test_event_time_extraction_fails_closed(self):
        self.assertIsNone(mod._event_first_pitch({"name": "x"}))
        self.assertEqual(
            mod._event_first_pitch({"startDate": "2026-08-24T00:10:00Z"}),
            datetime(2026, 8, 24, 0, 10, tzinfo=timezone.utc),
        )

    def test_persist_is_immutable_plus_latest_pointer(self):
        payload = {
            "captured_at": "2026-08-24T00:00:00+00:00",
            "payload_sha256": "a" * 64,
            "pit_target_quote_count": 1,
            "market_counts": {market: 0 for market in sorted(mod.TARGET_MARKETS)},
        }
        with tempfile.TemporaryDirectory() as td:
            immutable, latest = mod.persist_payload(payload, root=Path(td))
            self.assertTrue(immutable.exists())
            self.assertTrue(latest.exists())
            self.assertNotEqual(immutable, latest)
            self.assertIn("2026-08-24", str(immutable))

    def test_build_archive_accepts_strictly_pregame_quote_and_preserves_identity_raw_material(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:00:00Z", market="HITS")
        events = {"123": _event()}
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod, "_event_index", return_value=(events, [])
        ):
            payload = mod.build_archive_payload(
                now=datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc)
            )

        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["evidence_class"], "LIVE_PROVIDER_QUOTE_ARCHIVE")
        self.assertEqual(payload["pit_target_quote_count"], 1)
        self.assertEqual(payload["market_counts"]["HITS"], 1)
        self.assertEqual(payload["rejected_target_count"], 0)
        row = payload["quotes"][0]
        self.assertTrue(row["pit_eligible"])
        self.assertEqual(row["quote_retrieved_at"], "2026-08-24T00:00:00+00:00")
        self.assertEqual(row["first_pitch_at"], "2026-08-24T00:10:00+00:00")
        self.assertEqual(row["identity_state"], "PROVIDER_NATIVE_UNRESOLVED")
        self.assertIsNone(row["canonical_game_id"])
        self.assertIsNone(row["canonical_entity_id"])
        self.assertEqual(row["provider_event_snapshot"]["participants"][0]["name"], "Away")
        self.assertEqual(len(row["provider_event_sha256"]), 64)
        self.assertEqual(len(payload["payload_sha256"]), 64)

    def test_provider_event_metadata_hash_is_content_bound(self):
        raw = {"id": 123, "name": "Away @ Home", "startDate": "2026-08-24T00:10:00Z"}
        changed = {**raw, "name": "Different @ Home"}
        self.assertNotEqual(mod._sha256_json(raw), mod._sha256_json(changed))

    def test_build_archive_rejects_quote_at_or_after_first_pitch(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:10:00Z")
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod, "_event_index", return_value=({"123": _event()}, [])
        ):
            payload = mod.build_archive_payload(
                now=datetime(2026, 8, 24, 0, 11, tzinfo=timezone.utc)
            )

        self.assertEqual(payload["pit_target_quote_count"], 0)
        self.assertEqual(payload["rejected_target_count"], 1)
        self.assertEqual(payload["rejected_targets"][0]["reason"], "NOT_PREGAME")

    def test_build_archive_rejects_missing_event_time(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:00:00Z")
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod,
            "_event_index",
            return_value=({}, [{"provider_event_id": "123", "reason": "FIRST_PITCH_MISSING"}]),
        ):
            payload = mod.build_archive_payload(
                now=datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc)
            )

        self.assertEqual(payload["pit_target_quote_count"], 0)
        self.assertEqual(payload["event_failure_count"], 1)
        self.assertEqual(payload["rejected_target_count"], 1)
        self.assertEqual(payload["rejected_targets"][0]["reason"], "EVENT_TIME_UNAVAILABLE")

    def test_archive_does_not_claim_canonical_identity_or_settlement(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:00:00Z", market="RBI")
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod, "_event_index", return_value=({"123": _event()}, [])
        ):
            payload = mod.build_archive_payload(
                now=datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc)
            )
        row = payload["quotes"][0]
        self.assertIsNone(row["canonical_game_id"])
        self.assertIsNone(row["canonical_entity_id"])
        self.assertNotIn("settlement", row)
        self.assertFalse(payload["identity_policy"]["provider_event_is_canonical_game_id"])
        self.assertFalse(payload["identity_policy"]["participant_name_is_canonical_player_id"])


if __name__ == "__main__":
    unittest.main()
