from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.core.clv.football_forward_v2 import (
    POLICY_PATH,
    POLICY_SHA256,
    FootballForwardV2Error,
    load_forward_policy,
)


class FootballForwardV2PolicyAuthorityTests(unittest.TestCase):
    def test_exported_policy_sha_binds_exact_committed_bytes(self):
        self.assertEqual(POLICY_SHA256, sha256(POLICY_PATH.read_bytes()).hexdigest())

    def test_loader_derives_runtime_windows_from_policy_bytes(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        payload["decision_window_minutes_before_start"]["min"] = 46
        payload["close_window_minutes_before_start"]["max"] = 19
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            loaded = load_forward_policy(path)
        self.assertEqual(loaded["_decision_min"], 46)
        self.assertEqual(loaded["_close_max"], 19)
        self.assertEqual(loaded["_sha256"], sha256((json.dumps(payload, sort_keys=True) + "\n").encode()).hexdigest())

    def test_policy_activation_cannot_happen_by_config_only(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        payload["status"] = "ACTIVE"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(FootballForwardV2Error, "ACTIVATION_REQUIRES_CODE_REVIEW"):
                load_forward_policy(path)

    def test_policy_rejects_unsupported_market_surface(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        payload["markets"].append("player_props")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(FootballForwardV2Error, "POLICY_MARKETS_UNSUPPORTED"):
                load_forward_policy(path)


if __name__ == "__main__":
    unittest.main()
