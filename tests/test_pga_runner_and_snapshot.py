from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.pga.live_card import CandidateMarket
from sportsedge.pga.live_inputs import LiveGolferInput, LiveTournamentSnapshot, SourceStamp
from sportsedge.pga.market_identity import MarketIdentity, assert_same_market, canonical_market_key
from sportsedge.pga.runner import run_live_pga_model
from sportsedge.pga.snapshot import make_snapshot_envelope, payload_sha256, read_snapshot, write_snapshot


def _snapshot(now):
    stamp = SourceStamp("test", now)
    golfers = (
        LiveGolferInput("A", -4, 1.2, 1.5, 1.0, 0.3),
        LiveGolferInput("B", -2, 0.7, 0.6, 0.8, 0.2),
        LiveGolferInput("C", -1, 0.3, 0.4, 0.2, 0.1),
    )
    return LiveTournamentSnapshot(
        event="Test Event",
        round_number=2,
        rounds_remaining=2,
        is_no_cut=True,
        leaderboard_stamp=stamp,
        tee_times_stamp=stamp,
        weather_stamp=stamp,
        market_stamp=stamp,
        wd_status_verified=True,
        market_rules_verified=True,
        golfers=golfers,
    )


def test_live_runner_simulates_from_snapshot_and_prices_card():
    now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    candidate = CandidateMarket(
        market="top20",
        selection="A",
        offered_american=-110,
        model_probability=0.70,
        market_probability=0.58,
        min_edge=0.04,
        min_ev=0.03,
    )
    out = run_live_pga_model(
        snapshot=_snapshot(now - timedelta(minutes=1)),
        candidates=[candidate],
        n_sims=2_000,
        seed=7,
        now=now,
    )
    assert set(out.simulation_results) == {"A", "B", "C"}
    assert out.card[0].status == "OFFICIAL"


def test_runner_refuses_to_guess_cut_rules():
    now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    snapshot = _snapshot(now)
    snapshot = LiveTournamentSnapshot(**{**snapshot.__dict__, "is_no_cut": False})
    with pytest.raises(ValueError, match="cut-rule simulation"):
        run_live_pga_model(snapshot=snapshot, candidates=[], n_sims=100, now=now)


def test_market_identity_fails_closed_on_line_mismatch():
    a = MarketIdentity("round_score", 2, "A", line=68.5)
    b = MarketIdentity("round_score", 2, "A", line=69.5)
    assert canonical_market_key(a) != canonical_market_key(b)
    with pytest.raises(ValueError, match="market identity mismatch"):
        assert_same_market(a, b)


def test_snapshot_hash_and_immutable_round_trip(tmp_path):
    now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    payload = {"leaderboard": [{"player": "A", "score": -4}]}
    envelope = make_snapshot_envelope(
        event="Test Event",
        round_number=2,
        captured_at=now,
        payload=payload,
    )
    assert envelope.sha256 == payload_sha256(payload)
    path = tmp_path / "snapshot.json"
    write_snapshot(path, envelope)
    loaded = read_snapshot(path)
    assert loaded == envelope
    with pytest.raises(FileExistsError):
        write_snapshot(path, envelope)
