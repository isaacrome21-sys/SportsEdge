import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from scripts.run_cfb_auto import discover_cfb_week
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID, CFBJointScoreModel
from sportsedge.sports.cfb.model_artifact import (
    CFBModelArtifactError,
    build_cfb_model_artifact,
    load_cfb_model_artifact,
)
from sportsedge.sports.cfb.source import CFBGame


class CFBModelArtifactAndAutoCLITests(unittest.TestCase):
    def _model(self):
        return CFBJointScoreModel(
            model_id=CFB_JOINT_MODEL_ID,
            feature_contract=CFB_FEATURE_CONTRACT,
            feature_names=("a", "b"),
            feature_means=(0.0, 0.0),
            feature_scales=(1.0, 2.0),
            home_coefficients=(24.0, 1.0, -1.0),
            away_coefficients=(21.0, -1.0, 1.0),
            residual_pairs=((1.0, -1.0), (-2.0, 2.0)),
            overtime_deltas=((7, 0), (0, 7)),
            train_seasons=(2024, 2025),
            ridge_alpha=10.0,
        )

    def test_hash_bound_artifact_round_trip_and_tamper_rejection(self):
        artifact = build_cfb_model_artifact(
            self._model(),
            model_code_sha256="a" * 64,
            training_source_sha256="b" * 64,
        )
        loaded = load_cfb_model_artifact(
            artifact,
            expected_model_code_sha256="a" * 64,
            expected_training_source_sha256="b" * 64,
        )
        self.assertEqual(loaded, self._model())
        tampered = json.loads(json.dumps(artifact))
        tampered["model"]["home_coefficients"][0] = 999.0
        with self.assertRaisesRegex(CFBModelArtifactError, "CFB_MODEL_ARTIFACT_HASH_MISMATCH"):
            load_cfb_model_artifact(tampered)

    def test_model_code_identity_mismatch_fails_closed(self):
        artifact = build_cfb_model_artifact(
            self._model(),
            model_code_sha256="a" * 64,
            training_source_sha256="b" * 64,
        )
        with self.assertRaisesRegex(CFBModelArtifactError, "CFB_MODEL_CODE_SHA256_MISMATCH"):
            load_cfb_model_artifact(artifact, expected_model_code_sha256="c" * 64)

    def test_auto_week_discovery_uses_earliest_future_fbs_kickoff(self):
        def games(*, season, week, cfbd_api_key):
            self.assertEqual(season, 2026)
            self.assertEqual(cfbd_api_key, "key")
            if week == 1:
                return [CFBGame("old", 2026, 1, "2026-08-30T17:00:00+00:00", "A", "B", False)]
            if week == 2:
                return [CFBGame("next", 2026, 2, "2026-09-05T17:00:00+00:00", "C", "D", False)]
            if week == 3:
                return [CFBGame("later", 2026, 3, "2026-09-12T17:00:00+00:00", "E", "F", False)]
            return []

        from datetime import datetime, timezone
        week = discover_cfb_week(
            season=2026,
            now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
            cfbd_api_key="key",
            game_fetcher=games,
            max_week=3,
        )
        self.assertEqual(week, 2)

    def test_direct_cli_missing_artifact_is_explicit_blocker_without_network(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "card.json"
            env = dict(os.environ)
            env["SPORTSEDGE_CFBD_API_KEY"] = "fake"
            env["SPORTSEDGE_ODDS_API_KEY"] = "fake"
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_cfb_auto.py",
                    "--season", "2026",
                    "--week", "1",
                    "--model-artifact", str(Path(tmp) / "missing.json"),
                    "--output", str(out),
                ],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertEqual(payload["blocker"], "CFB_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
            self.assertFalse(payload["governance"]["model_fit_performed"])
            self.assertFalse(payload["governance"]["promotion_changed"])


if __name__ == "__main__":
    unittest.main()
