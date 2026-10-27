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


    def test_cli_rejects_date_path_escape_before_io(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            payload = d / "score.json"
            payload.write_text(json.dumps({"games": []}))
            out_dir = d / "finals"
            for bad in ("../escape", "../../escape", "2026-02-30", "2026-1-1"):
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "DATE_INVALID"):
                    C.main(["capture", "--date", bad, "--score-json", str(payload),
                            "--output-dir", str(out_dir)])
            self.assertFalse(out_dir.exists())
            self.assertFalse((d / "escape.json").exists())

    def test_missing_game_date_cannot_bind_to_requested_day(self):
        g = game(2026020101, "New York Rangers", "Boston Bruins", 3, 4)
        del g["gameDate"]
        with self.assertRaisesRegex(ValueError, "GAME_DATE_MISSING"):
            C.parse_scoreboard({"games": [g]}, date=DATE)

    def test_invalid_scoreboard_body_fails_closed(self):
        for value in ({}, {"games": None}, {"games": [{}]}, {"games": "not-list"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                C.parse_scoreboard(value, date=DATE)

    def test_existing_source_or_day_conflict_fails_closed(self):
        rows = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers",
                                                   "Boston Bruins", 3, 4)]}, date=DATE)
        doc, _ = C.merge(None, rows, date=DATE, captured_at="t1")
        for key, value in (("date", "2026-10-25"), ("source", "UNVERIFIED")):
            altered = {**doc, key: value}
            with self.subTest(key=key), self.assertRaisesRegex(
                ValueError, "EXISTING_SOURCE_DATE_CONFLICT"
            ):
                C.merge(altered, rows, date=DATE, captured_at="t2")

    def test_same_game_id_and_score_wrong_teams_is_conflict(self):
        a = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers",
                                                "Boston Bruins", 3, 4)]}, date=DATE)
        b = C.parse_scoreboard({"games": [game(2026020101, "New York Islanders",
                                                "Boston Bruins", 3, 4)]}, date=DATE)
        doc, _ = C.merge(None, a, date=DATE, captured_at="t1")
        with self.assertRaisesRegex(ValueError, "NHL_FINALS_CONFLICT"):
            C.merge(doc, b, date=DATE, captured_at="t2")

    def test_duplicate_persisted_game_id_cannot_grade_twice(self):
        rows = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers",
                                                   "Boston Bruins", 3, 4)]}, date=DATE)
        doc, _ = C.merge(None, rows, date=DATE, captured_at="t1")
        doc["games"].append(dict(doc["games"][0]))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dup.json"
            p.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, "DUPLICATE_GAME_ID"):
                C.load_finals(p)


    def test_corrupt_empty_archive_is_not_treated_as_new(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "score.json").write_text(json.dumps({"games": []}))
            out_dir = d / "nhl_finals"
            out_dir.mkdir()
            p = out_dir / f"{DATE}.json"
            p.write_text("{}")
            with self.assertRaisesRegex(ValueError, "NHL_FINALS_SCHEMA_INVALID"):
                C.main(["capture", "--date", DATE, "--score-json", str(d / "score.json"),
                        "--output-dir", str(out_dir)])
            self.assertEqual(p.read_text(), "{}")

    def test_existing_duplicate_ids_cannot_be_merged(self):
        rows = C.parse_scoreboard({"games": [game(2026020101, "New York Rangers",
                                                   "Boston Bruins", 3, 4)]}, date=DATE)
        doc, _ = C.merge(None, rows, date=DATE, captured_at="t1")
        doc["games"].append(dict(doc["games"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_GAME_ID"):
            C.merge(doc, [], date=DATE, captured_at="t2")


if __name__ == "__main__":
    unittest.main()
