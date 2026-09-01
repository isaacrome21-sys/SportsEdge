from __future__ import annotations

from datetime import datetime, timezone
import unittest

from sportsedge.delta_execution import (
    DeltaExecutionError,
    MarketDependency,
    execute_delta_rerun,
    plan_delta_rerun,
)
from sportsedge.shared_acquisition_contract import (
    ConfirmationStatus,
    FreshnessStatus,
    TrustClass,
    build_datum,
)

NOW = datetime(2026, 9, 1, 15, tzinfo=timezone.utc)


def datum(scope_type, scope_id, field_name, value, *, trust=TrustClass.MODEL_P_OBJECTIVE,
          observed_at=NOW, required=True, source_sha="a" * 64):
    return build_datum(
        sport="NFL", scope_type=scope_type, scope_id=scope_id, field_name=field_name,
        value=value, source_name="TEST", source_uri="https://example.test/source",
        observed_at=observed_at, retrieved_at=NOW, ttl_seconds=3600,
        confirmation_status=ConfirmationStatus.OFFICIAL,
        trust_class=trust, source_sha256=source_sha,
        required_for_evaluation=required,
    )


class DeltaExecutionTests(unittest.TestCase):
    def dep(self):
        return MarketDependency(
            market_id="g1:p1:REC_YDS", sport="NFL", game_id="g1", entity_ids=("p1",),
            model_keys=(("PLAYER", "p1", "injury"),),
            simulation_keys=(("GAME", "g1", "weather"),),
            pricing_keys=(("MARKET", "g1:p1:REC_YDS", "quote"),),
            correlation_groups=("GAME:g1", "PLAYER:p1"),
        )

    def base_rows(self):
        return [
            datum("PLAYER", "p1", "injury", "ACTIVE"),
            datum("GAME", "g1", "weather", {"wind": 5}),
            datum("MARKET", "g1:p1:REC_YDS", "quote", {"line": 70.5, "price": -110}, trust=TrustClass.MARKET_ONLY),
        ]

    def test_quote_only_delta_reprices_without_model_or_mc(self):
        before = self.base_rows()
        after = self.base_rows()
        after[-1] = datum("MARKET", "g1:p1:REC_YDS", "quote", {"line": 69.5, "price": -105}, trust=TrustClass.MARKET_ONLY)
        plan = plan_delta_rerun(run_id="run-1", previous=before, current=after, dependencies=[self.dep()])
        self.assertEqual(plan.model_p_market_ids, ())
        self.assertEqual(plan.monte_carlo_market_ids, ())
        self.assertEqual(plan.pricing_market_ids, ("g1:p1:REC_YDS",))
        self.assertTrue(plan.portfolio_refresh)
        self.assertIn("g1:p1:REC_YDS", plan.reusable_simulation_market_ids)

    def test_weather_delta_reruns_mc_not_model(self):
        before = self.base_rows()
        after = self.base_rows()
        after[1] = datum("GAME", "g1", "weather", {"wind": 22})
        plan = plan_delta_rerun(run_id="run-1", previous=before, current=after, dependencies=[self.dep()])
        self.assertEqual(plan.model_p_market_ids, ())
        self.assertEqual(plan.monte_carlo_market_ids, ("g1:p1:REC_YDS",))
        self.assertEqual(plan.pricing_market_ids, ("g1:p1:REC_YDS",))

    def test_injury_delta_reruns_full_predictive_path_only_for_dependent_market(self):
        dep2 = MarketDependency(
            market_id="g2:p2:RUSH_YDS", sport="NFL", game_id="g2",
            model_keys=(("PLAYER", "p2", "injury"),),
            pricing_keys=(("MARKET", "g2:p2:RUSH_YDS", "quote"),),
        )
        before = self.base_rows() + [
            datum("PLAYER", "p2", "injury", "ACTIVE"),
            datum("MARKET", "g2:p2:RUSH_YDS", "quote", {"line": 55.5, "price": -110}, trust=TrustClass.MARKET_ONLY),
        ]
        after = list(before)
        after[0] = datum("PLAYER", "p1", "injury", "OUT")
        plan = plan_delta_rerun(run_id="run-1", previous=before, current=after, dependencies=[self.dep(), dep2])
        self.assertEqual(plan.model_p_market_ids, ("g1:p1:REC_YDS",))
        self.assertEqual(plan.monte_carlo_market_ids, ("g1:p1:REC_YDS",))
        self.assertNotIn("g2:p2:RUSH_YDS", plan.pricing_market_ids)

    def test_shared_critical_delta_invalidates_all_enabled_markets(self):
        dep2 = MarketDependency(market_id="g2:TOTAL", sport="NFL", game_id="g2")
        shared = ("SHARED", "nfl", "model_artifact")
        before = self.base_rows() + [datum(*shared, "sha-a", required=False)]
        after = self.base_rows() + [datum(*shared, "sha-b", required=False)]
        plan = plan_delta_rerun(
            run_id="run-1", previous=before, current=after,
            dependencies=[self.dep(), dep2], shared_critical_keys=(shared,),
        )
        self.assertEqual(set(plan.model_p_market_ids), {"g1:p1:REC_YDS", "g2:TOTAL"})
        self.assertEqual(set(plan.monte_carlo_market_ids), {"g1:p1:REC_YDS", "g2:TOTAL"})

    def test_freshness_downgrade_blocks_required_market_even_if_value_same(self):
        before = self.base_rows()
        stale_time = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        after = self.base_rows()
        after[0] = datum("PLAYER", "p1", "injury", "ACTIVE", observed_at=stale_time)
        self.assertEqual(after[0].freshness_status, FreshnessStatus.STALE)
        plan = plan_delta_rerun(run_id="run-1", previous=before, current=after, dependencies=[self.dep()])
        self.assertEqual(plan.blocked_market_ids, ("g1:p1:REC_YDS",))
        self.assertNotIn("g1:p1:REC_YDS", plan.reusable_simulation_market_ids)

    def test_market_only_leak_into_model_dependency_fails_closed(self):
        bad = MarketDependency(
            market_id="bad", sport="NFL", game_id="g1",
            model_keys=(("MARKET", "bad", "quote"),),
        )
        before = [datum("MARKET", "bad", "quote", -110, trust=TrustClass.MARKET_ONLY)]
        after = [datum("MARKET", "bad", "quote", -105, trust=TrustClass.MARKET_ONLY)]
        with self.assertRaises(DeltaExecutionError):
            plan_delta_rerun(run_id="run", previous=before, current=after, dependencies=[bad])

    def test_execute_quote_only_delta_preserves_run_id_and_simulation(self):
        before = self.base_rows()
        after = self.base_rows()
        after[-1] = datum("MARKET", "g1:p1:REC_YDS", "quote", {"line": 69.5, "price": -105}, trust=TrustClass.MARKET_ONLY)
        plan = plan_delta_rerun(run_id="original-run", previous=before, current=after, dependencies=[self.dep()])
        calls = {"model":0,"mc":0,"price":0,"portfolio":0,"gate":0}
        prior = {"g1:p1:REC_YDS":{"model_p":0.57,"monte_carlo":{"p_over":0.57},"price":"old"}}
        result = execute_delta_rerun(
            plan=plan,
            prior_market_results=prior,
            model_p_fn=lambda market, old: calls.__setitem__("model", calls["model"]+1),
            monte_carlo_fn=lambda market, model, old: calls.__setitem__("mc", calls["mc"]+1),
            pricing_fn=lambda market, current, old: (calls.__setitem__("price", calls["price"]+1) or {**current, "price":"new"}),
            portfolio_fn=lambda state, groups: (calls.__setitem__("portfolio", calls["portfolio"]+1) or {"sized":True}),
            execution_gate_fn=lambda state, portfolio, blocked: (calls.__setitem__("gate", calls["gate"]+1) or {"ok":True}),
        )
        self.assertEqual(result.run_id, "original-run")
        self.assertEqual(calls["model"], 0)
        self.assertEqual(calls["mc"], 0)
        self.assertEqual(calls["price"], 1)
        self.assertEqual(result.market_results["g1:p1:REC_YDS"]["monte_carlo"], {"p_over":0.57})
        self.assertEqual(calls["portfolio"], 1)
        self.assertEqual(calls["gate"], 1)


if __name__ == "__main__":
    unittest.main()
