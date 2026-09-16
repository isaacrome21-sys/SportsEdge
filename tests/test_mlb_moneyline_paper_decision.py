from datetime import datetime, timedelta, timezone
import inspect
import unittest

from sportsedge.mlb_moneyline_forward_lane import load_forward_lane_binding, require_record_binding
from sportsedge.mlb_moneyline_paper_decision import (
    MLBMoneylinePaperDecisionError,
    freeze_paper_decision,
)


ARTIFACT = "a" * 64


def prediction(now, start, *, model_p=0.55):
    return {
        "schema_version": "mlb_moneyline_forward_model_p_v1",
        "promotion_authority": False,
        "market": "MONEYLINE",
        "game_pk": 123,
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


def quote(start, observed, *, home_odds=120, away_odds=-140, artifact=ARTIFACT):
    return {
        "evidence_disposition": "FORWARD_CAPTURE_PARTIAL",
        "promotion_authority": False,
        "sportsbook": "draftkings",
        "provider_event_id": "dk-123",
        "capture_observation_id": "dk-123__T30__x",
        "home_team": "Home Club",
        "away_team": "Away Club",
        "scheduled_start_utc": start.isoformat(),
        "observed_at_utc": observed.isoformat(),
        "capture_window": "T30",
        "model_artifact_sha256": artifact,
        "raw_sha256": "b" * 64,
        "moneyline": {
            "status": "OK",
            "home_price_american": home_odds,
            "away_price_american": away_odds,
        },
    }


class MLBMoneylinePaperDecisionTest(unittest.TestCase):
    def test_freezes_zero_stake_paper_bet_inside_window(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        out = freeze_paper_decision(
            prediction=prediction(now, start, model_p=0.55),
            quotes=[quote(start, now - timedelta(minutes=1))],
            now=now,
        )
        self.assertEqual(out["status"], "PAPER_BET_FROZEN")
        self.assertEqual(out["state"], "PAPER")
        self.assertEqual(out["stake_units"], 0.0)
        self.assertIs(out["graded_bet"], True)
        self.assertIs(out["evidence_counts"], True)
        self.assertEqual(out["selected_side"], "HOME")
        self.assertGreater(out["selected_edge_probability_points"], out["effective_edge_floor_probability_points"])
        self.assertGreater(out["selected_ev_per_dollar"], 0.0)
        self.assertIs(out["outcome_or_postgame_data_consumed"], False)
        self.assertIs(out["promotion_authority"], False)
        self.assertIs(out["staking_change_allowed"], False)
        self.assertIs(out["official_change_allowed"], False)
        require_record_binding(out, load_forward_lane_binding())

    def test_freezes_paper_pass_when_edge_floor_not_met(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        out = freeze_paper_decision(
            prediction=prediction(now, start, model_p=0.45),
            quotes=[quote(start, now - timedelta(minutes=1))],
            now=now,
        )
        self.assertEqual(out["status"], "PAPER_PASS_FROZEN")
        self.assertIs(out["graded_bet"], False)
        self.assertIs(out["evidence_counts"], False)
        self.assertIsNone(out["selected_side"])
        self.assertEqual(out["stake_units"], 0.0)

    def test_late_wall_clock_cannot_backfill_decision(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=29)
        out = freeze_paper_decision(
            prediction=prediction(now, start, model_p=0.55),
            quotes=[quote(start, now - timedelta(minutes=4))],
            now=now,
        )
        self.assertEqual(out["status"], "BLOCKED_MISSED_DECISION_FREEZE")
        self.assertEqual(out["state"], "BLOCKED")
        self.assertIs(out["evidence_counts"], False)
        self.assertIs(out["graded_bet"], False)

    def test_before_window_is_not_due(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=40)
        out = freeze_paper_decision(
            prediction=prediction(now, start), quotes=[], now=now
        )
        self.assertEqual(out["status"], "DECISION_NOT_DUE")

    def test_inside_window_without_quote_waits_not_backfills(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        out = freeze_paper_decision(
            prediction=prediction(now, start), quotes=[], now=now
        )
        self.assertEqual(out["status"], "WAITING_FOR_ADMISSIBLE_DECISION_QUOTE")

    def test_matching_quote_with_wrong_artifact_fails_closed(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        with self.assertRaisesRegex(MLBMoneylinePaperDecisionError, "artifact mismatch"):
            freeze_paper_decision(
                prediction=prediction(now, start),
                quotes=[quote(start, now - timedelta(minutes=1), artifact="c" * 64)],
                now=now,
            )

    def test_public_api_has_no_settlement_or_outcome_input(self):
        params = set(inspect.signature(freeze_paper_decision).parameters)
        self.assertNotIn("settlement", params)
        self.assertNotIn("outcome", params)


if __name__ == "__main__":
    unittest.main()
