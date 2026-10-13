"""Period-prefixed intake shapes (CFB 1H spread/ML, MLB F5) are parsed and
accounted for, but always routed BLOCKED and never into priced quotes."""
from unittest import TestCase

from sportsedge.manual_line_paste import ManualLinePasteError, parse_manual_line_paste
from sportsedge.mlb_lines_intake import parse_lines, period_for_market

CFB = """CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z
Texas @ Oklahoma
ML Texas -150 / Oklahoma +130
1H ML Texas -140 / Oklahoma +120
1H SPREAD Texas -3.5 -110 / Oklahoma +3.5 -110
"""


class CfbFirstHalfShapes(TestCase):
    def test_1h_rows_blocked_no_engine_and_full_game_unchanged(self):
        out = parse_manual_line_paste(CFB)
        self.assertEqual([q["market"] for q in out["quotes"]], ["moneyline", "moneyline"])
        b = out["blocked_selections"]
        self.assertEqual(len(b), 4)
        self.assertEqual({r["market"] for r in b}, {"first_half_moneyline", "first_half_spread"})
        for r in b:
            self.assertEqual((r["status"], r["block_reason"], r["period"]), ("BLOCKED", "NO_ENGINE", "1H"))
            self.assertFalse(r["priced"])
            self.assertFalse(r["pricing_authorized"])
        self.assertEqual(out["selection_accounting"], {"submitted": 6, "priced_path": 2, "blocked": 4})

    def test_only_1h_lines_still_accounted_not_error(self):
        text = "CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z\nTexas @ Oklahoma\n1H ML Texas -140 / Oklahoma +120\n"
        out = parse_manual_line_paste(text)
        self.assertEqual(out["quotes"], [])
        self.assertEqual(out["selection_accounting"]["blocked"], 2)

    def test_1h_total_not_in_scope_fails_closed(self):
        text = "CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z\nA @ B\n1H TOTAL 24.5 OVER -110 / UNDER -110\n"
        with self.assertRaisesRegex(ManualLinePasteError, "PERIOD_MARKET_NOT_SUPPORTED"):
            parse_manual_line_paste(text)

    def test_unopposed_1h_spread_rejected(self):
        text = "CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z\nA @ B\n1H SPREAD A -3.5 -110 / B +2.5 -110\n"
        with self.assertRaisesRegex(ManualLinePasteError, "NOT_OPPOSED"):
            parse_manual_line_paste(text)

    def test_one_sided_1h_rejected(self):
        text = "CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z\nA @ B\n1H ML A -140\n"
        with self.assertRaisesRegex(ManualLinePasteError, "UNRECOGNIZED"):
            parse_manual_line_paste(text)

    def test_bad_odds_rejected(self):
        text = "CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z\nA @ B\n1H ML A -50 / B +120\n"
        with self.assertRaises(ManualLinePasteError):
            parse_manual_line_paste(text)

    def test_f5_prefix_not_allowed_for_cfb(self):
        text = "CFB 2026-10-17 DK retrieved_at=2026-10-17T15:00:00Z\nA @ B\nF5 ML A -140 / B +120\n"
        with self.assertRaisesRegex(ManualLinePasteError, "PERIOD_NOT_SUPPORTED_FOR_SPORT"):
            parse_manual_line_paste(text)


class MlbF5Shapes(TestCase):
    def test_f5_paste_blocked_not_validated(self):
        text = ("MLB 2026-10-14 DK retrieved_at=2026-10-14T20:00:00Z\nDodgers @ Mets\n"
                "F5 ML Dodgers -130 / Mets +110\nF5 TOTAL 4.5 OVER -105 / UNDER -115\n")
        out = parse_manual_line_paste(text)
        self.assertEqual(out["quotes"], [])
        self.assertEqual(len(out["blocked_selections"]), 4)
        for r in out["blocked_selections"]:
            self.assertEqual((r["block_reason"], r["period"]), ("NOT_VALIDATED", "F5"))
            self.assertTrue(r["market"].startswith("f5_"))
            self.assertFalse(r["pricing_authorized"])

    def test_1h_prefix_not_allowed_for_mlb(self):
        text = "MLB 2026-10-14 DK retrieved_at=2026-10-14T20:00:00Z\nA @ B\n1H ML A -140 / B +120\n"
        with self.assertRaisesRegex(ManualLinePasteError, "PERIOD_NOT_SUPPORTED_FOR_SPORT"):
            parse_manual_line_paste(text)

    def test_mlb_lines_intake_period_field(self):
        self.assertEqual(period_for_market("FIRST_FIVE_MONEYLINE"), "F5")
        self.assertEqual(period_for_market("FIRST_FIVE_TEAM_TOTAL"), "F5")
        self.assertEqual(period_for_market("FIRST_INNING_TOTAL"), "FIRST_INNING")
        self.assertEqual(period_for_market("MONEYLINE"), "FULL_GAME")
        rows = parse_lines("Red Sox @ Yankees\nF5 ML +110 -130\nML +120 -140\n")
        self.assertEqual([period_for_market(r.market_type) for r in rows], ["F5", "FULL_GAME"])
