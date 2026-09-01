import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class NFLProductionKeyMathCLITests(unittest.TestCase):
    def _audit(self):
        return {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "seasons": [2021, 2022, 2023, 2024, 2025],
            "signed_margin_pmf": {"-7": 0.045, "-3": 0.072, "3": 0.083, "7": 0.051},
        }

    def _production(self):
        return {
            "model_id": "nfl_m2_ridge_v1",
            "feature_contract": "NFL_M2_V1_MARKET_BLIND",
            "production_distribution_profile": {
                "contract": "NFL_M2_OOS_EMERGENT_SIGNED_KEY_PMF_V1",
                "model_id": "nfl_m2_ridge_v1",
                "feature_contract": "NFL_M2_V1_MARKET_BLIND",
                "probability_source": "OOS_PRODUCTION_M2_PAIRED_RESIDUAL_SCORE_DISTRIBUTIONS",
                "heldout_game_count": 1000,
                "test_seasons": [2022, 2023, 2024, 2025],
                "signed_key_probability": {"-7": 0.044, "-3": 0.074, "3": 0.081, "7": 0.052},
            },
        }

    def test_cli_uses_exact_production_m2_profile_instead_of_smooth_candidate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            production = root / "production.json"
            output = root / "math.json"
            audit.write_text(json.dumps(self._audit()), encoding="utf-8")
            production.write_text(json.dumps(self._production()), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_nfl_simulator_profile.py",
                    str(audit),
                    "--production-evidence", str(production),
                    "--version", "nfl-m2-oos-key-emergent-v1",
                    "--require-pass",
                    "--out", str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["math_attestation"]["math_valid"])
            self.assertIsNone(payload["margin_mean"])
            self.assertIsNone(payload["margin_sigma"])
            self.assertEqual(
                payload["production_distribution_identity"]["contract"],
                "NFL_M2_OOS_EMERGENT_SIGNED_KEY_PMF_V1",
            )
            self.assertEqual(payload["fit"]["per_key"]["3"]["simulated_emergent"], 0.081)

    def test_cli_fails_closed_when_production_profile_is_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            production = root / "production.json"
            output = root / "math.json"
            audit.write_text(json.dumps(self._audit()), encoding="utf-8")
            production.write_text(json.dumps({
                "model_id": "nfl_m2_ridge_v1",
                "feature_contract": "NFL_M2_V1_MARKET_BLIND",
            }), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_nfl_simulator_profile.py",
                    str(audit),
                    "--production-evidence", str(production),
                    "--out", str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("NFL_PRODUCTION_KEY_PROFILE_REQUIRED", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
