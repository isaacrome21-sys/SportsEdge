import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.analyze_market_maker_radar import load_policy
from scripts.settle_market_maker_candidate_ledger import (
    _persist_settlement,
    settle_candidate,
    summarize,
)

UTC = timezone.utc
POLICY = load_policy("config/market_maker_radar_v2.json")


def pin_row(*, capture, captured_at, outcome, price, market="h2h", point=None):
    return {
        "capture_id": capture,
        "captured_at": captured_at,
        "commence_time": "2026-09-14T18:00:00Z",
        "event_id": "game-1",
        "sport_key": "americanfootball_nfl",
        "book": "pinnacle",
        "market": market,
        "outcome": outcome,
        "point": point,
        "price_american": price,
        "provider_retrieved_at": captured_at,
        "cross_book_retrieval_skew_seconds": 2.0,
        "leadership_timing_eligible": True,
        "timing_hygiene_version": "RADAR_TIMING_HYGIENE_V2",
    }


def candidate(*, market="h2h", point=None):
    return {
        "record_type": "MARKET_MAKER_RADAR_STALE_PRICE_CANDIDATE_V1",
        "candidate_id": "candidate-1",
        "source_family_id": "PINNACLE_TO_DRAFTKINGS_STALE_PRICE_H2H_V1",
        "event_id": "game-1",
        "market": market,
        "outcome": "Home" if market != "totals" else "Over",
        "soft_book": "draftkings",
        "offered_price_american": 100,
        "reference_pinnacle_fair_probability": 0.55,
        "flat_stake_units": 1.0,
        "point": point,
    }


class CandidateCLVSettlementTests(unittest.TestCase):
    def test_h2h_candidate_settles_against_exact_pinnacle_close(self):
        rows = [
            pin_row(capture="close", captured_at="2026-09-14T17:50:00Z", outcome="Home", price=-150),
            pin_row(capture="close", captured_at="2026-09-14T17:50:00Z", outcome="Away", price=135),
        ]
        settlement = settle_candidate(
            candidate(),
            rows,
            POLICY,
            now=datetime(2026, 9, 14, 18, 1, tzinfo=UTC),
        )
        self.assertIsNotNone(settlement)
        self.assertEqual(settlement["grading_status"], "SETTLED_CLV")
        self.assertEqual(settlement["closing_capture_id"], "close")
        self.assertGreater(settlement["clv"], 0.0)
        self.assertTrue(settlement["beat_close"])
        self.assertIsNone(settlement["flat_1u_roi"])

    def test_spread_point_change_is_ungradable_not_fake_probability_clv(self):
        rows = [
            pin_row(capture="close", captured_at="2026-09-14T17:50:00Z", outcome="Home", price=-110, market="spreads", point=-3.5),
            pin_row(capture="close", captured_at="2026-09-14T17:50:00Z", outcome="Away", price=-110, market="spreads", point=3.5),
        ]
        settlement = settle_candidate(
            candidate(market="spreads", point=-3.0),
            rows,
            POLICY,
            now=datetime(2026, 9, 14, 18, 1, tzinfo=UTC),
        )
        self.assertEqual(settlement["grading_status"], "UNGRADABLE_NO_EXACT_CONTRACT_CLOSE")
        self.assertIsNone(settlement["clv"])

    def test_source_family_stays_insufficient_below_100_clv_settlements(self):
        rows = [
            pin_row(capture="close", captured_at="2026-09-14T17:50:00Z", outcome="Home", price=-150),
            pin_row(capture="close", captured_at="2026-09-14T17:50:00Z", outcome="Away", price=135),
        ]
        record = candidate()
        settlement = settle_candidate(
            record,
            rows,
            POLICY,
            now=datetime(2026, 9, 14, 18, 1, tzinfo=UTC),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_dir = root / "archive" / "market-maker-radar" / "candidate-ledger" / record["source_family_id"]
            candidate_dir.mkdir(parents=True)
            (candidate_dir / f"{record['candidate_id']}.json").write_text(json.dumps(record))
            self.assertTrue(_persist_settlement(root, settlement))
            summary = summarize(root, POLICY)[record["source_family_id"]]
            self.assertEqual(summary["candidate_n"], 1)
            self.assertEqual(summary["clv_settled_n"], 1)
            self.assertEqual(summary["validation_status"], "INSUFFICIENT")
            self.assertIsNotNone(summary["mean_clv_pp"])
            self.assertIsNone(summary["flat_1u_roi"])


if __name__ == "__main__":
    unittest.main()
