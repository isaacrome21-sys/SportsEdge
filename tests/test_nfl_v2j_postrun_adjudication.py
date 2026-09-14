from __future__ import annotations

import copy
import unittest

from scripts.adjudicate_nfl_v2j_postrun import adjudicate


class NFLV2JPostrunAdjudicationTests(unittest.TestCase):
    def _policy(self) -> dict:
        return {
            "policy_id": "NFL_V2J_POSTRUN_ADJUDICATION_V1",
            "status": "FROZEN_PRE_READOUT",
            "frozen_gates": {
                "spread_fold_win_rate_min": 0.65,
                "total_fold_win_rate_min": 0.65,
                "spread_calibration_max_bin_deviation": 0.05,
                "total_calibration_max_bin_deviation": 0.05,
                "signed_key_max_abs_error": 0.005,
                "signed_keys": [-7, -3, 3, 7],
                "all_required": True,
            },
            "authority": {
                "model_p_authority": False,
                "promotion_authority": False,
                "staking_authority": False,
                "official_authority": False,
                "production_registry_authority": False,
                "nfl_m2_freeze_authorized": False,
                "v2k_automatically_activated": False,
            },
        }

    def _readout(self) -> dict:
        calibration = {
            "threshold": 0.05,
            "pass": True,
            "reason": "PASS",
        }
        return {
            "status": "FIRST_READOUT_DIAGNOSTIC_ONLY",
            "preregistration_locked": True,
            "post_readout_retuning_allowed": False,
            "promotion_eligible": False,
            "promotion_authority": False,
            "model_p_authority": False,
            "official_status_granted": False,
            "production_registry_consumes_this_artifact": False,
            "candidate_historical_evidence": {
                "spread": {
                    "fold_win_rate": 4 / 6,
                    "required_fold_win_rate": 0.65,
                    "historical_predictive_pass": True,
                    "calibration": copy.deepcopy(calibration),
                },
                "total": {
                    "fold_win_rate": 5 / 6,
                    "required_fold_win_rate": 0.65,
                    "historical_predictive_pass": True,
                    "calibration": copy.deepcopy(calibration),
                },
            },
        }

    def _key_math(self) -> dict:
        return {
            "status": "FIRST_READOUT_DIAGNOSTIC_ONLY",
            "promotion_eligible": False,
            "promotion_authority": False,
            "model_p_authority": False,
            "official_status_granted": False,
            "production_registry_consumes_this_artifact": False,
            "fit": {
                "pass": True,
                "max_abs_error": 0.005,
                "per_key": {},
            },
        }

    def _adjudicate(
        self,
        readout: dict | None = None,
        key_math: dict | None = None,
        policy: dict | None = None,
    ) -> dict:
        return adjudicate(
            readout or self._readout(),
            key_math or self._key_math(),
            policy or self._policy(),
            upstream_run_id=123,
            upstream_head_sha="1" * 40,
            adjudicator_git_sha="2" * 40,
            first_readout_sha256="3" * 64,
            key_math_sha256="4" * 64,
            policy_sha256="5" * 64,
        )

    def test_all_frozen_gates_pass_but_authority_stays_false(self) -> None:
        result = self._adjudicate()
        self.assertEqual(result["verdict"], "V2J_FROZEN_GATES_PASS_ZERO_AUTHORITY")
        self.assertTrue(result["frozen_gate_pass"])
        self.assertFalse(result["candidate_rejected_by_frozen_gates"])
        self.assertFalse(result["nfl_m2_freeze_authorized"])
        self.assertFalse(result["v2k_automatically_activated"])
        for field in (
            "model_p_authority",
            "promotion_authority",
            "staking_authority",
            "official_authority",
            "production_registry_authority",
        ):
            self.assertFalse(result[field])

    def test_historical_failure_is_a_zero_authority_frozen_gate_failure(self) -> None:
        readout = self._readout()
        readout["candidate_historical_evidence"]["spread"].update({
            "fold_win_rate": 0.50,
            "historical_predictive_pass": False,
        })
        result = self._adjudicate(readout=readout)
        self.assertEqual(result["verdict"], "V2J_FROZEN_GATES_FAIL_ZERO_AUTHORITY")
        self.assertFalse(result["frozen_gate_pass"])
        self.assertTrue(result["candidate_rejected_by_frozen_gates"])
        self.assertFalse(result["v2k_automatically_activated"])

    def test_key_failure_is_not_silently_ignored(self) -> None:
        key_math = self._key_math()
        key_math["fit"]["pass"] = False
        result = self._adjudicate(key_math=key_math)
        self.assertEqual(result["verdict"], "V2J_FROZEN_GATES_FAIL_ZERO_AUTHORITY")
        self.assertFalse(result["signed_key_gate_pass"])
        self.assertFalse(result["frozen_gate_pass"])

    def test_threshold_drift_fails_closed(self) -> None:
        readout = self._readout()
        readout["candidate_historical_evidence"]["spread"]["required_fold_win_rate"] = 0.60
        with self.assertRaisesRegex(ValueError, "FOLD_THRESHOLD_DRIFT"):
            self._adjudicate(readout=readout)

    def test_policy_drift_fails_closed(self) -> None:
        policy = self._policy()
        policy["frozen_gates"]["signed_key_max_abs_error"] = 0.01
        with self.assertRaisesRegex(ValueError, "POLICY_THRESHOLD_DRIFT"):
            self._adjudicate(policy=policy)

    def test_authority_escalation_fails_closed(self) -> None:
        readout = self._readout()
        readout["promotion_authority"] = True
        with self.assertRaisesRegex(ValueError, "READOUT_AUTHORITY_INVALID"):
            self._adjudicate(readout=readout)


if __name__ == "__main__":
    unittest.main()
