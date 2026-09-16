import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.settle_mlb_moneyline_forward_evidence_v2 import settle_v2
from sportsedge.mlb_moneyline_paper_decision import freeze_paper_decision


ARTIFACT = "a" * 64


def write_json(path: Path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prediction(now, start, *, model_p=0.55):
    return {
        "promotion_authority": False,
        "market": "MONEYLINE",
        "game_pk": 123,
        "away_team_id": 10,
        "home_team_id": 20,
        "away_team": "Away Club",
        "home_team": "Home Club",
        "model_side": "HOME",
        "model_p": model_p,
        "market_blind": True,
        "feature_asof_ts": (now - timedelta(minutes=20)).isoformat(),
        "prediction_generated_at_utc": (now - timedelta(minutes=15)).isoformat(),
        "event_start_ts": start.isoformat(),
        "model_artifact_sha256": ARTIFACT,
    }


def quote(start, observed, *, home_odds=120, away_odds=-140, obs_id="entry"):
    return {
        "promotion_authority": False,
        "sportsbook": "draftkings",
        "provider_event_id": "dk-123",
        "capture_observation_id": obs_id,
        "home_team": "Home Club",
        "away_team": "Away Club",
        "scheduled_start_utc": start.isoformat(),
        "observed_at_utc": observed.isoformat(),
        "model_artifact_sha256": ARTIFACT,
        "raw_sha256": "b" * 64,
        "moneyline": {
            "status": "OK",
            "home_price_american": home_odds,
            "away_price_american": away_odds,
        },
    }


def source(observed_at):
    raw = b'{"gamePk":123,"status":"Final"}'
    return {
        "settlement": {
            "game_pk": 123,
            "status": "FINAL",
            "away_team_id": 10,
            "home_team_id": 20,
            "away_score": 3,
            "home_score": 5,
        },
        "source_uri": "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk=123",
        "observed_at_utc": observed_at.isoformat(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": raw,
    }


class SettlementV2RunnerTest(unittest.TestCase):
    def roots(self, base):
        root = Path(base)
        return (
            root / "predictions",
            root / "quotes",
            root / "decisions",
            root / "evidence",
            root / "raw",
            root / "report.json",
        )

    def test_settles_only_pre_frozen_v2_bet(self):
        freeze_now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = freeze_now + timedelta(minutes=33)
        pred = prediction(freeze_now, start)
        entry = quote(start, freeze_now - timedelta(minutes=1), obs_id="entry")
        close = quote(start, start - timedelta(minutes=4), home_odds=-110, away_odds=-110, obs_id="close")
        decision = freeze_paper_decision(prediction=pred, quotes=[entry], now=freeze_now)
        self.assertEqual(decision["status"], "PAPER_BET_FROZEN")
        after = start + timedelta(hours=4)
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, report = self.roots(tmp)
            write_json(predictions / "p.json", pred)
            write_json(quotes / "entry.json", entry)
            write_json(quotes / "close.json", close)
            write_json(decisions / "d.json", decision)
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                report_path=report,
                now=after,
                settlement_fetcher=lambda game_pk: source(after),
            )
            files = list(evidence.rglob("*__v2.json"))
            self.assertEqual(len(files), 1)
            row = json.loads(files[0].read_text(encoding="utf-8"))
            raw_files = list(raw.rglob("*.json"))
        self.assertEqual(result["completed_v2_graded_bets"], 1)
        self.assertEqual(result["new_completed_v2_bets"], 1)
        self.assertEqual(result["close_rows_available"], 1)
        self.assertEqual(result["close_coverage"], 1.0)
        self.assertGreater(result["mean_clv_probability_points"], 0.0)
        self.assertEqual(result["next_checkpoint"], 50)
        self.assertEqual(result["checkpoint_evaluator_status"], "V2_CHECKPOINT_EVALUATOR_REQUIRED")
        self.assertEqual(row["status"], "FORWARD_EVIDENCE_COMPLETE_V2")
        self.assertEqual(row["selected_side"], "HOME")
        self.assertIs(row["promotion_authority"], False)
        self.assertEqual(len(raw_files), 1)

    def test_paper_pass_does_not_fetch_or_enter_denominator(self):
        freeze_now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = freeze_now + timedelta(minutes=33)
        pred = prediction(freeze_now, start, model_p=0.45)
        entry = quote(start, freeze_now - timedelta(minutes=1))
        decision = freeze_paper_decision(prediction=pred, quotes=[entry], now=freeze_now)
        self.assertEqual(decision["status"], "PAPER_PASS_FROZEN")
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, report = self.roots(tmp)
            write_json(predictions / "p.json", pred)
            write_json(quotes / "q.json", entry)
            write_json(decisions / "d.json", decision)
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                report_path=report,
                now=start + timedelta(hours=1),
                settlement_fetcher=lambda game_pk: calls.append(game_pk),
            )
        self.assertEqual(calls, [])
        self.assertEqual(result["paper_passes_frozen"], 1)
        self.assertEqual(result["completed_v2_graded_bets"], 0)
        self.assertEqual(result["new_completed_v2_bets"], 0)

    def test_legacy_completed_evidence_is_ignored_non_retroactively(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, report = self.roots(tmp)
            write_json(evidence / "legacy.json", {"status": "FORWARD_EVIDENCE_COMPLETE", "game_pk": 999})
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                report_path=report,
                now=datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc),
                settlement_fetcher=lambda game_pk: self.fail("legacy row must not be fetched"),
            )
        self.assertEqual(result["legacy_non_v2_completed_rows_ignored"], 1)
        self.assertEqual(result["completed_v2_graded_bets"], 0)
        self.assertIs(result["promotion_authority"], False)


if __name__ == "__main__":
    unittest.main()
