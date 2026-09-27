import copy
import unittest

from sportsedge.sports.nfl.attempt9_model_p import (
    CALIBRATION_CONTRACT,
    CANDIDATE_ID,
    MODEL_P_ID,
    MODEL_P_SCHEMA,
    MODEL_P_STATUS,
    canonical_sha256,
    fit_isotonic_blocks,
    model_probability,
    verify_model_p_artifact,
)
from sportsedge.truth_gate import decide_bet


class NFLAttempt9ModelPTests(unittest.TestCase):
    def _artifact(self):
        artifact = {
            "schema_version": MODEL_P_SCHEMA,
            "status": MODEL_P_STATUS,
            "model_p_id": MODEL_P_ID,
            "candidate_id": CANDIDATE_ID,
            "code_git_sha": "1" * 40,
            "runtime_artifact_sha256": "a" * 64,
            "source_sha256": "b" * 64,
            "calibration_fit": {
                "contract": CALIBRATION_CONTRACT,
                "seasons": [2017, 2018, 2019],
                "role": "SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE",
            },
            "markets": {
                "spread": {
                    "sigma": 13.8,
                    "calibration_blocks": [
                        {"lo": 0.0, "hi": 0.40, "weight": 200, "mean": 0.30},
                        {"lo": 0.40, "hi": 0.60, "weight": 300, "mean": 0.50},
                        {"lo": 0.60, "hi": 1.00, "weight": 200, "mean": 0.70},
                    ],
                },
                "total": {
                    "sigma": 14.0,
                    "calibration_blocks": [
                        {"lo": 0.0, "hi": 0.45, "weight": 200, "mean": 0.35},
                        {"lo": 0.45, "hi": 0.55, "weight": 300, "mean": 0.50},
                        {"lo": 0.55, "hi": 1.00, "weight": 200, "mean": 0.65},
                    ],
                },
            },
            "authority": {
                "creates_model_p": True,
                "historical_fit_promotion_authority": False,
                "deployed": False,
                "truth_gate_pass": False,
                "official_authority": False,
                "staking_authority": False,
            },
        }
        artifact["artifact_sha256"] = canonical_sha256(artifact)
        return artifact

    def test_serialized_artifact_creates_model_p_but_zero_promotion_authority(self):
        artifact = self._artifact()
        verify_model_p_artifact(artifact)
        self.assertTrue(artifact["authority"]["creates_model_p"])
        self.assertFalse(artifact["authority"]["historical_fit_promotion_authority"])
        self.assertFalse(artifact["authority"]["deployed"])
        self.assertFalse(artifact["authority"]["official_authority"])

    def test_noninteger_spread_produces_model_p_and_opposite_side_complements(self):
        artifact = self._artifact()
        home = model_probability(
            artifact, market="spread", raw_prediction=10.0, line=-3.5, selection="home"
        )
        away = model_probability(
            artifact, market="spread", raw_prediction=10.0, line=-3.5, selection="away"
        )
        self.assertEqual(home["model_p_id"], MODEL_P_ID)
        self.assertGreater(home["model_p"], 0.5)
        self.assertAlmostEqual(home["model_p"] + away["model_p"], 1.0, places=10)
        self.assertEqual(home["push_probability"], 0.0)
        self.assertFalse(home["deployed"])
        self.assertFalse(home["official_authority"])

    def test_total_model_p_uses_market_threshold_not_odds(self):
        artifact = self._artifact()
        over = model_probability(
            artifact, market="total", raw_prediction=52.0, line=45.5, selection="over"
        )
        under = model_probability(
            artifact, market="total", raw_prediction=52.0, line=45.5, selection="under"
        )
        self.assertGreater(over["model_p"], 0.5)
        self.assertAlmostEqual(over["model_p"] + under["model_p"], 1.0, places=10)

    def test_integer_line_fails_closed_until_push_mass_is_validated(self):
        artifact = self._artifact()
        with self.assertRaisesRegex(
            ValueError, "NFL_ATTEMPT9_MODEL_P_PUSH_MODEL_REQUIRED_FOR_INTEGER_LINE"
        ):
            model_probability(
                artifact, market="spread", raw_prediction=4.0, line=-3.0, selection="home"
            )
        with self.assertRaisesRegex(
            ValueError, "NFL_ATTEMPT9_MODEL_P_PUSH_MODEL_REQUIRED_FOR_INTEGER_LINE"
        ):
            model_probability(
                artifact, market="total", raw_prediction=44.0, line=44.0, selection="over"
            )

    def test_artifact_cannot_self_promote(self):
        artifact = self._artifact()
        artifact["authority"]["deployed"] = True
        artifact["artifact_sha256"] = canonical_sha256({k: v for k, v in artifact.items() if k != "artifact_sha256"})
        with self.assertRaisesRegex(ValueError, "NFL_ATTEMPT9_MODEL_P_AUTHORITY_INVALID:deployed"):
            verify_model_p_artifact(artifact)

    def test_truth_gate_stays_blocked_while_model_p_is_not_deployed(self):
        artifact = self._artifact()
        row = model_probability(
            artifact, market="spread", raw_prediction=20.0, line=-3.5, selection="home"
        )
        decision = decide_bet(
            row["model_p"],
            -110,
            fair_market_probability=0.50,
            bound=True,
            fresh=True,
            deployed=row["deployed"],
            edge_floor=0.03,
            push_probability=row["push_probability"],
        )
        self.assertEqual(decision.bet_status, "BLOCKED")
        self.assertNotEqual(decision.bet_status, "OFFICIAL_BET")

    def test_isotonic_fit_is_monotone(self):
        blocks = fit_isotonic_blocks(
            [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
            [0, 1, 0, 1, 0, 1],
        )
        means = [row["mean"] for row in blocks]
        self.assertEqual(means, sorted(means))
        self.assertEqual(sum(row["weight"] for row in blocks), 6)

    def test_artifact_hash_detects_calibration_mutation(self):
        artifact = self._artifact()
        artifact["markets"]["spread"]["sigma"] = 99.0
        with self.assertRaisesRegex(ValueError, "NFL_ATTEMPT9_MODEL_P_ARTIFACT_SHA_MISMATCH"):
            verify_model_p_artifact(artifact)


if __name__ == "__main__":
    unittest.main()
