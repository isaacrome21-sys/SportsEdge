from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MLBPITLocalCLITests(unittest.TestCase):
    def test_self_test_executes_from_real_cli_path(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_mlb_pit_local.py"), "--self-test"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip())
        self.assertEqual(payload["status"], "SELF_TEST_OK")
        self.assertEqual(payload["capture_minutes"], [7, 22, 37, 52])


if __name__ == "__main__":
    unittest.main()
