from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sportsedge.mlb_benchmark import (
    MLBBenchmarkError,
    MLBBenchmarkQuote,
    score_mlb_original_contract_clv,
    select_mlb_reference_pair,
)


NOW = datetime(2026, 8, 29, 13, 0, tzinfo=timezone.utc)


def q(qid, provider, side, odds, seconds_old, line=8.5):
    return MLBBenchmarkQuote(
        quote_id=qid,
        provider=provider,
        book=provider,
        game_id="g1",
        market="TOTALS",
        entity_id="g1",
        period="FG",
        side=side,
        line=line,
        american_odds=odds,
        captured_at=(NOW - timedelta(seconds=seconds_old)).isoformat(),
    )


class MLBBenchmarkTests(unittest.TestCase):
    def select(self, quotes, cutoff=NOW):
        return select_mlb_reference_pair(
            quotes,
            game_id="g1",
            market="TOTALS",
            entity_id="g1",
            period="FG",
            line=8.5,
            cutoff_ts=cutoff,
            provider_priority_tiers=(("PINNACLE",), ("DRAFTKINGS",)),
            max_quote_age_seconds=180,
            max_pair_skew_seconds=30,
        )

    def test_first_valid_priority_tier_wins(self):
        pair = self.select([
            q("p1", "PINNACLE", "OVER", -105, 20), q("p2", "PINNACLE", "UNDER", -105, 20),
            q("d1", "DRAFTKINGS", "OVER", 120, 5), q("d2", "DRAFTKINGS", "UNDER", -140, 5),
        ])
        self.assertEqual(pair.provider, "PINNACLE")
        self.assertFalse(pair.fallback_used)

    def test_asynchronous_pair_is_not_referenceable(self):
        with self.assertRaisesRegex(MLBBenchmarkError, "REFERENCE_PAIR_UNAVAILABLE"):
            self.select([q("p1", "PINNACLE", "OVER", -110, 10), q("p2", "PINNACLE", "UNDER", -110, 60)])

    def test_original_contract_clv_is_close_minus_decision(self):
        decision = self.select([q("d1", "PINNACLE", "OVER", -110, 120), q("d2", "PINNACLE", "UNDER", -110, 120)])
        close = self.select([q("c1", "PINNACLE", "OVER", -130, 5), q("c2", "PINNACLE", "UNDER", 110, 5)])
        scored = score_mlb_original_contract_clv(side="OVER", decision_reference=decision, closing_reference=close, model_p_at_decision=0.60)
        self.assertGreater(scored.clv_probability_points, 0.0)
        self.assertAlmostEqual(scored.model_vs_close_probability_points, 0.60 - scored.closing_novig_probability)

    def test_line_change_is_clv_unavailable_without_frozen_repricing(self):
        decision = self.select([q("d1", "PINNACLE", "OVER", -110, 120), q("d2", "PINNACLE", "UNDER", -110, 120)])
        close = replace(decision, line=9.0)
        with self.assertRaisesRegex(MLBBenchmarkError, "ORIGINAL_CONTRACT_LINE_MISMATCH"):
            score_mlb_original_contract_clv(side="OVER", decision_reference=decision, closing_reference=close)


if __name__ == "__main__":
    unittest.main()
