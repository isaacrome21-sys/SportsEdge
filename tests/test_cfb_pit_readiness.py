from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT
from sportsedge.sports.cfb.pit_readiness import (
    CFB_ASOF_AVAILABILITY_PROOF_CONTRACT,
    CFB_PAIRED_MARKET_EVIDENCE_CONTRACT,
    audit_cfb_pit_readiness,
)
from sportsedge.sports.cfb.source_manifest import CFB_PIT_SOURCE_MANIFEST_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
TRUTH_GATE = ROOT / "config" / "cfb_truth_gate_v1.json"


def _write_json(path: Path, payload: dict) -> bytes:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


class CFBPITReadinessTests(unittest.TestCase):
    def _build_ready_fixture(self, root: Path) -> dict[str, Path]:
        evidence_root = root / "evidence"
        evidence_root.mkdir()
        feature_bytes = b"historical feature snapshot\n"
        label_bytes = b"post-event labels\n"
        availability_bytes = b"archived availability proof\n"
        market_bytes = b"paired decision-close sportsbook rows\n"
        (evidence_root / "features.json").write_bytes(feature_bytes)
        (evidence_root / "labels.json").write_bytes(label_bytes)
        (evidence_root / "availability-proof.bin").write_bytes(availability_bytes)
        (evidence_root / "market-prices.csv").write_bytes(market_bytes)

        manifest = {
            "schema_version": CFB_PIT_SOURCE_MANIFEST_SCHEMA,
            "generated_at_utc": "2026-01-15T12:00:00+00:00",
            "fit_max_season": 2024,
            "training_window": {"min_season": 2022, "max_season": 2024},
            "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
            "feature_contract": CFB_FEATURE_CONTRACT,
            "post_cutoff_information_excluded": True,
            "market_data_used_as_model_feature": False,
            "sources": [
                {
                    "source_id": "features",
                    "role": "FEATURE_INPUT",
                    "provider": "fixture",
                    "dataset": "historical-features",
                    "locator": "fixture://features",
                    "snapshot_path": "features.json",
                    "retrieved_at_utc": "2026-01-15T10:00:00+00:00",
                    "content_sha256": sha256(feature_bytes).hexdigest(),
                    "availability_mode": "PRE_EVENT_ARCHIVE",
                    "availability_rule": "Archived before each target game.",
                    "market_data": False,
                    "post_cutoff_excluded": True,
                    "seasons": [2022, 2023, 2024],
                },
                {
                    "source_id": "labels",
                    "role": "LABEL",
                    "provider": "fixture",
                    "dataset": "final-labels",
                    "locator": "fixture://labels",
                    "snapshot_path": "labels.json",
                    "retrieved_at_utc": "2026-01-15T10:00:00+00:00",
                    "content_sha256": sha256(label_bytes).hexdigest(),
                    "availability_mode": "POST_EVENT_LABEL",
                    "availability_rule": "Final outcomes only; never predictive features.",
                    "market_data": False,
                    "post_cutoff_excluded": True,
                    "seasons": [2022, 2023, 2024],
                },
            ],
        }
        manifest_path = root / "cfb_pit_source_manifest.json"
        manifest_raw = _write_json(manifest_path, manifest)
        manifest_sha = sha256(manifest_raw).hexdigest()

        availability_path = root / "availability.json"
        _write_json(
            availability_path,
            {
                "contract": CFB_ASOF_AVAILABILITY_PROOF_CONTRACT,
                "source_manifest_sha256": manifest_sha,
                "as_of_game_proven": True,
                "evidence_files": [
                    {
                        "path": "availability-proof.bin",
                        "sha256": sha256(availability_bytes).hexdigest(),
                    }
                ],
            },
        )

        market_path = root / "market.json"
        _write_json(
            market_path,
            {
                "contract": CFB_PAIRED_MARKET_EVIDENCE_CONTRACT,
                "paired_decision_close_prices_proven": True,
                "decision_before_close_before_start": True,
                "same_paired_price_row": True,
                "markets": ["MONEYLINE", "SPREAD", "TOTAL"],
                "evidence_files": [
                    {
                        "path": "market-prices.csv",
                        "sha256": sha256(market_bytes).hexdigest(),
                    }
                ],
            },
        )

        current_release_path = root / "current_release_classification.json"
        _write_json(
            current_release_path,
            {
                "capture_classification": "CURRENT_HISTORICAL_RELEASE_NOT_POINT_IN_TIME",
                "point_in_time_as_of_game_proven": False,
                "promotion_evidence": False,
                "asset_count": 20,
            },
        )
        return {
            "evidence_root": evidence_root,
            "manifest": manifest_path,
            "availability": availability_path,
            "market": market_path,
            "current_release": current_release_path,
        }

    def test_missing_evidence_blocks_forward_clock(self) -> None:
        report = audit_cfb_pit_readiness(truth_gate_path=TRUTH_GATE)
        self.assertEqual(report["readiness_state"], "BLOCKED_EVIDENCE_INCOMPLETE")
        self.assertFalse(report["forward_clock_allowed"])
        self.assertFalse(report["historical_truth_gate_execution_allowed"])
        self.assertEqual(
            report["blockers"],
            [
                "ASOF_AVAILABILITY_PROOF_MISSING",
                "PAIRED_MARKET_EVIDENCE_MISSING",
                "PIT_SOURCE_MANIFEST_MISSING",
            ],
        )
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["eligibility_changed"])

    def test_current_release_capture_never_substitutes_for_pit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._build_ready_fixture(Path(tmp))
            report = audit_cfb_pit_readiness(
                truth_gate_path=TRUTH_GATE,
                current_release_classification_path=fixture["current_release"],
            )
        self.assertTrue(report["current_release"]["present"])
        self.assertFalse(report["current_release"]["usable_as_pit"])
        self.assertEqual(
            report["current_release"]["classification"],
            "CURRENT_HISTORICAL_RELEASE_NOT_POINT_IN_TIME",
        )
        self.assertFalse(report["forward_clock_allowed"])

    def test_hash_bound_pit_and_market_evidence_can_unlock_holdout_execution_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._build_ready_fixture(Path(tmp))
            report = audit_cfb_pit_readiness(
                truth_gate_path=TRUTH_GATE,
                current_release_classification_path=fixture["current_release"],
                pit_source_manifest_path=fixture["manifest"],
                availability_proof_path=fixture["availability"],
                paired_market_evidence_path=fixture["market"],
                evidence_root=fixture["evidence_root"],
            )
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["readiness_state"], "READY_FOR_REAL_HOLDOUT_EXECUTION")
        self.assertTrue(report["pit_source_manifest"]["source_snapshot_verified"])
        self.assertTrue(report["historical_truth_gate_execution_allowed"])
        self.assertTrue(report["forward_clock_allowed"])
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["model_p_created"])
        self.assertFalse(report["eligibility_changed"])

    def test_source_snapshot_hash_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._build_ready_fixture(Path(tmp))
            (fixture["evidence_root"] / "features.json").write_bytes(b"tampered\n")
            report = audit_cfb_pit_readiness(
                truth_gate_path=TRUTH_GATE,
                pit_source_manifest_path=fixture["manifest"],
                availability_proof_path=fixture["availability"],
                paired_market_evidence_path=fixture["market"],
                evidence_root=fixture["evidence_root"],
            )
        self.assertIn("PIT_SOURCE_SNAPSHOT_VERIFICATION_FAILED", report["blockers"])
        self.assertFalse(report["forward_clock_allowed"])

    def test_market_evidence_must_cover_all_frozen_markets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._build_ready_fixture(Path(tmp))
            payload = json.loads(fixture["market"].read_text())
            payload["markets"] = ["MONEYLINE", "SPREAD"]
            _write_json(fixture["market"], payload)
            report = audit_cfb_pit_readiness(
                truth_gate_path=TRUTH_GATE,
                pit_source_manifest_path=fixture["manifest"],
                availability_proof_path=fixture["availability"],
                paired_market_evidence_path=fixture["market"],
                evidence_root=fixture["evidence_root"],
            )
        self.assertIn("REQUIRED_MARKETS_NOT_COVERED", report["blockers"])
        self.assertFalse(report["forward_clock_allowed"])


if __name__ == "__main__":
    unittest.main()
