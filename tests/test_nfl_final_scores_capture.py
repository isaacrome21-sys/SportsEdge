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


C = _load("capture_nfl_final_scores")


def event(eid, away, home, ap, hp, name="STATUS_FINAL", done=True):
    return {"id": eid, "date": "2026-10-25T17:00Z", "competitions": [{
        "status": {"type": {"name": name, "completed": done}},
        "competitors": [
            {"homeAway": "away", "score": str(ap), "team": {"location": away, "displayName": away}},
            {"homeAway": "home", "score": str(hp), "team": {"location": home, "displayName": home}}]}]}


class FinalsCapture(unittest.TestCase):
    def test_only_completed_finals_are_kept(self):
        rows = C.parse_scoreboard({"events": [
            event("1", "Buffalo", "Kansas City", 20, 24),
            event("2", "A", "B", 7, 3, name="STATUS_IN_PROGRESS", done=False),
            event("3", "C", "D", 30, 27, name="STATUS_FINAL_OT")]})
        self.assertEqual([r["game_id"] for r in rows], ["1", "3"])

    def test_merge_is_append_only_and_conflict_aborts(self):
        rows = C.parse_scoreboard({"events": [event("1", "Buffalo", "Kansas City", 20, 24)]})
        doc, added = C.merge(None, rows, date="2026-10-25", captured_at="t1")
        self.assertEqual(added, 1)
        doc, added = C.merge(doc, rows, date="2026-10-25", captured_at="t2")
        self.assertEqual((added, doc["games"][0]["captured_at_utc"]), (0, "t1"))
        bad = C.parse_scoreboard({"events": [event("1", "Buffalo", "Kansas City", 21, 24)]})
        with self.assertRaisesRegex(ValueError, "NFL_FINALS_CONFLICT"):
            C.merge(doc, bad, date="2026-10-25", captured_at="t3")

    def test_invalid_score_rejected(self):
        with self.assertRaisesRegex(ValueError, "SCORE_INVALID"):
            C.parse_scoreboard({"events": [event("1", "A", "B", "7.5", 3)]})

    def test_persisted_finals_load_for_ledger_join(self):
        rows = C.parse_scoreboard({"events": [event("1", "Buffalo", "Kansas City", 20, 24)]})
        doc, _ = C.merge(None, rows, date="2026-10-25", captured_at="t1")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-10-25.json"
            p.write_text(json.dumps(doc))
            scores = C.load_finals(p)
        key = ("1", C._norm("Buffalo"), C._norm("Kansas City"))
        self.assertEqual(scores[key], (20, 24))

    def test_wrong_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps({"schema": "OTHER", "games": []}))
            with self.assertRaisesRegex(ValueError, "NFL_FINALS_SCHEMA_INVALID"):
                C.load_finals(p)

    def test_capture_cli_writes_date_file_from_saved_payload(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sb.json").write_text(json.dumps({"events": [event("1", "Buffalo", "Kansas City", 20, 24)]}))
            out_dir = d / "nfl_finals"
            C.main(["capture", "--date", "2026-10-25", "--scoreboard-json", str(d / "sb.json"),
                    "--output-dir", str(out_dir)])
            doc = json.loads((out_dir / "2026-10-25.json").read_text())
            self.assertEqual(doc["schema"], "NFL_FINAL_SCORES_V1")
            self.assertEqual(doc["games"][0]["away_points"], 20)


if __name__ == "__main__":
    unittest.main()
