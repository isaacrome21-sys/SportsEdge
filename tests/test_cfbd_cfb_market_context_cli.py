from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from sportsedge.cfbd_cfb_market_context import (
    CFBDMarketContextError,
    fetch_cfbd_cfb_market_context,
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_cfbd_cfb_market_context.py"
_spec = importlib.util.spec_from_file_location("run_cfbd_cfb_market_context_tested", SCRIPT)
assert _spec and _spec.loader
_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cli)


class _InvalidCredentialOpener:
    def __call__(self, request, timeout=20):
        raise HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=None)


class CFBDCredentialFailClosedTests(unittest.TestCase):
    def _run_cli(self, *, output: Path, env: dict[str, str], fetch_side_effect=None) -> tuple[int, dict]:
        argv = [
            str(SCRIPT),
            "--season", "2026",
            "--week", "4",
            "--asof", "2026-09-15T18:30:00+00:00",
            "--output", str(output),
        ]
        fetch_patch = patch.object(_cli, "fetch_cfbd_cfb_market_context", side_effect=fetch_side_effect) if fetch_side_effect else None
        with patch.object(sys, "argv", argv), patch.dict(os.environ, env, clear=True):
            if fetch_patch:
                with fetch_patch:
                    rc = _cli.main()
            else:
                rc = _cli.main()
        return rc, json.loads(output.read_text(encoding="utf-8"))

    def test_missing_key_writes_blocked_artifact_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "missing.json"
            rc, payload = self._run_cli(output=output, env={})
        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["blocker"], "CFBD_API_KEY_REQUIRED")
        self.assertFalse(payload["governance"]["ttl_eligible"])
        self.assertFalse(payload["governance"]["freshness_eligible"])
        self.assertFalse(payload["governance"]["official_authority"])

    def test_invalid_key_provider_failure_writes_blocked_artifact_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "invalid.json"
            rc, payload = self._run_cli(
                output=output,
                env={"CFBD_API_KEY": "invalid-test-key"},
                fetch_side_effect=CFBDMarketContextError("CFBD_FETCH_FAILED:HTTPError"),
            )
        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["blocker"], "CFBD_FETCH_FAILED:HTTPError")
        self.assertFalse(payload["governance"]["closing_benchmark_eligible"])
        self.assertFalse(payload["governance"]["model_p_eligible"])
        self.assertFalse(payload["governance"]["promotion_authority"])

    def test_source_401_is_not_converted_to_empty_success(self):
        with self.assertRaisesRegex(CFBDMarketContextError, "CFBD_FETCH_FAILED:HTTPError"):
            fetch_cfbd_cfb_market_context(
                year=2026,
                week=4,
                api_key="invalid-test-key",
                opener=_InvalidCredentialOpener(),
            )


if __name__ == "__main__":
    unittest.main()
