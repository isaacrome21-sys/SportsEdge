"""Regression: issue #2578 (WS G2) long header, parenthetical extras, info sections."""
import unittest

from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines, parse_lines_with_warnings
from sportsedge.mlb_resolve import build_bound_input
from sportsedge.mlb_source import GameSnapshot

TITLE = "[MLB LINES] TB Rays @ MIL Brewers WS G2"

BODY_2578 = """TB Rays @ MIL Brewers — WS Game 2, Sat Oct 24, 2026, 7:00 PM CT (DK event 34887981; DK lines captured 5:20-5:27 PM CT by Rocky; probables: TB Drew Rasmussen, MIL Logan Henderson)

ML +100 -120
RL -1.5 +180 / +1.5 -221
Total 6.5 -108 -111
F5 ML -110 -120
F5 RL -0.5 +135 / +0.5 -175 (also: -1.5 +250 / +1.5 -345; +0.5 -166 / -0.5 +130; +1.5 -345 / -1.5 +250)
F5 Total 3.5 +110 -140 (also: 2.5 -175 +135; 4.5 +195 -260)
F5 Team Totals: MIL 1.5 +105 -135; TB 1.5 +100 -130
YRFI (1st Inning Runs Over 0.5) +130 / NRFI (Under 0.5) -170 (also 1.5 total: +340 / -475)
Team Totals: MIL 3.5 +120 -154; TB 3.5 +120 -154
Team Total Hits: MIL 7.5 -105 -125; TB 7.5 -115 -115

Pitcher props — Drew Rasmussen (TB):
K 5.5 -159 +125 (ladder: 3+ -3000, 4+ -880, 5+ -355, 6+ -160, 7+ +131, 8+ +265, 9+ +534, 10+ +1140)
Outs 17.5 +110 -146
Hits Allowed 4.5 +107 -142
ER Allowed 1.5 -121 -110
Walks Allowed 1.5 +103 -136
Hits+Walks+ER 7.5 -111 -120
Win Yes +195 / No -277

Pitcher props — Logan Henderson (MIL):
K 4.5 -129 +101 (ladder: 3+ -830, 4+ -289, 5+ -129, 6+ +164, 7+ +336, 8+ +680, 9+ +1360)
Outs 14.5 -141 +106
Hits Allowed 3.5 -140 +105
ER Allowed 1.5 +114 -152
Walks Allowed 0.5 -219 +163
Hits+Walks+ER 6.5 +102 -136
Win Yes +316 / No -473

H2H: Most Ks — Henderson +176 / Rasmussen -249; Most Walks Allowed — Henderson +159 / Rasmussen -224; Race to 3 Ks — Rasmussen +105 / Henderson -145

Batter HR (1+ / 2+): Caminero +381/+3900; Bauers +518/+6200; Chourio +515/+6600
Batter Hits O/U 0.5 (Over/Under): Simpson -246/+182; Chourio -242/+179
Batter Total Bases O/U 1.5 (only 4 listed): Chourio +128/-170; Caminero +139/-186
Batter Walks O/U 0.5 (Over/Under): Bauers +125/-174; Contreras +187/-266
Batter Strikeouts ladder (1+/2+/3+): Aranda -541/+114/+529; Bauers -554/+113/+551
(No batter Strikeouts O/U section offered; no market literally labeled YRFI/NRFI — the 1st Inning Runs 0.5 line above is the equivalent.)
"""


def _game():
    return GameSnapshot(
        778001, "2026-10-25T00:00:00Z", "Preview", 139, "Tampa Bay Rays", 158, "Milwaukee Brewers",
        None, "Drew Rasmussen", None, "Logan Henderson", "2026-10-24T22:00:00+00:00",
    )


def _key(row):
    return (row.market_type, row.subject_name, row.team, row.side, row.line, row.price, row.paired_side, row.paired_price)


class Issue2578Test(unittest.TestCase):
    def setUp(self):
        self.rows, self.warnings = parse_lines_with_warnings(BODY_2578, title=TITLE)
        self.keys = {_key(r) for r in self.rows}

    def test_long_header_is_read(self):
        self.assertEqual({(r.away, r.home) for r in self.rows}, {("TB Rays", "MIL Brewers")})

    def test_core_markets_keep_offered_prices(self):
        expect = {
            ("MONEYLINE", None, None, "AWAY", 0.0, 100, "HOME", -120),
            ("RUN_LINE", None, None, "AWAY", -1.5, 180, "HOME", -221),
            ("GAME_TOTAL", None, None, "OVER", 6.5, -108, "UNDER", -111),
            ("FIRST_FIVE_MONEYLINE", None, None, "AWAY", 0.0, -110, "HOME", -120),
            ("FIRST_FIVE_RUN_LINE", None, None, "AWAY", -0.5, 135, "HOME", -175),
            ("FIRST_FIVE_TOTAL", None, None, "OVER", 3.5, 110, "UNDER", -140),
            ("FIRST_FIVE_TEAM_TOTAL", None, "MIL", "OVER", 1.5, 105, "UNDER", -135),
            ("FIRST_FIVE_TEAM_TOTAL", None, "TB", "OVER", 1.5, 100, "UNDER", -130),
            ("FIRST_INNING_TOTAL", None, None, "OVER", 0.5, 130, "UNDER", -170),
            ("TEAM_TOTAL", None, "MIL", "OVER", 3.5, 120, "UNDER", -154),
            ("TEAM_TOTAL", None, "TB", "OVER", 3.5, 120, "UNDER", -154),
        }
        self.assertTrue(expect <= self.keys, expect - self.keys)

    def test_pitcher_sections_bind_subject(self):
        expect = {
            ("PITCHER_STRIKEOUTS", "Drew Rasmussen", None, "OVER", 5.5, -159, "UNDER", 125),
            ("PITCHER_OUTS", "Drew Rasmussen", None, "OVER", 17.5, 110, "UNDER", -146),
            ("PITCHER_EARNED_RUNS", "Drew Rasmussen", None, "OVER", 1.5, -121, "UNDER", -110),
            ("PITCHER_HITS_WALKS_ER", "Drew Rasmussen", None, "OVER", 7.5, -111, "UNDER", -120),
            ("PITCHER_RECORD_WIN", "Drew Rasmussen", None, "YES", 0.0, 195, "NO", -277),
            ("PITCHER_STRIKEOUTS", "Logan Henderson", None, "OVER", 4.5, -129, "UNDER", 101),
            ("PITCHER_WALKS", "Logan Henderson", None, "OVER", 0.5, -219, "UNDER", 163),
            ("PITCHER_RECORD_WIN", "Logan Henderson", None, "YES", 0.0, 316, "NO", -473),
        }
        self.assertTrue(expect <= self.keys, expect - self.keys)
        self.assertEqual(sum(1 for r in self.rows if r.subject_name), 14)

    def test_info_lines_become_warnings_and_emit_no_rows(self):
        self.assertTrue(any("Team Total Hits" in w for w in self.warnings))
        self.assertTrue(any("H2H" in w for w in self.warnings))
        self.assertTrue(any("Batter HR" in w for w in self.warnings))
        # Ladder / "also" alternates never become rows.
        self.assertNotIn(4.5, {r.line for r in self.rows if r.market_type == "FIRST_FIVE_TOTAL"})
        self.assertEqual(len(self.rows), 25)

    def test_binds_to_schedule_with_abbreviations(self):
        payload = build_bound_input(BODY_2578, observed_at="2026-10-24T17:38:30-05:00",
                                    schedule=[_game()], title=TITLE)
        self.assertEqual({r["game_id"] for r in payload["rows"]}, {"Tampa Bay Rays@Milwaukee Brewers"})
        sides = {(r["market_type"], r.get("team_side"), r["line"]) for r in payload["rows"] if r.get("team_side")}
        self.assertIn(("TEAM_TOTAL", "HOME", 3.5), sides)
        self.assertIn(("FIRST_FIVE_TEAM_TOTAL", "AWAY", 1.5), sides)
        self.assertTrue(payload["intake_warnings"])

    def test_title_fallback_when_body_has_no_header(self):
        body = BODY_2578.split("\n", 1)[1]
        with self.assertRaises(LinesIntakeError):
            parse_lines(body)
        rows = parse_lines(body, title=TITLE)
        self.assertEqual((rows[0].away, rows[0].home), ("TB Rays", "MIL Brewers"))

    def test_one_sided_prices_still_fail_closed(self):
        for bad in ("ML +100", "RL -1.5 +180", "Total 6.5 -108", "K 5.5 -159"):
            text = f"TB Rays @ MIL Brewers\nPitcher props — Drew Rasmussen (TB):\n{bad}"
            with self.assertRaises(LinesIntakeError, msg=bad):
                parse_lines(text)

    def test_mismatched_run_line_sides_are_not_guessed(self):
        rows, warnings = parse_lines_with_warnings("TB @ MIL\nML +100 -120\nRL -1.5 +180 / -1.5 -221")
        self.assertEqual([r.market_type for r in rows], ["MONEYLINE"])
        self.assertTrue(warnings)

    def test_wrong_nickname_with_abbr_does_not_match(self):
        with self.assertRaises(LinesIntakeError):
            build_bound_input("TB Brewers @ MIL Brewers\nML +100 -120",
                              observed_at="2026-10-24T17:38:30-05:00", schedule=[_game()])


if __name__ == "__main__":
    unittest.main()
