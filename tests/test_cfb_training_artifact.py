from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT
from sportsedge.sports.cfb.model_artifact import cfb_model_code_surface_sha256, load_cfb_model_artifact
from sportsedge.sports.cfb.source_manifest import CFB_PIT_SOURCE_MANIFEST_SCHEMA
from sportsedge.sports.cfb.training_artifact import (
    CFB_PIT_TRAINING_BUNDLE_SCHEMA,
    CFB_TRAINING_FEATURE_SEMANTICS,
    CFBTrainingArtifactError,
    build_cfb_artifact_from_pit_bundle,
    validate_cfb_pit_training_bundle,
)

ROOT = Path(__file__).resolve().parents[1]

TEAM_KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
    "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
    "net_field_position", "explosive_rate",
)


def _metrics(offset: float, *, season: int, game_week: int) -> dict:
    values = {key: float(index + 1) / 10.0 + offset for index, key in enumerate(TEAM_KEYS)}
    if game_week == 1:
        values.update({
            "season": season - 1,
            "through_week": 99,
            "sample_source": "PRIOR_SEASON_FALLBACK",
            "feature_asof_ts": f"{season}-08-01T12:00:00+00:00",
        })
    else:
        values.update({
            "season": season,
            "through_week": game_week - 1,
            "sample_source": "CURRENT_SEASON_PRIOR_WEEKS",
            "feature_asof_ts": f"{season}-09-01T12:00:00+00:00",
        })
    return values


def _bundle() -> dict:
    rows = []
    for i in range(20):
        week = (i % 12) + 1
        rows.append({
            "game_id": f"2025_{i:02d}_AWAY_HOME",
            "season": 2025,
            "week": week,
            "neutral_site": False,
            "home_metrics": _metrics(i / 100.0, season=2025, game_week=week),
            "away_metrics": _metrics((20 - i) / 120.0, season=2025, game_week=week),
            "weather": {"game_indoor": False, "wind_speed": 5.0 + (i % 4), "temperature": 65.0 + (i % 9)},
            "home_score": 17 + (i % 18),
            "away_score": 13 + ((i * 3) % 20),
        })
    return {
        "schema_version": CFB_PIT_TRAINING_BUNDLE_SCHEMA,
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
        "source_manifest_sha256": "a" * 64,
        "generated_at_utc": "2026-01-15T12:00:00+00:00",
        "rows": rows,
    }


def _raw(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _bound_source_evidence(root: Path) -> tuple[dict, bytes]:
    feature_bytes = b"features"
    label_bytes = b"labels"
    (root / "features.json").write_bytes(feature_bytes)
    (root / "labels.json").write_bytes(label_bytes)
    manifest = {
        "schema_version": CFB_PIT_SOURCE_MANIFEST_SCHEMA,
        "generated_at_utc": "2026-01-15T11:00:00+00:00",
        "fit_max_season": 2025,
        "training_window": {"min_season": 2025, "max_season": 2025},
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
        "feature_contract": CFB_FEATURE_CONTRACT,
        "post_cutoff_information_excluded": True,
        "market_data_used_as_model_feature": False,
        "sources": [
            {
                "source_id": "features",
                "role": "FEATURE_INPUT",
                "provider": "fixture-provider",
                "dataset": "fixture-features",
                "locator": "fixture://features",
                "snapshot_path": "features.json",
                "retrieved_at_utc": "2026-01-15T10:00:00+00:00",
                "content_sha256": sha256(feature_bytes).hexdigest(),
                "availability_mode": "EVENT_TIMESTAMPED_REPLAY",
                "availability_rule": "Fixture PIT features only.",
                "market_data": False,
                "post_cutoff_excluded": True,
                "seasons": [2025],
            },
            {
                "source_id": "labels",
                "role": "LABEL",
                "provider": "fixture-provider",
                "dataset": "fixture-labels",
                "locator": "fixture://labels",
                "snapshot_path": "labels.json",
                "retrieved_at_utc": "2026-01-15T10:00:00+00:00",
                "content_sha256": sha256(label_bytes).hexdigest(),
                "availability_mode": "POST_EVENT_LABEL",
                "availability_rule": "Final-score labels only.",
                "market_data": False,
                "post_cutoff_excluded": True,
                "seasons": [2025],
            },
        ],
    }
    return manifest, _raw(manifest)


class CFBTrainingArtifactTests(unittest.TestCase):
    def test_valid_pit_bundle_builds_runtime_loadable_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence_root = Path(temp)
            manifest, manifest_raw = _bound_source_evidence(evidence_root)
            bundle = _bundle()
            bundle["source_manifest_sha256"] = sha256(manifest_raw).hexdigest()
            raw = _raw(bundle)
            artifact, provenance = build_cfb_artifact_from_pit_bundle(
                bundle,
                raw_bytes=raw,
                source_manifest=manifest,
                source_manifest_raw_bytes=manifest_raw,
                source_evidence_root=evidence_root,
                repo_root=ROOT,
                fit_max_season=2025,
                ridge_alpha=10.0,
            )
            self.assertEqual(provenance["row_count"], 20)
            self.assertEqual(provenance["train_seasons"], [2025])
            self.assertEqual(provenance["feature_semantics"], CFB_TRAINING_FEATURE_SEMANTICS)
            self.assertTrue(provenance["source_snapshot_verified"])
            self.assertEqual(provenance["verified_source_count"], 2)
            self.assertEqual(provenance["ridge_fit_policy"]["mode"], "FIXED_MANUAL")
            self.assertEqual(len(provenance["derivation_code_sha256"]), 64)
            self.assertFalse(provenance["promotion_changed"])
            model = load_cfb_model_artifact(
                artifact,
                expected_model_code_sha256=cfb_model_code_surface_sha256(ROOT),
                expected_training_source_sha256=provenance["training_bundle_sha256"],
            )
            self.assertEqual(model.train_seasons, (2025,))
            self.assertEqual(len(model.residual_pairs), 20)

    def test_wrong_materializer_identity_is_rejected(self):
        bundle = _bundle()
        bundle["materializer_version"] = "CFB_UNSAFE_EX_POST_V0"
        with self.assertRaisesRegex(CFBTrainingArtifactError, "MATERIALIZER_MISMATCH"):
            validate_cfb_pit_training_bundle(bundle, raw_bytes=_raw(bundle), fit_max_season=2025)

    def test_duplicate_game_is_rejected(self):
        bundle = _bundle()
        bundle["rows"][1]["game_id"] = bundle["rows"][0]["game_id"]
        with self.assertRaisesRegex(CFBTrainingArtifactError, "GAME_DUPLICATE"):
            validate_cfb_pit_training_bundle(bundle, raw_bytes=_raw(bundle), fit_max_season=2025)

    def test_future_season_is_rejected(self):
        bundle = _bundle()
        bundle["rows"][0]["season"] = 2026
        with self.assertRaisesRegex(CFBTrainingArtifactError, "FUTURE_SEASON_FORBIDDEN"):
            validate_cfb_pit_training_bundle(bundle, raw_bytes=_raw(bundle), fit_max_season=2025)

    def test_full_season_aggregate_cannot_masquerade_as_pit_materializer(self):
        bundle = _bundle()
        row = bundle["rows"][5]
        self.assertGreater(row["week"], 1)
        row["home_metrics"].update({
            "through_week": 99,
            "sample_source": "CURRENT_SEASON_PRIOR_WEEKS",
        })
        with self.assertRaisesRegex(CFBTrainingArtifactError, "ASOF_WEEK_FEATURE_SEMANTICS_MISMATCH"):
            validate_cfb_pit_training_bundle(bundle, raw_bytes=_raw(bundle), fit_max_season=2025)

    def test_week1_requires_prior_season_fallback(self):
        bundle = _bundle()
        row = bundle["rows"][0]
        self.assertEqual(row["week"], 1)
        row["away_metrics"].update({
            "season": 2025,
            "through_week": 0,
            "sample_source": "CURRENT_SEASON_PRIOR_WEEKS",
        })
        with self.assertRaisesRegex(CFBTrainingArtifactError, "WEEK1_FEATURE_SEMANTICS_MISMATCH"):
            validate_cfb_pit_training_bundle(bundle, raw_bytes=_raw(bundle), fit_max_season=2025)

    def test_market_contamination_cannot_enter_fitted_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence_root = Path(temp)
            manifest, manifest_raw = _bound_source_evidence(evidence_root)
            bundle = _bundle()
            bundle["source_manifest_sha256"] = sha256(manifest_raw).hexdigest()
            contaminated = deepcopy(bundle)
            contaminated["rows"][0]["home_metrics"]["spread_line"] = -3.5
            with self.assertRaisesRegex(CFBTrainingArtifactError, "CFB_MARKET_DATA_PROHIBITED"):
                build_cfb_artifact_from_pit_bundle(
                    contaminated,
                    raw_bytes=_raw(contaminated),
                    source_manifest=manifest,
                    source_manifest_raw_bytes=manifest_raw,
                    source_evidence_root=evidence_root,
                    repo_root=ROOT,
                    fit_max_season=2025,
                    ridge_alpha=10.0,
                )


if __name__ == "__main__":
    unittest.main()
