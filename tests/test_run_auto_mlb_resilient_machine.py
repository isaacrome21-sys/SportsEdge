import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.mlb_run_machine import MLBMachineReport, MLBMachineResult

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_auto_mlb_resilient.py"
SPEC = importlib.util.spec_from_file_location("run_auto_mlb_resilient", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def machine_report(*, run_status="PASS", market="HITS"):
    row = MLBMachineResult(
        source_index=0,
        game_id="123",
        market=market,
        entity_id="301",
        line=0.5,
        side="OVER",
        american_odds=-110,
        model_p=0.62,
        bet_status="BLOCKED",
        reason="deployment blocked",
        shadow_status="SHADOW_BET",
        implied_probability=0.50,
        edge=0.12,
        ev_per_dollar=0.13,
        model_input_hash="a" * 64,
        distribution_sha256="b" * 64,
        readout_sha256="c" * 64,
        readout_version="mlb_v7_game_readout_v1",
        engine_version="mlb_hitter_joint_empirical_v3",
        seed_policy="analytic_weighted_empirical_joint_game_rows",
        mc_paths=0,
        book_key="draftkings",
        sportsbook="DraftKings",
        quote_retrieved_at="2026-08-24T14:29:30+00:00",
        offer_id="offer-123",
    )
    return MLBMachineReport(
        mode="AUTOMATIC",
        slate_date_ct="2026-08-24",
        generated_at_utc="2026-08-24T14:30:00+00:00",
        run_status=run_status,
        results=(row,),
        source_failures=(),
        summary={"quote_count": 1},
    )


def legacy_report(*, market="MONEYLINE"):
    row = machine_report(market=market).results[0]
    return type("Legacy", (), {
        "slate_date_ct": "2026-08-24",
        "generated_at_utc": "2026-08-24T14:30:00+00:00",
        "run_status": "PASS",
        "card_status": "NO_BETS",
        "market_surface_version": "test-surface-v1",
        "coverage_slots": (),
        "results": (row,),
        "source_failures": (),
    })()


def argv_for(td, output, *extra):
    return [
        str(SCRIPT),
        "--output", str(output),
        "--prediction-journal-dir", str(Path(td) / "journal"),
        *extra,
    ]


def write_evidence(td):
    path = Path(td) / "evidence.json"
    path.write_text(json.dumps({
        "schema_version": "sportsedge_evidence_v1",
        "packets": [{
            "game_id": "123",
            "fact_type": "STARTER_ID",
            "subject_id": "HOME",
            "value": "999",
            "source_name": "MLB.com screenshot",
            "observed_at_utc": "2026-08-24T14:29:00+00:00",
            "authority": "AUTHORITATIVE",
            "verified": True,
        }],
    }))
    return path


class ResilientMachineRoutingTests(unittest.TestCase):
    def test_native_production_calls_run_it_once_with_entire_keyring_and_ignores_legacy_feature_url(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            env = {
                "SPORTSEDGE_ODDS_API_KEY": "key-one",
                "SPORTSEDGE_ODDS_API_KEY_2": "key-two",
                "SPORTSEDGE_ODDS_API_KEY_3": "key-three",
                "SPORTSEDGE_ODDS_BOOKMAKERS": "draftkings",
                "SPORTSEDGE_FEATURES_URL": "https://legacy-features-should-not-route-native",
            }
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output)), \
                 patch.object(mod, "run_it_mlb", return_value=machine_report()) as run_it, \
                 patch.object(mod, "should_rotate_odds_key", return_value=False), \
                 patch.object(mod, "run_auto_mlb_espn_game_odds", side_effect=AssertionError("fallback should not run")):
                code = mod.main()

            self.assertEqual(code, 0)
            self.assertEqual(run_it.call_count, 1)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["mode"], "AUTOMATIC")
            self.assertEqual(payload["funnel"]["odds_rows_fetched"], 1)
            self.assertEqual(payload["prediction_journal"]["schema_version"], "mlb_prediction_journal_v2")
            self.assertEqual(payload["prediction_journal"]["prediction_count"], 1)
            self.assertEqual(len(list((Path(td) / "journal").rglob("*.json"))), 1)
            kwargs = run_it.call_args.kwargs
            self.assertEqual(kwargs["mode"], "AUTOMATIC")
            self.assertEqual(kwargs["odds_api_key"], "key-one")
            self.assertEqual(kwargs["odds_api_keys"], ("key-two", "key-three"))
            self.assertIsNone(kwargs["evidence_packets"])
            self.assertNotIn("feature_url", kwargs)

    def test_manual_evidence_file_is_passed_to_canonical_native_machine(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            evidence = write_evidence(td)
            env = {"SPORTSEDGE_ODDS_API_KEY": "key-one"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output, "--evidence-file", str(evidence))), \
                 patch.object(mod, "run_it_mlb", return_value=machine_report()) as run_it, \
                 patch.object(mod, "should_rotate_odds_key", return_value=False), \
                 patch.object(mod, "run_auto_mlb_espn_game_odds", side_effect=AssertionError("fallback should not run")):
                code = mod.main()

            self.assertEqual(code, 0)
            packets = run_it.call_args.kwargs["evidence_packets"]
            self.assertEqual(len(packets), 1)
            self.assertEqual(packets[0].acquisition_mode, "MANUAL")
            self.assertEqual(packets[0].fact_type, "STARTER_ID")
            self.assertEqual(packets[0].value, "999")

    def test_manual_evidence_never_bypasses_gate_through_espn_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            evidence = write_evidence(td)
            env = {"SPORTSEDGE_ODDS_API_KEY": "bad-key"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output, "--evidence-file", str(evidence))), \
                 patch.object(mod, "run_it_mlb", side_effect=RuntimeError("native down")), \
                 patch.object(mod, "run_auto_mlb_espn_game_odds", side_effect=AssertionError("evidence must not be bypassed")):
                code = mod.main()

            self.assertEqual(code, 2)
            payload = json.loads(output.read_text())
            reasons = [str(item.get("reason")) for item in payload["source_failures"]]
            self.assertTrue(any("EVIDENCE_GATED_NATIVE_RUN_UNAVAILABLE" in reason for reason in reasons))

    def test_native_exception_falls_back_to_espn_and_records_failure(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            env = {"SPORTSEDGE_ODDS_API_KEY": "bad-key"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output)), \
                 patch.object(mod, "run_it_mlb", side_effect=RuntimeError("native down")), \
                 patch.object(mod, "run_auto_mlb_espn_game_odds", return_value=legacy_report()) as fallback:
                code = mod.main()

            self.assertEqual(code, 0)
            fallback.assert_called_once()
            self.assertIsNone(fallback.call_args.kwargs["feature_url"])
            payload = json.loads(output.read_text())
            reasons = [str(x.get("reason")) for x in payload["source_failures"]]
            self.assertTrue(any("native down" in reason for reason in reasons))
            self.assertIn("RuntimeError: native down", payload["funnel"]["gate_kill_counts"])
            self.assertEqual(payload["prediction_journal"]["schema_version"], "mlb_prediction_journal_v2")

    def test_unusable_native_report_falls_back_once(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            env = {"SPORTSEDGE_ODDS_API_KEY": "key-one", "SPORTSEDGE_ODDS_API_KEY_2": "key-two"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output)), \
                 patch.object(mod, "run_it_mlb", return_value=machine_report(run_status="BLOCKED_NO_ODDS")) as run_it, \
                 patch.object(mod, "should_rotate_odds_key", return_value=True), \
                 patch.object(mod, "run_auto_mlb_espn_game_odds", return_value=legacy_report()) as fallback:
                code = mod.main()
            self.assertEqual(code, 0)
            self.assertEqual(run_it.call_count, 1)
            fallback.assert_called_once()

    def test_no_native_key_uses_espn_without_legacy_feature_hijack(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            env = {"SPORTSEDGE_FEATURES_URL": "https://legacy-features"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output)), \
                 patch.object(mod, "run_it_mlb", side_effect=AssertionError("no key should not call native")), \
                 patch.object(mod, "run_auto_mlb_espn_game_odds", return_value=legacy_report()) as fallback:
                code = mod.main()
            self.assertEqual(code, 0)
            self.assertIsNone(fallback.call_args.kwargs["feature_url"])

    def test_external_quote_url_remains_explicit_legacy_lane(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "card.json"
            env = {
                "SPORTSEDGE_QUOTES_URL": "https://external-quotes",
                "SPORTSEDGE_FEATURES_URL": "https://external-features",
            }
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, "argv", argv_for(td, output)), \
                 patch.object(mod, "run_auto_mlb", return_value=legacy_report()) as legacy_runner, \
                 patch.object(mod, "run_it_mlb", side_effect=AssertionError("canonical native path should not own explicit legacy URL lane")):
                code = mod.main()

            self.assertEqual(code, 0)
            kwargs = legacy_runner.call_args.kwargs
            self.assertEqual(kwargs["quote_url"], "https://external-quotes")
            self.assertEqual(kwargs["feature_url"], "https://external-features")


if __name__ == "__main__":
    unittest.main()
