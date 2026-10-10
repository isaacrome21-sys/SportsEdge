import json
import unittest
from pathlib import Path
from unittest.mock import patch

from sportsedge.sports.cfb.totals_calibration import (
    apply_totals_calibration,
    load_totals_calibration,
)

ROOT = Path(__file__).resolve().parents[1]


class TotalsCalibrationTest(unittest.TestCase):
    def test_margin_unchanged(self):
        cal = load_totals_calibration()
        raw_h, raw_a = 31.4, 24.7
        cal_h, cal_a = apply_totals_calibration(raw_h, raw_a, cal)
        self.assertAlmostEqual(cal_h - cal_a, raw_h - raw_a, places=6)
        raw_total = raw_h + raw_a
        expected = cal["intercept"] + cal["scale"] * raw_total
        self.assertAlmostEqual(cal_h + cal_a, expected, places=5)

    def test_sha_present_on_card_payload(self):
        # Smoke: loading produces a SHA
        cal = load_totals_calibration()
        self.assertEqual(len(cal["sha256"]), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in cal["sha256"]))

    def test_schema_failure_fails_closed(self):
        bad = {"schema": "WRONG"}
        with patch("sportsedge.sports.cfb.totals_calibration.CAL_PATH") as mock_path:
            mock_path.read_bytes.return_value = json.dumps(bad).encode()
            # Clear cache
            import sportsedge.sports.cfb.totals_calibration as mod
            mod._CACHE = None
            with self.assertRaises(ValueError):
                load_totals_calibration()
        # Restore
        mod._CACHE = None


if __name__ == "__main__":
    unittest.main()
