import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from sportsedge.mlb_source import GameSnapshot


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_mlb_additional_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_mlb_additional_odds", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class ArchiveMLBAdditionalOddsTests(unittest.TestCase):
    def _game(self):
        return GameSnapshot(
            game_pk=123,
            game_date="2026-08-11T23:40:00Z",
            status="Preview",
            away_id=10,
            away_name="Texas Rangers",
            home_id=20,
            home_name="Los Angeles Angels",
            away_probable_pitcher_id=101,
            away_probable_pitcher_name="Away Pitcher",
            home_probable_pitcher_id=202,
            home_probable_pitcher_name="Home Pitcher",
            retrieved_at="2026-08-11T22:00:00Z",
            official_date="2026-08-11",
        )

    def _event(self, event_id="provider-event", away="Texas Rangers", home="Los Angeles Angels"):
        return {
            "id": event_id,
            "commence_time": "2026-08-11T23:40:00Z",
            "away_team": away,
            "home_team": home,
        }

    def _quote(self, *, market="NRFI", entity_id="123", side="YES", retrieved="2026-08-11T23:30:00Z"):
        return {
            "game_id": "123",
            "period": "1ST" if market in {"NRFI", "YRFI"} else "FG",
            "market": market,
            "entity_id": entity_id,
            "side": side,
            "line": 0.0,
            "book_key": "draftkings",
            "sportsbook": "DraftKings",
            "retrieved_at": retrieved,
            "is_alternate": False,
            "raw_market_name": "totals_1st_1_innings" if market in {"NRFI", "YRFI"} else "batter_first_home_run",
            "american_odds": -110,
            "ttl_seconds": 300,
            "provider_event_id": "provider-event",
        }

    def _build(self, *, quotes=None, events=None, participant_index=None, source_failures=()):
        return mod.build_archive_from_inputs(
            schedule=[self._game()],
            quote_rows=list(quotes if quotes is not None else [self._quote()]),
            provider_events=list(events if events is not None else [self._event()]),
            participant_index=participant_index or {123: {"battera": 301, "awaypitcher": 101, "homepitcher": 202}},
            captured_at=datetime(2026, 8, 11, 23, 31, tzinfo=timezone.utc),
            source_failures=source_failures,
        )

    def test_target_market_set_is_exactly_seven_and_matches_source(self):
        self.assertEqual(mod.TARGET_MARKETS, mod.CANONICAL_MARKETS)
        self.assertEqual(len(mod.TARGET_MARKETS), 7)

    def test_pregame_quote_is_archived_with_replayable_provider_and_canonical_hashes(self):
        payload = self._build()
        self.assertEqual(payload["pit_quote_count"], 1)
        self.assertEqual(payload["rejected_count"], 0)
        row = payload["quotes"][0]
        self.assertTrue(row["pit_eligible"])
        self.assertEqual(row["identity_binding_state"], mod.IDENTITY_STATE)
        self.assertEqual(row["provider_event_sha256"], mod._sha256_json(row["provider_event_snapshot"]))
        self.assertEqual(
            row["canonical_game_snapshot_sha256"],
            mod._sha256_json(row["canonical_game_snapshot"]),
        )
        self.assertEqual(len(row["identity_binding_sha256"]), 64)
        expected_payload_hash = mod._sha256_json({k: v for k, v in payload.items() if k != "payload_sha256"})
        self.assertEqual(payload["payload_sha256"], expected_payload_hash)

    def test_quote_at_first_pitch_is_rejected(self):
        payload = self._build(quotes=[self._quote(retrieved="2026-08-11T23:40:00Z")])
        self.assertEqual(payload["pit_quote_count"], 0)
        self.assertEqual(payload["rejected_count"], 1)
        self.assertIn("NOT_PREGAME", payload["rejected_quotes"][0]["reason"])

    def test_duplicate_provider_event_identity_fails_closed(self):
        event = self._event()
        payload = self._build(events=[event, dict(event)])
        self.assertEqual(payload["pit_quote_count"], 0)
        self.assertIn("PROVIDER_EVENT_NOT_FOUND_OR_AMBIGUOUS", payload["rejected_quotes"][0]["reason"])

    def test_provider_event_must_rebind_to_same_canonical_game(self):
        payload = self._build(events=[self._event(away="Other Team")])
        self.assertEqual(payload["pit_quote_count"], 0)
        self.assertTrue(
            "PROVIDER_EVENT_GAME_NOT_FOUND" in payload["rejected_quotes"][0]["reason"]
            or "CANONICAL_GAME_MISMATCH" in payload["rejected_quotes"][0]["reason"]
        )

    def test_binary_player_entity_must_be_reproducible_from_participant_index(self):
        quote = self._quote(market="FIRST_HOME_RUN", entity_id="301", side="YES")
        accepted = self._build(quotes=[quote], participant_index={123: {"battera": 301}})
        self.assertEqual(accepted["pit_quote_count"], 1)

        blocked = self._build(quotes=[quote], participant_index={123: {"other": 999}})
        self.assertEqual(blocked["pit_quote_count"], 0)
        self.assertIn("CANONICAL_ENTITY_NOT_REPRODUCIBLE", blocked["rejected_quotes"][0]["reason"])

    def test_source_failures_are_preserved_and_generators_count_correctly(self):
        payload = mod.build_archive_from_inputs(
            schedule=[self._game()],
            quote_rows=(row for row in [self._quote()]),
            provider_events=(row for row in [self._event()]),
            participant_index={123: {}},
            captured_at=datetime(2026, 8, 11, 23, 31, tzinfo=timezone.utc),
            source_failures=(row for row in [{"reason": "upstream"}]),
        )
        self.assertEqual(payload["source_quote_count"], 1)
        self.assertEqual(payload["source_failure_count"], 1)
        self.assertEqual(payload["source_failures"], [{"reason": "upstream"}])

    def test_persist_writes_immutable_file_and_latest_pointer(self):
        payload = self._build()
        with tempfile.TemporaryDirectory() as td:
            immutable, latest = mod.persist_payload(payload, root=Path(td))
            self.assertTrue(immutable.exists())
            self.assertTrue(latest.exists())
            self.assertNotEqual(immutable, latest)
            self.assertIn("2026-08-11", str(immutable))


if __name__ == "__main__":
    unittest.main()
