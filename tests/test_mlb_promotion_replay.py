from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from sportsedge.mlb_promotion_replay import (
    build_mlb_promotion_replay,
    enrich_joined_pit_observations,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "mlb_replay_policy_v1.json"


def _quote(*, book: str, side: str, entity: str, odds: int, ts: str, market: str = "MONEYLINE", line: float = 0.0, period: str = "FG", alt: bool = False) -> dict:
    return {
        "game_id": "g1", "period": period, "market": market, "entity_id": entity,
        "side": side, "line": line, "book_key": book, "sportsbook": book.title(),
        "retrieved_at": ts, "is_alternate": alt, "raw_market_name": "test",
        "american_odds": odds, "ttl_seconds": 180,
    }


def _obs(**overrides) -> dict:
    row = {
        "observation_key": "obs1", "game_id": "g1", "market": "MONEYLINE", "entity_id": "HOME_ID",
        "side": "HOME", "period": "FG", "is_alternate": False, "line": 0.0,
        "quote_ts": "2026-08-20T00:55:00+00:00", "first_pitch_ts": "2026-08-20T01:00:00+00:00",
        "candidate_p": 0.62, "source_evidence_class": "LIVE_PROVIDER_QUOTE_ARCHIVE",
        "model_evidence_class": "LIVE_PIT_MODEL", "official_fact_evidence_class": "LIVE_OFFICIAL_FACT_PROBE",
        "book_rule_evidence_class": "LIVE_BOOK_RULE_CAPTURE", "book_key": "pinnacle",
        "settlement_state": "SETTLEMENT_ELIGIBLE", "settled_outcome": "WIN",
    }
    row.update(overrides); return row


def _policy():
    raw = POLICY_PATH.read_bytes()
    return json.loads(raw.decode()), raw


class MLBPromotionReplayTests(unittest.TestCase):
    def test_featured_core_uses_first_valid_hierarchy_book_and_exact_close(self):
        policy, raw = _policy()
        quotes = [
            _quote(book="pinnacle", side="HOME", entity="HOME_ID", odds=-110, ts="2026-08-20T00:54:45+00:00"),
            _quote(book="pinnacle", side="AWAY", entity="AWAY_ID", odds=-110, ts="2026-08-20T00:54:50+00:00"),
            _quote(book="draftkings", side="HOME", entity="HOME_ID", odds=105, ts="2026-08-20T00:54:50+00:00"),
            _quote(book="draftkings", side="AWAY", entity="AWAY_ID", odds=-125, ts="2026-08-20T00:54:55+00:00"),
            _quote(book="pinnacle", side="HOME", entity="HOME_ID", odds=-130, ts="2026-08-20T00:59:40+00:00"),
            _quote(book="pinnacle", side="AWAY", entity="AWAY_ID", odds=110, ts="2026-08-20T00:59:45+00:00"),
        ]
        report = build_mlb_promotion_replay(
            pit_observations=[_obs()], quote_rows=quotes, replay_policy=policy,
            replay_policy_raw_bytes=raw, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(report["eligible_row_count"], 1)
        row = report["rows"][0]
        self.assertEqual(row["book_key"], "pinnacle")
        self.assertAlmostEqual(row["decision_no_vig_p"], 0.5)
        self.assertIsNotNone(row["close_no_vig_p"])
        self.assertGreater(row["clv_probability"], 0.0)
        self.assertTrue(row["settlement_compatible"])
        self.assertAlmostEqual(row["roi_per_dollar"], 100 / 110)
        self.assertEqual(row["fold_name"], "AUGUST")
        self.assertEqual(row["replay_policy_id"], "MLB_REPLAY_POLICY_V1")

    def test_higher_book_stale_pair_falls_through_to_registered_lower_book(self):
        policy, raw = _policy()
        quotes = [
            _quote(book="pinnacle", side="HOME", entity="HOME_ID", odds=-110, ts="2026-08-20T00:50:00+00:00"),
            _quote(book="pinnacle", side="AWAY", entity="AWAY_ID", odds=-110, ts="2026-08-20T00:50:05+00:00"),
            _quote(book="draftkings", side="HOME", entity="HOME_ID", odds=-105, ts="2026-08-20T00:54:45+00:00"),
            _quote(book="draftkings", side="AWAY", entity="AWAY_ID", odds=-115, ts="2026-08-20T00:54:50+00:00"),
        ]
        report = build_mlb_promotion_replay(
            pit_observations=[_obs(book_key="draftkings")], quote_rows=quotes, replay_policy=policy,
            replay_policy_raw_bytes=raw, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(report["rows"][0]["book_key"], "draftkings")

    def test_settlement_from_other_book_cannot_create_roi(self):
        policy, raw = _policy()
        quotes = [
            _quote(book="pinnacle", side="HOME", entity="HOME_ID", odds=-110, ts="2026-08-20T00:54:45+00:00"),
            _quote(book="pinnacle", side="AWAY", entity="AWAY_ID", odds=-110, ts="2026-08-20T00:54:50+00:00"),
        ]
        report = build_mlb_promotion_replay(
            pit_observations=[_obs(book_key="draftkings")], quote_rows=quotes, replay_policy=policy,
            replay_policy_raw_bytes=raw, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        row = report["rows"][0]
        self.assertFalse(row["settlement_compatible"])
        self.assertIsNone(row["roi_per_dollar"])

    def test_changed_close_threshold_does_not_count_as_clv(self):
        policy, raw = _policy()
        obs = _obs(market="HITS", entity_id="p1", side="OVER", line=1.5, book_key="draftkings")
        quotes = [
            _quote(book="draftkings", side="OVER", entity="p1", odds=-110, ts="2026-08-20T00:54:45+00:00", market="HITS", line=1.5),
            _quote(book="draftkings", side="UNDER", entity="p1", odds=-110, ts="2026-08-20T00:54:50+00:00", market="HITS", line=1.5),
            _quote(book="draftkings", side="OVER", entity="p1", odds=-125, ts="2026-08-20T00:59:40+00:00", market="HITS", line=2.5),
            _quote(book="draftkings", side="UNDER", entity="p1", odds=105, ts="2026-08-20T00:59:45+00:00", market="HITS", line=2.5),
        ]
        report = build_mlb_promotion_replay(
            pit_observations=[obs], quote_rows=quotes, replay_policy=policy,
            replay_policy_raw_bytes=raw, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(report["rows"][0]["close_no_vig_p"])
        self.assertIsNone(report["rows"][0]["clv_probability"])

    def test_first_home_run_is_excluded_under_v1(self):
        policy, raw = _policy()
        obs = _obs(market="FIRST_HOME_RUN", entity_id="p1", side="YES", line=0.0, book_key="draftkings")
        quotes = [
            _quote(book="draftkings", side="YES", entity="p1", odds=250, ts="2026-08-20T00:54:45+00:00", market="FIRST_HOME_RUN"),
            _quote(book="draftkings", side="NO", entity="p1", odds=-300, ts="2026-08-20T00:54:50+00:00", market="FIRST_HOME_RUN"),
        ]
        report = build_mlb_promotion_replay(
            pit_observations=[obs], quote_rows=quotes, replay_policy=policy,
            replay_policy_raw_bytes=raw, generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(report["eligible_row_count"], 0)
        self.assertIn("REPLAY_MARKET_NWAY_UNAUTHORIZED:FIRST_HOME_RUN", report["exclusions"][0]["reason"])

    def test_archive_enrichment_recovers_period_and_alternate_only_after_identity_check(self):
        archive = {
            "payload_sha256": "a" * 64,
            "quotes": [{"market": "HITS", "side": "OVER", "line": 1.5, "book_key": "draftkings", "quote_retrieved_at": "2026-08-20T00:55:00+00:00", "period": "FG", "is_alternate": True}],
        }
        joined = {
            "archive_payload_sha256": "a" * 64,
            "observations": [{"source_index": 0, "market": "HITS", "side": "OVER", "line": 1.5, "book_key": "draftkings", "quote_ts": "2026-08-20T00:55:00+00:00"}],
        }
        enriched = enrich_joined_pit_observations(join_payload=joined, archive_payload=archive)
        self.assertEqual(enriched[0]["period"], "FG")
        self.assertTrue(enriched[0]["is_alternate"])


if __name__ == "__main__":
    unittest.main()
