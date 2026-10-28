"""Adversarial tests for game JSON research-surface quarantine."""
import unittest
from copy import deepcopy

from sportsedge.game_candidate_quarantine import (
    game_claim_hold, quarantine_game_surfaces,
)


class GameQuarantineTests(unittest.TestCase):
    def row(self, ev=.04, **extra):
        result = dict(input_index=0, status="RESEARCH_POSITIVE_EV_UNVALIDATED",
                      ev_per_dollar=ev, estimate_p=.55)
        result.update(extra)
        return result

    def test_exact_threshold_and_lower_boundary(self):
        self.assertEqual(game_claim_hold(self.row(.4))[0],
                         "EXTREME_CLAIMED_EV_QUARANTINE")
        self.assertIsNone(game_claim_hold(self.row(.399999))[0])

    def test_hidden_independent_extreme(self):
        row = self.row(independent_projection={
            "ev_per_dollar": 2.818, "estimate_p": .7})
        self.assertEqual(game_claim_hold(row)[0],
                         "EXTREME_CLAIMED_EV_QUARANTINE")

    def test_nested_aliases(self):
        for key in ("raw_ev_per_dollar", "reported_ev_per_dollar"):
            with self.subTest(key=key):
                row = self.row(pricing_lanes={
                    "lane_a_independent": {key: .401}})
                self.assertEqual(game_claim_hold(row)[0],
                                 "EXTREME_CLAIMED_EV_QUARANTINE")

    def test_bad_probabilities(self):
        for p in (1.5, -.1, True, float("nan"), float("inf"), "bad"):
            with self.subTest(p=p):
                row = self.row(pricing_lanes={
                    "lane_b_anchored": {
                        "estimate_p": p, "ev_per_dollar": .02}})
                self.assertEqual(game_claim_hold(row)[0],
                                 "GAME_PROBABILITY_CLAIM_INVALID")

    def test_bad_evs(self):
        for ev in (True, float("nan"), float("inf"), "bad"):
            with self.subTest(ev=ev):
                self.assertEqual(game_claim_hold(self.row(ev))[0],
                                 "GAME_EV_CLAIM_INVALID")

    def test_malformed_nested(self):
        self.assertEqual(game_claim_hold(self.row(pricing_lanes=[]))[0],
                         "GAME_EV_CLAIM_INVALID")
        self.assertEqual(game_claim_hold(self.row(independent_projection=[]))[0],
                         "GAME_EV_CLAIM_INVALID")

    def test_all_surfaces_and_evidence_preserved(self):
        a = self.row(independent_projection={
            "raw_ev_per_dollar": 2.818})
        b = dict(self.row(.03), input_index=1)
        before = deepcopy([a, b])
        surfaces = {
            "edges": [a, b],
            "independent_candidates": [a, b],
            "independent_watchlist": [a],
            "lane_b_watchlist": [a, b],
        }
        filtered, ledger = quarantine_game_surfaces(surfaces)
        self.assertEqual([len(filtered[k]) for k in surfaces],
                         [1, 1, 0, 1])
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["source_surfaces"], list(surfaces))
        self.assertFalse(ledger[0]["eligible_for_headline"])
        self.assertEqual([a, b], before)

    def test_invalid_index_rejected(self):
        with self.assertRaisesRegex(ValueError, "INPUT_INDEX"):
            quarantine_game_surfaces({
                "edges": [dict(self.row(), input_index=True,
                               ev_per_dollar=.4)]})


if __name__ == "__main__":
    unittest.main()
