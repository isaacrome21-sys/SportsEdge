from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from sportsedge.sports.cfb.holdout_runner import HoldoutRunner, HoldoutRunnerError
from sportsedge.sports.cfb.truth_gate import TruthGate, TruthGateError

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "cfb_truth_gate_v1.json"


def passing_kwargs(gate: TruthGate):
    return dict(
        market="MONEYLINE",
        pit_reproducible=True,
        leakage_violations=0,
        n_forward_seasons=4,
        brier_model=0.20,
        brier_market=0.21,
        logloss_model=0.58,
        logloss_market=0.60,
        season_fold_scoring_win_rate=0.75,
        mean_novig_clv=0.006,
        clv_t_stat=2.2,
        roi_after_vig=0.01,
        calibration_slope=1.0,
        calibration_intercept=0.0,
        ece=0.02,
        n_promoted=200,
        recent_two_season_ok=True,
        paired_historical_price_evidence_complete=True,
        evidence_policy_sha256=gate.policy_sha256,
    )


class TruthGatePolicyTests(unittest.TestCase):
    def test_policy_uses_canonical_runtime_markets(self):
        gate = TruthGate(POLICY)
        self.assertEqual(gate.markets, {"MONEYLINE", "SPREAD", "TOTAL"})
        self.assertEqual(gate.policy["policy_id"], "CFB_TRUTH_GATE_V1")
        self.assertEqual(len(gate.policy_sha256), 64)

    def test_one_hard_failure_blocks_without_override(self):
        gate = TruthGate(POLICY)
        kwargs = passing_kwargs(gate)
        kwargs["leakage_violations"] = 1
        out = gate.evaluate(**kwargs)
        self.assertFalse(out.hard_gate_pass)
        self.assertFalse(out.promoted)
        self.assertEqual(out.status, "EXPERIMENTAL")
        self.assertIn("LEAKAGE_VIOLATIONS_EXCEEDED", out.failures)

    def test_minimum_not_preferred_sample_is_sufficient_hard_gate(self):
        gate = TruthGate(POLICY)
        out = gate.evaluate(**passing_kwargs(gate))
        self.assertTrue(out.hard_gate_pass)
        self.assertTrue(out.promoted)
        self.assertEqual(out.status, "OFFICIAL")
        self.assertEqual(out.diagnostics["preferred_promoted_sample"], 800)

    def test_policy_hash_mismatch_fails_closed(self):
        gate = TruthGate(POLICY)
        kwargs = passing_kwargs(gate)
        kwargs["evidence_policy_sha256"] = "0" * 64
        out = gate.evaluate(**kwargs)
        self.assertFalse(out.hard_gate_pass)
        self.assertIn("FROZEN_POLICY_HASH_MISMATCH", out.failures)

    def test_unknown_market_is_rejected(self):
        gate = TruthGate(POLICY)
        kwargs = passing_kwargs(gate)
        kwargs["market"] = "TEAM_TOTALS"
        with self.assertRaisesRegex(TruthGateError, "MARKET_UNSUPPORTED"):
            gate.evaluate(**kwargs)

    def test_candidate_bet_requires_official_market_live_gates_and_edge(self):
        gate = TruthGate(POLICY)
        report = gate.evaluate(**passing_kwargs(gate))
        low = gate.decide_candidate(
            report,
            model_prob=0.56,
            no_vig_prob=0.54,
            live_two_sided_quote=True,
            data_fresh=True,
            exposure_limits_ok=True,
        )
        self.assertEqual(low.bet_status, "NO_BET")
        stale = gate.decide_candidate(
            report,
            model_prob=0.58,
            no_vig_prob=0.54,
            live_two_sided_quote=True,
            data_fresh=False,
            exposure_limits_ok=True,
        )
        self.assertEqual(stale.bet_status, "BLOCKED")
        self.assertIn("DATA_NOT_FRESH", stale.failures)
        bet = gate.decide_candidate(
            report,
            model_prob=0.58,
            no_vig_prob=0.54,
            live_two_sided_quote=True,
            data_fresh=True,
            exposure_limits_ok=True,
        )
        self.assertEqual(bet.bet_status, "OFFICIAL_BET")


class HoldoutRunnerTests(unittest.TestCase):
    def test_vector_length_mismatch_fails_closed(self):
        runner = HoldoutRunner(POLICY)
        with self.assertRaisesRegex(HoldoutRunnerError, "VECTOR_LENGTH_MISMATCH"):
            runner.evaluate_market(
                "MONEYLINE",
                y_true=[1, 0],
                y_prob=[0.6],
                market_novig_prob=[0.5, 0.5],
                clv_series=[0.01, 0.01],
                roi_series=[0.1, -1.0],
                season_ids=[2022, 2022],
                pit_reproducible=True,
                leakage_violations=0,
                paired_historical_price_evidence_complete=True,
                recent_two_season_ok=True,
            )

    def test_full_card_requires_all_three_independent_markets(self):
        runner = HoldoutRunner(POLICY)
        with self.assertRaisesRegex(HoldoutRunnerError, "MARKET_SURFACE_MISMATCH"):
            runner.run_full_card({"MONEYLINE": {}})

    def test_promoted_subset_drives_clv_roi(self):
        runner = HoldoutRunner(POLICY)
        rng = np.random.default_rng(20260827)
        n = 12000
        y_prob = rng.uniform(0.15, 0.85, size=n)
        y_true = rng.binomial(1, y_prob).astype(float)
        market_prob = 0.5 + 0.45 * (y_prob - 0.5)
        edges = y_prob - market_prob
        promoted = edges >= runner.edge_floor
        self.assertGreater(int(promoted.sum()), 800)

        clv = np.full(n, -0.50)
        roi = np.full(n, -1.00)
        clv[promoted] = 0.006 + rng.normal(0.0, 0.002, size=int(promoted.sum()))
        roi[promoted] = 0.03 + rng.normal(0.0, 0.15, size=int(promoted.sum()))
        seasons = np.repeat(np.array([2022, 2023, 2024, 2025]), n // 4)

        out = runner.evaluate_market(
            "MONEYLINE",
            y_true=y_true,
            y_prob=y_prob,
            market_novig_prob=market_prob,
            clv_series=clv,
            roi_series=roi,
            season_ids=seasons,
            pit_reproducible=True,
            leakage_violations=0,
            paired_historical_price_evidence_complete=True,
            recent_two_season_ok=True,
        )
        self.assertGreater(out.metrics["mean_novig_clv"], 0.005)
        self.assertGreater(out.metrics["roi_after_vig"], 0.0)
        self.assertEqual(out.metrics["n_promoted"], int(promoted.sum()))

    def test_content_addressed_report_is_idempotent(self):
        gate = TruthGate(POLICY)
        report = gate.evaluate(**passing_kwargs(gate))
        runner = HoldoutRunner(POLICY)
        with tempfile.TemporaryDirectory() as tmp:
            first = runner.write_reports({"MONEYLINE": report}, tmp)
            second = runner.write_reports({"MONEYLINE": report}, tmp)
            self.assertEqual(first, second)
            self.assertEqual(len(list(Path(tmp).glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
