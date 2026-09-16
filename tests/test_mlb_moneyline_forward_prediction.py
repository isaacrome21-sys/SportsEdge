from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from sportsedge.mlb_moneyline_forward_prediction import (
    MLBMoneylineForwardPredictionBlocked,
    MLBMoneylineForwardPredictionError,
    build_forward_prediction,
    capture_due_predictions,
)


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
            artifact_sha="a" * 64, simulations=2000,
        )
        self.assertEqual(out["market"], "MONEYLINE")
        self.assertIs(out["market_blind"], True)
        self.assertEqual(out["model_side"], "HOME")
        self.assertEqual(out["reference_side_policy"], "FIXED_HOME_REFERENCE_NO_MARKET_SELECTION")
        self.assertTrue(0 < out["model_p"] < 1)
        self.assertLess(datetime.fromisoformat(out["feature_asof_ts"]), start)
        self.assertIs(out["promotion_authority"], False)
        self.assertIn("odds", out["forbidden_market_inputs"])
        self.assertEqual(out["feature_observation_count"], 24)
        self.assertEqual(len(out["feature_observations"]), 24)

    def test_prediction_after_start_fails_closed(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        with self.assertRaisesRegex(MLBMoneylineForwardPredictionError, "precede"):
            build_forward_prediction(
                snapshot=snapshot(now), history=FakeHistory(now), now=now,
                artifact_sha="a" * 64, simulations=2000,
            )

    def test_insufficient_history_blocks_due_game(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        start = now + timedelta(minutes=50)
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(MLBMoneylineForwardPredictionBlocked, "BLOCKED_DUE_MODEL_P"):
                capture_due_predictions(
                    schedule=[snapshot(start)], history=FakeHistory(now, n=9), now=now,
                    output_dir=tmp, artifact_sha="a" * 64, simulations=2000,
                )

    def test_capture_is_create_only_and_only_inside_window(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        due = snapshot(now + timedelta(minutes=50), 123)
        later = snapshot(now + timedelta(minutes=90), 456)
        with TemporaryDirectory() as tmp:
            first = capture_due_predictions(
                schedule=[due, later], history=FakeHistory(now), now=now,
                output_dir=tmp, artifact_sha="a" * 64, simulations=2000,
            )
            self.assertEqual(first["status"], "RETAINED")
            self.assertEqual(first["games_due"], 1)
            self.assertEqual(first["predictions_retained"], 1)
            path = Path(first["paths"][0])
            before = path.read_bytes()
            second = capture_due_predictions(
                schedule=[due, later], history=FakeHistory(now), now=now,
                output_dir=tmp, artifact_sha="a" * 64, simulations=2000,
            )
            self.assertEqual(second["status"], "ALREADY_CAPTURED")
            self.assertEqual(path.read_bytes(), before)

    def test_no_due_game_is_green_but_non_authoritative(self):
        now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            out = capture_due_predictions(
                schedule=[snapshot(now + timedelta(minutes=90))], history=FakeHistory(now), now=now,
                output_dir=tmp, artifact_sha="a" * 64, simulations=2000,
            )
            self.assertEqual(out["status"], "NO_PREDICTION_DUE")
            self.assertIs(out["promotion_authority"], False)


if __name__ == "__main__":
    unittest.main()
