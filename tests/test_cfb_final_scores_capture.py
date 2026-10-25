import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load("capture_cfb_final_scores")
L = _load("cfb_probation_ledger")


def event(eid, away, home, ap, hp, name="STATUS_FINAL", done=True):
    return {"id": eid, "date": "2026-10-10T16:00Z", "competitions": [{
        "status": {"type": {"name": name, "completed": done}},
        "competitors": [
            {"homeAway": "away", "score": str(ap), "team": {"location": away, "displayName": away}},
            {"homeAway": "home", "score": str(hp), "team": {"location": home, "displayName": home}}]}]}


def play(market="TOTAL", side="UNDER", line=53.5):
    return {"game_id": "1", "away": "UCF", "home": "Oklahoma State", "market": market, "side": side,
            "line": line, "american_odds": -110.0, "stake_units": 0.25, "market_p_novig": 0.5,
            "result": None, "units": None, "clv_status": "PENDING", "clv_novig_pp": None}


class FinalsCapture(unittest.TestCase):
    def test_only_completed_finals_are_kept(self):
        rows = C.parse_scoreboard({"events": [
            event("1", "UCF", "Oklahoma State", 20, 24),
            event("2", "A", "B", 7, 3, name="STATUS_IN_PROGRESS", done=False),
            event("3", "C", "D", 10, 10, name="STATUS_FINAL_OT")]})
        self.assertEqual([r["game_id"] for r in rows], ["1", "3"])

    def test_merge_is_append_only_and_conflict_aborts(self):
        rows = C.parse_scoreboard({"events": [event("1", "UCF", "Oklahoma State", 20, 24)]})
        doc, added = C.merge(None, rows, date="2026-10-10", captured_at="t1")
        self.assertEqual(added, 1)
        doc, added = C.merge(doc, rows, date="2026-10-10", captured_at="t2")
        self.assertEqual((added, doc["games"][0]["captured_at_utc"]), (0, "t1"))
        bad = C.parse_scoreboard({"events": [event("1", "UCF", "Oklahoma State", 21, 24)]})
        with self.assertRaisesRegex(ValueError, "CFB_FINALS_CONFLICT"):
            C.merge(doc, bad, date="2026-10-10", captured_at="t3")

    def test_invalid_score_rejected(self):
        with self.assertRaisesRegex(ValueError, "SCORE_INVALID"):
            C.parse_scoreboard({"events": [event("1", "A", "B", "7.5", 3)]})

    def test_persisted_finals_grade_ledger_all_markets(self):
        rows = C.parse_scoreboard({"events": [event("1", "UCF", "Oklahoma State", 20, 24)]})
        doc, _ = C.merge(None, rows, date="2026-10-10", captured_at="t1")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-10-10.json"
            p.write_text(json.dumps(doc))
            scores = C.load_finals(p)
        led = {"plays": [play(), play("SPREAD", "AWAY", 3.5), play("MONEYLINE", "HOME", None),
                         play("TOTAL", "OVER", 44.0)]}
        L.grade(led, scores)
        self.assertEqual([x["result"] for x in led["plays"]], ["WIN", "LOSS", "WIN", "PUSH"])
        self.assertEqual(led["plays"][0]["final_score"], {"away": 20.0, "home": 24.0})
        self.assertEqual(led["plays"][1]["units"], -0.25)

    def test_unknown_game_stays_pending(self):
        doc, _ = C.merge(None, [], date="2026-10-10", captured_at="t")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps(doc))
            led = {"plays": [play()]}
            L.grade(led, C.load_finals(p))
        self.assertIsNone(led["plays"][0]["result"])

    def test_grade_cli_writes_new_snapshot_and_refuses_overwrite(self):
        doc, _ = C.merge(None, C.parse_scoreboard({"events": [event("1", "UCF", "Oklahoma State", 20, 24)]}),
                         date="2026-10-10", captured_at="t")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "f.json").write_text(json.dumps(doc))
            (d / "l.json").write_text(json.dumps({"plays": [play()]}))
            C.main(["grade", "--ledger", str(d / "l.json"), "--finals", str(d / "f.json"), "--output", str(d / "g.json")])
            self.assertEqual(json.loads((d / "g.json").read_text())["plays"][0]["result"], "WIN")
            self.assertIsNone(json.loads((d / "l.json").read_text())["plays"][0]["result"])
            with self.assertRaises(SystemExit):
                C.main(["grade", "--ledger", str(d / "l.json"), "--finals", str(d / "f.json"), "--output", str(d / "g.json")])

    def test_wrong_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps({"schema": "OTHER", "games": []}))
            with self.assertRaisesRegex(ValueError, "CFB_FINALS_SCHEMA_INVALID"):
                C.load_finals(p)


if __name__ == "__main__":
    unittest.main()
