import unittest

from sportsedge.manual_quote import validate_manual_quote
from sportsedge.mlb_lines_intake import LinesIntakeError, build_input, parse_lines
from sportsedge.mlb_source import GameSnapshot


def _game(pk, away, home, start):
    return GameSnapshot(pk, start, "Preview", 1, away, 2, home, None, None, None, None, "2026-09-29T19:00:00+00:00")


SCHEDULE = [
    _game(849851, "Boston Red Sox", "New York Yankees", "2026-09-30T00:00:00+00:00"),
    _game(849849, "Chicago White Sox", "Houston Astros", "2026-09-29T21:00:00+00:00"),
    _game(849843, "Chicago Cubs", "San Diego Padres", "2026-09-30T02:00:00+00:00"),
]

BOARD = """
Red Sox @ Yankees
ML +116 -140
RL +1.5 -193 +159
Total 6 -112 -107
YRFI +135 -170
Yankees TT 3.5 +114 -145
Payton Tolle outs 16.5 +107 -135

White Sox at Astros
ml +102 -123
"""


class LinesIntakeTest(unittest.TestCase):
    def test_parses_every_market_shape(self):
        rows = parse_lines(BOARD)
        self.assertEqual([r.market_type for r in rows],
                         ["MONEYLINE", "RUN_LINE", "GAME_TOTAL", "FIRST_INNING_TOTAL", "TEAM_TOTAL",
                          "PITCHER_OUTS", "MONEYLINE"])
        tolle = rows[5]
        self.assertEqual((tolle.subject_name, tolle.line, tolle.price, tolle.paired_price),
                         ("Payton Tolle", 16.5, 107, -135))

    def test_header_words_inside_team_names_are_not_separators(self):
        row = parse_lines("Nationals at Athletics\nML +100 -120")[0]
        self.assertEqual((row.away, row.home), ("Nationals", "Athletics"))

    def test_nrfi_yes_price_is_mapped_to_canonical_yrfi_no(self):
        row = parse_lines("Cubs @ Padres\nNRFI -150 +120")[0]
        self.assertEqual((row.side, row.price, row.paired_price), ("OVER", 120, -150))

    def test_run_line_accepts_signed_away_favorite(self):
        row = parse_lines("Yankees @ Red Sox\nRL -1.5 +135 -160")[0]
        self.assertEqual((row.side, row.line, row.price, row.paired_side, row.paired_price),
                         ("AWAY", -1.5, 135, "HOME", -160))

    def test_unsigned_run_line_remains_away_plus(self):
        row = parse_lines("Red Sox @ Yankees\nRL 1.5 -193 +159")[0]
        self.assertEqual(row.line, 1.5)

    def test_build_input_resolves_games_and_passes_manual_contract(self):
        payload = build_input(BOARD, observed_at="2026-09-29T15:49:00-05:00", schedule=SCHEDULE)
        rows = payload["rows"]
        self.assertEqual(rows[0]["game_id"], "Boston Red Sox@New York Yankees")
        self.assertEqual(rows[-1]["game_id"], "Chicago White Sox@Houston Astros")
        self.assertEqual(rows[4]["team_side"], "HOME")
        self.assertTrue(all(r["timestamp_source"] == "INTAKE_STAMPED" for r in rows))
        for r in rows:
            validate_manual_quote(r)

    def test_one_sided_or_unknown_lines_fail_with_line_numbers(self):
        with self.assertRaises(LinesIntakeError) as ctx:
            parse_lines("Red Sox @ Yankees\nML -140\nsomething weird")
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("line 3", str(ctx.exception))

    def test_unknown_game_fails_closed(self):
        with self.assertRaises(LinesIntakeError):
            build_input("Mets @ Braves\nML +100 -120", observed_at="2026-09-29T15:49:00-05:00", schedule=SCHEDULE)


if __name__ == "__main__":
    unittest.main()
