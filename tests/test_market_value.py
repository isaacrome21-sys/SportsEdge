from dataclasses import asdict
import copy
import unittest

from sportsedge.market_value import (
    MarketValuePolicy,
    PriceQuote,
    ReferencePair,
    american_to_decimal,
    devig_proportional,
    devig_shin,
    evaluate_market,
    expected_value,
    load_policy,
    market_fair_probability,
    record_close,
)


def quote(
    book,
    selection,
    odds,
    when="2026-09-11T12:00:00Z",
    market="mlb:123:pitcher_k:5.5",
):
    return PriceQuote(
        book=book,
        market_key=market,
        selection=selection,
        american_odds=odds,
        captured_at=when,
        source=f"manual:{book}",
    )


def pair(
    book,
    over,
    under,
    when="2026-09-11T12:00:00Z",
    market="mlb:123:pitcher_k:5.5",
):
    return ReferencePair(
        quote(book, "OVER", over, when, market),
        quote(book, "UNDER", under, when, market),
    )


class MarketValueV1Tests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def test_frozen_policy_is_research_only_paper(self):
        self.assertEqual(self.policy.policy_id, "TOP_DOWN_MARKET_VALUE_V1")
        self.assertEqual(self.policy.lane_status, "PAPER")
        self.assertFalse(self.policy.eligible_for_official)
        self.assertFalse(self.policy.external_performance_claims_allowed)
        self.assertEqual(self.policy.min_ev, 0.02)

    def test_symmetric_two_way_market_devigs_to_half(self):
        for method in (devig_proportional, devig_shin):
            left, right = method(-110, -110)
            self.assertAlmostEqual(left, 0.5, places=12)
            self.assertAlmostEqual(right, 0.5, places=12)
            self.assertAlmostEqual(left + right, 1.0, places=12)

    def test_shin_probabilities_sum_to_one(self):
        favorite, dog = devig_shin(-150, +130)
        self.assertAlmostEqual(favorite + dog, 1.0, places=12)
        self.assertGreater(favorite, dog)

    def test_ev_uses_market_fair_probability_and_executable_price(self):
        p = 0.5826086956521739
        self.assertAlmostEqual(
            expected_value(p, -130),
            p * american_to_decimal(-130) - 1,
        )

    def test_pinnacle_lane_selects_larger_edge_and_never_outputs_model_p(self):
        decision = evaluate_market(
            [pair("Pinnacle", -150, +130)],
            [
                quote("DraftKings", "OVER", -130),
                quote("DraftKings", "UNDER", +125),
            ],
            reference_mode="PINNACLE_ONLY_V1",
            policy=self.policy,
            independent_model_selection="OVER",
        )
        self.assertEqual(decision.decision, "PAPER_BET")
        self.assertEqual(decision.selection, "OVER")
        self.assertGreaterEqual(decision.ev, 0.02)
        self.assertTrue(decision.model_agreement)
        payload = asdict(decision)
        self.assertIn("market_fair_p", payload)
        self.assertNotIn("model_p", payload)
        self.assertEqual(payload["lane_status"], "PAPER")

    def test_exact_two_percent_edge_qualifies(self):
        decision = evaluate_market(
            [pair("Pinnacle", -110, -110)],
            [
                quote("DraftKings", "OVER", +104),
                quote("DraftKings", "UNDER", -110),
            ],
            reference_mode="PINNACLE_ONLY_V1",
            policy=self.policy,
        )
        self.assertEqual(decision.decision, "PAPER_BET")
        self.assertAlmostEqual(decision.ev, 0.02, places=12)

    def test_below_threshold_stays_no_bet(self):
        decision = evaluate_market(
            [pair("Pinnacle", -110, -110)],
            [
                quote("DraftKings", "OVER", +102),
                quote("DraftKings", "UNDER", -110),
            ],
            reference_mode="PINNACLE_ONLY_V1",
            policy=self.policy,
        )
        self.assertEqual(decision.decision, "NO_BET")
        self.assertEqual(decision.reason, "MARKET_EV_BELOW_FROZEN_THRESHOLD")

    def test_frozen_american_odds_range_is_enforced(self):
        decision = evaluate_market(
            [pair("Pinnacle", -500, +350)],
            [
                quote("DraftKings", "OVER", -450),
                quote("DraftKings", "UNDER", +200),
            ],
            reference_mode="PINNACLE_ONLY_V1",
            policy=self.policy,
        )
        self.assertEqual(decision.decision, "NO_BET")
        self.assertEqual(
            decision.reason,
            "NO_EXECUTABLE_PRICE_IN_FROZEN_ODDS_RANGE",
        )

    def test_consensus_is_median_and_requires_two_frozen_sharp_books(self):
        refs = [
            pair("Pinnacle", -150, +130),
            pair("Circa", -145, +125),
            pair("Bookmaker", -155, +135),
        ]
        observed = market_fair_probability(
            refs,
            selection="OVER",
            reference_mode="SHARP_CONSENSUS_V1",
            policy=self.policy,
        )
        values = [
            devig_shin(ref.first.american_odds, ref.second.american_odds)[0]
            for ref in refs
        ]
        self.assertAlmostEqual(observed, sorted(values)[1], places=12)

        with self.assertRaisesRegex(ValueError, "at least 2"):
            market_fair_probability(
                [refs[0]],
                selection="OVER",
                reference_mode="SHARP_CONSENSUS_V1",
                policy=self.policy,
            )

    def test_reference_pair_rejects_mismatched_exact_market(self):
        with self.assertRaisesRegex(ValueError, "exact same market_key"):
            ReferencePair(
                quote("Pinnacle", "OVER", -110, market="pitcher:5.5"),
                quote("Pinnacle", "UNDER", -110, market="pitcher:6.5"),
            )

    def test_close_is_append_only_and_cannot_rewrite_original_decision(self):
        decision = evaluate_market(
            [pair("Pinnacle", -150, +130)],
            [
                quote("DraftKings", "OVER", -130),
                quote("DraftKings", "UNDER", +125),
            ],
            reference_mode="PINNACLE_ONLY_V1",
            policy=self.policy,
        )
        before = copy.deepcopy(asdict(decision))
        close = record_close(
            decision,
            [pair("Pinnacle", -165, +145, when="2026-09-11T23:00:00Z")],
            policy=self.policy,
        )
        self.assertEqual(asdict(decision), before)
        self.assertEqual(close.selection, decision.selection)
        self.assertEqual(close.original_execution_american_odds, -130)
        self.assertNotEqual(close.close_market_fair_p, decision.market_fair_p)

    def test_policy_rejects_attempt_to_make_lane_official(self):
        raw = {
            "policy_id": "TOP_DOWN_MARKET_VALUE_V1",
            "lane_status": "PAPER",
            "devig_method": "SHIN",
            "min_ev": 0.02,
            "american_odds_min": -400,
            "american_odds_max": 165,
            "reference_modes": self.policy.reference_modes,
            "eligible_for_official": True,
            "external_performance_claims_allowed": False,
        }
        with self.assertRaisesRegex(ValueError, "cannot be OFFICIAL"):
            MarketValuePolicy.from_mapping(raw)

    def test_policy_rejects_external_claims_as_validation(self):
        raw = {
            "policy_id": "TOP_DOWN_MARKET_VALUE_V1",
            "lane_status": "PAPER",
            "devig_method": "SHIN",
            "min_ev": 0.02,
            "american_odds_min": -400,
            "american_odds_max": 165,
            "reference_modes": self.policy.reference_modes,
            "eligible_for_official": False,
            "external_performance_claims_allowed": True,
        }
        with self.assertRaisesRegex(ValueError, "external performance claims"):
            MarketValuePolicy.from_mapping(raw)

    def test_unknown_policy_key_is_rejected_instead_of_shadowed(self):
        raw = {
            "policy_id": "TOP_DOWN_MARKET_VALUE_V1",
            "lane_status": "PAPER",
            "devig_method": "SHIN",
            "min_ev": 0.02,
            "american_odds_min": -400,
            "american_odds_max": 165,
            "reference_modes": self.policy.reference_modes,
            "eligible_for_official": False,
            "external_performance_claims_allowed": False,
            "unused_setting": 123,
        }
        with self.assertRaisesRegex(ValueError, "unknown=.*unused_setting"):
            MarketValuePolicy.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
