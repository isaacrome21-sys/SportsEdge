from datetime import datetime, timedelta, timezone
import copy
import unittest

from sportsedge.mlb_moneyline_paper_decision import freeze_paper_decision
from sportsedge.mlb_moneyline_v2_settlement import (
    MLBMoneylineV2SettlementError,
    complete_v2_evidence,
)


ARTIFACT = "a" * 64


def prediction(now, start, model_p=0.55):
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


def quote(start, observed, *, home_odds=120, away_odds=-140):
    return {
        "promotion_authority": False,
        "sportsbook": "draftkings",
        "provider_event_id": "dk-123",
        "capture_observation_id": f"obs-{int(observed.timestamp())}",
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


def frozen_bet(now, start):
    pred = prediction(now, start)
    entry = quote(start, now - timedelta(minutes=1))
    decision = freeze_paper_decision(prediction=pred, quotes=[entry], now=now)
    assert decision["status"] == "PAPER_BET_FROZEN"
    return pred, entry, decision


class MLBMoneylineV2SettlementTest(unittest.TestCase):
    def test_settles_pre_frozen_bet_and_computes_positive_market_clv(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        pred, entry, decision = frozen_bet(now, start)
        close = quote(start, start - timedelta(minutes=5), home_odds=-110, away_odds=-110)
        out = complete_v2_evidence(
            decision=decision,
            prediction=pred,
            quotes=[entry, close],
            settlement={"game_pk": 123, "status": "FINAL", "home_score": 5, "away_score": 3},
        )
        self.assertEqual(out["status"], "FORWARD_EVIDENCE_COMPLETE_V2")
        self.assertEqual(out["state"], "PAPER")
        self.assertIs(out["graded_bet"], True)
        self.assertEqual(out["stake_units"], 0.0)
        self.assertEqual(out["close_status"], "AVAILABLE")
        self.assertGreater(out["clv_probability_points"], 0.0)
        self.assertEqual(
            out["clv_metric"],
            "SELECTED_SIDE_CLOSE_FAIR_PROBABILITY_MINUS_ENTRY_FAIR_PROBABILITY",
        )
        self.assertEqual(out["outcome"], 1)
        self.assertGreater(out["paper_profit_units_per_1u"], 0.0)
        self.assertIs(out["promotion_authority"], False)

    def test_missing_close_still_counts_graded_bet_but_is_excluded_from_clv(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        pred, _entry, decision = frozen_bet(now, start)
        out = complete_v2_evidence(
            decision=decision,
            prediction=pred,
            quotes=[],
            settlement={"game_pk": 123, "status": "FINAL", "home_score": 2, "away_score": 4},
        )
        self.assertEqual(out["close_status"], "MISSING")
        self.assertIsNone(out["clv_probability_points"])
        self.assertEqual(out["close_coverage_value"], 0)
        self.assertIs(out["missing_close_counts_in_checkpoint_denominator"], True)
        self.assertIs(out["missing_close_excluded_from_clv"], True)
        self.assertEqual(out["outcome"], 0)
        self.assertEqual(out["paper_profit_units_per_1u"], -1.0)

    def test_paper_pass_cannot_be_settled_as_graded_bet(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        pred = prediction(now, start, model_p=0.45)
        entry = quote(start, now - timedelta(minutes=1))
        decision = freeze_paper_decision(prediction=pred, quotes=[entry], now=now)
        self.assertEqual(decision["status"], "PAPER_PASS_FROZEN")
        with self.assertRaisesRegex(MLBMoneylineV2SettlementError, "only frozen PAPER bets"):
            complete_v2_evidence(
                decision=decision,
                prediction=pred,
                quotes=[entry],
                settlement={"game_pk": 123, "status": "FINAL", "home_score": 5, "away_score": 3},
            )

    def test_mutated_post_window_decision_freeze_is_rejected(self):
        now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = now + timedelta(minutes=33)
        pred, entry, decision = frozen_bet(now, start)
        bad = copy.deepcopy(decision)
        bad["decision_frozen_at_utc"] = (start - timedelta(minutes=20)).isoformat()
        with self.assertRaisesRegex(MLBMoneylineV2SettlementError, "outside frozen"):
            complete_v2_evidence(
                decision=bad,
                prediction=pred,
                quotes=[entry],
                settlement={"game_pk": 123, "status": "FINAL", "home_score": 5, "away_score": 3},
            )


if __name__ == "__main__":
    unittest.main()
