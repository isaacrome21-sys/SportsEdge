import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.market_surface import (
    CoverageSlot,
    MarketSpec,
    build_market_grid,
    compose_run_status,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)
FIRST_PITCH = NOW + timedelta(hours=5)


def spec(market, *, retry=False, expected_by=90, provider_expected=True, terminal="ACQUISITION_MISSING"):
    return MarketSpec(
        market=market,
        scope="player",
        provider_expected=provider_expected,
        retry_eligible=retry,
        terminal_if_absent=terminal,
        opens_minutes_before_first_pitch=720,
        expected_by_minutes_before_first_pitch=expected_by,
    )


class MarketSurfaceStage0Tests(unittest.TestCase):
    def test_t1_offered_market_without_engine_is_no_engine(self):
        rows = build_market_grid(
            games=(("777", FIRST_PITCH),),
            specs=(spec("UNREGISTERED_PROP"),),
            quotes=({"game_id": "777", "market": "UNREGISTERED_PROP", "entity_id": "42"},),
            engine_capable_markets=frozenset(),
            now=NOW,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].acquisition_status, "OFFERED")
        self.assertEqual(rows[0].engine_status, "NO_ENGINE")
        self.assertIsNone(rows[0].decision_status)

    def test_t2_declared_market_missing_after_deadline_is_acquisition_missing(self):
        late = FIRST_PITCH - timedelta(minutes=30)
        rows = build_market_grid(
            games=(("777", FIRST_PITCH),),
            specs=(spec("PITCHER_K", retry=True, expected_by=90),),
            quotes=(),
            engine_capable_markets=frozenset({"PITCHER_K"}),
            now=late,
        )
        self.assertEqual(rows[0].acquisition_status, "ACQUISITION_MISSING")
        self.assertEqual(compose_run_status(rows), "DEGRADED")

    def test_t3_all_blocked_equivalent_health_is_not_ready(self):
        rows = (CoverageSlot(
            game_id="777",
            market="NRFI",
            scope="game",
            acquisition_status="OFFERED",
            engine_status="ENGINE_BLOCKED",
            decision_status=None,
            retry_eligible=False,
            reason="VALIDATION_GATE_FAILED",
        ),)
        self.assertNotEqual(compose_run_status(rows), "READY")
        self.assertEqual(compose_run_status(rows), "DEGRADED")

    def test_t4_retryable_absence_before_expected_posting_does_not_degrade(self):
        rows = build_market_grid(
            games=(("777", FIRST_PITCH),),
            specs=(spec("HITS", retry=True, expected_by=90),),
            quotes=(),
            engine_capable_markets=frozenset({"HITS"}),
            now=NOW,
        )
        self.assertEqual(rows[0].acquisition_status, "NOT_OFFERED")
        self.assertTrue(rows[0].retry_eligible)
        self.assertEqual(compose_run_status(rows), "READY")


    def test_declared_unavailable_market_is_visible_in_coverage_accounting(self):
        unavailable = spec("UNSUPPORTED_PROP", provider_expected=False, terminal="PROVIDER_UNSUPPORTED")
        unavailable = MarketSpec(
            market=unavailable.market,
            scope=unavailable.scope,
            provider_expected=unavailable.provider_expected,
            retry_eligible=unavailable.retry_eligible,
            terminal_if_absent=unavailable.terminal_if_absent,
            opens_minutes_before_first_pitch=unavailable.opens_minutes_before_first_pitch,
            expected_by_minutes_before_first_pitch=unavailable.expected_by_minutes_before_first_pitch,
            declared_availability="UNAVAILABLE",
        )
        rows = build_market_grid(
            games=(("777", FIRST_PITCH),),
            specs=(unavailable,),
            quotes=(),
            engine_capable_markets=frozenset(),
            now=NOW,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].declared_availability, "UNAVAILABLE")
        self.assertEqual(rows[0].acquisition_status, "PROVIDER_UNSUPPORTED")
        self.assertEqual(rows[0].engine_status, "NO_ENGINE")


if __name__ == "__main__":
    unittest.main()
