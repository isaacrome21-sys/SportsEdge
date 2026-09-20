import unittest
from datetime import datetime, timezone

from sportsedge.sports.cfb.forward_evidence import _nearest_early


def _row(lead: float, ident: str):
    return {
        "lead_minutes": lead,
        "captured_at": datetime(2026, 9, 14, tzinfo=timezone.utc),
        "capture_id": ident,
    }


class CFBForwardTargetDirectionTests(unittest.TestCase):
    def test_prefers_legal_early_capture_over_closer_late_capture(self):
        selected = _nearest_early([_row(55.0, "late"), _row(66.0, "early")], 60.0)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["capture_id"], "early")

    def test_returns_none_when_all_candidates_are_after_target(self):
        self.assertIsNone(
            _nearest_early([_row(59.9, "late"), _row(55.0, "later")], 60.0)
        )

    def test_exact_target_is_eligible(self):
        selected = _nearest_early([_row(60.0, "exact"), _row(61.0, "early")], 60.0)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["capture_id"], "exact")


if __name__ == "__main__":
    unittest.main()
