from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NflProviderPreflightExecutionTest(unittest.TestCase):
    def _run_help(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args, "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_direct_file_invocation_executes(self):
        result = self._run_help("scripts/nfl_2026_provider_preflight.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--schedule-csv", result.stdout)
        self.assertIn("--out", result.stdout)

    def test_module_invocation_executes(self):
        result = self._run_help("-m", "scripts.nfl_2026_provider_preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--schedule-csv", result.stdout)
        self.assertIn("--out", result.stdout)


if __name__ == "__main__":
    unittest.main()
