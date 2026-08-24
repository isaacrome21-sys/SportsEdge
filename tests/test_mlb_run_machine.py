import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sportsedge.engine_registry import engine_registry
from sportsedge.mlb_run_machine import (
    MLBRunMachineError,
    run_it_mlb,
    run_mlb_machine,
)
from sportsedge.unified_card import SUPPORTED_MARKETS

NOW = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
CATALOG_GROUPS = (
    "game_markets",
    "batter_markets",
    "pitcher_markets",
    "separate_protocol_markets",
    "binary_markets_not_coerced",
    "period_markets_not_coerced",
)


def result(*, market="HITS", status="BLOCKED", model_p=0.61, source_index=0):
    return SimpleNamespace(
        source_index=source_index,
        game_id="123",
        market=market,
        entity_id="301",
        line=0.5,
        side="OVER",
        american_odds=-110,
        model_p=model_p,
        bet_status=status,
        reason="deployment blocked" if status == "BLOCKED" else "ok",
        shadow_status="SHADOW_BET",
        implied_probability=0.50,
        edge=0.11,
        ev_per_dollar=0.12,
    )


def auto_report(rows=None):
    return SimpleNamespace(
        slate_date_ct="2026-08-24",
        generated_at_utc=NOW.isoformat(),
        run_status="PASS",
        results=tuple(rows or [result()]),
        source_failures=(),
    )


class MLBRunMachineTests(unittest.TestCase):
    def test_full_36_market_surface_is_one_registry(self):
        catalog = json.loads(Path("config/mlb_market_catalog.json").read_text())
        flat = [market for group in CATALOG_GROUPS for market in catalog[group]]
        self.assertEqual(len(flat), 36)
        self.assertEqual(len(set(flat)), 36)
        markets = set(flat)
        self.assertEqual(markets, set(SUPPORTED_MARKETS))
        self.assertEqual(markets, set(engine_registry()))

    @patch("sportsedge.mlb_run_machine.run_manual_hybrid_joint_mlb")
    def test_auto_select_full_snapshot_routes_manual(self, runner):
        runner.return_value = [result()]
        report = run_mlb_machine(
            quotes=[{"x": 1}],
            games=[object()],
            feature_rows=[{"x": 1}],
            now=NOW,
        )
        self.assertEqual(report.mode, "MANUAL")
        self.assertEqual(report.summary["quote_count"], 1)
        runner.assert_called_once()

    @patch("sportsedge.mlb_run_machine.run_auto_joint_mlb")
    def test_auto_select_quotes_only_routes_hybrid_and_preserves_quote_payload(self, runner):
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            with kwargs["opener"](kwargs["quote_url"]) as response:
                captured["quotes"] = json.loads(response.read())
            return auto_report()

        runner.side_effect = fake
        quotes = [{"game_id": "123", "market": "HITS", "entity_id": "301", "side": "OVER", "line": 0.5, "american_odds": -110}]
        report = run_mlb_machine(quotes=quotes, now=NOW)
        self.assertEqual(report.mode, "HYBRID")
        self.assertEqual(captured["quotes"], quotes)
        self.assertNotIn("odds_api_key", captured)

    @patch("sportsedge.mlb_run_machine.run_auto_mlb_native_odds")
    def test_auto_select_no_quotes_routes_automatic_and_forces_canonical_features(self, runner):
        runner.return_value = auto_report()
        report = run_mlb_machine(odds_api_key="secret", now=NOW)
        self.assertEqual(report.mode, "AUTOMATIC")
        kwargs = runner.call_args.kwargs
        self.assertEqual(kwargs["odds_api_key"], "secret")
        self.assertIsNone(kwargs["feature_url"])

    @patch("sportsedge.mlb_run_machine.run_auto_joint_mlb")
    def test_explicit_hybrid_never_fetches_sportsbook_quotes(self, runner):
        runner.return_value = auto_report()
        run_mlb_machine(mode="HYBRID", quotes=[{"anything": "user supplied"}], now=NOW)
        kwargs = runner.call_args.kwargs
        self.assertEqual(kwargs["quote_url"], "https://sportsedge.local/run-it-quotes")

    def test_auto_select_rejects_partial_manual_snapshot(self):
        with self.assertRaisesRegex(MLBRunMachineError, "AUTO_SELECT_INPUTS_AMBIGUOUS"):
            run_mlb_machine(quotes=[{"x": 1}], games=[object()], now=NOW)

    def test_automatic_requires_real_odds_key(self):
        with self.assertRaisesRegex(MLBRunMachineError, "AUTOMATIC_REQUIRES_ODDS_API_KEY"):
            run_mlb_machine(mode="AUTOMATIC", now=NOW)

    @patch("sportsedge.mlb_run_machine.run_auto_mlb_native_odds")
    def test_run_it_alias_uses_same_machine(self, runner):
        runner.return_value = auto_report([result(status="OFFICIAL_BET")])
        report = run_it_mlb(odds_api_key="secret", now=NOW)
        self.assertEqual(report.mode, "AUTOMATIC")
        self.assertEqual(report.summary["official_bets"], 1)
        self.assertEqual(report.summary["model_priced"], 1)

    @patch("sportsedge.mlb_run_machine.run_auto_mlb_native_odds")
    def test_report_preserves_blocked_rows_instead_of_hiding_them(self, runner):
        runner.return_value = auto_report([result(status="BLOCKED", model_p=None)])
        report = run_mlb_machine(mode="AUTOMATIC", odds_api_key="secret", now=NOW)
        self.assertEqual(report.summary["blocked"], 1)
        self.assertEqual(report.summary["model_priced"], 0)
        self.assertEqual(len(report.results), 1)


if __name__ == "__main__":
    unittest.main()
