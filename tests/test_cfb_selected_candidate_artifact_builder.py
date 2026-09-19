from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from scripts.build_cfb_selected_candidate_artifact import (
    CFBSelectedCandidateBuildError,
    build_from_inputs,
)
from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS
from sportsedge.sports.cfb.candidate_registry_v2 import BLEND

ROOT = Path(__file__).resolve().parents[1]


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _metrics(season: int, through_week: int, source: str, value: float, games: int):
    out = {key: float(value + idx * 0.002) for idx, key in enumerate(TEAM_METRIC_KEYS)}
    out.update({
        "team": "T",
        "season": season,
        "through_week": through_week,
        "sample_source": source,
        "games_in_sample": games,
    })
    return out


def _row(i: int):
    season = 2015 + (i % 11)
    week = 1 if i < 4 else 3 + (i % 6)
    games = max(0, week - 1)
    prior_h = _metrics(season - 1, 99, "PRIOR_SEASON_FALLBACK", 0.10 + i * 0.001, 0)
    prior_a = _metrics(season - 1, 99, "PRIOR_SEASON_FALLBACK", 0.15 + i * 0.001, 0)
    if week == 1:
        current_h = copy.deepcopy(prior_h)
        current_a = copy.deepcopy(prior_a)
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


class TestCFBSelectedCandidateArtifactBuilder(unittest.TestCase):
    def setUp(self):
        self.rows = [_row(i) for i in range(40)]
        rows_sha = _hash(self.rows)
        self.bundle = {
            "selection_rows_sha256": rows_sha,
            "source_manifest_sha256": "a" * 64,
            "predictive_code_manifest_sha256": "b" * 64,
            "acquisition_code_manifest_sha256": "c" * 64,
        }
        self.result = {
            "schema": "CFB_CANDIDATE_BAKEOFF_RESULT_V2",
            "status": "WINNER_SELECTED_FOR_FREEZE",
            "winner": BLEND,
            "input_identity": dict(self.bundle),
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
        self.result["result_sha256"] = _hash(self.result)
        self.policy = json.loads((ROOT / "config/cfb_selected_candidate_final_fit_policy_v1.json").read_text())

    def test_builds_hash_bound_zero_authority_model_proposal(self):
        artifact, attestation = build_from_inputs(
            rows=self.rows,
            bundle=self.bundle,
            result=self.result,
            policy=self.policy,
            repo_root=ROOT,
        )
        self.assertEqual(artifact["candidate_family"], BLEND)
        self.assertEqual(artifact["model"]["ridge_alpha"], 10.0)
        self.assertTrue(artifact["model"]["overtime_deltas"])
        self.assertTrue(all(value is False for value in artifact["authority"].values()))
        self.assertEqual(attestation["status"], "MODEL_PROPOSAL_BUILT_ZERO_AUTHORITY")
        self.assertEqual(attestation["final_alpha_source_season"], 2025)
        self.assertEqual(attestation["final_ridge_alpha"], 10.0)
        self.assertTrue(all(value is False for value in attestation["authority"].values()))

    def test_rejects_post_bakeoff_result_tamper(self):
        tampered = copy.deepcopy(self.result)
        tampered["observed"][BLEND]["folds"][-1]["alpha"] = 300.0
        with self.assertRaisesRegex(CFBSelectedCandidateBuildError, "RESULT_HASH_MISMATCH"):
            build_from_inputs(
                rows=self.rows,
                bundle=self.bundle,
                result=tampered,
                policy=self.policy,
                repo_root=ROOT,
            )

    def test_rejects_missing_overtime_profile(self):
        no_ot = copy.deepcopy(self.rows)
        no_ot[0].pop("regulation_home_score", None)
        no_ot[0].pop("regulation_away_score", None)
        rows_sha = _hash(no_ot)
        bundle = dict(self.bundle)
        bundle["selection_rows_sha256"] = rows_sha
        result = copy.deepcopy(self.result)
        result["rows_sha256"] = rows_sha
        result["input_identity"] = dict(bundle)
        result.pop("result_sha256", None)
        result["result_sha256"] = _hash(result)
        with self.assertRaisesRegex(CFBSelectedCandidateBuildError, "OVERTIME_PROFILE_EMPTY"):
            build_from_inputs(
                rows=no_ot,
                bundle=bundle,
                result=result,
                policy=self.policy,
                repo_root=ROOT,
            )


if __name__ == "__main__":
    unittest.main()
