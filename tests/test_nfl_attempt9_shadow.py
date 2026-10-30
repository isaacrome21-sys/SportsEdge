import copy
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts.capture_nfl_attempt9_prospective_predictions import capture, _first_write
from scripts.run_nfl_attempt9_shadow import run_shadow
from tests.test_nfl_attempt9_prospective_capture import _artifact, _write_schedule


class Attempt9ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schedule = self.root / "games.csv"
        _write_schedule(self.schedule)
        self.now = datetime(2026, 9, 20, 16, 0, tzinfo=timezone.utc)
        self.game_id = "2026_02_B_A"

    def quote(self, market="spread", line=-3.5):
        first, second = ("home", "away") if "spread" in market else ("over", "under")
        common = {"game_id": self.game_id, "bookmaker": "draftkings", "period": "FULL_GAME",
                  "observed_at": self.now.isoformat()}
        return {**common, "market": market, "line": line, "selection": first,
                "kickoff_utc": "2026-09-20T17:00:00+00:00", "outcomes": [
                    {**common, "selection": first, "line": line, "american_odds": -110},
                    {**common, "selection": second, "line": -line if "spread" in market else line, "american_odds": -110}]}

    def run_report(self, quotes):
        return run_shadow(schedule=self.schedule, quotes=quotes, now=self.now, code_sha="b" * 40)

    def test_frozen_inference_reaches_real_truth_gate_without_staking(self):
        report = self.run_report([self.quote(), self.quote("total", 45.5)])
        for row in report["rows"]:
            self.assertGreater(row["model_p"], 0)
            self.assertLess(row["model_p"], 1)
            self.assertEqual(row["decision"]["bet_status"], "BLOCKED")
            self.assertEqual(row["decision"]["kelly_fraction"], 0)
            self.assertEqual(row["stake"], 0)
        self.assertEqual(report["official_count"], 0)
        self.assertFalse(report["forward_evidence_authority"])
        self.assertEqual(len(report["market_coverage"]), 51)

    def test_integer_and_unsupported_markets_never_create_probability(self):
        quotes = [self.quote(line=-3), self.quote("moneyline"), self.quote("passing_yards")]
        report = self.run_report(quotes)
        self.assertIn("PUSH_MODEL_REQUIRED", report["rows"][0]["reason"])
        for row in report["rows"]:
            self.assertIsNone(row["model_p"])
            self.assertEqual(row["bet_status"], "BLOCKED")

    def test_bad_pair_provenance_and_time_fail_closed(self):
        mutations = [
            lambda q: q["outcomes"][1].update(bookmaker="fanduel"),
            lambda q: q["outcomes"][1].update(game_id="different"),
            lambda q: q["outcomes"][1].update(line=-3.5),
            lambda q: q["outcomes"].pop(),
            lambda q: q.update(period="FIRST_HALF"),
            lambda q: q.update(observed_at="2026-09-20T15:56:59Z"),
            lambda q: q.update(observed_at="2026-09-20T16:00:01Z"),
            lambda q: q.update(kickoff_utc="2026-09-20T18:00:00Z"),
            lambda q: q["outcomes"][1].update(observed_at="2026-09-20T15:59:59Z"),
            lambda q: q["outcomes"][1].update(period="FIRST_HALF"),
        ]
        for mutate in mutations:
            quote = self.quote()
            mutate(quote)
            row = self.run_report([quote])["rows"][0]
            self.assertIsNone(row["model_p"], row)
            self.assertEqual(row["bet_status"], "BLOCKED")

    def test_prices_cannot_change_model_probability(self):
        original = self.quote()
        changed = copy.deepcopy(original)
        changed["outcomes"][0]["american_odds"] = -200
        changed["outcomes"][1]["american_odds"] = 175
        a, b = self.run_report([original, changed])["rows"]
        self.assertEqual(a["model_p"], b["model_p"])
        self.assertEqual(a["raw_prediction"], b["raw_prediction"])
        self.assertNotEqual(a["decision"]["implied_probability"], b["decision"]["implied_probability"])

    def test_alternate_spread_uses_same_distribution_and_away_line_orientation(self):
        home = self.quote("alternate_spread", -6.5)
        away = copy.deepcopy(home)
        away["selection"] = "away"
        a, b = self.run_report([home, away])["rows"]
        self.assertAlmostEqual(a["model_p"] + b["model_p"], 1)
        self.assertEqual(a["raw_prediction"], b["raw_prediction"])

    def capture(self):
        return capture(artifact=_artifact(), schedule=self.schedule, output_dir=self.root / "predictions",
                       capture_code_git_sha="b" * 40, captured=self.now, horizon_days=9)

    def test_existing_prediction_mutation_is_detected(self):
        self.capture()
        path = self.root / "predictions" / (self.game_id + ".json")
        row = json.loads(path.read_text())
        row["raw_predicted_home_margin"] = 999
        path.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            self.capture()

    def test_atomic_first_write_never_overwrites(self):
        path = self.root / "first.json"
        _first_write(path, {"x": 1})
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            _first_write(path, {"x": 2})
        self.assertEqual(path.read_bytes(), before)

    def test_duplicate_schedule_cannot_double_count_history(self):
        lines = self.schedule.read_text().splitlines()
        self.schedule.write_text("\n".join(lines + [lines[1]]) + "\n")
        with self.assertRaisesRegex(ValueError, "DUPLICATE_GAME"):
            self.capture()

    def test_same_day_scores_do_not_change_frozen_date_batched_features(self):
        baseline = self.run_report([])["predictions"][0]["feature_values"]
        with self.schedule.open() as fh:
            rows = list(csv.DictReader(fh))
        extra = dict(rows[0])
        extra.update(game_id="same_day", gameday="2026-09-20", gametime="10:00",
                     home_score="99", away_score="0")
        with self.schedule.open("w") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows + [extra])
        actual = self.run_report([])["predictions"][0]["feature_values"]
        self.assertEqual(actual, baseline)

    def test_changed_kickoff_cannot_reuse_an_existing_prediction(self):
        self.capture()
        self.schedule.write_text(self.schedule.read_text().replace("2026-09-20,13:00", "2026-09-20,14:00"))
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH:kickoff_utc"):
            self.capture()

    def test_future_result_and_path_traversal_are_rejected(self):
        original = self.schedule.read_text()
        for changes, message in [({"home_score": "14"}, "FUTURE_GAME_HAS_SCORE"),
                                 ({"game_id": "../escape"}, "SCHEDULE_IDENTITY_INVALID")]:
            self.schedule.write_text(original)
            with self.schedule.open() as fh:
                rows = list(csv.DictReader(fh))
            rows[-1].update(changes)
            with self.schedule.open("w") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, message):
                self.capture()


if __name__ == "__main__":
    unittest.main()
