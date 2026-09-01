from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.live_acquisition import AcquisitionGap, LiveAcquisitionBundle, LiveEventRef, merge_manual_quote
from sportsedge.live_markets import LiveMarketQuote, requested_market_scope
from sportsedge.live_policy import assert_market_blind
from sportsedge.live_snapshot import LivePITSnapshot, LiveSnapshotError, assert_feature_timestamps_at_or_before_cutoff
from sportsedge.live_validation import LiveEvaluationRow, actionable_sample_status, clustered_mean


NOW = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)


def test_market_blindness_rejects_live_odds():
    with pytest.raises(ValueError):
        assert_market_blind({"score_margin": 7, "live_odds": -120})


def test_live_pit_rejects_future_feature():
    with pytest.raises(LiveSnapshotError):
        assert_feature_timestamps_at_or_before_cutoff(
            {"score": NOW + timedelta(seconds=1)},
            NOW,
        )


def test_snapshot_id_is_deterministic_and_market_blind():
    snap = LivePITSnapshot(
        event_id="g1",
        sport="NFL",
        source_as_of=NOW - timedelta(seconds=2),
        retrieved_at=NOW,
        pit_cutoff=NOW,
        state_sequence="drive-14-play-3",
        provider="fixture",
        raw_state={"score": [10, 7]},
        model_features={"score_margin": 3, "down": 2, "distance": 6},
    )
    assert snap.snapshot_id == snap.snapshot_id
    assert len(snap.snapshot_id) == 64


def test_snapshot_rejects_state_after_cutoff():
    with pytest.raises(LiveSnapshotError):
        LivePITSnapshot(
            event_id="g1",
            sport="NFL",
            source_as_of=NOW + timedelta(seconds=1),
            retrieved_at=NOW + timedelta(seconds=2),
            pit_cutoff=NOW,
            state_sequence="x",
            provider="fixture",
            raw_state={},
            model_features={},
        ).validate()


def test_all_market_scope_contains_core_markets():
    for sport in ("NFL", "CFB", "MLB"):
        scope = requested_market_scope(sport)
        assert "MONEYLINE" in scope
        assert "TOTAL" in scope
        assert "TEAM_TOTAL" in scope
        assert "PLAYER_PROP" in scope
    assert "RUN_LINE" in requested_market_scope("MLB")
    assert "SPREAD" in requested_market_scope("NFL")


def test_manual_quote_fills_only_matching_gap():
    event = LiveEventRef("MLB", "m1", "LIVE", NOW, "A", "B")
    bundle = LiveAcquisitionBundle(
        event=event,
        state_payload={"inning": 6},
        state_source_as_of=NOW,
        state_provider="auto",
        gaps=(
            AcquisitionGap("m1", "RUN_LINE", "paired_price", "LIVE_QUOTE_DATA_GAP", False),
            AcquisitionGap("m1", "BATTER_PROP", "quote", "SOURCE_UNAVAILABLE_AUTO", False),
        ),
    )
    quote = LiveMarketQuote(
        sport="MLB",
        event_id="m1",
        book="DK",
        market="RUN_LINE",
        contract_key="HOME_-1.5",
        focal_selection="HOME -1.5",
        opposite_selection="AWAY +1.5",
        focal_odds=120,
        opposite_odds=-145,
        source_as_of=NOW,
        retrieved_at=NOW,
        active=True,
        provider="MANUAL_SCREENSHOT",
    )
    merged = merge_manual_quote(bundle, quote)
    assert len(merged.gaps) == 1
    assert merged.gaps[0].market == "BATTER_PROP"


def test_actionable_sample_counts_games_not_snapshots():
    rows = []
    for game in range(2):
        for snap in range(100):
            rows.append(LiveEvaluationRow(f"g{game}", f"s{snap}", .55, .50, 1.0, clv=.01))
    status = actionable_sample_status(rows, minimum_game_clusters=20)
    assert status["snapshots"] == 200
    assert status["game_clusters"] == 2
    assert status["passes"] is False


def test_clustered_clv_uses_game_clusters():
    rows = [
        LiveEvaluationRow("g1", "s1", .55, .50, 1, clv=.01),
        LiveEvaluationRow("g1", "s2", .56, .51, 1, clv=.03),
        LiveEvaluationRow("g2", "s3", .45, .50, 0, clv=-.01),
    ]
    metric = clustered_mean(rows, "clv")
    assert metric.game_clusters == 2
    assert metric.snapshots == 3
    assert metric.value == pytest.approx(.005)
