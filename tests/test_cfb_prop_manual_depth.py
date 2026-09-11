from __future__ import annotations

from copy import deepcopy
import unittest

from sportsedge.sports.cfb.depth_chart_source import CORROBORATION_SOURCE_ID
from sportsedge.sports.cfb.prop_manual_depth import (
    CFBPropManualDepthError,
    bind_manual_depth_to_live_features,
)


class CFBPropManualDepthTests(unittest.TestCase):
    def features(self):
        def usage(team, qb, rb):
            return {
                "quarterback_id": qb,
                "players": [
                    {"player_id": qb, "player_name": f"{team} QB", "team": team, "position": "QB", "active": True,
                     "snap_share": .95, "route_participation": .0, "target_share": 0.0, "rush_share": .15, "red_zone_share": .20},
                    {"player_id": rb, "player_name": f"{team} RB", "team": team, "position": "RB", "active": True,
                     "snap_share": .70, "route_participation": .55, "target_share": .12, "rush_share": .62, "red_zone_share": .65},
                ],
            }
        return {
            "sport": "CFB",
            "asof_ts": "2026-09-11T16:00:00Z",
            "source_manifest_sha256": "1" * 64,
            "games": [{
                "game_id": "g1", "game_start_ts": "2026-09-12T00:00:00Z",
                "home_team": "HOME", "away_team": "AWAY",
                "provider_home_team": "Home", "provider_away_team": "Away",
                "home_usage": usage("HOME", "home-qb", "home-rb"),
                "away_usage": usage("AWAY", "away-qb", "away-rb"),
            }],
        }

    def entry(self, team, digest, qb, rb):
        return {
            "team_id": team,
            "previous_game_end": "2026-09-07T02:00:00Z",
            "expected_content_sha256": digest,
            "primary_snapshot": {
                "source_id": "TWO_DEEP_PROJECTED_TWO_DEEP",
                "source_kind": "PROJECTED_TWO_DEEP",
                "retrieved_at": "2026-09-11T15:30:00Z",
                "source_updated_at": "2026-09-10T18:00:00Z",
                "source_url": f"https://www.thetwodeep.com/college/{team.lower()}",
                "content_sha256": digest,
                "team_id": team,
                "players": [
                    {"player_id": qb, "position": "QB", "depth_rank": 1, "unavailable": False},
                    {"player_id": rb, "position": "RB", "depth_rank": 1, "unavailable": False},
                ],
            },
            "corroboration": {
                "source_id": CORROBORATION_SOURCE_ID,
                "starter_player_ids": {"QB": qb, "RB": rb},
            },
        }

    def manual(self):
        return {
            "schema_version": "CFB_PROP_MANUAL_DEPTH_INPUT_V1",
            "decision_time": "2026-09-11T16:10:00Z",
            "teams": [
                self.entry("HOME", "a" * 64, "home-qb", "home-rb"),
                self.entry("AWAY", "b" * 64, "away-qb", "away-rb"),
            ],
        }

    def test_binds_depth_provenance_without_changing_usage(self):
        features = self.features()
        before = deepcopy(features["games"])
        out = bind_manual_depth_to_live_features(
            live_features=features, manual_input=self.manual(), manual_bytes_sha256="c" * 64
        )
        self.assertEqual(out["games"], before)
        self.assertNotEqual(out["source_manifest_sha256"], "1" * 64)
        self.assertEqual(out["input_manifest_sha256"], out["source_manifest_sha256"])
        self.assertFalse(out["depth_input_can_create_usage"])
        self.assertFalse(out["depth_input_can_promote"])

    def test_stale_depth_blocks(self):
        manual = self.manual()
        manual["teams"][0]["primary_snapshot"]["source_updated_at"] = "2026-09-06T00:00:00Z"
        with self.assertRaisesRegex(CFBPropManualDepthError, "DEPTH_CHART_STALE"):
            bind_manual_depth_to_live_features(
                live_features=self.features(), manual_input=manual, manual_bytes_sha256="c" * 64
            )

    def test_unavailable_active_usage_player_blocks(self):
        manual = self.manual()
        manual["teams"][0]["primary_snapshot"]["players"][1]["unavailable"] = True
        with self.assertRaisesRegex(CFBPropManualDepthError, "PLAYER_UNAVAILABLE"):
            bind_manual_depth_to_live_features(
                live_features=self.features(), manual_input=manual, manual_bytes_sha256="c" * 64
            )

    def test_starter_conflict_blocks(self):
        manual = self.manual()
        manual["teams"][0]["corroboration"]["starter_player_ids"]["QB"] = "other-qb"
        with self.assertRaisesRegex(CFBPropManualDepthError, "STARTER_CONFLICT"):
            bind_manual_depth_to_live_features(
                live_features=self.features(), manual_input=manual, manual_bytes_sha256="c" * 64
            )

    def test_market_fields_are_forbidden_from_model_input(self):
        manual = self.manual()
        manual["teams"][0]["odds"] = -110
        with self.assertRaisesRegex(CFBPropManualDepthError, "MARKET_FIELD_FORBIDDEN"):
            bind_manual_depth_to_live_features(
                live_features=self.features(), manual_input=manual, manual_bytes_sha256="c" * 64
            )

    def test_depth_does_not_refresh_stale_numeric_usage_timestamp(self):
        features = self.features()
        features["asof_ts"] = "2026-09-11T12:00:00Z"
        out = bind_manual_depth_to_live_features(
            live_features=features, manual_input=self.manual(), manual_bytes_sha256="c" * 64
        )
        self.assertEqual(out["asof_ts"], "2026-09-11T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
