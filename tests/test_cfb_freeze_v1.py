from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from scripts.cfb_2025_holdout import CFBHoldoutError, validate_training_rows

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "config/cfb_freeze_v1.json"


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


class CFBFreezeV1Tests(unittest.TestCase):
    def test_frozen_engine_blob_shas_match(self):
        freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(freeze["freeze_id"], "cfb_freeze_v1")
        for item in freeze["engine_files"]:
            path = ROOT / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual(git_blob_sha(path), item["blob_sha"], item["path"])

    def test_training_window_excludes_2025(self):
        freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertLess(freeze["training_window"]["max_season"], 2025)
        validate_training_rows([{"season": 2023}, {"season": 2024}])
        with self.assertRaisesRegex(CFBHoldoutError, "2025_DATA_IN_TRAINING"):
            validate_training_rows([{"season": 2024}, {"season": 2025}])


if __name__ == "__main__":
    unittest.main()
