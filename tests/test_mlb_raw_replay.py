from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.mlb_raw_replay import replay_mlb_game_quotes, replay_mlb_player_prop_quotes
from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_api_replay import FrozenOddsApiReplay, OddsApiReplayError, REPLAY_MANIFEST_SCHEMA


class MlbRawReplayTests(unittest.TestCase):
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

    def _replay(self, root: Path, payloads: dict[str, object]) -> FrozenOddsApiReplay:
        raw_root = root / "private"
        raw_root.mkdir(parents=True)
        rows = []
        for index, (label, payload) in enumerate(payloads.items()):
            raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
            path = f"r{index}.json"
            (raw_root / path).write_bytes(raw)
            rows.append({"label": label, "path": path, "sha256": sha256(raw).hexdigest()})
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": REPLAY_MANIFEST_SCHEMA, "responses": rows}), encoding="utf-8")
        return FrozenOddsApiReplay.from_manifest(manifest, raw_root=raw_root)

    def test_game_market_replay_uses_only_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            replay = self._replay(root, {"game-markets": [event]})
            snapshot = replay_mlb_game_quotes(replay=replay, schedule=[self._game()])
            self.assertFalse(snapshot.failures)
            self.assertEqual(len(snapshot.quotes), 2)
            self.assertTrue(all(q["source_event_id"] == "provider-event-123" for q in snapshot.quotes))

    def test_player_prop_cache_miss_aborts_whole_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {
                "id": "provider-event-123",
                "commence_time": "2026-08-11T23:40:00Z",
                "home_team": "Los Angeles Angels",
                "away_team": "Texas Rangers",
            }
            replay = self._replay(root, {"events": [event]})
            with self.assertRaisesRegex(OddsApiReplayError, "ODDS_REPLAY_CACHE_MISS:event:provider-event-123"):
                replay_mlb_player_prop_quotes(
                    replay=replay,
                    schedule=[self._game()],
                    participant_index={123: {"awaysp": 101, "homesp": 202}},
                )


if __name__ == "__main__":
    unittest.main()
