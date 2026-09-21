import unittest
from dataclasses import asdict

from sportsedge.sports.nfl.prop_role_challenger import (
    AUTHORITY_FOOTER,
    STATUS,
    SUPPORTED_MARKETS,
    PropChallengerError,
    PropSimulation,
    apply_context,
    diagnostic_tags,
    evaluate_paired_quote,
    simulate_player_props,
    stabilize_role,
)


class NFLPropRoleChallengerTests(unittest.TestCase):
    def setUp(self):
        self.prior = {"pass_attempts": 34.0, "rush_attempts": 3.0, "targets": 8.0}
        self.eff = {
            "completion_rate": 0.66,
            "catch_rate": 0.68,
            "pass_td_rate": 0.052,
            "interception_rate": 0.021,
            "yards_per_attempt": 7.3,
            "yards_per_carry": 4.5,
            "yards_per_target": 8.1,
        }

    def test_sparse_player_uses_projected_role_fallback(self):
        role = stabilize_role(entity_id="p1", history=[], projected_role=self.prior)
        self.assertEqual(role.source, "PROJECTED_ROLE")
        self.assertEqual(role.history_games, 0)
        self.assertAlmostEqual(role.pass_attempt_mean, 34.0)
        self.assertEqual(role.status, STATUS)

    def test_history_is_shrunk_toward_role_prior(self):
        hist = [
            {"pass_attempts": 20, "rush_attempts": 2, "targets": 4},
            {"pass_attempts": 24, "rush_attempts": 3, "targets": 5},
            {"pass_attempts": 26, "rush_attempts": 4, "targets": 6},
            {"pass_attempts": 28, "rush_attempts": 3, "targets": 7},
        ]
        role = stabilize_role(entity_id="p1", history=hist, projected_role=self.prior)
        self.assertEqual(role.source, "HISTORY_BLEND")
        self.assertGreater(role.pass_attempt_mean, 20)
        self.assertLess(role.pass_attempt_mean, 34)

    def test_probability_lane_rejects_market_inputs_recursively(self):
        with self.assertRaisesRegex(PropChallengerError, "MARKET_INPUT_FORBIDDEN"):
            stabilize_role(entity_id="p1", history=[], projected_role={**self.prior, "nested": {"sportsbook": "DraftKings"}})
        role = stabilize_role(entity_id="p1", history=[], projected_role=self.prior)
        with self.assertRaisesRegex(PropChallengerError, "MARKET_INPUT_FORBIDDEN"):
            apply_context(role, {"opponent": {"spread": -3.5}})
        with self.assertRaisesRegex(PropChallengerError, "MARKET_INPUT_FORBIDDEN"):
            simulate_player_props(role=role, efficiency={**self.eff, "price": -110}, paths=100)

    def test_context_is_explicit_multiplier_not_hidden_score(self):
        role = stabilize_role(entity_id="p1", history=[], projected_role=self.prior)
        adjusted = apply_context(role, {"pass_volume_multiplier": 0.9, "rush_volume_multiplier": 1.1, "target_multiplier": 1.05})
        self.assertAlmostEqual(adjusted.pass_attempt_mean, role.pass_attempt_mean * 0.9)
        self.assertAlmostEqual(adjusted.rush_attempt_mean, role.rush_attempt_mean * 1.1)
        self.assertAlmostEqual(adjusted.target_mean, role.target_mean * 1.05)

    def test_shared_simulation_is_deterministic_and_supports_all_ten_families(self):
        role = stabilize_role(entity_id="p1", history=[], projected_role=self.prior)
        a = simulate_player_props(role=role, efficiency=self.eff, paths=500, seed=77)
        b = simulate_player_props(role=role, efficiency=self.eff, paths=500, seed=77)
        self.assertEqual(a.sha256, b.sha256)
        self.assertEqual(len(SUPPORTED_MARKETS), 10)
        for market in SUPPORTED_MARKETS:
            over, under, push = a.probabilities(market, 10.5)
            self.assertAlmostEqual(over + under + push, 1.0, places=12)

    def test_rush_receiving_yards_comes_from_same_path(self):
        role = stabilize_role(entity_id="p1", history=[], projected_role=self.prior)
        sim = simulate_player_props(role=role, efficiency=self.eff, paths=250, seed=9)
        for row in sim.paths:
            self.assertEqual(row["rush_receiving_yards"], row["rushing_yards"] + row["receiving_yards"])

    def test_paired_fresh_same_book_quote_produces_research_evaluation(self):
        sim = PropSimulation("p1", tuple({"receptions": x} for x in ([4] * 20 + [5] * 30 + [6] * 50)), 1)
        over = {"side": "OVER", "line": 4.5, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T18:00:00Z"}
        under = {"side": "UNDER", "line": 4.5, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T18:00:10Z"}
        result = evaluate_paired_quote(simulation=sim, market="RECEPTIONS", side="OVER", line=4.5, over_quote=over, under_quote=under, as_of="2026-09-21T18:01:00Z")
        self.assertAlmostEqual(result.estimate_p, 0.80)
        self.assertAlmostEqual(result.push_p, 0.0)
        self.assertAlmostEqual(result.market_no_vig_p, 0.5, places=8)
        self.assertGreater(result.ev_per_dollar, 0)
        self.assertFalse(result.official)
        self.assertFalse(result.staking_authority)
        self.assertEqual(result.authority_footer, AUTHORITY_FOOTER)
        payload = asdict(result)
        self.assertNotIn("model_p", payload)
        self.assertNotIn("score", payload)
        self.assertNotIn("why", payload)

    def test_one_sided_or_mismatched_quotes_fail_closed(self):
        sim = PropSimulation("p1", tuple({"receptions": 5} for _ in range(10)), 1)
        over = {"side": "OVER", "line": 4.5, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T18:00:00Z"}
        missing_price = {"side": "UNDER", "line": 4.5, "book": "DraftKings", "retrieved_at": "2026-09-21T18:00:00Z"}
        with self.assertRaisesRegex(PropChallengerError, "BAD_AMERICAN_ODDS"):
            evaluate_paired_quote(simulation=sim, market="RECEPTIONS", side="OVER", line=4.5, over_quote=over, under_quote=missing_price, as_of="2026-09-21T18:01:00Z")
        other_book = {"side": "UNDER", "line": 4.5, "price": -110, "book": "FanDuel", "retrieved_at": "2026-09-21T18:00:00Z"}
        with self.assertRaisesRegex(PropChallengerError, "PAIRED_QUOTE_BOOK_MISMATCH"):
            evaluate_paired_quote(simulation=sim, market="RECEPTIONS", side="OVER", line=4.5, over_quote=over, under_quote=other_book, as_of="2026-09-21T18:01:00Z")

    def test_quote_freshness_and_pair_skew_fail_closed(self):
        sim = PropSimulation("p1", tuple({"receptions": 5} for _ in range(10)), 1)
        over = {"side": "OVER", "line": 4.5, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T17:55:00Z"}
        under = {"side": "UNDER", "line": 4.5, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T17:55:00Z"}
        with self.assertRaisesRegex(PropChallengerError, "QUOTE_STALE"):
            evaluate_paired_quote(simulation=sim, market="RECEPTIONS", side="OVER", line=4.5, over_quote=over, under_quote=under, as_of="2026-09-21T18:00:00Z")
        over2 = {**over, "retrieved_at": "2026-09-21T18:00:00Z"}
        under2 = {**under, "retrieved_at": "2026-09-21T18:00:31Z"}
        with self.assertRaisesRegex(PropChallengerError, "PAIRED_QUOTE_TIME_SKEW"):
            evaluate_paired_quote(simulation=sim, market="RECEPTIONS", side="OVER", line=4.5, over_quote=over2, under_quote=under2, as_of="2026-09-21T18:00:31Z")

    def test_integer_line_push_mass_is_carried_into_ev(self):
        rows = ({"pass_attempts": 2}, {"pass_attempts": 3}, {"pass_attempts": 4}, {"pass_attempts": 4})
        sim = PropSimulation("qb", rows, 3)
        over = {"side": "OVER", "line": 3.0, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T18:00:00Z"}
        under = {"side": "UNDER", "line": 3.0, "price": -110, "book": "DraftKings", "retrieved_at": "2026-09-21T18:00:00Z"}
        result = evaluate_paired_quote(simulation=sim, market="PASS_ATTEMPTS", side="OVER", line=3.0, over_quote=over, under_quote=under, as_of="2026-09-21T18:00:10Z")
        self.assertAlmostEqual(result.estimate_p, 0.5)
        self.assertAlmostEqual(result.push_p, 0.25)
        self.assertAlmostEqual(result.estimate_p_nonpush, 2 / 3)
        self.assertGreater(result.ev_per_dollar, 0)

    def test_diagnostic_tags_are_separate_from_probability_lane(self):
        role = stabilize_role(entity_id="p1", history=[], projected_role=self.prior)
        tags = diagnostic_tags(role=role, football_context={"wind_mph": 18}, market_context={"book_count": 6})
        self.assertIn("PROJECTED_ROLE", tags)
        self.assertIn("HIGH_WIND", tags)
        self.assertIn("DEEP_MARKET", tags)
        self.assertEqual(role.pass_attempt_mean, 34.0)


if __name__ == "__main__":
    unittest.main()
