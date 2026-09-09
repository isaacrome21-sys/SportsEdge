from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.football_prop_run_machine import (
    FootballPropRunError,
    canonical_hash,
    run_football_props,
)


class FootballPropRunMachineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 9, 16, 0, tzinfo=timezone.utc)
        self.start = self.now + timedelta(hours=2)
        self.code_sha = "a" * 40
        profile = {
            "pass_rate": 0.57,
            "completion_rate": 0.64,
            "success_rate": 0.45,
            "explosive_rate": 0.10,
            "turnover_rate": 0.018,
            "sack_rate": 0.06,
            "field_goal_attempt_rate": 0.82,
            "field_goal_skill": 0.84,
            "pace_seconds_mean": 31.0,
        }
        self.artifact = {
            "schema_version": "FOOTBALL_PROP_MODEL_ARTIFACT_V1",
            "sport": "NFL",
            "artifact_version": "fixture-v1",
            "code_git_sha": self.code_sha,
            "source_manifest_sha256": "b" * 64,
            "team_drive_profiles": {"H": dict(profile), "A": dict(profile)},
        }
        self.artifact_sha = canonical_hash(self.artifact)

        def player(pid, name, team, pos, *, snap, route, target, rush, rz, active=True):
            return {
                "player_id": pid, "player_name": name, "team": team,
                "position": pos, "active": active, "snap_share": snap,
                "route_participation": route, "target_share": target,
                "rush_share": rush, "red_zone_share": rz,
            }

        self.features = {
            "schema_version": "FOOTBALL_PROP_LIVE_FEATURES_V1",
            "sport": "NFL",
            "asof_ts": (self.now - timedelta(minutes=1)).isoformat(),
            "source_manifest_sha256": "c" * 64,
            "games": [{
                "game_id": "g1",
                "game_start_ts": self.start.isoformat(),
                "home_team": "H", "away_team": "A",
                "provider_home_team": "Home Team",
                "provider_away_team": "Away Team",
                "provider_event_id": "evt1",
                "home_usage": {
                    "quarterback_id": "H-QB",
                    "players": [
                        player("H-QB", "Home Quarterback", "H", "QB", snap=1.0, route=0.0, target=0.0, rush=0.20, rz=0.30),
                        player("H-RB", "Home Runner", "H", "RB", snap=0.75, route=0.55, target=0.20, rush=0.80, rz=0.60),
                        player("H-WR", "Home Receiver", "H", "WR", snap=0.90, route=0.95, target=0.80, rush=0.0, rz=0.40),
                    ],
                },
                "away_usage": {
                    "quarterback_id": "A-QB",
                    "players": [
                        player("A-QB", "Away Quarterback", "A", "QB", snap=1.0, route=0.0, target=0.0, rush=0.20, rz=0.30),
                        player("A-RB", "Away Runner", "A", "RB", snap=0.75, route=0.55, target=0.20, rush=0.80, rz=0.60),
                        player("A-WR", "Away Receiver", "A", "WR", snap=0.90, route=0.95, target=0.80, rush=0.0, rz=0.40),
                    ],
                },
            }],
        }
        self.odds = self._odds(line=100.5)

    def _odds(self, *, line: float, update: datetime | None = None):
        observed = update or (self.now - timedelta(seconds=20))
        return {
            "schema_version": "FOOTBALL_PROP_ODDS_SNAPSHOT_V1",
            "observed_at": observed.isoformat(),
            "events": [{
                "id": "evt1",
                "home_team": "Home Team", "away_team": "Away Team",
                "commence_time": self.start.isoformat(),
                "bookmakers": [{
                    "key": "draftkings", "title": "DraftKings",
                    "markets": [{
                        "key": "player_pass_yds",
                        "last_update": observed.isoformat(),
                        "outcomes": [
                            {"name": "Over", "description": "Home Quarterback", "price": -110, "point": line},
                            {"name": "Under", "description": "Home Quarterback", "price": -110, "point": line},
                        ],
                    }],
                }],
            }],
        }

    def _run(self, **overrides):
        kwargs = {
            "sport": "NFL",
            "now": self.now,
            "artifact_payload": self.artifact,
            "expected_artifact_sha256": self.artifact_sha,
            "runtime_code_git_sha": self.code_sha,
            "live_features": self.features,
            "odds_snapshot": self.odds,
            "root_seed": 17,
            "n_paths": 24,
        }
        kwargs.update(overrides)
        return run_football_props(**kwargs)

    def test_prices_from_shared_distribution_but_promotes_nothing(self):
        report = self._run()
        self.assertEqual(report["run_status"], "BLOCKED_PROMOTION_EVIDENCE_REQUIRED")
        self.assertEqual(len(report["results"]), 2)
        self.assertEqual(report["summary"]["official_bets"], 0)
        self.assertTrue(all(row["bet_status"] == "BLOCKED" for row in report["results"]))
        self.assertTrue(all(isinstance(row["model_p"], float) for row in report["results"]))
        self.assertTrue(all(row["reason"] == "NFL_PROP_PROMOTION_EVIDENCE_REQUIRED" for row in report["results"]))
        self.assertEqual(len({row["distribution_sha256"] for row in report["results"]}), 1)
        self.assertTrue(report["governance"]["model_market_firewall"])
        self.assertFalse(report["governance"]["sportsbook_used_to_create_model_p"])

    def test_market_line_change_does_not_change_underlying_distribution(self):
        first = self._run()
        second = self._run(odds_snapshot=self._odds(line=125.5))
        self.assertEqual(
            first["game_distribution_sha256"]["g1"],
            second["game_distribution_sha256"]["g1"],
        )

    def test_independent_artifact_hash_mismatch_blocks(self):
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_MODEL_ARTIFACT_SHA256_MISMATCH"):
            self._run(expected_artifact_sha256="d" * 64)

    def test_code_git_binding_blocks(self):
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_MODEL_CODE_GIT_SHA_MISMATCH"):
            self._run(runtime_code_git_sha="e" * 40)

    def test_game_must_still_be_pregame(self):
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_GAME_NOT_PREGAME:g1"):
            self._run(now=self.start)

    def test_feature_snapshot_must_be_pregame(self):
        features = deepcopy(self.features)
        features["asof_ts"] = self.start.isoformat()
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_FEATURE_SNAPSHOT_NOT_PREGAME:g1"):
            self._run(live_features=features, now=self.start - timedelta(minutes=1))

    def test_feature_snapshot_must_be_fresh(self):
        features = deepcopy(self.features)
        features["asof_ts"] = (self.now - timedelta(hours=3)).isoformat()
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_LIVE_FEATURE_SNAPSHOT_STALE"):
            self._run(live_features=features)

    def test_quote_must_be_strictly_before_kickoff(self):
        odds = self._odds(line=100.5, update=self.start)
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_QUOTE_FROM_FUTURE"):
            self._run(odds_snapshot=odds)
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_QUOTE_NOT_PREGAME:g1"):
            self._run(odds_snapshot=odds, now=self.start + timedelta(seconds=1))

    def test_stale_quote_retains_model_but_no_market_economics(self):
        odds = self._odds(line=100.5, update=self.now - timedelta(minutes=10))
        report = self._run(odds_snapshot=odds)
        for row in report["results"]:
            self.assertIsInstance(row["model_p"], float)
            self.assertIsNone(row["fair_market_p"])
            self.assertIsNone(row["edge"])
            self.assertEqual(row["reason"], "NFL_PROP_QUOTE_STALE")

    def test_unresolved_participation_blocks(self):
        features = deepcopy(self.features)
        del features["games"][0]["home_usage"]["players"][0]["active"]
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_PARTICIPATION_UNRESOLVED:H-QB"):
            self._run(live_features=features)

    def test_same_machine_supports_cfb_without_market_contamination(self):
        artifact = deepcopy(self.artifact)
        artifact["sport"] = "CFB"
        features = deepcopy(self.features)
        features["sport"] = "CFB"
        report = self._run(
            sport="CFB",
            artifact_payload=artifact,
            expected_artifact_sha256=canonical_hash(artifact),
            live_features=features,
        )
        self.assertEqual(report["sport"], "CFB")
        self.assertTrue(all(row["reason"] == "CFB_PROP_PROMOTION_EVIDENCE_REQUIRED" for row in report["results"]))


if __name__ == "__main__":
    unittest.main()
