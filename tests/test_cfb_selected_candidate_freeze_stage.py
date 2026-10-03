from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_cfb_selected_candidate_artifact import build_from_inputs
from scripts.stage_cfb_selected_candidate_freeze import (
    CFBSelectedFreezeStageError,
    stage,
)
from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS
from sportsedge.sports.cfb.candidate_registry_v2 import BLEND
from sportsedge.sports.cfb.reconstructed_selection import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]


def _hash(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _metrics(season: int, week: int, source: str, value: float, games: int):
    row = {key: float(value + i * 0.002) for i, key in enumerate(TEAM_METRIC_KEYS)}
    row.update({
        "team": "T",
        "season": season,
        "through_week": week,
        "sample_source": source,
        "games_in_sample": games,
    })
    return row


def _row(i: int):
    season = 2015 + (i % 11)
    week = 1 if i < 4 else 3 + (i % 6)
    prior_h = _metrics(season - 1, 99, "PRIOR_SEASON_FALLBACK", 0.10 + i * 0.001, 0)
    prior_a = _metrics(season - 1, 99, "PRIOR_SEASON_FALLBACK", 0.15 + i * 0.001, 0)
    games = max(0, week - 1)
    if week == 1:
        current_h, current_a = copy.deepcopy(prior_h), copy.deepcopy(prior_a)
    else:
        current_h = _metrics(season, week - 1, "CURRENT_SEASON_PRIOR_WEEKS", 0.20 + i * 0.003, games)
        current_a = _metrics(season, week - 1, "CURRENT_SEASON_PRIOR_WEEKS", 0.18 + i * 0.002, games)
    row = {
        "season": season,
        "week": week,
        "neutral_site": bool(i % 7 == 0),
        "weather": {"game_indoor": True},
        "home_metrics": copy.deepcopy(current_h),
        "away_metrics": copy.deepcopy(current_a),
        "home_prior_metrics": prior_h,
        "away_prior_metrics": prior_a,
        "home_current_metrics": current_h,
        "away_current_metrics": current_a,
        "home_score": 20 + (i * 7) % 31,
        "away_score": 13 + (i * 5) % 28,
    }
    if i == 0:
        row.update({
            "regulation_home_score": 24,
            "regulation_away_score": 24,
            "home_score": 31,
            "away_score": 24,
        })
    return row


class TestCFBSelectedCandidateFreezeStage(unittest.TestCase):
    def _inputs(self, root: Path):
        rows = [_row(i) for i in range(44)]
        source_manifest = {
            "schema": "CFB_RECONSTRUCTED_SOURCE_MANIFEST_TEST",
            "responses": [{
                "endpoint": "/stats/season/advanced",
                "season": 2025,
                "end_week": 15,
                "provider_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
                "query_sha256": "1" * 64,
                "response_sha256": "2" * 64,
                "retrieved_at_utc": "2026-10-03T00:00:00+00:00",
            }],
        }
        rows_sha = _hash(rows)
        source_sha = canonical_sha256(source_manifest)
        bundle = {
            "schema": "CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1",
            "status": "READY_FOR_CANDIDATE_EVALUATION",
            "selection_rows_sha256": rows_sha,
            "source_manifest_sha256": source_sha,
            "predictive_code_manifest_sha256": "b" * 64,
            "acquisition_code_manifest_sha256": "c" * 64,
            "feature_semantics": "AS_OF_WEEK_MATCHED_V1",
            "feature_value_source_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
        }
        result = {
            "schema": "CFB_CANDIDATE_BAKEOFF_RESULT_V2",
            "status": "WINNER_SELECTED_FOR_FREEZE",
            "winner": BLEND,
            "input_identity": {
                key: bundle[key] for key in (
                    "selection_rows_sha256",
                    "source_manifest_sha256",
                    "predictive_code_manifest_sha256",
                    "acquisition_code_manifest_sha256",
                )
            },
            "rows_sha256": rows_sha,
            "observed": {
                BLEND: {
                    "selection_metric": 12.0,
                    "folds": [
                        {"season": 2024, "rows": 10, "alpha": 30.0, "rmse": 12.2},
                        {"season": 2025, "rows": 10, "alpha": 10.0, "rmse": 11.8},
                    ],
                }
            },
            "authority": {
                "model_p_created": False,
                "truth_gate_authority": False,
                "promotion_authority": False,
                "eligibility_changed": False,
                "staking_authority": False,
                "evidence_clock_authority": False,
                "backfill": False,
                "official_authority": False,
            },
        }
        result["result_sha256"] = _hash(result)
        policy = json.loads((ROOT / "config/cfb_selected_candidate_final_fit_policy_v1.json").read_text())
        proposal, attestation = build_from_inputs(
            rows=rows,
            bundle=bundle,
            result=result,
            policy=policy,
            repo_root=ROOT,
        )
        acquisition = {
            "schema": "CFB_RECONSTRUCTED_ACQUISITION_READINESS_PUBLIC_V1",
            "status": "ACQUISITION_COMPLETE_READY_FOR_SELECTION",
            "source_manifest_sha256": source_sha,
            "authority": {"official": False, "promotion": False},
        }

        paths = {}
        payloads = {
            "proposal": proposal,
            "attestation": attestation,
            "bundle": bundle,
            "source": source_manifest,
            "acquisition": acquisition,
            "result": result,
        }
        for name, payload in payloads.items():
            path = root / f"{name}.json"
            text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            path.write_text(text)
            paths[name] = path
        attestation["model_artifact_file_sha256"] = sha256(paths["proposal"].read_bytes()).hexdigest()
        paths["attestation"].write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
        return paths

    def test_stages_exact_artifact_registry_and_public_freeze_evidence(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            p = self._inputs(root)
            result = stage(
                proposal_path=p["proposal"],
                attestation_path=p["attestation"],
                selection_bundle_path=p["bundle"],
                source_manifest_path=p["source"],
                acquisition_manifest_path=p["acquisition"],
                bakeoff_result_path=p["result"],
                artifact_output=root / "models/cfb_joint_v1.json",
                registry_output=root / "config/cfb_game_model_freeze.json",
                evidence_output=root / "config/cfb_selected_candidate_freeze_evidence_v1.json",
                repo_root=ROOT,
            )
            registry = json.loads((root / "config/cfb_game_model_freeze.json").read_text())
            evidence = json.loads((root / "config/cfb_selected_candidate_freeze_evidence_v1.json").read_text())
            self.assertEqual(result["status"], "FREEZE_PR_BYTES_STAGED")
            self.assertEqual(registry["status"], "FROZEN")
            self.assertEqual(registry["model_family"], "CFB_SELECTED_CANDIDATE_MODEL_V1")
            self.assertEqual(registry["selection_result_sha256"], json.loads(p["result"].read_text())["result_sha256"])
            self.assertFalse(registry["promotion_authority"])
            self.assertFalse(registry["evidence_clock_authority"])
            self.assertEqual(evidence["status"], "READY_FOR_SEPARATE_MAIN_FREEZE_COMMIT")
            self.assertEqual(
                (root / "models/cfb_joint_v1.json").read_bytes(),
                p["proposal"].read_bytes(),
            )

    def test_source_manifest_tamper_fails_closed(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            p = self._inputs(root)
            source = json.loads(p["source"].read_text())
            source["responses"][0]["response_sha256"] = "9" * 64
            p["source"].write_text(json.dumps(source, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(CFBSelectedFreezeStageError, "SOURCE_MANIFEST_HASH_MISMATCH"):
                stage(
                    proposal_path=p["proposal"],
                    attestation_path=p["attestation"],
                    selection_bundle_path=p["bundle"],
                    source_manifest_path=p["source"],
                    acquisition_manifest_path=p["acquisition"],
                    bakeoff_result_path=p["result"],
                    artifact_output=root / "model.json",
                    registry_output=root / "freeze.json",
                    evidence_output=root / "evidence.json",
                    repo_root=ROOT,
                )


if __name__ == "__main__":
    unittest.main()
