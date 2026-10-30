import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class NFLPlayLevelResearchRunnerTests(unittest.TestCase):
    def _write_fixture(self, path: Path):
        fieldnames = ["season", "game_id", "posteam", "play_type", "epa", "success", "yards_gained", "down", "cpoe", "sack", "interception", "fumble_lost"]
        rows = []
        for season in (2021, 2022, 2023, 2024):
            for game_no in (1, 2):
                for team, epa in (("CHI", 0.2 + game_no), ("GB", -0.1 + game_no)):
                    rows.append({
                        "season": season,
                        "game_id": f"{season}_g{game_no}",
                        "posteam": team,
                        "play_type": "pass",
                        "epa": epa,
                        "success": 1,
                        "yards_gained": 12,
                        "down": 1,
                        "cpoe": 3.0,
                        "sack": 0,
                        "interception": 0,
                        "fumble_lost": 0,
                    })
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_runner_builds_hash_bound_research_only_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "plays.csv"
            out = root / "artifact.json"
            self._write_fixture(src)
            proc = subprocess.run(
                [sys.executable, "scripts/run_nfl_play_level_research.py", "--input", str(src), "--output", str(out)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            artifact = json.loads(out.read_text())
            self.assertEqual(artifact["status"], "RESEARCH_ONLY_NO_MODEL_P_AUTHORITY")
            self.assertFalse(artifact["splits"]["2025_used"])
            self.assertFalse(artifact["splits"]["2026_used"])
            self.assertFalse(artifact["governance"]["model_p_created"])
            self.assertFalse(artifact["governance"]["market_prices_used_as_features"])
            self.assertGreater(artifact["splits"]["development_feature_rows"], 0)
            self.assertGreater(artifact["splits"]["validation_feature_rows"], 0)
            self.assertEqual(len(artifact["source"]["sha256"]), 64)

    def test_runner_rejects_2025_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "plays.csv"
            out = root / "artifact.json"
            with src.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["season", "game_id", "posteam", "play_type", "epa"])
                writer.writeheader()
                writer.writerow({"season": 2025, "game_id": "g", "posteam": "CHI", "play_type": "pass", "epa": 0.0})
            proc = subprocess.run(
                [sys.executable, "scripts/run_nfl_play_level_research.py", "--input", str(src), "--output", str(out)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("NFL_RESEARCH_SEASON_NOT_ALLOWED:2025", proc.stderr + proc.stdout)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
