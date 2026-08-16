import unittest
from datetime import datetime, timezone

from sportsedge.source_lineage import (
    SourceLineageError,
    build_feature_lineage,
    build_source_snapshot,
    canonical_game_identity,
    canonical_json_sha256,
)

UTC = timezone.utc


class SourceLineageTests(unittest.TestCase):
    def setUp(self):
        self.game = canonical_game_identity(
            mlb_game_pk=777,
            scheduled_start="2026-08-16T19:05:00Z",
            away_team_id=1,
            home_team_id=2,
            game_number=1,
        )

    def test_game_identity_is_deterministic_and_gamepk_anchored(self):
        same = canonical_game_identity(
            mlb_game_pk=777,
            scheduled_start="2026-08-16T14:05:00-05:00",
            away_team_id=1,
            home_team_id=2,
            game_number=1,
        )
        self.assertEqual(self.game, same)
        self.assertTrue(self.game.sportsedge_game_id.startswith("MLB:777:"))

    def test_doubleheader_games_do_not_collide(self):
        second = canonical_game_identity(
            mlb_game_pk=778,
            scheduled_start="2026-08-16T23:05:00Z",
            away_team_id=1,
            home_team_id=2,
            game_number=2,
        )
        self.assertNotEqual(self.game.sportsedge_game_id, second.sportsedge_game_id)

    def test_source_snapshot_hash_is_canonical(self):
        a = canonical_json_sha256({"b": 2, "a": 1})
        b = canonical_json_sha256({"a": 1, "b": 2})
        self.assertEqual(a, b)
        snap = build_source_snapshot(
            source_name="MLB_STATCAST",
            source_record_id="pitch-1",
            source_event_time="2026-08-16T17:00:00Z",
            fetched_at_utc="2026-08-16T17:05:00Z",
            game=self.game,
            payload={"xwoba": 0.31, "player_id": 10},
            parser_version="statcast_v1",
        )
        self.assertEqual(len(snap.payload_sha256), 64)
        self.assertEqual(snap.mlb_game_pk, 777)

    def test_impossible_source_chronology_rejected(self):
        with self.assertRaises(SourceLineageError):
            build_source_snapshot(
                source_name="MLB",
                source_record_id="x",
                source_event_time="2026-08-16T18:00:00Z",
                fetched_at_utc="2026-08-16T17:00:00Z",
                game=self.game,
                payload={},
                parser_version="v1",
            )

    def test_feature_lineage_rejects_future_or_post_asof_source(self):
        snap = build_source_snapshot(
            source_name="MLB",
            source_record_id="x",
            source_event_time="2026-08-16T17:00:00Z",
            fetched_at_utc="2026-08-16T18:00:00Z",
            game=self.game,
            payload={"v": 1},
            parser_version="v1",
        )
        with self.assertRaises(SourceLineageError):
            build_feature_lineage(
                feature_as_of_utc="2026-08-16T17:30:00Z",
                scheduled_first_pitch="2026-08-16T19:05:00Z",
                feature_contract_version="v7",
                feature_contract={"features": ["v"]},
                snapshots=[snap],
            )

    def test_feature_asof_must_precede_first_pitch(self):
        snap = build_source_snapshot(
            source_name="MLB",
            source_record_id="x",
            source_event_time="2026-08-16T17:00:00Z",
            fetched_at_utc="2026-08-16T17:01:00Z",
            game=self.game,
            payload={"v": 1},
            parser_version="v1",
        )
        with self.assertRaises(SourceLineageError):
            build_feature_lineage(
                feature_as_of_utc="2026-08-16T19:05:00Z",
                scheduled_first_pitch="2026-08-16T19:05:00Z",
                feature_contract_version="v7",
                feature_contract={"features": ["v"]},
                snapshots=[snap],
            )

    def test_lineage_is_order_independent(self):
        snaps = [
            build_source_snapshot(
                source_name="MLB", source_record_id=str(i),
                source_event_time="2026-08-16T17:00:00Z",
                fetched_at_utc="2026-08-16T17:01:00Z",
                game=self.game, payload={"v": i}, parser_version="v1",
            ) for i in (1, 2)
        ]
        kwargs = dict(
            feature_as_of_utc="2026-08-16T18:00:00Z",
            scheduled_first_pitch="2026-08-16T19:05:00Z",
            feature_contract_version="v7",
            feature_contract={"features": ["a", "b"]},
        )
        a = build_feature_lineage(snapshots=snaps, **kwargs)
        b = build_feature_lineage(snapshots=list(reversed(snaps)), **kwargs)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
