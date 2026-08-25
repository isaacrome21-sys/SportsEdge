import unittest

from sportsedge.football_full_model import build_declared_market_grid, finalize_football_run


SURFACE = "config/football_market_surface.json"


class FootballFullModelStageZeroTests(unittest.TestCase):
    def test_declared_grid_exists_before_provider_response(self):
        rows = build_declared_market_grid(
            game_id="nfl-2026-w1-g1",
            sport="NFL",
            surface_path=SURFACE,
            provider_supported_markets={"moneyline", "spread", "total"},
            request_succeeded=True,
            offered_markets={"moneyline"},
        )
        names = {row.market for row in rows}
        self.assertIn("moneyline", names)
        self.assertIn("spread", names)
        self.assertIn("passing_yards", names)
        self.assertGreater(len(rows), 40)
        by_market = {row.market: row for row in rows}
        self.assertEqual(by_market["moneyline"].acquisition, "OFFERED")
        self.assertEqual(by_market["spread"].acquisition, "NOT_OFFERED")
        self.assertEqual(by_market["passing_yards"].acquisition, "PROVIDER_UNSUPPORTED")

    def test_provider_transport_failure_is_not_mislabeled_not_offered(self):
        rows = build_declared_market_grid(
            game_id="g",
            sport="NFL",
            surface_path=SURFACE,
            provider_supported_markets={"moneyline", "spread"},
            request_succeeded=False,
            offered_markets=set(),
        )
        by_market = {row.market: row for row in rows}
        self.assertEqual(by_market["moneyline"].acquisition, "ACQUISITION_MISSING")
        self.assertEqual(by_market["spread"].acquisition, "ACQUISITION_MISSING")
        self.assertEqual(by_market["total"].acquisition, "PROVIDER_UNSUPPORTED")

    def test_full_grid_cannot_claim_ready_when_every_offered_slot_is_engine_blocked(self):
        rows = build_declared_market_grid(
            game_id="g",
            sport="NFL",
            surface_path=SURFACE,
            provider_supported_markets={"moneyline", "spread"},
            request_succeeded=True,
            offered_markets={"moneyline", "spread"},
        )
        states = []
        for row in rows:
            if row.acquisition == "OFFERED":
                states.append(row.with_engine("ENGINE_BLOCKED"))
            else:
                states.append(row.with_engine("INPUT_MISSING"))
        result = finalize_football_run(states)
        self.assertEqual(result.run_status, "BLOCKED")
        self.assertEqual(result.card_status, "NO_BETS")

    def test_known_not_offered_markets_do_not_turn_a_healthy_priced_run_degraded(self):
        rows = build_declared_market_grid(
            game_id="g",
            sport="NFL",
            surface_path=SURFACE,
            provider_supported_markets={"moneyline", "spread"},
            request_succeeded=True,
            offered_markets={"moneyline"},
        )
        states = []
        for row in rows:
            if row.market == "moneyline":
                states.append(row.with_engine("PRICED").with_decision("PASS"))
            else:
                states.append(row.with_engine("INPUT_MISSING"))
        result = finalize_football_run(states)
        self.assertEqual(result.run_status, "READY")
        self.assertEqual(result.card_status, "NO_BETS")
        self.assertEqual(result.priced_slots, 1)


if __name__ == "__main__":
    unittest.main()
