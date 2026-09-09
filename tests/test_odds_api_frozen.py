from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.game_odds_source import GAME_MARKETS
from sportsedge.mlb_frozen_quotes import replay_mlb_game_quotes, replay_mlb_player_prop_quotes
from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_api_frozen import (
    MANIFEST_SCHEMA,
    FrozenOddsReplayError,
    FrozenOddsReplayStore,
    build_public_manifest_entry,
    canonical_request_identity,
    raw_response_sha256,
    request_sha256,
)
from sportsedge.odds_api_source import MARKETS, _event_url, _get_json


class FrozenOddsReplayTests(unittest.TestCase):
    def _game(self) -> GameSnapshot:
        return GameSnapshot(
            game_pk=123,
            game_date="2026-08-11T23:40:00Z",
            status="Preview",
            away_id=10,
            away_name="Texas Rangers",
            home_id=20,
            home_name="Los Angeles Angels",
            away_probable_pitcher_id=101,
            away_probable_pitcher_name="Away SP",
            home_probable_pitcher_id=202,
            home_probable_pitcher_name="Home SP",
            retrieved_at="2026-08-11T23:30:00Z",
            official_date="2026-08-11",
        )

    def _store_for_entries(
        self,
        root: Path,
        entries: list[tuple[str, bytes]],
    ) -> FrozenOddsReplayStore:
        rows = []
        for index, (url, raw) in enumerate(entries):
            private_path = f"responses/frozen-response-{index}.bin"
            path = root / private_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            rows.append(
                build_public_manifest_entry(
                    url_or_request=url,
                    raw_response_bytes=raw,
                    private_path=private_path,
                )
            )
        return FrozenOddsReplayStore(
            private_root=root,
            manifest={"schema_version": MANIFEST_SCHEMA, "responses": rows},
        )

    def _store_for(self, root: Path, *, url: str, raw: bytes) -> FrozenOddsReplayStore:
        return self._store_for_entries(root, [(url, raw)])

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
            (root / "responses/frozen-response-0.bin").write_bytes(b'[{"id":"tampered"}]\n')
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

    def test_game_replay_uses_production_request_and_parser_without_network(self):
        game_url = _event_url(
            "/sports/baseball_mlb/odds",
            api_key="capture-key",
            params={
                "regions": "us",
                "bookmakers": "draftkings",
                "markets": ",".join(GAME_MARKETS),
                "oddsFormat": "american",
                "dateFormat": "iso",
                "includeSids": "true",
            },
        )
        event = {
            "id": "provider-event-123",
            "commence_time": "2026-08-11T23:40:00Z",
            "home_team": "Los Angeles Angels",
            "away_team": "Texas Rangers",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-08-11T23:35:00Z",
                "markets": [{
                    "key": "totals",
                    "last_update": "2026-08-11T23:35:00Z",
                    "outcomes": [
                        {"name": "Over", "point": 9.0, "price": -105},
                        {"name": "Under", "point": 9.0, "price": -115},
                    ],
                }],
            }],
        }
        raw = (json.dumps([event], separators=(",", ":")) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_for(Path(tmp), url=game_url, raw=raw)
            snapshot = replay_mlb_game_quotes(replay_store=store, schedule=[self._game()])
            self.assertFalse(snapshot.failures)
            self.assertEqual(len(snapshot.quotes), 2)
            self.assertTrue(all(q["source_event_id"] == "provider-event-123" for q in snapshot.quotes))

    def test_game_replay_turns_cache_miss_into_hard_failure(self):
        unrelated_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey=x"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_for(Path(tmp), url=unrelated_url, raw=b'[]\n')
            with self.assertRaisesRegex(FrozenOddsReplayError, "FrozenOddsReplayError"):
                replay_mlb_game_quotes(replay_store=store, schedule=[])

    def test_player_replay_missing_events_cache_aborts(self):
        unrelated_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?apiKey=x&markets=h2h"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_for(Path(tmp), url=unrelated_url, raw=b'[]\n')
            with self.assertRaises(FrozenOddsReplayError):
                replay_mlb_player_prop_quotes(
                    replay_store=store,
                    schedule=[self._game()],
                    participant_index={123: {"awaysp": 101, "homesp": 202}},
                )

    def test_player_replay_missing_per_event_cache_aborts_whole_replay(self):
        events_url = _event_url("/sports/baseball_mlb/events", api_key="capture-key")
        event = {
            "id": "provider-event-123",
            "commence_time": "2026-08-11T23:40:00Z",
            "home_team": "Los Angeles Angels",
            "away_team": "Texas Rangers",
        }
        raw = (json.dumps([event], separators=(",", ":")) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_for(Path(tmp), url=events_url, raw=raw)
            with self.assertRaisesRegex(FrozenOddsReplayError, "FrozenOddsReplayError"):
                replay_mlb_player_prop_quotes(
                    replay_store=store,
                    schedule=[self._game()],
                    participant_index={123: {"awaysp": 101, "homesp": 202}},
                )

    def test_capture_and_replay_prop_market_lists_share_ordered_contract(self):
        # The capture script and production fetch path both use the insertion
        # order of MARKETS. Freeze identities would diverge if this were sorted
        # in one path and not the other.
        self.assertTrue(MARKETS)
        self.assertEqual(",".join(MARKETS), ",".join(list(MARKETS.keys())))


if __name__ == "__main__":
    unittest.main()
