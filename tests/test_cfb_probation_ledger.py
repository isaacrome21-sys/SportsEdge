import csv
import gzip
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cfb_probation_ledger", ROOT / "scripts" / "cfb_probation_ledger.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def card(rows):
    return {"schema": "CFB_SDV_CARD_V2", "scored_at_utc": NOW.isoformat(),
            "probation": {"policy": "CFB_PROBATION_POLICY_V1", "policy_sha256": "a" * 64,
                          "slate_total_bias_signal": "MODEL_HIGH"},
            "results": rows}


def row(market="TOTAL", side="UNDER", line=53.5, odds=-108, start="2026-10-10T16:00:00Z", probation=True):
    return {"game_id": "1", "matchup": "UCF @ Oklahoma State", "market": market, "side": side,
            "line": line, "american_odds": odds, "stake_units": 0.25, "model_p": .56, "market_p": .496,
            "edge": .064, "bet_status": "LEAN", "probation": probation, "start_ts": start,
            "home_mean": 26.3, "away_mean": 24.6}


def schedule(path, games):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["away_team", "home_team", "away_points", "home_points", "completed"])
        w.writeheader()
        for a, h, ap, hp, done in games:
            w.writerow({"away_team": a, "home_team": h, "away_points": ap, "home_points": hp, "completed": done})


class RecordTest(unittest.TestCase):
    def test_records_only_probation_rows(self):
        led = L.record(card([row(), row(probation=False)]), card_sha256="b" * 64, recorded_at=NOW)
        self.assertEqual(len(led["plays"]), 1)
        p = led["plays"][0]
        self.assertEqual((p["away"], p["home"], p["market"], p["side"], p["line"]), ("UCF", "Oklahoma State", "TOTAL", "UNDER", 53.5))
        self.assertFalse(led["official"])

    def test_refuses_backfill_after_kickoff(self):
        with self.assertRaisesRegex(ValueError, "NO_BACKFILL"):
            L.record(card([row(start="2026-10-10T09:00:00Z")]), card_sha256="b" * 64, recorded_at=NOW)

    def test_requires_probation_block(self):
        c = card([row()])
        c.pop("probation")
        with self.assertRaisesRegex(ValueError, "PROBATION_BLOCK_MISSING"):
            L.record(c, card_sha256="b" * 64, recorded_at=NOW)


class SettleTest(unittest.TestCase):
    def p(self, market, side, line):
        return {"market": market, "side": side, "line": line}

    def test_totals(self):
        self.assertEqual(L.settle(self.p("TOTAL", "UNDER", 53.5), 20, 30), "WIN")
        self.assertEqual(L.settle(self.p("TOTAL", "UNDER", 53.5), 30, 30), "LOSS")
        self.assertEqual(L.settle(self.p("TOTAL", "OVER", 50), 20, 30), "PUSH")

    def test_spreads_and_ml(self):
        self.assertEqual(L.settle(self.p("SPREAD", "AWAY", 7.5), 21, 28), "WIN")
        self.assertEqual(L.settle(self.p("SPREAD", "HOME", -7.5), 21, 28), "LOSS")
        self.assertEqual(L.settle(self.p("SPREAD", "HOME", -7), 21, 28), "PUSH")
        self.assertEqual(L.settle(self.p("MONEYLINE", "AWAY", None), 31, 28), "WIN")


class GradeTest(unittest.TestCase):
    def test_grade_units_and_exact_clv(self):
        led = L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv.gz"
            schedule(path, [("UCF", "Oklahoma State", 20, 27, "true")])
            close = [{"away": "UCF", "home": "Oklahoma State", "total": [53.5, -105, -115]}]
            L.grade(led, L.load_final_scores(path), close)
        p = led["plays"][0]
        self.assertEqual(p["result"], "WIN")
        self.assertAlmostEqual(p["units"], round(0.25 * 100 / 108, 4))
        self.assertEqual(p["clv_status"], "EXACT_CONTRACT")
        self.assertGreater(p["clv_novig_pp"], 0)  # closed at -115 on the Under: beat the close

    def test_line_move_makes_clv_unavailable_not_repriced(self):
        led = L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW)
        L.grade(led, {}, [{"away": "UCF", "home": "Oklahoma State", "total": [52.5, -110, -110]}])
        p = led["plays"][0]
        self.assertIsNone(p["result"])
        self.assertEqual(p["clv_status"], "UNAVAILABLE_LINE_MOVED_OR_MISSING")
        self.assertIsNone(p["clv_novig_pp"])

    def test_unfinished_game_stays_pending(self):
        led = L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv.gz"
            schedule(path, [("UCF", "Oklahoma State", "", "", "false")])
            L.grade(led, L.load_final_scores(path))
        self.assertIsNone(led["plays"][0]["result"])

    def test_spread_close_handles_flipped_board(self):
        led = L.record(card([row(market="SPREAD", side="AWAY", line=10.5)]), card_sha256="b" * 64, recorded_at=NOW)
        close = [{"away": "Oklahoma State", "home": "UCF", "spread": [-10.5, -120, 100]}]
        L.grade(led, {}, close)
        p = led["plays"][0]
        self.assertEqual(p["clv_status"], "EXACT_CONTRACT")
        self.assertEqual((p["close_odds"], p["close_opposite_odds"]), (100.0, -120.0))


class SummaryTest(unittest.TestCase):
    def plays(self, n, clv, result="WIN"):
        return [{"market": "TOTAL", "result": result, "units": .2 if result == "WIN" else -.25, "stake_units": .25,
                 "clv_status": "EXACT_CONTRACT", "clv_novig_pp": clv + (i % 3 - 1) * .1} for i in range(n)]

    def test_kill_after_50_negative_clv(self):
        s = L.summarize([{"plays": self.plays(50, -1.0, "LOSS")}])
        self.assertEqual(s["markets"]["TOTAL"]["decision"], "KILL")

    def test_promotion_review_after_100_positive_clv(self):
        s = L.summarize([{"plays": self.plays(100, 1.0)}])
        self.assertEqual(s["markets"]["TOTAL"]["decision"], "PROMOTION_REVIEW")
        self.assertFalse(s["official"])

    def test_small_sample_continues(self):
        s = L.summarize([{"plays": self.plays(10, -2.0, "LOSS")}])
        self.assertEqual(s["markets"]["TOTAL"]["decision"], "CONTINUE")


if __name__ == "__main__":
    unittest.main()
