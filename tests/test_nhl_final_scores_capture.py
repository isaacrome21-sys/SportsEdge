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


C = _load("capture_nhl_final_scores")
DATE = "2026-10-24"


def game(gid, away, home, ag, hg, state="OFF", gdate=DATE):
    def team(label, goals):
        place, _, common = label.rpartition(" ")
        return {"abbrev": label[:3].upper(), "score": goals,
                "placeName": {"default": place}, "commonName": {"default": common}}
    return {"id": gid, "gameDate": gdate, "gameType": 2, "gameState": state,
            "startTimeUTC": f"{gdate}T23:00:00Z",
            "awayTeam": team(away, ag), "homeTeam": team(home, hg)}


class FinalsCapture(unittest.TestCase):
    def test_only_completed_games_are_kept(self):
        rows = C.parse_scoreboard({"games": [
            game(2026020101, "New York Rangers", "Boston Bruins", 3, 4),
            game(2026020102, "A B", "C D", 1, 2, state="LIVE"),
            game(2026020103, "E F", "G H", 5, 4, state="FINAL"),
            game(2026020104, "I J", "K L", 2, 2, gdate="2026-10-25")]}, date=DATE)
        self.assertEqual([r["game_id"] for r in rows], ["2026020101", "2026020103"])
        self.assertEqual(rows[0]["away_team"], "New York Rangers")

    def test_merge_is_append_only_and_conflict_aborts(self):
        rows = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers", "Boston Bruins", 3, 4)]}, date=DATE)
        doc, added = C.merge(None, rows, date=DATE, captured_at="t1")
        self.assertEqual(added, 1)
        doc, added = C.merge(doc, rows, date=DATE, captured_at="t2")
        self.assertEqual((added, doc["games"][0]["captured_at_utc"]), (0, "t1"))
        bad = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers", "Boston Bruins", 3, 5)]}, date=DATE)
        with self.assertRaisesRegex(ValueError, "NHL_FINALS_CONFLICT"):
            C.merge(doc, bad, date=DATE, captured_at="t3")

    def test_invalid_score_rejected(self):
        g = game(2026020101, "New York Rangers", "Boston Bruins", 3, 4)
        g["awayTeam"]["score"] = 3.5
        with self.assertRaisesRegex(ValueError, "SCORE_INVALID"):
            C.parse_scoreboard({"games": [g]}, date=DATE)

    def test_missing_score_rejected(self):
        g = game(2026020101, "New York Rangers", "Boston Bruins", 3, 4)
        del g["homeTeam"]["score"]
        with self.assertRaisesRegex(ValueError, "TEAM_INVALID"):
            C.parse_scoreboard({"games": [g]}, date=DATE)

    def test_persisted_finals_load_for_ledger_join(self):
        rows = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers", "Boston Bruins", 3, 4)]}, date=DATE)
        doc, _ = C.merge(None, rows, date=DATE, captured_at="t1")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / f"{DATE}.json"
            p.write_text(json.dumps(doc))
            scores = C.load_finals(p)
        key = ("2026020101", C._norm("New York Rangers"), C._norm("Boston Bruins"))
        self.assertEqual(scores[key], (3, 4))

    def test_wrong_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text(json.dumps({"schema": "OTHER", "games": []}))
            with self.assertRaisesRegex(ValueError, "NHL_FINALS_SCHEMA_INVALID"):
                C.load_finals(p)

    def test_capture_cli_writes_date_file_from_saved_payload(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "score.json").write_text(json.dumps(
                {"games": [game(2026020101, "New York Rangers", "Boston Bruins", 3, 4)]}))
            out_dir = d / "nhl_finals"
            C.main(["capture", "--date", DATE, "--score-json", str(d / "score.json"),
                    "--output-dir", str(out_dir)])
            doc = json.loads((out_dir / f"{DATE}.json").read_text())
            self.assertEqual(doc["schema"], "NHL_FINAL_SCORES_V1")
            self.assertEqual(doc["games"][0]["home_points"], 4)


if __name__ == "__main__":
    unittest.main()
