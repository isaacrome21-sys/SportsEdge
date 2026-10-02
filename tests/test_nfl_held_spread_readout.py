from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts import run_nfl_lines_card


class HeldSpreadReadoutTests(TestCase):
    def test_half_point_spread_is_priced_but_never_promoted_to_pick(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            ticket = {
                "slate": "2026-10-01",
                "games": [
                    {
                        "away": "PIT",
                        "home": "CLE",
                        "markets": [
                            {
                                "market": "spread",
                                "line": -2.5,
                                "away_or_over_price": -120,
                                "home_or_under_price": 100,
                                "raw": "Spread -2.5 -120 +100",
                            }
                        ],
                    }
                ],
            }
            history_rows = []
            for i in range(5):
                history_rows.append(
                    {
                        "date": f"2026-09-{i + 1:02d}",
                        "id": f"pit-{i}",
                        "home": "PIT",
                        "away": "BAL",
                        "hs": 24 + i,
                        "as": 20,
                    }
                )
                history_rows.append(
                    {
                        "date": f"2026-09-{i + 10:02d}",
                        "id": f"cle-{i}",
                        "home": "CLE",
                        "away": "CIN",
                        "hs": 21 + i,
                        "as": 19,
                    }
                )
            ticket_path = root / "ticket.json"
            history_path = root / "history.json"
            output_path = root / "card.json"
            ticket_path.write_text(json.dumps(ticket), encoding="utf-8")
            history_path.write_text(json.dumps({"games": history_rows}), encoding="utf-8")

            argv = [
                "run_nfl_lines_card.py",
                "--input",
                str(ticket_path),
                "--history",
                str(history_path),
                "--output",
                str(output_path),
            ]
            with patch("sys.argv", argv):
                self.assertEqual(run_nfl_lines_card.main(), 0)

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            game = payload["games"][0]
            row = game["markets"][0]
            self.assertIsNone(row["no_model"])
            self.assertIsNone(row["pick"])
            self.assertEqual(
                row["validation_hold"],
                "NO_MODEL:SPREAD_HELD_FOR_DISCRETE_MARGIN_VALIDATION",
            )
            self.assertIn("held_pick", row)
            self.assertIn(row["held_pick"]["selection"], {"PIT", "CLE"})
            self.assertEqual(game["picks"], [])


if __name__ == "__main__":
    import unittest

    unittest.main()
