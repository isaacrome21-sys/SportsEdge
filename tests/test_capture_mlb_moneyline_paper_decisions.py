from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.capture_mlb_moneyline_paper_decisions import capture_decisions


ARTIFACT = "a" * 64


def write_json(path: Path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pred(now, start):
    return {
        "promotion_authority": False,
        "market": "MONEYLINE",
        "game_pk": 123,
        "away_team": "Away Club",
        "home_team": "Home Club",
        "model_side": "HOME",
        "model_p": 0.55,
        "market_blind": True,
        "feature_asof_ts": (now - timedelta(minutes=20)).isoformat(),
        "prediction_generated_at_utc": (now - timedelta(minutes=15)).isoformat(),
        "event_start_ts": start.isoformat(),
        "model_artifact_sha256": ARTIFACT,
    }


def q(start, observed):
    return {
        "promotion_authority": False,
        "sportsbook": "draftkings",
        "provider_event_id": "dk-123",
        "capture_observation_id": "obs-123",
        "home_team": "Home Club",
        "away_team": "Away Club",
        "scheduled_start_utc": start.isoformat(),
        "observed_at_utc": observed.isoformat(),
        "model_artifact_sha256": ARTIFACT,
        "raw_sha256": "b" * 64,
        "moneyline": {"status": "OK", "home_price_american": 120, "away_price_american": -140},
    }


class CapturePaperDecisionTest(unittest.TestCase):
    def test_create_only_decision_then_identical_rerun_is_already_captured(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            predictions = root / "predictions"
            quotes = root / "quotes"
            decisions = root / "decisions"
            write_json(predictions / "p.json", pred(now, start))
            write_json(quotes / "q.json", q(start, now - timedelta(minutes=1)))
            first = capture_decisions(
                prediction_root=predictions, quote_root=quotes, decision_root=decisions, now=now
            )
            self.assertEqual(first["status"], "RETAINED")
            self.assertEqual(first["decisions_retained"], 1)
            decision_path = Path(first["retained_paths"][0])
            before = decision_path.read_bytes()
            second = capture_decisions(
                prediction_root=predictions, quote_root=quotes, decision_root=decisions, now=now
            )
            self.assertEqual(second["status"], "ALREADY_CAPTURED")
            self.assertEqual(decision_path.read_bytes(), before)

    def test_missed_window_is_persisted_blocked_not_graded(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=29)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            predictions = root / "predictions"
            quotes = root / "quotes"
            decisions = root / "decisions"
            write_json(predictions / "p.json", pred(now, start))
            out = capture_decisions(
                prediction_root=predictions, quote_root=quotes, decision_root=decisions, now=now
            )
            self.assertEqual(out["status"], "BLOCKED_MISSED_DECISION_WINDOW")
            self.assertEqual(out["newly_blocked_game_pks"], [123])
            row = json.loads(Path(out["retained_paths"][0]).read_text(encoding="utf-8"))
            self.assertEqual(row["status"], "BLOCKED_MISSED_DECISION_FREEZE")
            self.assertIs(row["evidence_counts"], False)
            self.assertIs(row["graded_bet"], False)


if __name__ == "__main__":
    unittest.main()
