import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.market_surface import (
    MarketSurfaceEntry,
    build_market_slots,
    compose_run_status,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)
START = NOW + timedelta(hours=2)


class MarketSurfaceHealthTests(unittest.TestCase):
    def test_offered_market_without_engine_is_no_engine(self):
        surface = [MarketSurfaceEntry(
            market="UNMODELED_PROP", scope="player", provider_expected=True,
            retry_eligible=False, terminal_if_absent="ACQUISITION_MISSING",
            availability_window={"opens_minutes_before_first_pitch": 720, "terminal_minutes_before_first_pitch": 60},
        )]
        slots = build_market_slots(
            surface=surface,
            game_id="1",
            first_pitch_at=START,
            now=NOW,
            offered_markets={"UNMODELED_PROP"},
            engine_markets=set(),
            input_missing_markets=set(),
            engine_blocked_markets=set(),
        )
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].acquisition_state, "OFFERED")
        self.assertEqual(slots[0].engine_state, "NO_ENGINE")
        self.assertIsNone(slots[0].decision)

    def test_declared_market_missing_from_acquisition_is_visible(self):
        surface = [MarketSurfaceEntry(
            market="EXPECTED_MARKET", scope="game", provider_expected=True,
            retry_eligible=False, terminal_if_absent="ACQUISITION_MISSING",
            availability_window={"opens_minutes_before_first_pitch": 1440, "terminal_minutes_before_first_pitch": 1440},
        )]
        slots = build_market_slots(
            surface=surface, game_id="1", first_pitch_at=START, now=NOW,
            offered_markets=set(), engine_markets={"EXPECTED_MARKET"},
            input_missing_markets=set(), engine_blocked_markets=set(),
        )
        self.assertEqual(slots[0].acquisition_state, "ACQUISITION_MISSING")
        self.assertEqual(compose_run_status(slots), "DEGRADED")

    def test_all_blocked_rows_cannot_report_ready(self):
        surface = [MarketSurfaceEntry(
            market="BLOCKED_MARKET", scope="game", provider_expected=True,
            retry_eligible=False, terminal_if_absent="ACQUISITION_MISSING",
            availability_window={"opens_minutes_before_first_pitch": 1440, "terminal_minutes_before_first_pitch": 1440},
        )]
        slots = build_market_slots(
            surface=surface, game_id="1", first_pitch_at=START, now=NOW,
            offered_markets={"BLOCKED_MARKET"}, engine_markets={"BLOCKED_MARKET"},
            input_missing_markets=set(), engine_blocked_markets={"BLOCKED_MARKET"},
        )
        self.assertNotEqual(compose_run_status(slots), "READY")

    def test_retry_eligible_not_offered_does_not_degrade(self):
        surface = [MarketSurfaceEntry(
            market="EARLY_PROP", scope="player", provider_expected=True,
            retry_eligible=True, terminal_if_absent="ACQUISITION_MISSING",
            availability_window={"opens_minutes_before_first_pitch": 360, "terminal_minutes_before_first_pitch": 30},
        )]
        slots = build_market_slots(
            surface=surface, game_id="1", first_pitch_at=START, now=NOW,
            offered_markets=set(), engine_markets={"EARLY_PROP"},
            input_missing_markets=set(), engine_blocked_markets=set(),
        )
        self.assertEqual(slots[0].acquisition_state, "NOT_OFFERED")
        self.assertTrue(slots[0].retry_eligible)
        self.assertEqual(compose_run_status(slots), "READY")


if __name__ == "__main__":
    unittest.main()
