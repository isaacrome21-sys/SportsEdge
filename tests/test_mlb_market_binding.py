import json
import unittest
from datetime import datetime, timedelta, timezone

import sportsedge.mlb_market_binding as M
from sportsedge.mlb_market_binding import (
    BindingError,
    MARKET_BINDINGS,
    audit_status,
    settlement_pl,
    validate_binding,
    validate_paired_quote,
    validate_quote_binding,
)

NOW = datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc)
with open("config/deployments.json", encoding="utf-8") as handle:
    DECLARED = set(json.load(handle)["markets"])


def row(mid, **kw):
    spec = MARKET_BINDINGS[mid]
    binding_type = M._BINDING_TYPE_BY_ENTITY[spec.entity_type]
    result = {
        "event_id": "e1",
        "game_number": 1,
        "book_key": "dk",
        "retrieved_at": NOW,
        "market_id": mid,
        "period": spec.period,
        "side": spec.sides[0],
        "american_odds": -110,
        "probability_event_id": "e1",
        "probability_market_id": mid,
        "probability_bound_market_id": mid,
        "probability_side": spec.sides[0],
        "push_probability": 0.0,
    }
    if spec.threshold_semantics == M.NO_THRESHOLD:
        result["line"] = None
    elif spec.threshold_semantics == M.RUN_LINE_SIGNED:
        result.update(line=1.5, probability_line=1.5)
    else:
        result.update(line=6.5, probability_line=6.5)
    if binding_type == M.TEAM_BINDING:
        result.update(
            team_id="HOME_T",
            probability_team_id="HOME_T",
            event_home_team_id="HOME_T",
            event_away_team_id="AWAY_T",
        )
    elif binding_type == M.PLAYER_BINDING:
        result.update(entity_id="p1", probability_entity_id="p1")
    elif binding_type == M.GAME_BINDING:
        result.update(entity_id="e1", probability_entity_id="e1")
    elif binding_type == M.MULTI_ENTITY_BINDING:
        result.update(entity_ids=["p1", "p2"], probability_entity_ids=["p1", "p2"])
    elif binding_type == M.NWAY_OUTCOME_BINDING:
        result.update(
            outcome_id="o1",
            outcome_player_id="p1",
            probability_outcome_id="o1",
            probability_outcome_player_id="p1",
        )
    result.update(kw)
    if "side" in kw and "probability_side" not in kw:
        result["probability_side"] = kw["side"]
    if "event_id" in kw and "probability_event_id" not in kw:
        result["probability_event_id"] = str(kw["event_id"])
    if "line" in kw and "probability_line" in result and "probability_line" not in kw:
        result["probability_line"] = kw["line"]
    if "outcome_id" in kw and "probability_outcome_id" not in kw:
        result["probability_outcome_id"] = kw["outcome_id"]
    return result


class BindingContractTests(unittest.TestCase):
    def test_complete_38_market_declaration(self):
        self.assertEqual(len(DECLARED), 38)
        self.assertEqual(set(MARKET_BINDINGS), DECLARED)

    def test_threshold_domain_is_explicit_on_every_market(self):
        for mid, spec in MARKET_BINDINGS.items():
            self.assertIn(spec.threshold_domain, M.VALID_THRESHOLD_DOMAINS, mid)

    def test_code_wired_markets_are_not_audit_pass_without_source_evidence(self):
        code_wired = {m for m, spec in MARKET_BINDINGS.items() if spec.production_wired}
        self.assertEqual(code_wired, {"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})
        self.assertEqual({m for m in DECLARED if audit_status(m) == "PASS"}, set())
        for mid in code_wired:
            self.assertEqual(audit_status(mid), "BLOCKED_SOURCE_IDENTITY_UNVERIFIED")

    def test_all_quote_identity_fields_are_mandatory(self):
        for mid in MARKET_BINDINGS:
            for field in M.REQUIRED_QUOTE_IDENTITY:
                candidate = row(mid)
                candidate.pop(field, None)
                with self.assertRaises(BindingError, msg=f"{mid}/{field}"):
                    validate_quote_binding(candidate)

    def test_all_probability_identity_fields_are_mandatory(self):
        for mid in MARKET_BINDINGS:
            for field in M.REQUIRED_PROBABILITY_IDENTITY:
                candidate = row(mid)
                candidate.pop(field, None)
                with self.assertRaises(BindingError, msg=f"{mid}/{field}"):
                    validate_binding(candidate)

    def test_quote_stage_does_not_require_model_probability_fields(self):
        candidate = row("TOTALS")
        for field in list(M.REQUIRED_PROBABILITY_IDENTITY) + [
            "probability_entity_id",
            "probability_line",
            "push_probability",
        ]:
            candidate.pop(field, None)
        validate_quote_binding(candidate)

    def test_full_binding_rejects_wrong_probability_event_side_and_entity(self):
        bad = [
            row("TOTALS", probability_event_id="e2"),
            row("TOTALS", probability_side="UNDER"),
            row("TOTALS", probability_entity_id="e2"),
        ]
        for candidate in bad:
            with self.assertRaises(BindingError):
                validate_binding(candidate)

    def test_home_away_identity_is_canonical(self):
        with self.assertRaisesRegex(BindingError, "SIDE_TEAM_MISMATCH"):
            validate_quote_binding(row("MONEYLINE", side="HOME", team_id="AWAY_T", probability_team_id="AWAY_T"))
        with self.assertRaisesRegex(BindingError, "SIDE_TEAM_MISMATCH"):
            validate_quote_binding(row("MONEYLINE", side="AWAY", team_id="HOME_T", probability_team_id="HOME_T"))

    def test_team_total_team_must_belong_to_event(self):
        with self.assertRaisesRegex(BindingError, "TEAM_NOT_IN_EVENT"):
            validate_quote_binding(row("TEAM_TOTALS", team_id="OTHER", probability_team_id="OTHER"))

    def test_game_market_entity_must_equal_event(self):
        with self.assertRaisesRegex(BindingError, "GAME_ENTITY_EVENT_MISMATCH"):
            validate_quote_binding(row("TOTALS", entity_id="e2", probability_entity_id="e2"))

    def test_valid_moneyline_pair(self):
        home = row("MONEYLINE", side="HOME", team_id="HOME_T", probability_team_id="HOME_T")
        away = row("MONEYLINE", side="AWAY", team_id="AWAY_T", probability_team_id="AWAY_T")
        validate_paired_quote(home, away)

    def test_valid_runline_pair_and_same_sign_reject(self):
        home = row("RUN_LINE", side="HOME", line=-1.5, probability_line=-1.5, team_id="HOME_T", probability_team_id="HOME_T")
        away = row("RUN_LINE", side="AWAY", line=1.5, probability_line=1.5, team_id="AWAY_T", probability_team_id="AWAY_T")
        validate_paired_quote(home, away)
        with self.assertRaisesRegex(BindingError, "NOT_OPPOSITE|RUN_LINE_NOT_OPPOSITE"):
            validate_paired_quote(home, dict(away, line=-1.5, probability_line=-1.5))

    def test_team_total_and_player_pairs_require_same_subject(self):
        team_total = row("TEAM_TOTALS", side="OVER", line=4.5, probability_line=4.5)
        validate_paired_quote(team_total, dict(team_total, side="UNDER", probability_side="UNDER"))
        with self.assertRaises(BindingError):
            validate_paired_quote(
                team_total,
                dict(team_total, side="UNDER", probability_side="UNDER", team_id="AWAY_T", probability_team_id="AWAY_T"),
            )
        player = row("PITCHER_K", side="OVER")
        validate_paired_quote(player, dict(player, side="UNDER", probability_side="UNDER"))
        with self.assertRaises(BindingError):
            validate_paired_quote(
                player,
                dict(player, side="UNDER", probability_side="UNDER", entity_id="p9", probability_entity_id="p9"),
            )

    def test_cross_market_and_timestamp_pairing_fail_closed(self):
        with self.assertRaises(BindingError):
            validate_paired_quote(row("NRFI", side="YES"), row("YRFI", side="NO"))
        left = row("TOTALS", side="OVER")
        right = row("TOTALS", side="UNDER", retrieved_at=NOW - timedelta(seconds=60))
        with self.assertRaisesRegex(BindingError, "SKEW"):
            validate_paired_quote(left, right)

    def test_semantically_impossible_thresholds_fail(self):
        for mid in ("TOTALS", "TEAM_TOTALS", "PITCHER_K", "HITS"):
            with self.assertRaises(BindingError):
                validate_binding(row(mid, line=-6.5, probability_line=-6.5))
        for mid in ("TOTALS", "HITS"):
            with self.assertRaises(BindingError):
                validate_binding(row(mid, line=400, probability_line=400))
        with self.assertRaises(BindingError):
            validate_binding(row("TOTALS", line=6.37, probability_line=6.37))

    def test_price_timestamp_game_number_and_push_are_governed(self):
        for odds in (0, 50, -50, float("nan"), True):
            with self.assertRaises(BindingError):
                validate_binding(row("TOTALS", american_odds=odds))
        for timestamp in (datetime(2026, 9, 8), "bad"):
            with self.assertRaises(BindingError):
                validate_binding(row("TOTALS", retrieved_at=timestamp))
        for game_number in (0, 3, "1", True):
            with self.assertRaises(BindingError):
                validate_binding(row("TOTALS", game_number=game_number))
        for push_probability in (-0.1, 1.1, float("nan"), True):
            with self.assertRaises(BindingError):
                validate_binding(row("TOTALS", push_probability=push_probability))

    def test_half_point_cannot_have_push_mass(self):
        with self.assertRaisesRegex(BindingError, "HALF_POINT_GIVEN_PUSH_MASS"):
            validate_binding(row("TOTALS", line=8.5, probability_line=8.5, push_probability=0.02))

    def test_multi_entity_and_nway_are_explicit(self):
        with self.assertRaises(BindingError):
            validate_binding(row("EITHER_PITCHER_BB", entity_ids=["p1"], probability_entity_ids=["p1"]))
        with self.assertRaises(BindingError):
            validate_binding(row("FIRST_HOME_RUN", outcome_player_id=""))
        with self.assertRaises(BindingError):
            validate_binding(row("FIRST_HOME_RUN", devig_method="MULTIPLICATIVE_V1"))

    def test_f5_two_way_tie_is_not_a_priced_side(self):
        self.assertEqual(MARKET_BINDINGS["F5_MONEYLINE"].sides, ("HOME", "AWAY"))
        self.assertTrue(MARKET_BINDINGS["F5_MONEYLINE"].push_supported)
        with self.assertRaises(BindingError):
            validate_binding(row("F5_MONEYLINE", side="TIE", probability_side="TIE"))

    def test_settlement_pl(self):
        self.assertEqual(settlement_pl("LOSS", -110, 100), -100)
        self.assertEqual(settlement_pl("PUSH", -110, 100), 0)
        self.assertAlmostEqual(settlement_pl("WIN", 150, 100), 150)
        with self.assertRaises(BindingError):
            settlement_pl("WON", -110, 100)


if __name__ == "__main__":
    unittest.main()
