from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sportsedge.mlb_moneyline_forward_calibration import (
    MLBMoneylineForwardCalibrationError,
    settle_forward_calibration,
)


ARTIFACT = "a" * 64
PRIOR_ARTIFACT = "b" * 64


def prediction(game_pk: int = 1, *, leak: bool = False, artifact: str = ARTIFACT):
    start = datetime(2026, 9, 16, 20, tzinfo=timezone.utc)
    feature = start if leak else start - timedelta(minutes=50)
    return {
        "schema_version": "mlb_moneyline_forward_model_p_v2_production_parity",
        "evidence_disposition": "FORWARD_MODEL_P_PREDICTION",
        "promotion_authority": False,
        "market": "MONEYLINE",
        "game_pk": game_pk,
        "away_team_id": 10,
        "away_team": "Away",
        "home_team_id": 20,
        "home_team": "Home",
        "model_side": "HOME",
        "model_p": 0.60,
        "market_blind": True,
        "feature_asof_ts": feature.isoformat(),
        "event_start_ts": start.isoformat(),
        "prediction_generated_at_utc": (start - timedelta(minutes=45)).isoformat(),
        "model_artifact_sha256": artifact,
    }


def final_source(game_pk: int = 1):
    raw = b'{"final":true}'
    return {
        "settlement": {
            "game_pk": game_pk,
            "status": "FINAL",
            "away_team_id": 10,
            "home_team_id": 20,
            "away_score": 2,
            "home_score": 4,
        },
        "raw_bytes": raw,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_uri": f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk={game_pk}",
        "observed_at_utc": datetime(2026, 9, 17, 1, tzinfo=timezone.utc).isoformat(),
    }


class ForwardCalibrationTest(unittest.TestCase):
    def test_empty_clock_is_non_authoritative_and_accumulating(self):
        with TemporaryDirectory() as td, patch(
            "sportsedge.mlb_moneyline_forward_calibration.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ):
            root = Path(td)
            report = settle_forward_calibration(
                prediction_root=root / "pred",
                calibration_root=root / "cal",
                raw_root=root / "raw",
                report_path=root / "report.json",
                now=datetime(2026, 9, 17, tzinfo=timezone.utc),
                settlement_fetcher=lambda _: None,
            )
            self.assertEqual(report["completed_calibration_rows"], 0)
            self.assertEqual(report["calibration_metrics"]["n"], 0)
            self.assertFalse(report["promotion_authority"])

    def test_every_prospective_prediction_can_be_graded_without_market_data(self):
        with TemporaryDirectory() as td, patch(
            "sportsedge.mlb_moneyline_forward_calibration.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ):
            root = Path(td)
            pred = root / "pred" / "2026-09-16"
            pred.mkdir(parents=True)
            (pred / "game_1.json").write_text(
                json.dumps(prediction()) + "\n", encoding="utf-8"
            )
            report = settle_forward_calibration(
                prediction_root=root / "pred",
                calibration_root=root / "cal",
                raw_root=root / "raw",
                report_path=root / "report.json",
                now=datetime(2026, 9, 17, tzinfo=timezone.utc),
                settlement_fetcher=lambda _: final_source(),
            )
            self.assertEqual(report["completed_calibration_rows"], 1)
            self.assertEqual(report["calibration_metrics"]["n"], 1)
            self.assertFalse(report["calibration_metrics"]["sample_gate_pass"])
            self.assertFalse(report["promotion_authority"])
            rows = list((root / "cal").rglob("*.json"))
            self.assertEqual(len(rows), 1)
            text = rows[0].read_text(encoding="utf-8")
            self.assertNotIn("odds", text.lower())

    def test_equal_feature_asof_is_hard_pit_failure(self):
        with TemporaryDirectory() as td, patch(
            "sportsedge.mlb_moneyline_forward_calibration.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ):
            root = Path(td)
            pred = root / "pred"
            pred.mkdir(parents=True)
            (pred / "game_1.json").write_text(
                json.dumps(prediction(leak=True)) + "\n", encoding="utf-8"
            )
            with self.assertRaises(MLBMoneylineForwardCalibrationError):
                settle_forward_calibration(
                    prediction_root=pred,
                    calibration_root=root / "cal",
                    raw_root=root / "raw",
                    report_path=root / "report.json",
                    now=datetime(2026, 9, 17, tzinfo=timezone.utc),
                    settlement_fetcher=lambda _: final_source(),
                )

    def test_prior_artifact_predictions_are_retained_but_excluded_from_new_clock(self):
        with TemporaryDirectory() as td, patch(
            "sportsedge.mlb_moneyline_forward_calibration.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ):
            root = Path(td)
            pred = root / "pred"
            pred.mkdir(parents=True)
            stale = prediction(game_pk=9, artifact=PRIOR_ARTIFACT)
            stale["market_blind"] = False
            stale["feature_asof_ts"] = stale["event_start_ts"]
            (pred / "prior.json").write_text(
                json.dumps(stale) + "\n", encoding="utf-8"
            )
            (pred / "current.json").write_text(
                json.dumps(prediction()) + "\n", encoding="utf-8"
            )
            report = settle_forward_calibration(
                prediction_root=pred,
                calibration_root=root / "cal",
                raw_root=root / "raw",
                report_path=root / "report.json",
                now=datetime(2026, 9, 17, tzinfo=timezone.utc),
                settlement_fetcher=lambda game_pk: final_source(game_pk),
            )
            self.assertEqual(report["predictions_seen_current_artifact"], 1)
            self.assertEqual(report["prior_artifact_predictions_ignored"], 1)
            self.assertEqual(
                report["prior_prediction_artifact_sha256s"], [PRIOR_ARTIFACT]
            )
            self.assertEqual(report["calibration_metrics"]["n"], 1)
            self.assertEqual(
                report["clock_reset_rule"],
                "MODEL_ARTIFACT_SHA_CHANGE_RESETS_CURRENT_CALIBRATION_CLOCK",
            )

    def test_invalid_artifact_identity_never_silently_resets_clock(self):
        with TemporaryDirectory() as td, patch(
            "sportsedge.mlb_moneyline_forward_calibration.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ):
            root = Path(td)
            pred = root / "pred"
            pred.mkdir(parents=True)
            bad = prediction()
            bad["model_artifact_sha256"] = "not-a-sha"
            (pred / "bad.json").write_text(json.dumps(bad) + "\n", encoding="utf-8")
            with self.assertRaises(MLBMoneylineForwardCalibrationError):
                settle_forward_calibration(
                    prediction_root=pred,
                    calibration_root=root / "cal",
                    raw_root=root / "raw",
                    report_path=root / "report.json",
                    now=datetime(2026, 9, 17, tzinfo=timezone.utc),
                    settlement_fetcher=lambda _: final_source(),
                )


if __name__ == "__main__":
    unittest.main()
