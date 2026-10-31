import csv
import gzip
import io
import json
from contextlib import redirect_stderr
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

RECEIPT_SHA = "a" * 64  # Synthetic verifier fixture, NOT provider evidence.
ENTRY_RECEIPT_SHA = "c" * 64


def with_verified_entry(ledger):
    # Synthetic test fixture only; NEVER a real authenticated DK entry.
    ledger["plays"][0].update(
        entry_receipt_sha256=ENTRY_RECEIPT_SHA,
        entry_source_sha256="d" * 64,
        entry_provider="DraftKings",
        entry_source_type="rendered_browser",
        entry_captured_at_utc="2026-10-10T14:00:00Z",
    )
    return ledger



def verified_close(**overrides):
    item = {
        "game_id": "1", "away": "UCF", "home": "Oklahoma State",
        "start_ts": "2026-10-10T16:00:00Z",
        "captured_at_utc": "2026-10-10T15:55:00Z",
        "authorized_close_cutoff_utc": "2026-10-10T15:59:00Z",
        "provider": "DraftKings", "source_type": "rendered_browser",
        "source_sha256": "b" * 64, "receipt_sha256": RECEIPT_SHA,
    }
    item.update(overrides)
    return item



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
        w = csv.DictWriter(fh, fieldnames=["game_id", "away_team", "home_team", "away_points", "home_points", "completed"])
        w.writeheader()
        for a, h, ap, hp, done in games:
            w.writerow({"game_id": "1", "away_team": a, "home_team": h, "away_points": ap, "home_points": hp, "completed": done})


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
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv.gz"
            schedule(path, [("UCF", "Oklahoma State", 20, 27, "true")])
            close = [verified_close(total=[53.5, -105, -115])]
            L.grade(led, L.load_final_scores(path), close,
                    verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
        p = led["plays"][0]
        self.assertEqual(p["result"], "WIN")
        self.assertAlmostEqual(p["units"], round(0.25 * 100 / 108, 4))
        self.assertEqual(p["clv_status"], "EXACT_CONTRACT")
        self.assertGreater(p["clv_novig_pp"], 0)  # closed at -115 on the Under: beat the close

    def test_line_move_makes_clv_unavailable_not_repriced(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        L.grade(led, {}, [verified_close(total=[52.5, -110, -110])],
                verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
        p = led["plays"][0]
        self.assertIsNone(p["result"])
        self.assertEqual(p["clv_status"], "UNAVAILABLE_UNVERIFIED_OR_MISMATCHED_CLOSE")
        self.assertIsNone(p["clv_novig_pp"])

    def test_unfinished_game_stays_pending(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv.gz"
            schedule(path, [("UCF", "Oklahoma State", "", "", "false")])
            L.grade(led, L.load_final_scores(path))
        self.assertIsNone(led["plays"][0]["result"])

    def test_other_meeting_does_not_settle(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        L.grade(led, {("other-game", "ucf", "oklahoma state"): (20, 27)})
        self.assertIsNone(led["plays"][0]["result"])

    def test_invalid_final_score_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv.gz"
            schedule(path, [("UCF", "Oklahoma State", "nan", 27, "true")])
            with self.assertRaisesRegex(ValueError, "FINAL_SCORE_INVALID"):
                L.load_final_scores(path)

    def test_spread_close_handles_flipped_board(self):
        led = with_verified_entry(L.record(card([row(market="SPREAD", side="AWAY", line=10.5)]), card_sha256="b" * 64, recorded_at=NOW))
        close = [verified_close(away="Oklahoma State", home="UCF", spread=[-10.5, -120, 100])]
        L.grade(led, {}, close, verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
        p = led["plays"][0]
        self.assertEqual(p["clv_status"], "EXACT_CONTRACT")
        self.assertEqual((p["close_odds"], p["close_opposite_odds"]), (100.0, -120.0))


    def test_legacy_name_only_close_never_authenticates(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        L.grade(led, {}, [{"away": "UCF", "home": "Oklahoma State",
                           "total": [53.5, -105, -115], "authenticated": True}])
        p = led["plays"][0]
        self.assertEqual(p["clv_status"], "UNAVAILABLE_UNVERIFIED_OR_MISMATCHED_CLOSE")
        self.assertIsNone(p["clv_novig_pp"])

    def test_untrusted_row_flag_and_sha_do_not_substitute_for_verifier(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        L.grade(led, {}, [verified_close(total=[53.5, -105, -115], authenticated=True)])
        self.assertIsNone(led["plays"][0]["clv_novig_pp"])

    def test_wrong_game_clock_or_provider_refused(self):
        for change in (
            {"game_id": "UNRELATED_GAME"},
            {"start_ts": "2026-10-11T16:00:00Z"},
            {"captured_at_utc": "2026-10-10T16:01:00Z"},
            {"captured_at_utc": "2026-10-10T16:00:00Z",
             "authorized_close_cutoff_utc": "2026-10-10T16:00:00Z"},
            {"captured_at_utc": "2026-10-10T13:59:00Z"},
            {"captured_at_utc": "NOT_A_TIME"},
            {"provider": "OTHER_BOOK"},
            {"source_type": "direct_json"},
            {"receipt_sha256": "not-a-sha"},
            {"source_sha256": "bogus"},
        ):
            with self.subTest(change=change):
                led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
                L.grade(led, {}, [verified_close(total=[53.5, -105, -115], **change)],
                        verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
                self.assertIsNone(led["plays"][0]["clv_novig_pp"])

    def test_missing_authenticated_entry_receipt_refused(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        del led["plays"][0]["entry_receipt_sha256"]
        L.grade(led, {}, [verified_close(total=[53.5, -105, -115])],
                verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
        self.assertIsNone(led["plays"][0]["clv_novig_pp"])

    def test_moved_line_before_valid_same_event_does_not_block(self):
        led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
        board = [verified_close(total=[52.5, -110, -110]),
                 verified_close(total=[53.5, -105, -115])]
        L.grade(led, {}, board, verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
        self.assertEqual(led["plays"][0]["clv_status"], "EXACT_CONTRACT")

    def test_duplicate_or_conflicting_exact_closes_refused(self):
        for prices in ((-105, -115), (-110, -110)):
            with self.subTest(prices=prices):
                led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
                board = [verified_close(total=[53.5, -105, -115]),
                         verified_close(total=[53.5, *prices])]
                L.grade(led, {}, board, verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
                self.assertIsNone(led["plays"][0]["clv_novig_pp"])

    def test_invalid_american_prices_fail_closed(self):
        for price in (float("nan"), float("inf"), 0, -99, True, "bad"):
            with self.subTest(price=price):
                led = with_verified_entry(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW))
                L.grade(led, {}, [verified_close(total=[53.5, price, -110])],
                        verified_receipt_shas=frozenset({RECEIPT_SHA, ENTRY_RECEIPT_SHA}))
                self.assertIsNone(led["plays"][0]["clv_novig_pp"])


class CliSafetyTest(unittest.TestCase):
    def test_record_cli_rejects_supplied_historical_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "card.json"
            source.write_text(json.dumps(card([row()])))
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                L.main(["record", "--card", str(source), "--output", str(root / "ledger.json"),
                        "--recorded-at", "2026-10-10T10:00:00Z"])
            self.assertEqual(caught.exception.code, 2)
            self.assertFalse((root / "ledger.json").exists())

    def test_grade_cli_preserves_original_pregame_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pregame.json"
            source.write_text(json.dumps(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW)))
            original = source.read_bytes()
            scores = root / "scores.csv.gz"
            schedule(scores, [("UCF", "Oklahoma State", 20, 27, "true")])
            output = root / "settled.json"
            self.assertEqual(L.main(["grade", "--ledger", str(source),
                                     "--scores", str(scores), "--output", str(output)]), 0)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(json.loads(output.read_text())["plays"][0]["result"], "WIN")

    def test_grade_cli_refuses_overwrite_even_with_explicit_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pregame.json"
            source.write_text(json.dumps(L.record(card([row()]), card_sha256="b" * 64, recorded_at=NOW)))
            scores = root / "scores.csv.gz"
            schedule(scores, [("UCF", "Oklahoma State", 20, 27, "true")])
            with self.assertRaisesRegex(SystemExit, "CFB_LEDGER_IMMUTABLE_OUTPUT_REQUIRED"):
                L.main(["grade", "--ledger", str(source), "--scores", str(scores),
                        "--output", str(source)])


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

    def test_missing_clv_is_not_negative_evidence(self):
        plays = self.plays(100, 1.0)
        for p in plays:
            p.update(clv_status="PENDING", clv_novig_pp=None)
        result = L.summarize([{"plays": plays}])["markets"]["TOTAL"]
        self.assertEqual(result["decision"], "CONTINUE")
        self.assertEqual(result["clv_n"], 0)

    def test_ungraded_clv_does_not_promote(self):
        plays = self.plays(100, 1.0)
        for p in plays:
            p.update(result=None, units=None)
        result = L.summarize([{"plays": plays}])["markets"]["TOTAL"]
        self.assertEqual(result["clv_n"], 0)

    def test_small_sample_continues(self):
        s = L.summarize([{"plays": self.plays(10, -2.0, "LOSS")}])
        self.assertEqual(s["markets"]["TOTAL"]["decision"], "CONTINUE")


if __name__ == "__main__":
    unittest.main()
