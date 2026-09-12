import json
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT
from sportsedge.sports.cfb.source_manifest import CFB_PIT_SOURCE_MANIFEST_SCHEMA
from sportsedge.sports.cfb.training_artifact import CFB_PIT_TRAINING_BUNDLE_SCHEMA


TEAM_KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
    "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
    "net_field_position", "explosive_rate",
)


def _metrics(offset: float, *, season: int, week: int) -> dict:
    metrics = {key: (i + 1) / 10.0 + offset for i, key in enumerate(TEAM_KEYS)}
    if week == 1:
        metrics.update({
            "season": season - 1,
            "through_week": 99,
            "sample_source": "PRIOR_SEASON_FALLBACK",
        })
    else:
        metrics.update({
            "season": season,
            "through_week": week - 1,
            "sample_source": "CURRENT_SEASON_PRIOR_WEEKS",
        })
    return metrics


def _row(season: int, index: int) -> dict:
    week = index + 1
    return {
        "game_id": f"{season}_{index}",
        "season": season,
        "week": week,
        "neutral_site": False,
        "home_metrics": _metrics(index / 100.0, season=season, week=week),
        "away_metrics": _metrics((index + 5) / 110.0, season=season, week=week),
        "weather": {"game_indoor": False, "wind_speed": 7.0, "temperature": 68.0},
        "home_score": 20 + (index % 10),
        "away_score": 14 + ((index * 2) % 10),
    }


class TestCFBOOSProvenanceRunner(unittest.TestCase):
    def test_runner_binds_bundle_manifest_and_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "features.json").write_bytes(b"features")
            (evidence / "labels.json").write_bytes(b"labels")
            fit_max = 2025
            manifest = {
                "schema_version": CFB_PIT_SOURCE_MANIFEST_SCHEMA,
                "generated_at_utc": "2026-09-01T00:00:00+00:00",
                "fit_max_season": fit_max,
                "training_window": {"min_season": 2024, "max_season": fit_max},
                "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
                "feature_contract": CFB_FEATURE_CONTRACT,
                "post_cutoff_information_excluded": True,
                "market_data_used_as_model_feature": False,
                "sources": [
                    {"source_id": "features", "role": "FEATURE_INPUT", "provider": "fixture", "dataset": "features",
                     "locator": "fixture://features", "snapshot_path": "features.json", "retrieved_at_utc": "2026-09-01T00:00:00+00:00",
                     "content_sha256": sha256(b"features").hexdigest(), "availability_mode": "EVENT_TIMESTAMPED_REPLAY",
                     "availability_rule": "fixture", "market_data": False, "post_cutoff_excluded": True, "seasons": [2024, 2025]},
                    {"source_id": "labels", "role": "LABEL", "provider": "fixture", "dataset": "labels",
                     "locator": "fixture://labels", "snapshot_path": "labels.json", "retrieved_at_utc": "2026-09-01T00:00:00+00:00",
                     "content_sha256": sha256(b"labels").hexdigest(), "availability_mode": "POST_EVENT_LABEL",
                     "availability_rule": "fixture", "market_data": False, "post_cutoff_excluded": True, "seasons": [2024, 2025]},
                ],
            }
            manifest_raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
            manifest_path = root / "manifest.json"
            manifest_path.write_bytes(manifest_raw)
            rows = [_row(2024, i) for i in range(24)] + [_row(2025, i) for i in range(12)]
            bundle = {
                "schema_version": CFB_PIT_TRAINING_BUNDLE_SCHEMA,
                "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
                "source_manifest_sha256": sha256(manifest_raw).hexdigest(),
                "generated_at_utc": "2026-09-01T00:00:00+00:00",
                "rows": rows,
            }
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            out = root / "out.json"
            cmd = [sys.executable, "scripts/validate_cfb_oos.py", "--training-bundle", str(bundle_path),
                   "--source-manifest", str(manifest_path), "--source-evidence-root", str(evidence),
                   "--fit-max-season", "2025", "--output", str(out)]
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "RESEARCH_ONLY_NOT_PROMOTION_EVIDENCE")
            self.assertTrue(payload["source_snapshot_verified"])
            self.assertFalse(payload["governance"]["promotion_changed"])
            self.assertFalse(payload["governance"]["model_p_created"])
            self.assertFalse(payload["governance"]["calibration_evidence"])

            (evidence / "features.json").write_bytes(b"tampered")
            blocked = subprocess.run(cmd, check=False, capture_output=True, text=True)
            self.assertEqual(blocked.returncode, 2)
            blocked_payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(blocked_payload["status"], "BLOCKED")
            self.assertIn("SNAPSHOT_SHA256_MISMATCH:features", blocked_payload["blocker"])


if __name__ == "__main__":
    unittest.main()
