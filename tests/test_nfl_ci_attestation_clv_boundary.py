import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class NFLCIAttestationCLVBoundaryTests(unittest.TestCase):
    def test_ci_attestation_script_rejects_free_form_clv_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            clv = root / "clv.json"
            clv.write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/attest_nfl_ci_and_build_registry.py",
                    "--bundle-dir", str(root / "bundle"),
                    "--workflow-name", "football-nfl-promotion-evidence",
                    "--workflow-conclusion", "success",
                    "--workflow-head-sha", "1" * 40,
                    "--workflow-run-id", "12345",
                    "--clv-evidence", str(clv),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_EXTERNAL_ATTESTATION_REQUIRED", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
