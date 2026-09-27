import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import scripts.nfl_direct_dk_preflight as probe


class DirectDkPreflightTests(unittest.TestCase):
    def test_healthy_probe_is_diagnostic_only(self):
        transport = {"source_class": "DRAFTKINGS_DIRECT_WEB_V1", "raw_sha256": "a" * 64}
        rows = [{"spread": {"status": "OK"}, "total": {"status": "OK"}}]
        out = io.StringIO()
        with patch.object(probe, "acquire_board", return_value=transport), patch.object(probe, "game_rows_direct", return_value=rows), redirect_stdout(out):
            self.assertEqual(probe.main(), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["state"], "DIRECT_DK_HEALTHY")
        self.assertFalse(payload["evidence_authority"])

    def test_failure_is_fail_closed_and_non_authoritative(self):
        out = io.StringIO()
        with patch.object(probe, "acquire_board", side_effect=RuntimeError("down")), redirect_stdout(out):
            self.assertEqual(probe.main(), 2)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["state"], "DIRECT_DK_UNAVAILABLE")
        self.assertFalse(payload["evidence_authority"])


if __name__ == "__main__":
    unittest.main()
