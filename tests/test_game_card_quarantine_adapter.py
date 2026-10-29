"""Non-frozen research adapter regression: frozen game engine is untouched."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from artifacts.free_models import run as run_frozen_engine
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


    def test_extreme_in_one_surface_quarantines_clean_copy_in_all(self):
        card = self.card()
        # Make original evidence ordinary, so ONLY the displayed watchlist
        # carries the extreme claim. Earlier clean edges must still be held.
        card["evaluated_rows"][0]["independent_projection"] = {
            "raw_ev_per_dollar": .04
        }
        for name in ("edges", "independent_candidates",
                     "independent_watchlist", "lane_b_watchlist"):
            card[name] = [deepcopy(row) for row in card[name]]
            for row in card[name]:
                row.pop("independent_projection", None)
        card["lane_b_watchlist"][0]["raw_ev_per_dollar"] = 2.818
        before = deepcopy(card)
        result = sanitize_card(card)
        self.assertEqual(card, before)
        self.assertEqual(result["evaluated_rows"], before["evaluated_rows"])
        self.assertEqual([len(result[k]) for k in (
            "edges", "independent_candidates", "independent_watchlist",
            "lane_b_watchlist")], [1, 1, 0, 1])
        self.assertEqual(len(result["game_quarantined"]), 1)
        self.assertEqual(set(result["game_quarantined"][0]["source_surfaces"]),
                         {"edges", "independent_candidates",
                          "independent_watchlist", "lane_b_watchlist"})
        self.assertEqual(result["game_quarantined"][0]["max_finite_claimed_ev"],
                         2.818)

    def test_duplicate_clean_display_index_refuses(self):
        card = self.card()
        card["edges"].append(deepcopy(card["edges"][1]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_INPUT_INDEX"):
            sanitize_card(card)



    def test_detached_pit_settlement_quote_and_authority_conflicts_refuse(self):
        # These are untrusted copies, not authenticated DK observations.
        claims = {
            "kickoff_utc": ("2026-10-28T23:00:00Z", "2026-10-29T23:00:00Z"),
            "team_totals_team": ("A", "B"),
            "period": ("FULL_GAME", "FIRST_HALF"),
            "settlement_type": ("REGULATION", "INCLUDING_OVERTIME"),
            "event_id": ("event-1", "event-2"),
            "dk_event_id": ("dk-1", "dk-2"),
            "odds_american": (-110, 120),
            "pricing_provenance": ({"lane": "LANE_A_INDEPENDENT"},
                                   {"lane": "LANE_B_ANCHORED"}),
            "quote_freshness": ({"status": "FRESH"}, {"status": "STALE"}),
            "quote_captured_at": ("2026-10-28T22:00:00Z",
                                  "2026-10-28T22:30:00Z"),
            "book": ("draftkings", "other"),
            "status": ("RESEARCH_POSITIVE_EV_UNVALIDATED", "OFFICIAL"),
            "research_only": (True, False),
            "model_p_authority": (False, True),
        }
        for key, (original_value, forged_value) in claims.items():
            with self.subTest(field=key):
                card = self.card()
                original = card["evaluated_rows"][1]
                original[key] = deepcopy(original_value)
                detached = deepcopy(original)
                detached[key] = deepcopy(forged_value)
                card["edges"] = [detached]
                with self.assertRaisesRegex(ValueError,
                                            "GAME_SURFACE_IDENTITY_CONFLICT:" + key):
                    sanitize_card(card)

    def test_detached_original_known_field_cannot_be_silently_omitted(self):
        for key, value in (
            ("kickoff_utc", "2026-10-28T23:00:00Z"),
            ("team_totals_team", "A"),
            ("period", "FULL_GAME"),
            ("quote_freshness", {"status": "FRESH"}),
            ("odds_american", -110),
            ("model_p_authority", False),
        ):
            with self.subTest(field=key):
                card = self.card()
                original = card["evaluated_rows"][1]
                original[key] = deepcopy(value)
                detached = deepcopy(original)
                del detached[key]
                card["edges"] = [detached]
                with self.assertRaisesRegex(ValueError,
                                            "GAME_SURFACE_IDENTITY_MISSING:" + key):
                    sanitize_card(card)

    def test_detached_identity_not_in_original_cannot_be_invented(self):
        for key, forged_value in (
            ("kickoff_utc", "2026-10-28T23:00:00Z"),
            ("team_totals_team", "B"),
            ("period", "FIRST_HALF"),
            ("event_id", "invented"),
            ("quote_captured_at", "2026-10-28T22:00:00Z"),
            ("book", "draftkings"),
            ("model_p_authority", True),
        ):
            with self.subTest(field=key):
                card = self.card()
                detached = deepcopy(card["evaluated_rows"][1])
                detached[key] = forged_value
                card["edges"] = [detached]
                with self.assertRaisesRegex(ValueError,
                                            "GAME_SURFACE_IDENTITY_UNATTESTED:" + key):
                    sanitize_card(card)

    def test_matching_detached_pit_and_settlement_fields_stay_research_only(self):
        card = self.card()
        ordinary = card["evaluated_rows"][1]
        ordinary.update({
            "kickoff_utc": "2026-10-28T23:00:00Z",
            "team_totals_team": "A",
            "period": "FULL_GAME",
            "quote_freshness": {"status": "FRESH"},
            "model_p_authority": False,
        })
        card["edges"] = [deepcopy(ordinary)]
        result = sanitize_card(card)
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["edges"][0]["input_index"], 1)
        self.assertFalse(result["game_quarantine_adapter"]["forward_clock_authority"])
        self.assertEqual(result["evaluated_rows"], card["evaluated_rows"])


    def test_contradictory_top_level_authority_refuses(self):
        for key, value in (("research_only", False), ("official", True),
                           ("model_p", True), ("truth_gate", True),
                           ("staking", True), ("validated_profitability", True),
                           ("forward_clock", True), ("official", 0),
                           ("research_only", 1)):
            with self.subTest(key=key, value=value):
                card = self.card()
                card["authority"] = {key: value}
                before = deepcopy(card)
                with self.assertRaisesRegex(ValueError, "GAME_CARD_AUTHORITY"):
                    sanitize_card(card)
                self.assertEqual(card, before)

    def test_malformed_top_level_authority_refuses(self):
        for value in (None, [], "RESEARCH_ONLY", False):
            with self.subTest(value=value):
                card = self.card()
                card["authority"] = value
                with self.assertRaisesRegex(ValueError, "GAME_CARD_AUTHORITY"):
                    sanitize_card(card)

    def test_missing_or_partial_authority_emits_complete_research_contract(self):
        expected = {"research_only": True, "official": False, "model_p": False,
                    "truth_gate": False, "staking": False,
                    "validated_profitability": False}
        for authority in (None, {}, {"official": False}):
            with self.subTest(authority=authority):
                card = self.card()
                if authority is not None:
                    card["authority"] = authority
                result = sanitize_card(card)
                self.assertEqual(result["authority"], expected)
                self.assertEqual(result["lane_b_edges"], [])

    def test_nonempty_or_malformed_legacy_edge_surface_refuses(self):
        for value in ([{"ev_per_dollar": 2.818}], [self.card()["edges"][1]],
                      None, {}, "", False):
            with self.subTest(value=value):
                card = self.card()
                card["lane_b_edges"] = value
                before = deepcopy(card)
                with self.assertRaisesRegex(ValueError, "GAME_LEGACY_EDGES"):
                    sanitize_card(card)
                self.assertEqual(card, before)

    def test_contradictory_legacy_edge_count_refuses(self):
        for count in (1, -1, False, "0", None):
            with self.subTest(count=count):
                card = self.card()
                card["lane_b_edges"] = []
                card["summary"]["lane_b_edges"] = count
                with self.assertRaisesRegex(ValueError, "GAME_LEGACY_EDGE_COUNT"):
                    sanitize_card(card)

    def test_real_frozen_engine_blocked_evidence_is_retained(self):
        def no_network(*args, **kwargs):
            self.fail("offline compatibility regression must not fetch sources")

        card = run_frozen_engine(
            [None, {}], now=datetime(2026, 10, 29, tzinfo=timezone.utc),
            auto_context=False, getter=no_network,
        )
        before = deepcopy(card)
        self.assertTrue(all(r["status"] == "BLOCKED_INVALID"
                            for r in card["evaluated_rows"]))
        result = sanitize_card(card)
        self.assertEqual(card, before)
        for key in ("evaluated_rows", "diagnostics", "summary", "authority",
                    "source_receipts", "input_snapshot"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(result["game_quarantined"], [])

    def test_unranked_blocked_row_does_not_discard_valid_candidates(self):
        card = self.card()
        blocked = {"input_index": 2, "status": "BLOCKED_INVALID",
                   "reason": "LINE_MUST_BE_OBJECT"}
        card["evaluated_rows"].append(blocked)
        card["diagnostics"] = [deepcopy(blocked)]
        result = sanitize_card(card)
        self.assertEqual([r["input_index"] for r in result["edges"]], [1])
        self.assertEqual(result["evaluated_rows"], card["evaluated_rows"])
        self.assertEqual(result["diagnostics"], card["diagnostics"])

    def test_blocked_evidence_cannot_be_ranked_even_with_identity(self):
        for has_identity in (False, True):
            with self.subTest(has_identity=has_identity):
                card = self.card()
                blocked = {"input_index": 2, "status": "BLOCKED_INVALID"}
                if has_identity:
                    blocked.update(game="A@B", selection="A", ev_per_dollar=.04)
                card["evaluated_rows"].append(blocked)
                card["edges"].append(deepcopy(blocked))
                with self.assertRaisesRegex(ValueError, "GAME_SURFACE_BLOCKED_EVIDENCE"):
                    sanitize_card(card)

    def test_unknown_card_schema_refuses(self):
        for schema in (None, "OTHER_CARD", 1):
            with self.subTest(schema=schema):
                card = self.card()
                card["schema"] = schema
                with self.assertRaisesRegex(ValueError, "GAME_CARD_SCHEMA"):
                    sanitize_card(card)


    def test_top_level_authority_aliases_refuse_even_false(self):
        for key, value in (("official", True), ("official", False),
                           ("staking", True), ("model_p", True),
                           ("forward_clock", True), ("research_only", True),
                           ("verified", True), ("model_verified", True)):
            with self.subTest(key=key):
                card = self.card()
                card[key] = value
                before = deepcopy(card)
                with self.assertRaisesRegex(ValueError, "GAME_CARD_TOP_LEVEL_AUTHORITY_ALIAS"):
                    sanitize_card(card)
                self.assertEqual(card, before)

    def test_conflicting_play_gate_and_quote_age_refuse(self):
        cases = (
            ("play_gate", {"rule": "ALLOW_STAKING"}),
            ("play_gate", {"anchored_max_surface": "PLAY"}),
            ("play_gate", {"unexpected_authority": True}),
            ("quote_freshness_policy", {"max_age_seconds": 999999999}),
            ("quote_freshness_policy", {"max_age_seconds": 180.0}),
            ("quote_freshness_policy", {"max_age_seconds": True}),
            ("quote_freshness_policy", {"stale_quotes_are_watch_only": False}),
            ("quote_freshness_policy", {"unexpected_policy": "ALLOW"}),
        )
        for key, policy in cases:
            with self.subTest(key=key, policy=policy):
                card = self.card()
                card[key] = policy
                before = deepcopy(card)
                with self.assertRaisesRegex(ValueError, "GAME_CARD_POLICY_CONFLICT"):
                    sanitize_card(card)
                self.assertEqual(card, before)

    def test_malformed_policy_objects_refuse(self):
        for key in ("play_gate", "quote_freshness_policy"):
            for value in (None, [], False, "ALLOW_STAKING"):
                with self.subTest(key=key, value=value):
                    card = self.card()
                    card[key] = value
                    with self.assertRaisesRegex(ValueError, "GAME_CARD_POLICY_NOT_OBJECT"):
                        sanitize_card(card)

    def test_canonical_policy_projected_without_claiming_quote_authentication(self):
        card = self.card()
        result = sanitize_card(card)
        self.assertEqual(result["play_gate"], {
            "rule": "INDEPENDENT_PROBABILITY_REQUIRED_FOR_PLAY",
            "anchored_max_surface": "WATCH",
            "anchored_ev_in_edges_lists": "SUPPRESSED",
            "undetermined_provenance": "FAIL_CLOSED",
            "availability_unverified_max_surface": "RESEARCH_ONLY",
        })
        self.assertEqual(result["quote_freshness_policy"], {
            "max_age_seconds": 180, "stale_quotes_are_watch_only": True,
        })
        self.assertFalse(result["authority"]["staking"])
        self.assertFalse(result["game_quarantine_adapter"]["forward_clock_authority"])

    def test_frozen_engine_policy_control_unchanged(self):
        def no_network(*args, **kwargs):
            self.fail("offline policy control must not fetch sources")
        card = run_frozen_engine(
            [None], now=datetime(2026, 10, 29, tzinfo=timezone.utc),
            auto_context=False, getter=no_network,
        )
        result = sanitize_card(card)
        self.assertEqual(result["play_gate"], card["play_gate"])
        self.assertEqual(result["quote_freshness_policy"], card["quote_freshness_policy"])
        self.assertEqual(result["evaluated_rows"], card["evaluated_rows"])


if __name__ == "__main__":
    unittest.main()

