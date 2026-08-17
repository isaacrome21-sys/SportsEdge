import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sportsedge.generic_card_pipeline import _feature_index, run_generic_card
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.orchestrator import run_candidate as real_run_candidate

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def lineup_rows(start):
    return [{"player_id": start + i, "slot": i + 1, "sequence": 0} for i in range(9)]


def frozen_game():
    snap = GameSnapshot(
        game_pk=777,
        game_date="2026-08-10T23:00:00Z",
        status="Preview",
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="Away SP",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="Home SP",
        retrieved_at="2026-08-10T19:59:00+00:00",
    )
    return make_live_game(snap, lineup_rows(100), lineup_rows(200))


def frozen_feature():
    return {
        "game_pk": 777,
        "entity_id": "777",
        "market": "TOTALS",
        "away_mean_runs": 4.1,
        "home_mean_runs": 4.6,
        "source_subset_hash": "fixture-v1",
    }


def frozen_quote(side, odds):
    return {
        "game_id": "777",
        "period": "FG",
        "market": "TOTALS",
        "entity_id": "777",
        "line": 8.5,
        "side": side,
        "american_odds": odds,
        "book_key": "draftkings",
        "is_alternate": False,
        "raw_market_name": "Game Total",
        "retrieved_at": "2026-08-10T19:59:00Z",
        "ttl_seconds": 300,
    }


def write_registry(path):
    path.write_text(json.dumps({
        "schema_version": 1,
        "markets": {
            "TOTALS": {"eligible": True, "stage": "DEPLOYED", "reason": "frozen-fixture-ci"}
        },
    }))


def write_floors(path):
    path.write_text(json.dumps({
        "truth_gate": {
            "schema_version": 1,
            "production": {
                "fail_closed": True,
                "allow_cli_floor_override": False,
                "require_frozen_floor_for_eligible_market": True,
            },
            "edge_floors": {
                "TOTALS": {
                    "status": "FROZEN",
                    "value_probability_points": 0.01,
                    "method_version": "fixture-ci-v1",
                    "evidence": {
                        "evidence_sha256": "fixture-evidence-sha256",
                        "derivation_code_sha256": "fixture-derivation-sha256",
                        "oos_cutoff_utc": "2026-08-09T00:00:00Z",
                    },
                    "frozen": {"frozen_by_commit": "fixture-ci"},
                }
            },
        }
    }))


class MLBFixtureFullPipelineTests(unittest.TestCase):
    def test_identical_feature_reuse_is_idempotent_but_conflict_still_fails_closed(self):
        row = frozen_feature()
        indexed = _feature_index([row, dict(row)])
        self.assertEqual(list(indexed), [("777", "777", "TOTALS")])

        conflict = dict(row)
        conflict["away_mean_runs"] = 9.9
        with self.assertRaisesRegex(ValueError, "conflicting generic feature identity"):
            _feature_index([row, conflict])

    def test_frozen_totals_fixture_executes_model_mc_ev_kelly_and_truth_gate_for_both_sides(self):
        features = [frozen_feature(), frozen_feature()]
        quotes = [frozen_quote("OVER", -110), frozen_quote("UNDER", -110)]
        captured = []

        def capture_candidate(**kwargs):
            result = real_run_candidate(**kwargs)
            captured.append(result)
            return result

        with tempfile.TemporaryDirectory() as td:
            registry = Path(td) / "deployments.json"
            floors = Path(td) / "floors.json"
            write_registry(registry)
            write_floors(floors)
            with patch("sportsedge.generic_card_pipeline.run_candidate", side_effect=capture_candidate):
                results = run_generic_card(
                    games=[frozen_game()],
                    feature_rows=features,
                    quotes=quotes,
                    ingestion_now=NOW,
                    finalization_now=NOW,
                    registry_path=str(registry),
                    edge_floor_config_path=str(floors),
                    kelly_multiplier=0.25,
                )

        self.assertEqual(len(results), 2)
        self.assertEqual({r.side for r in results}, {"OVER", "UNDER"})
        self.assertTrue(all(r.model_p is not None for r in results))
        self.assertTrue(all(r.implied_probability is not None for r in results))
        self.assertTrue(all(r.edge is not None for r in results))
        self.assertTrue(all(r.ev_per_dollar is not None for r in results))
        self.assertFalse(any("duplicate generic feature identity" in r.reason for r in results))

        self.assertEqual(len(captured), 2)
        self.assertTrue(all(r.decision is not None for r in captured))
        self.assertTrue(all(r.decision.model_status == "MODEL_OK" for r in captured))
        self.assertTrue(all(r.decision.kelly_fraction >= 0.0 for r in captured))
        self.assertTrue(all(r.bet_status in {"PASS", "OFFICIAL_BET"} for r in captured))


if __name__ == "__main__":
    unittest.main()
