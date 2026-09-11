from __future__ import annotations

from datetime import datetime, timezone
import unittest

from scripts.run_cfb_props_manual import (
    CFBPropManualRunError,
    _require_manual_decision_not_after_runtime,
    _runtime_asof,
)


class CFBPropManualRuntimeTimeTests(unittest.TestCase):
    def test_manual_decision_must_not_be_after_runtime_asof(self):
        runtime = datetime(2026, 9, 11, 16, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(CFBPropManualRunError, "CFB_PROP_MANUAL_DEPTH_AFTER_RUNTIME_ASOF"):
            _require_manual_decision_not_after_runtime(
                {"decision_time": "2026-09-11T16:01:00Z"}, runtime
            )

    def test_manual_decision_at_or_before_runtime_asof_is_allowed(self):
        runtime = datetime(2026, 9, 11, 16, 10, tzinfo=timezone.utc)
        decision = _require_manual_decision_not_after_runtime(
            {"decision_time": "2026-09-11T16:10:00Z"}, runtime
        )
        self.assertEqual(decision, runtime)

    def test_runtime_asof_requires_timezone(self):
        with self.assertRaisesRegex(CFBPropManualRunError, "CFB_PROP_MANUAL_RUNTIME_ASOF_INVALID"):
            _runtime_asof("2026-09-11T16:10:00")

    def test_manual_decision_requires_timezone(self):
        runtime = datetime(2026, 9, 11, 16, 10, tzinfo=timezone.utc)
        with self.assertRaisesRegex(CFBPropManualRunError, "CFB_PROP_MANUAL_DEPTH_DECISION_TIME_INVALID"):
            _require_manual_decision_not_after_runtime(
                {"decision_time": "2026-09-11T16:00:00"}, runtime
            )


if __name__ == "__main__":
    unittest.main()
