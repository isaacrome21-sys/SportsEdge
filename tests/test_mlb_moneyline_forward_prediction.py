from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.mlb_moneyline_forward_prediction import (
    MLBMoneylineForwardPredictionBlocked,
    MLBMoneylineForwardPredictionError,
    PRODUCTION_ENGINE_DISPATCH,
    build_forward_prediction,
    capture_due_predictions,
    production_moneyline_model_input,
)
from sportsedge.shared_game_engine import V8_PRIMARY_GAME_MIN_SIMULATIONS


class FakeHistory:
    def __init__(self, retrieved_at, n=12):
        self.retrieved_at = retrieved_at
        self.n = n

    def team_rows(self, *, team_id, target_date):
        base = 3 if int(team_id) == 10 else 4
        return [
            {"date": target_date - timedelta(days=self.n - i), "stat": {"runs": base + (i % 3)}}
            for i in range(self.n)
        ]


def snapshot(start, game_pk=123):
    return SimpleNamespace(
        game_pk=game_pk,
        game_date=start.isoformat(),
        status="Preview",
        away_id=10,
        away_name="Away Club",
        home_id=20,
        home_name="Home Club",
        official_date=start.date().isoformat(),
    )


class ForwardPredictionTest(unittest.TestCase):
    def test_build_prediction_is_market_blind_fixed_home_reference(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        start = now + timedelta(minutes=50)
        out = build_forward_prediction(
            snapshot=snapshot(start), history=FakeHistory(now), now=now,
            artifact_sha="a" * 64, simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
        )
        self.assertEqual(out["market"], "MONEYLINE")
        self.assertIs(out["market_blind"], True)
        self.assertEqual(out["model_side"], "HOME")
        self.assertEqual(out["reference_side_policy"], "FIXED_HOME_REFERENCE_NO_MARKET_SELECTION")
        self.assertEqual(out["production_engine_dispatch"], PRODUCTION_ENGINE_DISPATCH)
        self.assertTrue(0 < out["model_p"] < 1)
        self.assertEqual(datetime.fromisoformat(out["feature_asof_ts"]), now)
        self.assertEqual(datetime.fromisoformat(out["prediction_generated_at_utc"]), now)
        self.assertLess(datetime.fromisoformat(out["feature_asof_ts"]), start)
        self.assertIs(out["promotion_authority"], False)
        self.assertIn("odds", out["forbidden_market_inputs"])
        self.assertEqual(out["feature_observation_count"], 24)
        self.assertEqual(len(out["feature_observations"]), 24)
        self.assertEqual(out["source_timestamp_semantics"], "POST_RESPONSE_RECEIPT_TIME_CONSERVATIVE")
        self.assertEqual(out["mc_paths"], V8_PRIMARY_GAME_MIN_SIMULATIONS)
        self.assertEqual(len(out["distribution_sha256"]), 64)
        self.assertEqual(len(out["readout_sha256"]), 64)

    def test_forward_probability_is_exact_canonical_registry_probability(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        start = now + timedelta(minutes=50)
        out = build_forward_prediction(
            snapshot=snapshot(start, 789), history=FakeHistory(now), now=now,
            artifact_sha="a" * 64, simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
        )
        model_input = production_moneyline_model_input(
            game_pk=out["game_pk"],
            away_mean_runs=out["away_mean_runs"],
            home_mean_runs=out["home_mean_runs"],
            feature_source_hash=out["feature_source_hash"],
            simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS,
        )
        live = engine_registry()["MONEYLINE"](model_input)
        self.assertEqual(out["model_p"], live["model_p"])
        self.assertEqual(out["model_input_hash"], live["model_input_hash"])
        self.assertEqual(out["distribution_sha256"], live["distribution_sha256"])
        self.assertEqual(out["readout_sha256"], live["readout_sha256"])
        self.assertEqual(out["engine_version"], live["engine_version"])
        self.assertEqual(out["seed_policy"], live["seed_policy"])
        self.assertEqual(out["mc_paths"], live["mc_paths"])

    def test_production_floor_cannot_be_reduced_by_forward_lane(self):
        with self.assertRaisesRegex(MLBMoneylineForwardPredictionError, "production parity"):
            production_moneyline_model_input(
                game_pk=123,
                away_mean_runs=4.0,
                home_mean_runs=4.2,
                feature_source_hash="f" * 64,
                simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS - 1,
            )

    def test_prediction_after_start_fails_closed(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        with self.assertRaisesRegex(MLBMoneylineForwardPredictionError, "precede"):
            build_forward_prediction(
                snapshot=snapshot(now), history=FakeHistory(now), now=now,
                artifact_sha="a" * 64, simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
            )

    def test_insufficient_history_blocks_due_game(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        start = now + timedelta(minutes=50)
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(MLBMoneylineForwardPredictionBlocked, "BLOCKED_DUE_MODEL_P"):
                capture_due_predictions(
                    schedule=[snapshot(start)], history=FakeHistory(now, n=9), now=now,
                    output_dir=tmp, artifact_sha="a" * 64,
                    simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
                )

    def test_capture_is_create_only_and_only_inside_window(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        due = snapshot(now + timedelta(minutes=50), 123)
        later = snapshot(now + timedelta(minutes=90), 456)
        with TemporaryDirectory() as tmp:
            first = capture_due_predictions(
                schedule=[due, later], history=FakeHistory(now), now=now,
                output_dir=tmp, artifact_sha="a" * 64,
                simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
            )
            self.assertEqual(first["status"], "RETAINED")
            self.assertEqual(first["games_due"], 1)
            self.assertEqual(first["predictions_retained"], 1)
            path = Path(first["paths"][0])
            before = path.read_bytes()
            second = capture_due_predictions(
                schedule=[due, later], history=FakeHistory(now), now=now,
                output_dir=tmp, artifact_sha="a" * 64,
                simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
            )
            self.assertEqual(second["status"], "ALREADY_CAPTURED")
            self.assertEqual(path.read_bytes(), before)

    def test_no_due_game_is_green_but_non_authoritative(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            out = capture_due_predictions(
                schedule=[snapshot(now + timedelta(minutes=90))], history=FakeHistory(now), now=now,
                output_dir=tmp, artifact_sha="a" * 64,
                simulations=V8_PRIMARY_GAME_MIN_SIMULATIONS, clock=lambda: now,
            )
            self.assertEqual(out["status"], "NO_PREDICTION_DUE")
            self.assertIs(out["promotion_authority"], False)


if __name__ == "__main__":
    unittest.main()
