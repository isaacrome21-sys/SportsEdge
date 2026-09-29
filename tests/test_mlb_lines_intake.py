import unittest

from sportsedge.engine_registry import resolve_manual_market_type
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.mlb_lines_intake import LinesIntakeError, build_input, parse_lines
from sportsedge.mlb_source import GameSnapshot


def _game(pk, away, home, start):
    return GameSnapshot(
        pk,
        start,
        "Preview",
        1,
        away,
        2,
        home,
        None,
        None,
        None,
        None,
        "2026-09-29T19:00:00+00:00",
    )


SCHEDULE = [
    _game(849851, "Boston Red Sox", "New York Yankees", "2026-09-30T00:00:00+00:00"),
    _game(849849, "Chicago White Sox", "Houston Astros", "2026-09-29T21:00:00+00:00"),
    _game(849843, "Chicago Cubs", "San Diego Padres", "2026-09-30T02:00:00+00:00"),
]

BOARD = """
Red Sox @ Yankees
ML +116 -140
RL +1.5 -193 +159
Total 6 -116 -104
YRFI +130 -165
Yankees TT 3.5 +114 -145
F5 ML +100 -130
F5 RL +0.5 -145 +114
F5 Total 3.5 -110 -120
Yankees F5 TT 1.5 -154 +120
Cam Schlittler K 6.5 -149 +117
Cam Schlittler outs 17.5 -174 +130
Cam Schlittler hits allowed 3.5 -145 +109
Cam Schlittler earned runs 1.5 +104 -138
Cam Schlittler pitcher walks 1.5 -133 +100
Cam Schlittler hits+walks+er 6.5 -143 +107
Cam Schlittler win +159 -223
Payton Tolle outs 15.5 -121 -109
Aaron Judge hits 1.5 +120 -150
Aaron Judge TB 1.5 +105 -135
Aaron Judge HR 0.5 +150 -200
Aaron Judge walks 0.5 -110 -120
Aaron Judge batter K 1.5 +125 -155
Aaron Judge singles 0.5 -140 +110
Aaron Judge doubles 0.5 +170 -220
Aaron Judge SB 0.5 +250 -350
Aaron Judge XBH 0.5 +125 -155
Aaron Judge H+R+RBI 2.5 +100 -130
Aaron Judge H+R+SB 2.5 +130 -165
Aaron Judge R+RBI 1.5 +115 -145
Aaron Judge H+SB 1.5 +110 -140
Aaron Judge H+BB+SB 2.5 +120 -150
Aaron Judge first HR +550 -900
Either pitcher hits allowed 5.5 +115 -145
Either pitcher walks 2.5 +125 -155
Either pitcher ER 2.5 +100 -130
"""


class LinesIntakeTest(unittest.TestCase):
    def test_parses_full_supported_phone_board(self):
        rows = parse_lines(BOARD)
        market_types = [row.market_type for row in rows]
        self.assertIn("MONEYLINE", market_types)
        self.assertIn("RUN_LINE", market_types)
        self.assertIn("GAME_TOTAL", market_types)
        self.assertIn("FIRST_INNING_TOTAL", market_types)
        self.assertIn("TEAM_TOTAL", market_types)
        self.assertIn("FIRST_FIVE_MONEYLINE", market_types)
        self.assertIn("FIRST_FIVE_RUN_LINE", market_types)
        self.assertIn("FIRST_FIVE_TOTAL", market_types)
        self.assertIn("FIRST_FIVE_TEAM_TOTAL", market_types)
        self.assertIn("PITCHER_RECORD_WIN", market_types)
        self.assertIn("PITCHER_HITS_WALKS_ER", market_types)
        self.assertIn("BATTER_STRIKEOUTS", market_types)
        self.assertIn("HITS_WALKS_STOLEN_BASES", market_types)
        self.assertIn("FIRST_HOME_RUN", market_types)
        self.assertIn("EITHER_PITCHER_HITS_ALLOWED", market_types)
        self.assertIn("EITHER_PITCHER_WALKS", market_types)
        self.assertIn("EITHER_PITCHER_EARNED_RUNS", market_types)

    def test_every_non_first_inning_manual_type_resolves_to_an_engine(self):
        for row in parse_lines(BOARD):
            if row.market_type != "FIRST_INNING_TOTAL":
                self.assertTrue(resolve_manual_market_type(row.market_type))

    def test_header_words_inside_team_names_are_not_separators(self):
        row = parse_lines("Nationals at Athletics\nML +100 -120")[0]
        self.assertEqual((row.away, row.home), ("Nationals", "Athletics"))

    def test_nrfi_yes_price_maps_to_canonical_yrfi_no(self):
        row = parse_lines("Cubs @ Padres\nNRFI -150 +120")[0]
        self.assertEqual((row.side, row.price, row.paired_side, row.paired_price), ("OVER", 120, "UNDER", -150))

    def test_signed_full_game_and_f5_run_lines_are_preserved(self):
        rows = parse_lines(
            "Yankees @ Red Sox\nRL -1.5 +135 -160\nF5 RL -0.5 +125 -155"
        )
        self.assertEqual(rows[0].line, -1.5)
        self.assertEqual(rows[1].line, -0.5)

    def test_unsigned_run_line_remains_away_plus(self):
        row = parse_lines("Red Sox @ Yankees\nRL 1.5 -193 +159")[0]
        self.assertEqual(row.line, 1.5)

    def test_binary_player_markets_use_yes_no_without_invented_line(self):
        rows = parse_lines(
            "Red Sox @ Yankees\nCam Schlittler win +159 -223\nAaron Judge first HR +550 -900"
        )
        self.assertEqual((rows[0].side, rows[0].line, rows[0].paired_side), ("YES", 0.0, "NO"))
        self.assertEqual((rows[1].side, rows[1].line, rows[1].paired_side), ("YES", 0.0, "NO"))

    def test_bare_k_is_pitcher_but_batter_k_is_explicit(self):
        rows = parse_lines(
            "Red Sox @ Yankees\nCam Schlittler K 6.5 -149 +117\nAaron Judge batter K 1.5 +125 -155"
        )
        self.assertEqual(rows[0].market_type, "PITCHER_STRIKEOUTS")
        self.assertEqual(rows[1].market_type, "BATTER_STRIKEOUTS")

    def test_build_input_resolves_games_and_passes_manual_quote_contract(self):
        payload = build_input(BOARD, observed_at="2026-09-29T15:49:00-05:00", schedule=SCHEDULE)
        rows = payload["rows"]
        self.assertEqual(rows[0]["game_id"], "Boston Red Sox@New York Yankees")
        self.assertEqual(next(row for row in rows if row["market_type"] == "TEAM_TOTAL")["team_side"], "HOME")
        self.assertEqual(next(row for row in rows if row["market_type"] == "FIRST_FIVE_TEAM_TOTAL")["team_side"], "HOME")
        self.assertTrue(all(row["timestamp_source"] == "INTAKE_STAMPED" for row in rows))
        for row in rows:
            validate_manual_quote(row)

    def test_multiple_games_are_bound_independently(self):
        payload = build_input(
            "Red Sox @ Yankees\nML +116 -140\n\nWhite Sox at Astros\nML +102 -123",
            observed_at="2026-09-29T15:49:00-05:00",
            schedule=SCHEDULE,
        )
        self.assertEqual(payload["rows"][0]["game_id"], "Boston Red Sox@New York Yankees")
        self.assertEqual(payload["rows"][1]["game_id"], "Chicago White Sox@Houston Astros")

    def test_one_sided_or_unknown_lines_fail_with_line_numbers(self):
        with self.assertRaises(LinesIntakeError) as ctx:
            parse_lines("Red Sox @ Yankees\nML -140\nsomething weird")
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("line 3", str(ctx.exception))

    def test_unknown_game_fails_closed(self):
        with self.assertRaises(LinesIntakeError):
            build_input(
                "Mets @ Braves\nML +100 -120",
                observed_at="2026-09-29T15:49:00-05:00",
                schedule=SCHEDULE,
            )


if __name__ == "__main__":
    unittest.main()
