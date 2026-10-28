"""Non-frozen research adapter regression: frozen game engine is untouched."""
from copy import deepcopy
import unittest

from scripts.quarantine_game_card_json import sanitize_card


class GameCardAdapterTests(unittest.TestCase):
    def card(self):
        extreme = {
            "input_index": 0, "status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
            "game": "A@B", "selection": "A",
            "ev_per_dollar": .03, "estimate_p": .55,
            "independent_projection": {"raw_ev_per_dollar": 2.818},
        }
        ordinary = {
            "input_index": 1, "status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
            "game": "A@B", "selection": "B",
            "ev_per_dollar": .03, "estimate_p": .55,
        }
        return {
            "schema": "SPORTSEDGE_FREE_RESEARCH_CARD_V1",
            "evaluated_rows": [extreme, ordinary],
            "edges": [extreme, ordinary],
            "independent_candidates": [extreme, ordinary],
            "independent_watchlist": [extreme],
            "lane_b_watchlist": [extreme, ordinary],
            "summary": {"rows": 2, "edges": 2, "lane_b_watchlist": 2},
            "source_receipts": [{"source": "untrusted_test_fixture"}],
        }

    def test_extreme_hidden_raw_claim_is_excluded_but_evidence_retained(self):
        card = self.card()
        before = deepcopy(card)
        result = sanitize_card(card)
        self.assertEqual(card, before)
        self.assertEqual(result["evaluated_rows"], before["evaluated_rows"])
        self.assertEqual([len(result[k]) for k in (
            "edges", "independent_candidates", "independent_watchlist",
            "lane_b_watchlist")], [1, 1, 0, 1])
        self.assertEqual(result["summary"]["edges"], 1)
        self.assertEqual(result["pre_quarantine_ranked_counts"]["edges"], 2)
        self.assertEqual(result["source_receipts"], before["source_receipts"])
        self.assertEqual(result["game_quarantined"][0]["input_index"], 0)
        self.assertFalse(result["game_quarantined"][0]["eligible_for_forward_clock"])
        self.assertFalse(result["game_quarantine_adapter"]["model_verification_authority"])

    def test_no_quarantine_when_below_threshold(self):
        card = self.card()
        card["evaluated_rows"][0]["independent_projection"]["raw_ev_per_dollar"] = .399
        result = sanitize_card(card)
        self.assertEqual(len(result["edges"]), 2)
        self.assertEqual(result["game_quarantined"], [])

    def test_invalid_probability_is_quarantined(self):
        card = self.card()
        card["evaluated_rows"][0]["independent_projection"] = {"estimate_p": 1.5}
        result = sanitize_card(card)
        self.assertEqual(result["game_quarantined"][0]["reason"],
                         "GAME_PROBABILITY_CLAIM_INVALID")

    def test_missing_evidence_refuses(self):
        card = self.card()
        card["evaluated_rows"] = [card["evaluated_rows"][1]]
        with self.assertRaisesRegex(ValueError, "REFERENCE_NOT_IN_EVIDENCE"):
            sanitize_card(card)

    def test_malformed_surface_refuses(self):
        card = self.card()
        card["edges"] = "not a list"
        with self.assertRaisesRegex(ValueError, "SURFACE_NOT_LIST"):
            sanitize_card(card)

    def test_already_partitioned_refuses(self):
        card = self.card()
        card["game_quarantined"] = []
        with self.assertRaisesRegex(ValueError, "ALREADY_PARTITIONED"):
            sanitize_card(card)

    def test_no_evaluated_rows_refuses(self):
        card = self.card()
        del card["evaluated_rows"]
        with self.assertRaisesRegex(ValueError, "EVALUATED_ROWS_REQUIRED"):
            sanitize_card(card)


    def test_detached_low_ev_surface_cannot_hide_original_extreme(self):
        card = self.card()
        for name in ("edges", "independent_candidates", "independent_watchlist", "lane_b_watchlist"):
            card[name] = [deepcopy(r) for r in card[name]]
            for r in card[name]:
                r.pop("independent_projection", None)
        result = sanitize_card(card)
        self.assertEqual([len(result[k]) for k in ("edges", "independent_candidates", "independent_watchlist", "lane_b_watchlist")], [1, 1, 0, 1])
        self.assertEqual(result["game_quarantined"][0]["max_finite_claimed_ev"], 2.818)
        self.assertTrue(result["game_quarantined"][0]["evidence_bound"])

    def test_clean_surface_with_missing_original_fails_closed(self):
        card = self.card()
        card["edges"] = [{"input_index": 999, "ev_per_dollar": .04}]
        with self.assertRaisesRegex(ValueError, "REFERENCE_NOT_IN_EVIDENCE"):
            sanitize_card(card)

    def test_duplicate_original_index_refuses(self):
        card = self.card()
        card["evaluated_rows"].append(deepcopy(card["evaluated_rows"][1]))
        with self.assertRaisesRegex(ValueError, "INPUT_INDEX_DUPLICATE"):
            sanitize_card(card)

    def test_bool_negative_fractional_indices_refuse(self):
        for source in ("evaluated_rows", "edges"):
            for invalid in (True, -1, "1", 1.0, None):
                with self.subTest(source=source, invalid=invalid):
                    card = self.card()
                    card[source][0] = dict(card[source][0], input_index=invalid)
                    with self.assertRaisesRegex(ValueError, "INPUT_INDEX_INVALID"):
                        sanitize_card(card)

    def test_identity_mismatch_refuses_even_with_low_ev(self):
        card = self.card()
        card["edges"] = [dict(card["evaluated_rows"][1], selection="Other")]
        with self.assertRaisesRegex(ValueError, "IDENTITY_CONFLICT:selection"):
            sanitize_card(card)

    def test_missing_fixture_identity_refuses(self):
        card = self.card()
        card["edges"] = [deepcopy(card["evaluated_rows"][1])]
        del card["edges"][0]["selection"]
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISSING:selection"):
            sanitize_card(card)

    def test_original_fixture_identity_cannot_be_forged_by_display(self):
        # The ranked row can claim a valid game/selection, but the original
        # evidence must independently carry that identity.
        for key in ("game", "selection"):
            for bad in (None, "", "   ", 42, True):
                with self.subTest(key=key, bad=bad):
                    card = self.card()
                    detached = deepcopy(card["edges"][1])
                    card["evaluated_rows"][1][key] = bad
                    card["edges"] = [detached]
                    with self.assertRaisesRegex(
                        ValueError, "GAME_EVALUATED_IDENTITY_INVALID:" + key
                    ):
                        sanitize_card(card)

    def test_original_probability_invalid_even_if_surface_sanitized(self):
        card = self.card()
        card["evaluated_rows"][1]["estimate_p"] = 1.5
        card["edges"] = [deepcopy(card["evaluated_rows"][1])]
        card["edges"][0]["estimate_p"] = .55
        result = sanitize_card(card)
        self.assertEqual(len(result["edges"]), 0)
        self.assertEqual(result["game_quarantined"][0]["reason"], "GAME_PROBABILITY_CLAIM_INVALID")

    def test_surface_claim_invalid_even_if_original_clean(self):
        card = self.card()
        card["evaluated_rows"][0]["independent_projection"]["raw_ev_per_dollar"] = .04
        card["edges"] = [dict(card["evaluated_rows"][1], estimate_p=float("nan"))]
        result = sanitize_card(card)
        self.assertEqual(len(result["edges"]), 0)
        self.assertEqual(result["game_quarantined"][0]["reason"], "GAME_PROBABILITY_CLAIM_INVALID")


if __name__ == "__main__":
    unittest.main()
