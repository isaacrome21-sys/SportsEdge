import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import intake_mlb_lines_file
from sportsedge.mlb_source import GameSnapshot


def _game(pk, away, home, start):
    return GameSnapshot(
        pk, start, "Preview", 1, away, 2, home,
        None, None, None, None, "2026-10-05T20:00:00+00:00",
    )


class FastMlbTextIntakeTests(unittest.TestCase):
    def test_plain_text_builds_canonical_rows_and_embeds_schedule(self):
        schedule = [
            _game(1, "Chicago White Sox", "Cleveland Guardians", "2026-10-05T23:00:00+00:00")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "2026-10-05-sox-guardians.txt"
            out = Path(tmp) / "out.json"
            inp.write_text(
                "White Sox @ Guardians\n"
                "ML +120 -140\n"
                "Total 7.5 -110 -110\n"
                "YRFI +105 -135\n",
                encoding="utf-8",
            )
            with patch.object(intake_mlb_lines_file, "fetch_schedule", side_effect=[schedule, []]), \
                 patch("sys.argv", [
                     "intake_mlb_lines_file.py",
                     "--input", str(inp),
                     "--observed-at", "2026-10-05T16:00:00-05:00",
                     "--output", str(out),
                 ]):
                self.assertEqual(intake_mlb_lines_file.main(), 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["rows"]), 3)
            self.assertEqual(payload["rows"][0]["game_pk"], 1)
            self.assertEqual(payload["rows"][0]["timestamp_source"], "INTAKE_STAMPED")
            self.assertEqual(payload["intake"]["mode"], "FAST_TEXT_INTAKE")
            self.assertEqual(len(payload["schedule_snapshot"]), 1)

    def test_naive_observed_timestamp_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "lines.txt"
            out = Path(tmp) / "out.json"
            inp.write_text("White Sox @ Guardians\nML +120 -140\n", encoding="utf-8")
            with patch("sys.argv", [
                "intake_mlb_lines_file.py",
                "--input", str(inp),
                "--observed-at", "2026-10-05T16:00:00",
                "--output", str(out),
            ]):
                with self.assertRaises(SystemExit) as ctx:
                    intake_mlb_lines_file.main()
            self.assertIn("TZ_REQUIRED", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
