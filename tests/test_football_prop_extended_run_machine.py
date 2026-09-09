from __future__ import annotations

from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.football_prop_extended_run_machine import run_football_extended_props
from sportsedge.football_prop_run_machine import FootballPropRunError, canonical_hash


class FootballPropExtendedRunMachineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 9, 16, 0, tzinfo=timezone.utc)
        self.start = self.now + timedelta(hours=2)
        self.code_sha = "a" * 40
        drive = {
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
        st = {
            "fg_base_skill": 0.86,
            "xp_make_rate": 0.94,
            "two_point_attempt_rate": 0.02,
            "two_point_success_rate": 0.48,
        }
        self.artifact = {
            "schema_version": "FOOTBALL_PROP_MODEL_ARTIFACT_V1",
            "sport": "NFL",
            "artifact_version": "fixture-v2",
            "code_git_sha": self.code_sha,
            "source_manifest_sha256": "b" * 64,
            "team_drive_profiles": {"H": dict(drive), "A": dict(drive)},
            "team_special_teams_rates": {"H": dict(st), "A": dict(st)},
        }
        self.artifact_sha = canonical_hash(self.artifact)

        def offense(pid, name, team, pos, snap, route, target, rush, rz):
            return {
                "player_id": pid,
                "player_name": name,
                "team": team,
                "position": pos,
                "active": True,
                "snap_share": snap,
                "route_participation": route,
                "target_share": target,
                "rush_share": rush,
                "red_zone_share": rz,
            }

        def defender(pid, name, team, pos, tackle, assist, sack, interception):
            return {
                "player_id": pid,
                "player_name": name,
                "team": team,
                "position": pos,
                "active": True,
                "snap_share": 0.95,
                "tackle_share": tackle,
                "assist_share": assist,
                "sack_share": sack,
                "interception_share": interception,
            }

        self.features = {
            "schema_version": "FOOTBALL_PROP_LIVE_FEATURES_V1",
            "sport": "NFL",
            "asof_ts": (self.now - timedelta(minutes=1)).isoformat(),
            "source_manifest_sha256": "c" * 64,
            "games": [{
                "game_id": "g1",
                "game_start_ts": self.start.isoformat(),
                "home_team": "H",
                "away_team": "A",
                "provider_home_team": "Home Team",
                "provider_away_team": "Away Team",
                "provider_event_id": "evt1",
                "weather": {"wind_mph": 5.0, "roof_closed": False},
                "home_kicker": {"player_id": "H-K", "player_name": "Home Kicker", "active": True},
                "away_kicker": {"player_id": "A-K", "player_name": "Away Kicker", "active": True},
                "tackle_settlement_provider": "fixture-official-stats",
                "home_usage": {
                    "quarterback_id": "H-QB",
                    "players": [
                        offense("H-QB", "Home Quarterback", "H", "QB", 1.0, 0.0, 0.0, 0.20, 0.30),
                        offense("H-RB", "Home Runner", "H", "RB", 0.80, 0.60, 0.25, 0.80, 0.60),
                        offense("H-WR", "Home Receiver", "H", "WR", 0.95, 0.98, 0.75, 0.0, 0.50),
                    ],
                },
                "away_usage": {
                    "quarterback_id": "A-QB",
                    "players": [
                        offense("A-QB", "Away Quarterback", "A", "QB", 1.0, 0.0, 0.0, 0.20, 0.30),
                        offense("A-RB", "Away Runner", "A", "RB", 0.80, 0.60, 0.25, 0.80, 0.60),
                        offense("A-WR", "Away Receiver", "A", "WR", 0.95, 0.98, 0.75, 0.0, 0.50),
                    ],
                },
                "home_defense": {
                    "assist_probability": 0.45,
                    "players": [
                        defender("H-D1", "Home Defender", "H", "LB", 0.7, 0.7, 0.7, 0.5),
                        defender("H-D2", "Home Safety", "H", "S", 0.3, 0.3, 0.3, 0.5),
                    ],
                },
                "away_defense": {
                    "assist_probability": 0.45,
                    "players": [
                        defender("A-D1", "Away Defender", "A", "LB", 0.7, 0.7, 0.7, 0.5),
                        defender("A-D2", "Away Safety", "A", "S", 0.3, 0.3, 0.3, 0.5),
                    ],
                },
            }],
        }
        self.odds = self._odds()

    def _market(self, key, outcomes):
        return {
            "key": key,
            "last_update": (self.now - timedelta(seconds=20)).isoformat(),
            "outcomes": outcomes,
        }

    def _odds(self, pass_td_line=1.5):
        return {
            "schema_version": "FOOTBALL_PROP_ODDS_SNAPSHOT_V1",
            "observed_at": (self.now - timedelta(seconds=20)).isoformat(),
            "events": [{
                "id": "evt1",
                "home_team": "Home Team",
                "away_team": "Away Team",
                "commence_time": self.start.isoformat(),
                "bookmakers": [{
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        self._market("player_pass_tds", [
                            {"name": "Over", "description": "Home Quarterback", "price": -110, "point": pass_td_line},
                            {"name": "Under", "description": "Home Quarterback", "price": -110, "point": pass_td_line},
                        ]),
                        self._market("player_rush_tds", [
                            {"name": "Over", "description": "Home Runner", "price": 115, "point": 0.5},
                            {"name": "Under", "description": "Home Runner", "price": -135, "point": 0.5},
                        ]),
                        self._market("player_field_goals", [
                            {"name": "Over", "description": "Home Kicker", "price": -105, "point": 1.5},
                            {"name": "Under", "description": "Home Kicker", "price": -115, "point": 1.5},
                        ]),
                        self._market("player_sacks", [
                            {"name": "Over", "description": "Home Defender", "price": 120, "point": 0.5},
                            {"name": "Under", "description": "Home Defender", "price": -140, "point": 0.5},
                        ]),
                        self._market("player_tackles_assists", [
                            {"name": "Over", "description": "Home Defender", "price": -110, "point": 5.5},
                            {"name": "Under", "description": "Home Defender", "price": -110, "point": 5.5},
                        ]),
                        # Deliberately YES-only: model probability is allowed,
                        # but no-vig fair probability/edge may not be invented.
                        self._market("player_anytime_td", [
                            {"name": "Yes", "description": "Home Runner", "price": 140},
                        ]),
                    ],
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
            "root_seed": 23,
            "n_paths": 32,
        }
        kwargs.update(overrides)
        return run_football_extended_props(**kwargs)

    def test_offense_kicker_defense_and_scorer_share_one_distribution(self):
        report = self._run()
        families = {row["family"] for row in report["results"]}
        self.assertEqual(families, {"OFFENSE", "KICKER", "DEFENSE", "SCORER"})
        self.assertEqual(report["summary"]["official_bets"], 0)
        self.assertTrue(all(row["bet_status"] == "BLOCKED" for row in report["results"]))
        self.assertEqual(len({row["distribution_sha256"] for row in report["results"]}), 1)
        self.assertTrue(all(isinstance(row["model_p"], float) for row in report["results"]))
        self.assertTrue(report["governance"]["single_shared_engine_a_path_per_game"])
        self.assertTrue(report["governance"]["kicker_engine_c_on_shared_path"])
        self.assertTrue(report["governance"]["defense_engine_b_on_shared_path"])

    def test_frozen_policy_changes_prices_without_changing_model_distribution(self):
        baseline = self._run()
        policy = json.loads(Path('config/truth_gate_floors.json').read_text())
        policy['truth_gate']['devig_policy']['haircut_probability_points'] = '0.01'
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'floors.json'
            path.write_text(json.dumps(policy))
            changed = self._run(floor_path=str(path))
        self.assertEqual(baseline['game_distribution_sha256'], changed['game_distribution_sha256'])
        for before, after in zip(baseline['results'], changed['results']):
            self.assertEqual(before['model_p'], after['model_p'])
            if before['fair_market_p'] is not None:
                self.assertAlmostEqual(after['fair_market_p'] - before['fair_market_p'], 0.01)
                self.assertAlmostEqual(before['edge'] - after['edge'], 0.01)
            self.assertFalse(after['official_eligible'])

    def test_one_sided_anytime_td_never_invents_opposite_price_or_edge(self):
        report = self._run()
        row = next(row for row in report["results"] if row["provider_market"] == "player_anytime_td")
        self.assertIsInstance(row["model_p"], float)
        self.assertFalse(row["paired_price_available"])
        self.assertIsNone(row["fair_market_p"])
        self.assertIsNone(row["edge"])
        self.assertIsNone(row["ev_per_dollar"])
        self.assertEqual(row["reason"], "NFL_PROP_PAIRED_PRICE_REQUIRED")
        self.assertFalse(report["governance"]["one_sided_market_opposite_price_invented"])

    def test_td_market_line_change_cannot_change_underlying_distribution(self):
        first = self._run()
        second = self._run(odds_snapshot=self._odds(pass_td_line=2.5))
        self.assertEqual(first["game_distribution_sha256"], second["game_distribution_sha256"])

    def test_tackle_market_requires_explicit_settlement_provider(self):
        features = deepcopy(self.features)
        del features["games"][0]["tackle_settlement_provider"]
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_TACKLE_SETTLEMENT_PROVIDER_REQUIRED"):
            self._run(live_features=features)

    def test_kicker_market_requires_artifact_bound_special_team_rates(self):
        artifact = deepcopy(self.artifact)
        del artifact["team_special_teams_rates"]
        with self.assertRaisesRegex(FootballPropRunError, "FOOTBALL_PROP_SPECIAL_TEAMS_RATES_REQUIRED"):
            self._run(
                artifact_payload=artifact,
                expected_artifact_sha256=canonical_hash(artifact),
            )


if __name__ == "__main__":
    unittest.main()
