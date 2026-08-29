from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sportsedge.core.leakage import assert_source_pit_integrity
from sportsedge.core.prior_decay import fit_prior_decay_artifact
from sportsedge.sports.cfb.audit_contracts import (
    CFBAuditContractError,
    CFBOverride,
    CoverageItem,
    CoverageReport,
    PITObservation,
    assert_mode_identity,
)
from sportsedge.sports.cfb.benchmark import (
    BenchmarkQuote,
    CFBBenchmarkError,
    score_original_contract_clv,
    select_reference_pair,
)
from sportsedge.sports.cfb.decision_policy import historical_candidate_policy, live_candidate_decision
from sportsedge.sports.cfb.entity_registry import CFBEntity, CFBEntityRegistry, CFBEntityResolutionError
from sportsedge.sports.cfb.governed_run import build_coverage_report, govern_cfb_report
from sportsedge.sports.cfb.key_number_validation import CFBKeyNumberError, key_number_calibration_report
from sportsedge.sports.cfb.opponent_adjust import CFBOpponentAdjustError, fit_schedule_adjusted_metric
from sportsedge.sports.cfb.prop_contract import CFBPropContractError, assert_prop_isolation
from sportsedge.sports.cfb.run_machine import CFBMachineReport, CFBMachineResult
from sportsedge.sports.cfb.truth_gate_v1 import CFBTruthGateEvidence, evaluate_cfb_truth_gate_v1


UTC = timezone.utc
NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)
START = NOW + timedelta(hours=10)


def result(game_id: str = "g1", market: str = "SPREAD", edge: float = 0.05, ev: float = 0.08) -> CFBMachineResult:
    return CFBMachineResult(
        game_id=game_id,
        market=market,
        side="HOME" if market != "TOTAL" else "OVER",
        line=-3.0 if market == "SPREAD" else 50.0 if market == "TOTAL" else 0.0,
        american_odds=-110.0,
        model_p=0.58,
        push_p=0.02 if market != "MONEYLINE" else 0.0,
        fair_market_p=0.50,
        raw_implied_p=0.5238,
        hold=0.0476,
        edge=edge,
        ev_per_dollar=ev,
        bet_status="BLOCKED",
        engine_status="PRICED",
        reason="CFB_PROMOTION_EVIDENCE_REQUIRED",
        model_artifact_sha256="a" * 64,
        distribution_sha256="b" * 64,
        seed=1,
        seed_policy="TEST",
        book_key="draftkings",
        sportsbook="DraftKings",
        quote_retrieved_at=NOW.isoformat(),
        offer_id="offer",
    )


def report(*rows: CFBMachineResult, mode: str = "MANUAL") -> CFBMachineReport:
    return CFBMachineReport(
        mode=mode,
        season=2026,
        week=1,
        generated_at_utc=NOW.isoformat(),
        run_status="READY",
        machine_version="TEST",
        results=tuple(rows),
        source_failures=(),
        summary={},
    )


def passing_gate_evidence(market: str = "SPREAD") -> CFBTruthGateEvidence:
    return CFBTruthGateEvidence(
        market=market,
        forward_seasons=4,
        promoted_sample=250,
        brier_model=0.20,
        brier_novig_market=0.21,
        logloss_model=0.58,
        logloss_novig_market=0.60,
        mean_novig_clv=0.006,
        clv_tstat=2.2,
        roi_after_vig=0.01,
        calibration_slope=1.0,
        calibration_intercept=0.0,
        ece=0.02,
        recent_2season_deterioration=False,
        leakage_violations=0,
        paired_historical_prices_present=True,
        pit_reproducible=True,
        policy_sha_valid=True,
        benchmark_methodology_sha_valid=True,
        all_promoted_rows_replayable=True,
    )


class PITTests(unittest.TestCase):
    def test_source_pit_rejects_post_kick_and_latency(self):
        base = dict(
            game_id="g1",
            source_id="CFBD",
            source_version="v1",
            provenance_id="p1",
            source_asof_ts=(NOW - timedelta(minutes=2)).isoformat(),
            feature_asof_ts=NOW.isoformat(),
            ingested_ts=(NOW - timedelta(minutes=1)).isoformat(),
            game_start_ts=START.isoformat(),
            max_latency_seconds=120,
        )
        assert_source_pit_integrity([base])
        leaked = dict(base, source_asof_ts=(START + timedelta(seconds=1)).isoformat(), feature_asof_ts=(START + timedelta(seconds=2)).isoformat())
        with self.assertRaisesRegex(ValueError, "SOURCE_TIME_LEAK|FEATURE_TIME_LEAK"):
            assert_source_pit_integrity([leaked])
        late = dict(base, ingested_ts=(NOW + timedelta(minutes=10)).isoformat())
        with self.assertRaisesRegex(ValueError, "SOURCE_LATENCY_EXCEEDED"):
            assert_source_pit_integrity([late])

    def test_pit_observation_requires_provenance(self):
        good = PITObservation(
            "CFBD", "v1", (NOW - timedelta(minutes=2)).isoformat(), NOW.isoformat(),
            (NOW - timedelta(minutes=1)).isoformat(), START.isoformat(), 120, "prov",
        )
        self.assertIs(good.validate(), good)
        with self.assertRaisesRegex(CFBAuditContractError, "PROVENANCE"):
            replace(good, provenance_id="").validate()


class EntityCoverageTests(unittest.TestCase):
    def test_entity_registry_collision_fails_closed(self):
        a = CFBEntity("a", "Alpha State", "FBS", ("ASU",))
        b = CFBEntity("b", "Another State", "FCS", ("ASU",))
        with self.assertRaisesRegex(CFBEntityResolutionError, "ALIAS_COLLISION"):
            CFBEntityRegistry(version="v1", entities=[a, b])

    def test_entity_registry_classifies_fbs_fcs(self):
        registry = CFBEntityRegistry(version="v1", entities=[
            CFBEntity("a", "Alpha State", "FBS", ("Alpha",)),
            CFBEntity("b", "Beta Tech", "FCS", ("Beta",)),
        ])
        self.assertEqual(registry.classify_matchup("Alpha", "Beta"), "FBS_FCS")
        with self.assertRaisesRegex(CFBEntityResolutionError, "BLOCKED_ENTITY_RESOLUTION"):
            registry.resolve("Alfa State")

    def test_coverage_silent_drop_fails(self):
        coverage = CoverageReport(
            ("g1", "g2"),
            (CoverageItem("g1", "FBS_FBS", "SCORED"),),
        )
        with self.assertRaisesRegex(CFBAuditContractError, "COVERAGE_SILENT_DROP"):
            coverage.validate()

    def test_machine_coverage_marks_missing_quote_game_unavailable(self):
        coverage = build_coverage_report(
            expected_games=[
                {"game_id": "g1", "classification": "FBS_FBS"},
                {"game_id": "g2", "classification": "FBS_FCS"},
            ],
            machine_report=report(result("g1")),
        )
        states = {item.game_id: item.status for item in coverage.items}
        self.assertEqual(states, {"g1": "SCORED", "g2": "UNAVAILABLE"})


class PriorAndDecisionTests(unittest.TestCase):
    def test_prior_artifact_rejects_outer_test_season(self):
        rows = []
        for season in (2022, 2023):
            for week in (1, 2, 3, 4):
                rows.append({"season": season, "week": week, "target": 1.0, "prior_pred": 0.8, "current_pred": 0.5})
        artifact = fit_prior_decay_artifact(rows, test_season=2024, prior_version="prior-v1")
        self.assertEqual(len(artifact.content_hash()), 64)
        with self.assertRaisesRegex(ValueError, "TEST_SEASON_IN_TRAINING"):
            fit_prior_decay_artifact(rows, test_season=2023, prior_version="prior-v1")

    def test_historical_policy_breaks_circular_gate(self):
        historical = historical_candidate_policy(
            edge=0.03,
            ev_per_dollar=0.02,
            quote_fresh=True,
            two_sided=True,
            data_quality_ok=True,
            pit_ok=True,
            coverage_ok=True,
            policy_sha_ok=True,
        )
        self.assertEqual(historical.status, "SHADOW_QUALIFIED")
        blocked_live = live_candidate_decision(
            edge=0.03,
            ev_per_dollar=0.02,
            quote_fresh=True,
            two_sided=True,
            exposure_ok=True,
            data_quality_ok=True,
            coverage_ok=True,
            override_log_complete=True,
            policy_sha_ok=True,
            historical_status="UNRUN",
        )
        self.assertEqual(blocked_live.status, "BLOCKED")
        official = live_candidate_decision(
            edge=0.03,
            ev_per_dollar=0.02,
            quote_fresh=True,
            two_sided=True,
            exposure_ok=True,
            data_quality_ok=True,
            coverage_ok=True,
            override_log_complete=True,
            policy_sha_ok=True,
            historical_status="OFFICIAL",
        )
        self.assertEqual(official.status, "OFFICIAL_BET")

    def test_automatic_mode_rejects_narrative_override(self):
        override = CFBOverride(
            "o1", NOW.isoformat(), "g1", "AUTOMATIC", "QB_NEWS", ("source1",), "BLOCK",
        )
        with self.assertRaises(CFBAuditContractError):
            override.validate()
        manual = CFBOverride(
            "o2", NOW.isoformat(), "g1", "MANUAL", "QB_NEWS", ("source1",), "BLOCK",
        )
        governed = govern_cfb_report(
            report(result("g1"), mode="MANUAL"),
            expected_games=[{"game_id": "g1", "classification": "FBS_FBS"}],
            decision_stage="LIVE",
            historical_market_status={"SPREAD": "OFFICIAL"},
            exposure_ok=True,
            data_quality_ok=True,
            policy_sha_ok=True,
            overrides=[manual],
        )
        self.assertEqual(governed.results[0].governed_status, "BLOCKED")
        self.assertAlmostEqual(governed.results[0].engine_result.model_p, 0.58)


class BenchmarkTests(unittest.TestCase):
    def q(self, quote_id, provider, side, odds, captured, line=-3.0):
        return BenchmarkQuote(quote_id, provider, provider, "g1", "SPREAD", side, line, odds, captured)

    def test_reference_uses_priority_tier_not_soft_best_price(self):
        ts = (NOW - timedelta(seconds=20)).isoformat()
        quotes = [
            self.q("p1", "PINNACLE", "HOME", -105, ts), self.q("p2", "PINNACLE", "AWAY", -105, ts),
            self.q("d1", "DRAFTKINGS", "HOME", 110, ts), self.q("d2", "DRAFTKINGS", "AWAY", -130, ts),
        ]
        pair = select_reference_pair(
            quotes,
            game_id="g1",
            market="SPREAD",
            line=-3.0,
            cutoff_ts=NOW,
            provider_priority_tiers=(("PINNACLE",), ("DRAFTKINGS",)),
            max_quote_age_seconds=180,
        )
        self.assertEqual(pair.provider, "PINNACLE")
        self.assertFalse(pair.fallback_used)

    def test_clv_is_close_minus_decision_for_original_contract(self):
        decision_ts = (NOW - timedelta(minutes=2)).isoformat()
        close_ts = NOW.isoformat()
        decision = select_reference_pair(
            [self.q("d1", "PINNACLE", "HOME", -110, decision_ts), self.q("d2", "PINNACLE", "AWAY", -110, decision_ts)],
            game_id="g1", market="SPREAD", line=-3.0, cutoff_ts=NOW - timedelta(minutes=1),
            provider_priority_tiers=(("PINNACLE",),), max_quote_age_seconds=180,
        )
        close = select_reference_pair(
            [self.q("c1", "PINNACLE", "HOME", -130, close_ts), self.q("c2", "PINNACLE", "AWAY", 110, close_ts)],
            game_id="g1", market="SPREAD", line=-3.0, cutoff_ts=NOW,
            provider_priority_tiers=(("PINNACLE",),), max_quote_age_seconds=180,
        )
        scored = score_original_contract_clv(side="HOME", decision_reference=decision, closing_reference=close, model_p_at_decision=0.60)
        self.assertGreater(scored.clv_probability_points, 0.0)
        self.assertAlmostEqual(scored.model_vs_close_probability_points, 0.60 - scored.closing_novig_probability)
        moved_line = replace(close, line=-3.5)
        with self.assertRaisesRegex(CFBBenchmarkError, "ORIGINAL_CONTRACT_LINE_MISMATCH"):
            score_original_contract_clv(side="HOME", decision_reference=decision, closing_reference=moved_line)


class GateOpponentAndIsolationTests(unittest.TestCase):
    def test_frozen_cfb_gate_passes_only_complete_evidence(self):
        passed = evaluate_cfb_truth_gate_v1(passing_gate_evidence())
        self.assertEqual(passed.status, "OFFICIAL")
        failed = evaluate_cfb_truth_gate_v1(replace(passing_gate_evidence(), roi_after_vig=0.0, forward_seasons=3))
        self.assertEqual(failed.status, "FAILED")
        self.assertIn("ROI_AFTER_VIG_NOT_STRICTLY_POSITIVE", failed.failures)
        self.assertIn("FORWARD_SEASONS_LT_4", failed.failures)

    def test_opponent_adjust_forbids_outer_test_season(self):
        rows = []
        teams = ("A", "B", "C", "D")
        for season in (2022, 2023):
            for repeat in range(3):
                for i, team in enumerate(teams):
                    opponent = teams[(i + 1 + repeat) % len(teams)]
                    if opponent == team:
                        opponent = teams[(i + 1) % len(teams)]
                    rows.append({"season": season, "team": team, "opponent": opponent, "ppa": 0.1 * i - 0.03 * repeat})
        model = fit_schedule_adjusted_metric(rows, metric_key="ppa", test_season=2024, min_observations_per_team=2)
        self.assertEqual(len(model.content_hash()), 64)
        self.assertTrue(all(abs(model.expected_metric("A", "B")) < 10 for _ in [0]))
        with self.assertRaisesRegex(CFBOpponentAdjustError, "TEST_SEASON_IN_TRAINING"):
            fit_schedule_adjusted_metric(rows, metric_key="ppa", test_season=2023, min_observations_per_team=2)

    def test_key_number_report_can_fail_closed(self):
        empirical = [{"margin": 3}] * 20 + [{"margin": 7}] * 10 + [{"margin": 1}] * 70
        simulated = [{"margin": 1}] * 100
        report_ = key_number_calibration_report(empirical, simulated, tolerance=0.05)
        self.assertFalse(report_.passed)
        with self.assertRaisesRegex(CFBKeyNumberError, "KEY_NUMBER_CALIBRATION_FAILED"):
            report_.require_pass()

    def test_props_cannot_inherit_main_truth_gate(self):
        assert_prop_isolation(status="EXPERIMENTAL_PROP", truth_gate_policy="NONE")
        with self.assertRaisesRegex(CFBPropContractError, "MAIN_GATE_INHERITANCE_FORBIDDEN"):
            assert_prop_isolation(status="EXPERIMENTAL_PROP", truth_gate_policy="CFB_TRUTH_GATE_V1")

    def test_mode_identity(self):
        base = {"model_p": 0.55, "edge": 0.03, "fair_price": -122, "mode": "MANUAL"}
        payloads = {
            "MANUAL": base,
            "HYBRID": dict(base, mode="HYBRID"),
            "AUTOMATIC": dict(base, mode="AUTOMATIC"),
        }
        assert_mode_identity(payloads)
        payloads["AUTOMATIC"]["edge"] = 0.031
        with self.assertRaisesRegex(CFBAuditContractError, "MODE_MATHEMATICAL_IDENTITY_FAILED"):
            assert_mode_identity(payloads)


if __name__ == "__main__":
    unittest.main()
