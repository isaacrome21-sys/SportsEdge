import unittest

from sportsedge.core.validation.math_attestation import attest_validated_math
from sportsedge.sports.nfl.simulator_profile import (
    build_math_attestation_artifact,
    build_nfl_simulator_profile,
    validate_profile_fit,
)


class NFLSimulatorMathArtifactTests(unittest.TestCase):
    def _profile_and_fit(self, bad=False):
        audit = {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "seasons": [2021, 2022, 2023, 2024, 2025],
            "signed_margin_pmf": {"-7": 0.045, "-3": 0.072, "3": 0.083, "7": 0.051},
        }
        profile = build_nfl_simulator_profile(audit, version="nfl-key-emergent-v3")
        simulated = {-7: 0.044, -3: 0.074, 3: 0.060 if bad else 0.081, 7: 0.052}
        fit = validate_profile_fit(profile, simulated, max_abs_error=0.005)
        return profile, fit

    def test_bridge_emits_exact_math_attestation_contract(self):
        profile, fit = self._profile_and_fit()
        artifact = build_math_attestation_artifact(profile, fit)
        self.assertEqual(artifact["provenance"], "REAL_PUBLIC_HISTORY")
        self.assertEqual(artifact["profile_version"], "nfl-key-emergent-v3")
        self.assertEqual(artifact["key_numbers"], [-7, -3, 3, 7])
        result = attest_validated_math(artifact)
        self.assertTrue(result["math_valid"])

    def test_failed_fit_stays_failed_through_attestation_bridge(self):
        profile, fit = self._profile_and_fit(bad=True)
        artifact = build_math_attestation_artifact(profile, fit)
        result = attest_validated_math(artifact)
        self.assertFalse(result["math_valid"])
        self.assertEqual(result["failed_keys"], [3])

    def test_bridge_rejects_mismatched_contract(self):
        profile, fit = self._profile_and_fit()
        broken = dict(fit)
        broken["contract"] = "OLD_CONTRACT"
        with self.assertRaisesRegex(ValueError, "FIT_PROFILE_CONTRACT_MISMATCH"):
            build_math_attestation_artifact(profile, broken)


if __name__ == "__main__":
    unittest.main()
