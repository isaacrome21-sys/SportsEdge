"""CLI boundary tests with a stub summarizer; not a real model backtest."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_pit_replay_gate import BASE, HOLD, CUTOFF


class PITReplayCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = types.ModuleType("sportsedge.research.multi_market_backtest")
        class ResearchBacktestError(ValueError): pass
        cls.stub.ResearchBacktestError = ResearchBacktestError
        cls.received = []
        def summarize_binary_market(rows):
            cls.received.append(rows)
            if all(r["outcome"] is None for r in rows):
                raise ResearchBacktestError("NO_BINARY_ROWS_FOR_BRIER")
            return {"n_rows": len(rows), "bet_roi": None, "avg_clv_pct": None}
        cls.stub.summarize_binary_market = summarize_binary_market
        sys.modules[cls.stub.__name__] = cls.stub
        file = Path(__file__).parents[1] / "scripts" / "audit_research_replay_pit.py"
        spec = importlib.util.spec_from_file_location("audit_research_replay_pit", file)
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop(cls.stub.__name__, None)

    def run_cli(self, rows):
        with tempfile.TemporaryDirectory() as temp:
            inp, out = Path(temp) / "in.jsonl", Path(temp) / "out.json"
            inp.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            with patch.object(sys, "argv", ["audit", str(inp), "--holdout-start", CUTOFF, "--output", str(out)]):
                self.assertEqual(self.cli.main(), 0)
            return json.loads(out.read_text(encoding="utf-8"))

    def test_holdout_only_and_no_unverified_financials(self):
        self.received.clear()
        report = self.run_cli([BASE, {**HOLD, "offered_decimal": 5, "clv_pct": 99, "benchmark_p": 0.9, "selected": True}])
        self.assertEqual(report["train_n"], 1)
        self.assertEqual(report["holdout_n"], 1)
        self.assertEqual(len(self.received), 1)
        row = self.received[0][0]
        self.assertEqual(row["event_id"], "G2")
        self.assertIsNone(row["offered_decimal"])
        self.assertIsNone(row["clv_pct"])
        self.assertIsNone(row["benchmark_p"])
        self.assertIs(row["selected"], False)
        self.assertIs(report["production_eligible"], False)
        self.assertEqual(report["markets"][0]["clv_roi_status"], "UNAVAILABLE_AUTHENTICATED_QUOTES_REQUIRED")

    def test_push_only_holdout_is_insufficient_data(self):
        report = self.run_cli([BASE, {**HOLD, "outcome": None, "settlement_status": "PUSH"}])
        self.assertEqual(report["markets"][0]["status"], "INSUFFICIENT_DATA")
        self.assertEqual(report["markets"][0]["blocker"], "NO_BINARY_ROWS_FOR_BRIER")

    def test_multiple_versions_separately_reported(self):
        # Each frozen (sport, market, version) needs its own settled,
        # pre-cutoff training row. A v1 prior cannot qualify v2.
        v2_train = {**BASE, "selection_id": "S4",
                    "model_version": "v2", "model_hash": "hash-v2"}
        third = {**HOLD, "event_id": "G3", "selection_id": "S3",
                 "model_version": "v2", "model_hash": "hash-v2"}
        report = self.run_cli([BASE, v2_train, HOLD, third])
        self.assertEqual((report["train_n"], report["holdout_n"]), (2, 2))
        self.assertEqual(len(report["markets"]), 2)
        self.assertEqual({r["model_version"] for r in report["markets"]}, {"v1", "v2"})
        self.assertIs(report["production_eligible"], False)

    def test_missing_v2_prior_refuses_at_cli_boundary(self):
        # Preserve the stricter gate; this is NOT a reason to weaken it.
        import io
        third = {**HOLD, "event_id": "G3", "selection_id": "S3",
                 "model_version": "v2", "model_hash": "hash-v2"}
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as raised:
                self.run_cli([BASE, HOLD, third])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("TRAINING_GROUP_MISSING:NFL/TOTAL/v2", stderr.getvalue())


if __name__ == "__main__": unittest.main()
