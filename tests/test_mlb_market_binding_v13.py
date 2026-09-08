import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.mlb_market_binding_v13 import (
    BindingError,
    MARKET_BINDINGS,
    PRODUCTION_WIRED_MARKETS,
    attach_runtime_binding_context,
    audit_status,
    runtime_full_binding_row,
    runtime_quote_binding_row,
    validate_binding,
    validate_quote_binding,
    validate_quote_pair,
)
from sportsedge.orchestrator import run_candidate

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


class Game:
    game_pk = 777
    game_number = 1
    home_team_id = 20
    away_team_id = 10


def q(market, side, entity, line, odds=-110):
    raw = {
        "game_id": "777", "period": "FG", "market": market,
        "entity_id": str(entity), "line": line, "side": side,
        "american_odds": odds, "book_key": "draftkings",
        "retrieved_at": NOW, "ttl_seconds": 300,
        "is_alternate": False, "raw_market_name": market.lower(),
    }
    return attach_runtime_binding_context(raw, Game())


class SpecTests(unittest.TestCase):
    def test_all_38_declared_and_only_first_four_production_wired(self):
        self.assertEqual(len(MARKET_BINDINGS), 38)
        passed = {m for m in MARKET_BINDINGS if audit_status(m) == "PASS"}
        self.assertEqual(passed, PRODUCTION_WIRED_MARKETS)
        self.assertEqual(passed, {"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})

    def test_domains_are_explicit_and_contradictions_fail(self):
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
            validate_quote_pair(runtime_quote_binding_row(over), runtime_quote_binding_row(q("TEAM_TOTALS", "UNDER", 10, 4.5)))

    def test_missing_event_instance_and_bad_threshold_fail(self):
        row = runtime_quote_binding_row(q("TOTALS", "OVER", 777, 8.5))
        row.pop("game_number")
        with self.assertRaisesRegex(BindingError, "game_number"):
            validate_quote_binding(row)
        bad = runtime_quote_binding_row(q("TOTALS", "OVER", 777, -8.5))
        with self.assertRaisesRegex(BindingError, "OUT_OF_DOMAIN"):
            validate_quote_binding(bad)


class FullBindingTests(unittest.TestCase):
    def test_probability_team_and_line_mismatches_fail(self):
        quote = q("RUN_LINE", "HOME", 20, -1.5)
        output = {"game_id": "777", "market": "RUN_LINE", "entity_id": "20", "line": -1.5, "side": "HOME", "model_p": 0.55, "push_p": 0.0}
        row = runtime_full_binding_row(quote, output)
        validate_binding(row)
        row["probability_team_id"] = "10"
        with self.assertRaisesRegex(BindingError, "PROBABILITY_TEAM_MISMATCH"):
            validate_binding(row)

    def test_orchestrator_executes_binding_for_first_four(self):
        cases = [
            ("MONEYLINE", q("MONEYLINE", "HOME", 20, 0.0, -120), q("MONEYLINE", "AWAY", 10, 0.0, +110), 0.56, 0.0),
            ("RUN_LINE", q("RUN_LINE", "HOME", 20, -1.5, +105), q("RUN_LINE", "AWAY", 10, +1.5, -125), 0.51, 0.0),
            ("TOTALS", q("TOTALS", "OVER", 777, 8.5, -110), q("TOTALS", "UNDER", 777, 8.5, -110), 0.54, 0.0),
            ("TEAM_TOTALS", q("TEAM_TOTALS", "OVER", 20, 4.5, -110), q("TEAM_TOTALS", "UNDER", 20, 4.5, -110), 0.54, 0.0),
        ]
        floor = SimpleNamespace(value_probability_points=0.03)
        with patch("sportsedge.orchestrator.require_production_edge_floor", return_value=floor):
            for market, quote, opposite, p, push in cases:
                model_input = {"game_id": "777", "market": market, "entity_id": quote["entity_id"], "line": quote["line"], "side": quote["side"]}
                def engine(mi, p=p, push=push):
                    return {"model_p": p, "push_p": push}
                result = run_candidate(
                    model_input=model_input, quote=quote, paired_quote=opposite,
                    deployment={"eligible": True, "market": market}, engine_fn=engine,
                    ingestion_now=NOW, finalization_now=NOW,
                )
                self.assertIsNotNone(result.model_p, f"{market}: {result.reason}")
                self.assertNotEqual(result.bet_status, "BLOCKED", f"{market}: {result.reason}")

    def test_binding_failure_blocks_only_row(self):
        quote = q("MONEYLINE", "HOME", 10, 0.0, -120)
        opposite = q("MONEYLINE", "AWAY", 10, 0.0, +110)
        model_input = {"game_id": "777", "market": "MONEYLINE", "entity_id": "10", "line": 0.0, "side": "HOME"}
        with patch("sportsedge.orchestrator.require_production_edge_floor", return_value=SimpleNamespace(value_probability_points=0.03)):
            result = run_candidate(
                model_input=model_input, quote=quote, paired_quote=opposite,
                deployment={"eligible": True, "market": "MONEYLINE"},
                engine_fn=lambda _: {"model_p": 0.55, "push_p": 0.0},
                ingestion_now=NOW, finalization_now=NOW,
            )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIn("SIDE_TEAM_MISMATCH", result.reason)


if __name__ == "__main__":
    unittest.main()
