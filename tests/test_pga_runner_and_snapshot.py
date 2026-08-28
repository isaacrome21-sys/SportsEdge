from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from sportsedge.pga.live_card import CandidateMarket
from sportsedge.pga.live_inputs import LiveGolferInput, LiveTournamentSnapshot, SourceStamp
from sportsedge.pga.market_identity import (
    MarketIdentity,
    assert_same_market,
    canonical_market_group_key,
    canonical_market_key,
)
from sportsedge.pga.runner import run_live_pga_model
from sportsedge.pga.snapshot import make_snapshot_envelope, payload_sha256, read_snapshot, write_snapshot


class PGARunnerAndSnapshotTests(unittest.TestCase):
    def _snapshot(self, now: datetime, *, no_cut: bool = True) -> LiveTournamentSnapshot:
        stamp = SourceStamp("test", now)
        golfers = (
            LiveGolferInput("A", -4, 1.2, 1.5, 1.0, 0.3, wave="AM"),
            LiveGolferInput("B", -2, 0.7, 0.6, 0.8, 0.2, wave="PM"),
            LiveGolferInput("C", -1, 0.3, 0.4, 0.2, 0.1, wave="PM"),
        )
        return LiveTournamentSnapshot(
            event="Test Event",
            round_number=2,
            rounds_remaining=2,
            is_no_cut=no_cut,
            leaderboard_stamp=stamp,
            tee_times_stamp=stamp,
            weather_stamp=stamp,
            market_stamp=stamp,
            wd_status_verified=True,
            market_rules_verified=True,
            golfers=golfers,
        )

    def test_live_runner_derives_model_probability_and_does_not_promote_by_default(self):
        now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
        candidate = CandidateMarket(
            market="TOP20",
            selection="A",
            offered_american=-110,
            market_probability=0.40,
            min_edge=0.02,
            min_ev=0.02,
            bound=True,
        )
        out = run_live_pga_model(
            snapshot=self._snapshot(now - timedelta(minutes=1)),
            candidates=[candidate],
            n_sims=500,
            seed=7,
            now=now,
        )
        self.assertEqual(set(out.simulation_results), {"A", "B", "C"})
        decision = out.card[0]
        self.assertEqual(decision.price.raw_finish_probability, out.simulation_results["A"].top20_prob)
        self.assertEqual(decision.price.expected_paid_fraction, out.simulation_results["A"].top20_dead_heat_payout)
        self.assertEqual(decision.status, "BLOCKED")
        self.assertEqual(decision.block_reason, "PGA_MARKET_NOT_PROMOTED")

    def test_unbound_candidate_stays_blocked_even_if_promoted_flag_is_true(self):
        now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
        candidate = CandidateMarket(
            market="OUTRIGHT",
            selection="A",
            offered_american=500,
            market_probability=0.10,
            min_edge=0.01,
            min_ev=0.01,
            bound=False,
            promoted=True,
        )
        out = run_live_pga_model(
            snapshot=self._snapshot(now - timedelta(minutes=1)),
            candidates=[candidate],
            n_sims=200,
            seed=7,
            now=now,
        )
        self.assertEqual(out.card[0].status, "BLOCKED")
        self.assertEqual(out.card[0].block_reason, "MARKET_NOT_BOUND")

    def test_candidate_has_no_model_probability_injection_parameter(self):
        with self.assertRaises(TypeError):
            CandidateMarket(
                market="TOP20",
                selection="A",
                offered_american=-110,
                model_probability=0.99,  # type: ignore[call-arg]
                market_probability=0.50,
                min_edge=0.02,
                min_ev=0.02,
            )

    def test_runner_refuses_to_guess_live_cut_state(self):
        now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "CUT_EVENT_STATE_REQUIRED"):
            run_live_pga_model(
                snapshot=self._snapshot(now, no_cut=False),
                candidates=[],
                n_sims=100,
                now=now,
            )

    def test_h2h_market_group_identity_is_order_invariant(self):
        a = MarketIdentity("h2h", None, "A", opponent="B", scope="event")
        b = MarketIdentity("h2h", None, "B", opponent="A", scope="event")
        self.assertNotEqual(canonical_market_key(a), canonical_market_key(b))
        self.assertEqual(canonical_market_group_key(a), canonical_market_group_key(b))
        assert_same_market(a, b, selection_specific=False)

    def test_selection_specific_identity_still_fails_closed_on_line_mismatch(self):
        a = MarketIdentity("round_score", 2, "A", line=68.5)
        b = MarketIdentity("round_score", 2, "A", line=69.5)
        with self.assertRaisesRegex(ValueError, "market identity mismatch"):
            assert_same_market(a, b)

    def test_snapshot_hash_aware_timestamp_and_immutable_round_trip(self):
        now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
        payload = {"leaderboard": [{"player": "A", "score": -4}]}
        envelope = make_snapshot_envelope(
            event="Test Event",
            round_number=2,
            captured_at=now,
            payload=payload,
        )
        self.assertEqual(envelope.sha256, payload_sha256(payload))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot.json"
            write_snapshot(path, envelope)
            self.assertEqual(read_snapshot(path), envelope)
            with self.assertRaises(FileExistsError):
                write_snapshot(path, envelope)
        with self.assertRaisesRegex(ValueError, "TIMEZONE_REQUIRED"):
            make_snapshot_envelope(
                event="Test Event",
                round_number=2,
                captured_at=datetime(2026, 8, 28, 15, 0),
                payload=payload,
            )


if __name__ == "__main__":
    unittest.main()
