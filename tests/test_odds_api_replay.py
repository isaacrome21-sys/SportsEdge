from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.odds_api_replay import (
    FrozenOddsApiReplay,
    OddsApiReplayError,
    REPLAY_MANIFEST_SCHEMA,
)


class OddsApiReplayTests(unittest.TestCase):
    def _write_fixture(self, root: Path, *, label: str = "events") -> tuple[Path, Path, bytes]:
        raw_root = root / "private_raw"
        raw_root.mkdir(parents=True)
        raw = b'[{"id":"provider-event-1","home_team":"Home","away_team":"Away"}]\n'
        raw_path = raw_root / "events.json"
        raw_path.write_bytes(raw)
        manifest = {
            "schema_version": REPLAY_MANIFEST_SCHEMA,
            "responses": [
                {
                    "label": label,
                    "path": "events.json",
                    "sha256": sha256(raw).hexdigest(),
                }
            ],
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path, raw_root, raw

    def test_reads_exact_verified_bytes_then_parses_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, raw_root, raw = self._write_fixture(root)
            replay = FrozenOddsApiReplay.from_manifest(manifest_path, raw_root=raw_root)

            self.assertEqual(replay.read_bytes("events"), raw)
            payload = replay.read_json("events")
            self.assertEqual(payload[0]["id"], "provider-event-1")
            self.assertEqual(len(replay.manifest_sha256), 64)

    def test_cache_miss_fails_closed_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, raw_root, _ = self._write_fixture(root)
            replay = FrozenOddsApiReplay.from_manifest(manifest_path, raw_root=raw_root)

            with self.assertRaisesRegex(OddsApiReplayError, "ODDS_REPLAY_CACHE_MISS:event:missing"):
                replay.read_json("event:missing")

    def test_tampered_raw_bytes_fail_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, raw_root, _ = self._write_fixture(root)
            replay = FrozenOddsApiReplay.from_manifest(manifest_path, raw_root=raw_root)
            (raw_root / "events.json").write_bytes(b'[{"id":"tampered"}]\n')

            with self.assertRaisesRegex(OddsApiReplayError, "ODDS_REPLAY_RAW_SHA256_MISMATCH:events"):
                replay.read_json("events")

    def test_missing_raw_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, raw_root, _ = self._write_fixture(root)
            replay = FrozenOddsApiReplay.from_manifest(manifest_path, raw_root=raw_root)
            (raw_root / "events.json").unlink()

            with self.assertRaisesRegex(OddsApiReplayError, "ODDS_REPLAY_RAW_BYTES_MISSING:events"):
                replay.read_bytes("events")

    def test_manifest_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "schema_version": REPLAY_MANIFEST_SCHEMA,
                "responses": [
                    {"label": "events", "path": "../secret.json", "sha256": "a" * 64}
                ],
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(OddsApiReplayError, "ODDS_REPLAY_PATH_INVALID"):
                FrozenOddsApiReplay.from_manifest(path, raw_root=root)

    def test_manifest_rejects_duplicate_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "schema_version": REPLAY_MANIFEST_SCHEMA,
                "responses": [
                    {"label": "events", "path": "a.json", "sha256": "a" * 64},
                    {"label": "events", "path": "b.json", "sha256": "b" * 64},
                ],
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(OddsApiReplayError, "ODDS_REPLAY_LABEL_DUPLICATE:events"):
                FrozenOddsApiReplay.from_manifest(path, raw_root=root)


if __name__ == "__main__":
    unittest.main()
