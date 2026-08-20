import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sportsedge.market_surface import CoverageSlot, build_market_grid, compose_run_status, load_market_surface

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)
KICK = NOW + timedelta(hours=5)


class MultiSportSurfaceTests(unittest.TestCase):
    def _surface(self, sport):
        path = Path("config") / f"{sport.lower()}_market_surface.json"
        version, specs = load_market_surface(path)
        self.assertTrue(version)
        self.assertGreater(len(specs), 20)
        return specs

    def _assert_four(self, sport):
        specs = self._surface(sport)
        spec = specs[0]
        t1 = build_market_grid(
            games=(("g1", KICK),),
            specs=(spec,),
            quotes=({"game_id": "g1", "market": spec.market, "entity_id": "game"},),
            engine_capable_markets=frozenset(),
            now=NOW,
        )
        self.assertEqual(
            (t1[0].acquisition_status, t1[0].engine_status, t1[0].decision_status),
            ("OFFERED", "NO_ENGINE", None),
        )

        late = KICK - timedelta(minutes=1)
        retry_spec = next(x for x in specs if x.retry_eligible)
        t2 = build_market_grid(
            games=(("g1", KICK),), specs=(retry_spec,), quotes=(),
            engine_capable_markets={retry_spec.market}, now=late,
        )
        self.assertIn(t2[0].acquisition_status, {"ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED"})

        blocked = (CoverageSlot(
            "g1", spec.market, spec.scope, "OFFERED", "ENGINE_BLOCKED", None,
            False, "VALIDATION_GATE_FAILED",
        ),)
        self.assertEqual(compose_run_status(blocked), "DEGRADED")

        t4 = build_market_grid(
            games=(("g1", KICK),), specs=(retry_spec,), quotes=(),
            engine_capable_markets={retry_spec.market}, now=NOW,
        )
        if (KICK - NOW).total_seconds() / 60 > retry_spec.expected_by_minutes_before_first_pitch:
            self.assertEqual(t4[0].acquisition_status, "NOT_OFFERED")
            self.assertTrue(t4[0].retry_eligible)
            self.assertEqual(compose_run_status(t4), "READY")

    def test_nfl_surface_uses_shared_health_contract(self):
        self._assert_four("nfl")

    def test_cfb_surface_uses_shared_health_contract(self):
        self._assert_four("cfb")


if __name__ == "__main__":
    unittest.main()
