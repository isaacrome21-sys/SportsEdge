import unittest

from sportsedge.mlb_edge_score import qualification_score, score_mlb_edge
from sportsedge.mlb_myspari_own_model import myspari_rows, render_markdown


class MLBScoreRuleBTests(unittest.TestCase):
    def test_score_is_invariant_to_probability_price_edge_and_ev(self):
        first = score_mlb_edge(
            estimate_p=0.55,
            american_odds=120,
            opposite_odds=-140,
            n_paths=100000,
            quote_age_seconds=60,
            quote_ttl_seconds=3600,
        )
        second = score_mlb_edge(
            estimate_p=0.72,
            american_odds=-110,
            opposite_odds=-110,
            n_paths=100000,
            quote_age_seconds=60,
            quote_ttl_seconds=3600,
        )
        self.assertNotAlmostEqual(first.edge, second.edge)
        self.assertNotAlmostEqual(first.ev_per_dollar, second.ev_per_dollar)
        self.assertEqual(first.confidence_score, second.confidence_score)
        self.assertIn("SCORE_B_QUALIFICATION_ONLY", first.reason_codes)

    def test_zero_mc_paths_receive_no_simulation_points(self):
        self.assertEqual(
            qualification_score(n_paths=0, quote_age_seconds=0, quote_ttl_seconds=3600, push_p=0),
            60,
        )
        self.assertEqual(
            qualification_score(n_paths=100000, quote_age_seconds=0, quote_ttl_seconds=3600, push_p=0),
            100,
        )

    def test_push_mass_reduces_only_push_quality_component(self):
        clean = qualification_score(n_paths=100000, quote_age_seconds=0, quote_ttl_seconds=3600, push_p=0)
        pushed = qualification_score(n_paths=100000, quote_age_seconds=0, quote_ttl_seconds=3600, push_p=0.15)
        self.assertEqual(clean, 100)
        self.assertEqual(pushed, 90)

    def test_stale_quote_fails_closed_before_score(self):
        scored = score_mlb_edge(
            estimate_p=0.60,
            american_odds=110,
            opposite_odds=-130,
            n_paths=100000,
            quote_age_seconds=3601,
            quote_ttl_seconds=3600,
        )
        self.assertEqual(scored.status, "BLOCKED")
        self.assertEqual(scored.confidence_score, 0)
        self.assertEqual(scored.reason_codes, ("STALE_QUOTE",))

    def test_renderer_reports_presentation_block_not_official_engine_reason(self):
        payload = {
            "results": [
                {
                    "game_id": "1", "market": "MONEYLINE", "entity_id": "1", "line": 0,
                    "side": "AWAY", "american_odds": 120, "model_p": 0.55,
                    "implied_probability": 0.45, "edge": 0.10, "mc_paths": 100000,
                    "engine_version": "mlb_v7_distribution_v3_rng_provenance",
                    "bet_status": "MODEL_CANDIDATE",
                    "reason": "OFFICIAL_BLOCKED:live production inference path not attested",
                },
                {
                    "game_id": "1", "market": "MONEYLINE", "entity_id": "1", "line": 0,
                    "side": "HOME", "american_odds": -140, "model_p": 0.45,
                    "implied_probability": 0.55, "edge": -0.10, "mc_paths": 100000,
                    "engine_version": "mlb_v7_distribution_v3_rng_provenance",
                    "bet_status": "MODEL_CANDIDATE",
                    "reason": "OFFICIAL_BLOCKED:live production inference path not attested",
                },
            ]
        }
        rows = myspari_rows(payload, quote_age_seconds=3601, quote_ttl_seconds=3600)
        text = render_markdown(rows, header="t")
        self.assertIn("STALE_QUOTE", text)
        self.assertNotIn("OFFICIAL_BLOCKED:live production inference path not attested", text)


if __name__ == "__main__":
    unittest.main()
