from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.mlb_frozen_quotes import replay_mlb_game_quotes
from sportsedge.odds_api_frozen import (
    MANIFEST_SCHEMA,
    FrozenOddsReplayError,
    FrozenOddsReplayStore,
    build_public_manifest_entry,
    canonical_request_identity,
    raw_response_sha256,
    request_sha256,
)
from sportsedge.odds_api_source import _get_json


class FrozenOddsReplayTests(unittest.TestCase):
    def _store_for(self, root: Path, *, url: str, raw: bytes) -> FrozenOddsReplayStore:
        private_path = "responses/frozen-response.bin"
        path = root / private_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "responses": [
                build_public_manifest_entry(
                    url_or_request=url,
                    raw_response_bytes=raw,
                    private_path=private_path,
                )
            ],
        }
        return FrozenOddsReplayStore(private_root=root, manifest=manifest)

    def test_request_identity_never_contains_api_key(self):
        left = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=secret-one&dateFormat=iso"
        right = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?dateFormat=iso&apiKey=secret-two"

        identity = canonical_request_identity(left)

        self.assertNotIn(b"secret-one", identity)
        self.assertNotIn(b"apiKey", identity)
        self.assertEqual(request_sha256(left), request_sha256(right))

    def test_raw_response_hash_is_byte_sensitive_not_semantic(self):
        compact = b'{"a":1,"b":2}\n'
        pretty = b'{\n  "a": 1,\n  "b": 2\n}\n'
        self.assertEqual(json.loads(compact), json.loads(pretty))
        self.assertNotEqual(raw_response_sha256(compact), raw_response_sha256(pretty))

    def test_replay_serves_exact_raw_bytes_into_parser(self):
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=do-not-store&dateFormat=iso"
        raw = b'[\n {"id":"evt-1","home_team":"A","away_team":"B"}\n]\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store_for(root, url=url, raw=raw)

            with store.open(url) as response:
                self.assertEqual(response.read(), raw)
            parsed = _get_json(url, opener=store.open, label="frozen-test")

            self.assertEqual(parsed[0]["id"], "evt-1")

    def test_missing_manifest_request_fails_closed(self):
        manifested_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=x"
        missing_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?apiKey=x&markets=h2h"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_for(Path(tmp), url=manifested_url, raw=b'[]\n')
            with self.assertRaisesRegex(FrozenOddsReplayError, "FROZEN_ODDS_REQUEST_NOT_MANIFESTED"):
                store.raw_bytes_for(missing_url)

    def test_missing_private_bytes_fails_closed(self):
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=x"
        raw = b'[]\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = build_public_manifest_entry(
                url_or_request=url,
                raw_response_bytes=raw,
                private_path="responses/missing.bin",
            )
            store = FrozenOddsReplayStore(
                private_root=root,
                manifest={"schema_version": MANIFEST_SCHEMA, "responses": [entry]},
            )
            with self.assertRaisesRegex(FrozenOddsReplayError, "FROZEN_ODDS_CACHE_MISS"):
                store.raw_bytes_for(url)

    def test_tampered_private_bytes_fail_hash_check(self):
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=x"
        original = b'[{"id":"original"}]\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store_for(root, url=url, raw=original)
            (root / "responses/frozen-response.bin").write_bytes(b'[{"id":"tampered"}]\n')
            with self.assertRaisesRegex(
                FrozenOddsReplayError,
                "FROZEN_ODDS_(BYTE_LENGTH_MISMATCH|RESPONSE_SHA_MISMATCH)",
            ):
                store.raw_bytes_for(url)

    def test_public_manifest_rejects_private_path_escape(self):
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=x"
        with self.assertRaisesRegex(FrozenOddsReplayError, "FROZEN_ODDS_PRIVATE_PATH_INVALID"):
            build_public_manifest_entry(
                url_or_request=url,
                raw_response_bytes=b'[]',
                private_path="../paid-provider-response.json",
            )

    def test_game_replay_turns_cache_miss_into_hard_failure(self):
        unrelated_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=x"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_for(Path(tmp), url=unrelated_url, raw=b'[]\n')
            with self.assertRaisesRegex(FrozenOddsReplayError, "FROZEN_ODDS_REQUEST_NOT_MANIFESTED"):
                replay_mlb_game_quotes(replay_store=store, schedule=[])


if __name__ == "__main__":
    unittest.main()
