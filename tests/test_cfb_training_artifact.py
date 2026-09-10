from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from sportsedge.sports.cfb.fit_policy import CFB_FIXED_RIDGE_POLICY_VERSION, CFB_RIDGE_POLICY_VERSION
from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.model_artifact import cfb_model_code_surface_sha256, load_cfb_model_artifact
from sportsedge.sports.cfb.training_artifact import (
    CFB_PIT_TRAINING_BUNDLE_SCHEMA,
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


def _metrics(offset: float) -> dict:
    return {key: float(index + 1) / 10.0 + offset for index, key in enumerate(TEAM_KEYS)}


def _bundle() -> dict:
    rows = []
    for season_index, season in enumerate((2022, 2023, 2024, 2025)):
        for i in range(24):
            offset = season_index * 24 + i
            rows.append({
                "game_id": f"{season}_{i:02d}_AWAY_HOME",
                "season": season,
                "week": (i % 12) + 1,
                "neutral_site": bool(i % 11 == 0),
                "home_metrics": _metrics(offset / 100.0),
                "away_metrics": _metrics((96 - offset) / 120.0),
                "weather": {"game_indoor": False, "wind_speed": 5.0 + (i % 4), "temperature": 65.0 + (i % 9)},
                "home_score": 17 + ((offset * 5) % 24),
                "away_score": 13 + ((offset * 3) % 20),
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


class CFBTrainingArtifactTests(unittest.TestCase):
    def test_valid_pit_bundle_selects_alpha_temporally_and_builds_runtime_loadable_artifact(self):
        bundle = _bundle()
        raw = _raw(bundle)
        artifact, provenance = build_cfb_artifact_from_pit_bundle(
            bundle,
            raw_bytes=raw,
            repo_root=ROOT,
            fit_max_season=2025,
        )
        self.assertEqual(provenance["row_count"], 96)
        self.assertEqual(provenance["train_seasons"], [2022, 2023, 2024, 2025])
        self.assertEqual(provenance["ridge_policy_version"], CFB_RIDGE_POLICY_VERSION)
        self.assertGreaterEqual(provenance["ridge_selection"]["fold_count"], 2)
        self.assertEqual(provenance["ridge_alpha"], provenance["ridge_selection"]["selected_alpha"])
        self.assertRegex(provenance["derivation_code_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(provenance["promotion_changed"])
        model = load_cfb_model_artifact(
            artifact,
            expected_model_code_sha256=cfb_model_code_surface_sha256(ROOT),
            expected_training_source_sha256=provenance["training_bundle_sha256"],
        )
        self.assertEqual(model.train_seasons, (2022, 2023, 2024, 2025))
        self.assertEqual(len(model.residual_pairs), 96)
        self.assertEqual(model.ridge_alpha, provenance["ridge_alpha"])

    def test_explicit_fixed_alpha_remains_labeled_and_does_not_run_temporal_selection(self):
        bundle = _bundle()
        artifact, provenance = build_cfb_artifact_from_pit_bundle(
            bundle,
            raw_bytes=_raw(bundle),
            repo_root=ROOT,
            fit_max_season=2025,
            ridge_alpha=7.5,
        )
        self.assertEqual(provenance["ridge_policy_version"], CFB_FIXED_RIDGE_POLICY_VERSION)
        self.assertEqual(provenance["ridge_alpha"], 7.5)
        self.assertEqual(provenance["ridge_selection"]["fold_count"], 0)
        self.assertEqual(artifact["model"]["ridge_alpha"], 7.5)

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

    def test_market_contamination_cannot_enter_fitted_artifact(self):
        bundle = _bundle()
        contaminated = deepcopy(bundle)
        contaminated["rows"][0]["home_metrics"]["spread_line"] = -3.5
        with self.assertRaisesRegex(CFBTrainingArtifactError, "CFB_MARKET_DATA_PROHIBITED"):
            build_cfb_artifact_from_pit_bundle(
                contaminated,
                raw_bytes=_raw(contaminated),
                repo_root=ROOT,
                fit_max_season=2025,
            )


if __name__ == "__main__":
    unittest.main()
