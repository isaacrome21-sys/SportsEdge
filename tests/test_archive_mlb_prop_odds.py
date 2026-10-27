import importlib.util
import json
import subprocess
import sys
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
    def test_direct_cli_works_without_pythonpath_or_working_directory(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--self-test"],
                                    cwd=td, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "SELF_TEST_OK")

    def test_naive_provider_timestamp_is_not_assumed_utc(self):
        self.assertIsNone(mod._parse_iso("2026-08-24T00:10:00"))

    def test_capture_crossing_first_pitch_is_rejected(self):
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=_snapshot(retrieved_at="2026-08-24T00:09:59Z")), patch.object(mod, "_event_index", return_value=({"123": _event()}, [])), patch.object(mod, "_utcnow", side_effect=[datetime(2026,8,24,0,9,58,tzinfo=timezone.utc), datetime(2026,8,24,0,10,1,tzinfo=timezone.utc)]):
            result = mod.build_archive_payload()
        self.assertEqual(result["pit_target_quote_count"], 0)
        self.assertEqual(result["rejected_targets"][0]["reason"], "NOT_PREGAME")

    def test_future_quote_cannot_be_accepted(self):
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=_snapshot(retrieved_at="2026-08-24T00:09:59Z")), patch.object(mod, "_event_index", return_value=({"123": _event()}, [])):
            result = mod.build_archive_payload(now=datetime(2026,8,24,0,5,tzinfo=timezone.utc))
        self.assertEqual(result["pit_target_quote_count"], 0)
        self.assertEqual(result["rejected_targets"][0]["reason"], "QUOTE_TIMESTAMP_AFTER_CAPTURE")

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


class PrequoteContextWorkflowTests(unittest.TestCase):
    def test_context_is_captured_before_quotes_and_persisted_with_them(self):
        # Exercise the workflow's persistence shell in a temporary git repository.
        # This guards against capturing context but leaving it invisible to the
        # downstream reader, which reads only origin/data immutable run paths.
        workflow = (SCRIPT.parent.parent / '.github/workflows/mlb-prop-pit-archive.yml').read_text()
        self.assertLess(workflow.index('run: bash scripts/run_mlb_context_diagnostic.sh'),
                        workflow.index('python scripts/archive_mlb_prop_odds.py |'))
        start = workflow.index('          # Persist the preceding context')
        end = workflow.index('          if git diff --cached --quiet', start)
        shell = '\n'.join(line[10:] for line in workflow[start:end].splitlines())
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / 'artifacts/mlb-context/2026-10-26'
            ctx.mkdir(parents=True)
            payload = '{"game_id":"123","retrieved_at":"2026-10-26T20:00:00Z"}\n'
            (ctx / 'game_123.json').write_text(payload)
            repo = root / '.data-branch'
            repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            quotes = repo / 'runtime/mlb-prop-pit'
            quotes.mkdir(parents=True)
            (quotes / 'props_test.json').write_text('{}')
            subprocess.run(['bash', '-eu', '-c', shell], cwd=root, check=True,
                           env={**os.environ, 'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2'})
            archived = 'runtime/mlb-context/runs/1234_2_prop_prequote/2026-10-26/game_123.json'
            self.assertEqual((repo / archived).read_text(), payload)
            staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=repo, text=True)
            self.assertIn(archived, staged)
            self.assertIn('runtime/mlb-prop-pit/props_test.json', staged)


class ArchiveAuthorizationTests(unittest.TestCase):
    def test_archive_mutation_requires_main_ref(self):
        workflow = (SCRIPT.parent.parent / '.github/workflows/mlb-prop-pit-archive.yml').read_text()
        archive_job = workflow.split('\n  archive:\n', 1)[1].split('\n  ', 1)[0]
        self.assertIn("github.ref == 'refs/heads/main'", archive_job)
        self.assertIn("github.event_name != 'pull_request'", archive_job)
