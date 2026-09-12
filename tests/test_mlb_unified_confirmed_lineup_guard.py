import unittest
from datetime import datetime, timezone

from sportsedge.unified_card import run_unified_card


class MLBUnifiedConfirmedLineupGuardTests(unittest.TestCase):
    def test_false_confirmed_lineup_mode_fails_closed_before_pricing(self):
        now = datetime.now(timezone.utc)
        with self.assertRaisesRegex(ValueError, "CONFIRMED_LINEUP_REQUIRED_FOR_PRODUCTION"):
            run_unified_card(
                games=[],
                feature_rows=[],
                quotes=[],
                ingestion_now=now,
                finalization_now=now,
                require_confirmed_lineup=False,
            )


if __name__ == "__main__":
    unittest.main()
