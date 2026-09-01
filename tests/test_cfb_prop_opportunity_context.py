import unittest

from sportsedge.cfb_prop_opportunity_context import (
    CFBPropOpportunityObservation,
    prop_evaluation_sequence,
)


class CFBPropOpportunityContextTests(unittest.TestCase):
    def test_cfb_prop_context_starts_outside_model_and_truth_gate(self):
        row = CFBPropOpportunityObservation(
            game_id="g1",
            entity_id="p1",
            prop_family="qb_rushing",
            as_of_utc="2026-08-31T16:00:00+00:00",
            source_uri="https://example.com/pit",
            source_sha256="a" * 64,
            features={"designed_run_share": 0.25, "scramble_rate": 0.11},
        )
        self.assertFalse(row.model_p_eligible)
        self.assertFalse(row.truth_gate_eligible)
        self.assertEqual(row.subdivision, "FBS")

    def test_cfb_prop_context_rejects_market_or_social_contamination(self):
        with self.assertRaises(ValueError):
            CFBPropOpportunityObservation(
                game_id="g1",
                entity_id="p1",
                prop_family="qb_passing",
                as_of_utc="2026-08-31T16:00:00+00:00",
                source_uri="https://example.com/pit",
                source_sha256="b" * 64,
                features={"odds": -110},
            )

    def test_cfb_run_it_sequence_places_price_after_distribution(self):
        seq = prop_evaluation_sequence()
        self.assertLess(seq.index("distribution"), seq.index("market_price"))
        self.assertLess(seq.index("market_price"), seq.index("ev"))
        self.assertLess(seq.index("ev"), seq.index("execution_gate"))


if __name__ == "__main__":
    unittest.main()
