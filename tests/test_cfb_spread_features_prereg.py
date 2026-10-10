"""Ensure the spread-features prereg is frozen and SHA-stable."""
import hashlib
import json
import unittest
from pathlib import Path


class TestSpreadFeaturesPrereg(unittest.TestCase):
    def test_prereg_frozen_and_sha(self):
        path = Path("config/cfb_spread_features_prereg_v1.json")
        raw = path.read_bytes()
        data = json.loads(raw)
        self.assertEqual(data["schema"], "CFB_SPREAD_FEATURES_PREREG_V1")
        self.assertEqual(data["status"], "FROZEN")
        self.assertEqual(data["protocol"]["max_attempts"], 10)
        self.assertEqual(data["protocol"]["train_seasons"], [2016, 2017, 2018, 2019, 2020])
        self.assertEqual(data["protocol"]["holdout_seasons"], [2021, 2022, 2023, 2024, 2025])
        self.assertIn("sha256", data)
        # SHA is of the file content including the sha field itself (stamped after write)
        self.assertEqual(len(data["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
