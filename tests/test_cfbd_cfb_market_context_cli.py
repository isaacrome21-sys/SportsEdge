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


class _JsonResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class _JsonOpener:
    def __init__(self, payload):
        self.payload = payload

    def __call__(self, request, timeout=20):
        return _JsonResponse(self.payload)


class CFBDCredentialFailClosedTests(unittest.TestCase):
    def _run_cli(
        self,
        *,
        output: Path,
        env: dict[str, str],
        fetch_side_effect=None,
        fetch_result=None,
    ) -> tuple[int, dict]:
        argv = [
            str(SCRIPT),
            "--season", "2026",
            "--week", "4",
            "--asof", "2026-09-15T18:30:00+00:00",
            "--output", str(output),
        ]
        kwargs = {}
        if fetch_side_effect is not None:
            kwargs["side_effect"] = fetch_side_effect
        if fetch_result is not None:
            kwargs["return_value"] = fetch_result
        fetch_patch = patch.object(_cli, "fetch_cfbd_cfb_market_context", **kwargs) if kwargs else None
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

    def test_http_200_scheduled_game_with_empty_lines_is_blocked_no_odds(self):
        source_snapshot = fetch_cfbd_cfb_market_context(
            year=2026,
            week=4,
            api_key="fixture-key",
            opener=_JsonOpener([
                {
                    "id": 401234567,
                    "season": 2026,
                    "week": 4,
                    "seasonType": "regular",
                    "homeTeam": "Home State",
                    "awayTeam": "Away Tech",
                    "lines": [],
                }
            ]),
        )
        self.assertEqual(source_snapshot.rows, ())
        self.assertEqual(source_snapshot.rejected[0]["reason"], "CFBD_LINES_MISSING")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "no-odds.json"
            rc, payload = self._run_cli(
                output=output,
                env={"CFBD_API_KEY": "fixture-key"},
                fetch_result=source_snapshot,
            )
        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "BLOCKED_NO_ODDS")
        self.assertEqual(payload["blocker"], "CFBD_LINES_MISSING")
        self.assertEqual(payload["rows"], [])

    def test_http_200_empty_game_list_is_valid_no_bet_slate(self):
        source_snapshot = fetch_cfbd_cfb_market_context(
            year=2026,
            week=4,
            api_key="fixture-key",
            opener=_JsonOpener([]),
        )
        self.assertEqual(source_snapshot.rows, ())
        self.assertEqual(source_snapshot.rejected, ())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "empty-slate.json"
            rc, payload = self._run_cli(
                output=output,
                env={"CFBD_API_KEY": "fixture-key"},
                fetch_result=source_snapshot,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "VALID_NO_BET_SLATE")
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["rejected"], [])


if __name__ == "__main__":
    unittest.main()
