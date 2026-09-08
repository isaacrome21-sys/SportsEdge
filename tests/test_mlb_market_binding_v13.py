import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.mlb_market_binding_v13 import (
    BINDING_PASS_MARKETS,
    BindingError,
    MARKET_BINDINGS,
    STRUCTURALLY_WIRED_MARKETS,
    audit_status,
    runtime_full_binding_row,
    runtime_quote_binding_row,
    validate_binding,
    validate_quote_binding,
    validate_quote_pair,
)
from sportsedge.orchestrator import run_candidate

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


def q(market, side, entity, line, odds=-110, *, game_number=1):
    raw = {
        "game_id": "777", "event_id": "777", "game_number": game_number,
        "event_home_team_id": "20", "event_away_team_id": "10",
        "period": "FG", "market": market, "entity_id": str(entity),
        "line": line, "side": side, "american_odds": odds,
        "book_key": "draftkings", "retrieved_at": NOW, "ttl_seconds": 300,
        "is_alternate": False, "raw_market_name": market.lower(),
    }
    if game_number is None:
        raw.pop("game_number")
    if MARKET_BINDINGS[market].entity_type == "TEAM":
        raw["team_id"] = str(entity)
    return raw


def engine_output(model_input, p=0.55, push=0.0):
    return {
        "game_id": model_input["game_id"],
        "market": model_input["market"],
        "entity_id": model_input["entity_id"],
        "line": model_input["line"],
        "side": model_input["side"],
        "model_p": p,
        "push_p": push,
    }


class SpecTests(unittest.TestCase):
    def test_all_38_declared_but_none_self_report_pass(self):
        self.assertEqual(len(MARKET_BINDINGS), 38)
        self.assertEqual(BINDING_PASS_MARKETS, frozenset())
        passed = {m for m in MARKET_BINDINGS if audit_status(m) == "PASS"}
        self.assertEqual(passed, set())
        self.assertEqual(STRUCTURALLY_WIRED_MARKETS, {"MONEYLINE", "RUN_LINE", "TOTALS"})
        for market in STRUCTURALLY_WIRED_MARKETS:
            self.assertEqual(audit_status(market), "WIRED_UNVERIFIED")
        self.assertEqual(audit_status("TEAM_TOTALS"), "UNAUDITABLE_IMPLICIT")

    def test_domains_are_explicit(self):
        for spec in MARKET_BINDINGS.values():
            self.assertTrue(spec.threshold_domain)


class QuoteBindingTests(unittest.TestCase):
    def test_valid_moneyline_and_runline_pairs(self):
        home = q("MONEYLINE", "HOME", 20, 0.0, -120)
        away = q("MONEYLINE", "AWAY", 10, 0.0, +110)
        validate_quote_pair(runtime_quote_binding_row(home), runtime_quote_binding_row(away))

        home_rl = q("RUN_LINE", "HOME", 20, -1.5, +105)
        away_rl = q("RUN_LINE", "AWAY", 10, +1.5, -125)
        validate_quote_pair(runtime_quote_binding_row(home_rl), runtime_quote_binding_row(away_rl))

    def test_ordinary_game_pair_needs_event_id_not_fake_game_number(self):
        home = q("MONEYLINE", "HOME", 20, 0.0, -120, game_number=None)
        away = q("MONEYLINE", "AWAY", 10, 0.0, +110, game_number=None)
        validate_quote_pair(runtime_quote_binding_row(home), runtime_quote_binding_row(away))
        broken = dict(home)
        broken.pop("event_id")
        with self.assertRaisesRegex(BindingError, "event_id"):
            validate_quote_binding(runtime_quote_binding_row(broken))

    def test_invalid_supplied_game_number_fails(self):
        bad = q("TOTALS", "OVER", 777, 8.5)
        bad["game_number"] = 3
        with self.assertRaisesRegex(BindingError, "ILLEGAL_GAME_NUMBER"):
            validate_quote_binding(runtime_quote_binding_row(bad))

    def test_home_side_bound_to_away_team_fails(self):
        bad = q("MONEYLINE", "HOME", 10, 0.0)
        with self.assertRaisesRegex(BindingError, "SIDE_TEAM_MISMATCH"):
            validate_quote_binding(runtime_quote_binding_row(bad))

    def test_equal_signed_runlines_fail(self):
        a = q("RUN_LINE", "HOME", 20, -1.5)
        b = q("RUN_LINE", "AWAY", 10, -1.5)
        with self.assertRaisesRegex(BindingError, "NOT_OPPOSITE"):
            validate_quote_pair(runtime_quote_binding_row(a), runtime_quote_binding_row(b))

    def test_team_total_pair_must_be_same_team(self):
        over = q("TEAM_TOTALS", "OVER", 20, 4.5)
        under = q("TEAM_TOTALS", "UNDER", 20, 4.5)
        validate_quote_pair(runtime_quote_binding_row(over), runtime_quote_binding_row(under))
        with self.assertRaises(BindingError):
            validate_quote_pair(
                runtime_quote_binding_row(over),
                runtime_quote_binding_row(q("TEAM_TOTALS", "UNDER", 10, 4.5)),
            )

    def test_bad_threshold_fails(self):
        bad = runtime_quote_binding_row(q("TOTALS", "OVER", 777, -8.5))
        with self.assertRaisesRegex(BindingError, "OUT_OF_DOMAIN"):
            validate_quote_binding(bad)


class FullBindingTests(unittest.TestCase):
    def test_probability_team_and_line_mismatches_fail(self):
        quote = q("RUN_LINE", "HOME", 20, -1.5)
        output = {
            "game_id": "777", "market": "RUN_LINE", "entity_id": "20",
            "line": -1.5, "side": "HOME", "model_p": 0.55, "push_p": 0.0,
        }
        row = runtime_full_binding_row(quote, output)
        validate_binding(row)
        row["probability_team_id"] = "10"
        with self.assertRaisesRegex(BindingError, "PROBABILITY_TEAM_MISMATCH"):
            validate_binding(row)

    def test_orchestrator_executes_structural_binding_for_first_three(self):
        cases = [
            ("MONEYLINE", q("MONEYLINE", "HOME", 20, 0.0, -120), q("MONEYLINE", "AWAY", 10, 0.0, +110), 0.56, 0.0),
            ("RUN_LINE", q("RUN_LINE", "HOME", 20, -1.5, +105), q("RUN_LINE", "AWAY", 10, +1.5, -125), 0.51, 0.0),
            ("TOTALS", q("TOTALS", "OVER", 777, 8.5, -110), q("TOTALS", "UNDER", 777, 8.5, -110), 0.54, 0.0),
        ]
        floor = SimpleNamespace(value_probability_points=0.03)
        with patch("sportsedge.orchestrator.require_production_edge_floor", return_value=floor):
            for market, quote, opposite, p, push in cases:
                model_input = {
                    "game_id": "777", "market": market,
                    "entity_id": quote["entity_id"], "line": quote["line"],
                    "side": quote["side"],
                }
                result = run_candidate(
                    model_input=model_input,
                    quote=quote,
                    paired_quote=opposite,
                    deployment={"eligible": True, "market": market},
                    engine_fn=lambda mi, p=p, push=push: engine_output(mi, p, push),
                    ingestion_now=NOW,
                    finalization_now=NOW,
                )
                self.assertIsNotNone(result.model_p, f"{market}: {result.reason}")
                self.assertNotEqual(result.bet_status, "BLOCKED", f"{market}: {result.reason}")

    def test_engine_cannot_omit_identity_on_structurally_wired_market(self):
        quote = q("TOTALS", "OVER", 777, 8.5, -110)
        result = run_candidate(
            model_input={"game_id": "777", "market": "TOTALS", "entity_id": "777", "line": 8.5, "side": "OVER"},
            quote=quote,
            paired_quote=q("TOTALS", "UNDER", 777, 8.5, -110),
            deployment={"eligible": True, "market": "TOTALS"},
            engine_fn=lambda _: {"model_p": 0.55, "push_p": 0.0},
            ingestion_now=NOW,
            finalization_now=NOW,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIn("ENGINE_READOUT_IDENTITY_MISSING", result.reason)

    def test_binding_failure_blocks_only_row(self):
        quote = q("MONEYLINE", "HOME", 10, 0.0, -120)
        opposite = q("MONEYLINE", "AWAY", 10, 0.0, +110)
        model_input = {"game_id": "777", "market": "MONEYLINE", "entity_id": "10", "line": 0.0, "side": "HOME"}
        with patch("sportsedge.orchestrator.require_production_edge_floor", return_value=SimpleNamespace(value_probability_points=0.03)):
            result = run_candidate(
                model_input=model_input,
                quote=quote,
                paired_quote=opposite,
                deployment={"eligible": True, "market": "MONEYLINE"},
                engine_fn=lambda mi: engine_output(mi),
                ingestion_now=NOW,
                finalization_now=NOW,
            )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIn("SIDE_TEAM_MISMATCH", result.reason)


if __name__ == "__main__":
    unittest.main()
