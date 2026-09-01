from datetime import datetime, timezone

import pytest

from sportsedge.live_acquisition import LiveAcquisitionBundle, LiveEventRef
from sportsedge.live_engine import LiveEngineError, LiveModelOutput
from sportsedge.live_runtime import build_runtime_input


NOW = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)


def nfl_bundle():
    event = LiveEventRef(
        sport="NFL",
        event_id="nfl-live-1",
        status="LIVE",
        scheduled_start=NOW,
        home_team="Home",
        away_team="Away",
    )
    state = {
        "period": 2,
        "clock_display": "12:34",
        "home_score": 7,
        "away_score": 3,
        "down": 2,
        "distance": 6,
        "yardline_100": 44,
        "timeouts_home": 3,
        "timeouts_away": 2,
        "plays_home": 19,
        "plays_away": 17,
        "possession": "HOME",
    }
    return LiveAcquisitionBundle(
        event=event,
        state_payload=state,
        state_source_as_of=NOW,
        state_provider="fixture",
    )


def test_runtime_bridge_freezes_snapshot_at_state_as_of():
    runtime = build_runtime_input(nfl_bundle(), retrieved_at=NOW)
    assert runtime.game_state.period == "Q2"
    assert runtime.game_state.clock_seconds == 12 * 60 + 34
    assert runtime.snapshot.pit_cutoff == NOW
    assert runtime.snapshot.snapshot_id


def test_runtime_adapter_missing_required_state_fails_closed():
    bundle = nfl_bundle()
    broken = LiveAcquisitionBundle(
        event=bundle.event,
        state_payload={"period": 2, "home_score": 7, "away_score": 3},
        state_source_as_of=NOW,
        state_provider="fixture",
    )
    with pytest.raises(LiveEngineError):
        build_runtime_input(broken, retrieved_at=NOW)


def test_model_diagnostics_cannot_smuggle_live_market_feature():
    model = LiveModelOutput(
        model_p=0.55,
        deployed=True,
        validated=True,
        diagnostics={"model_features": {"live_odds": -110, "down": 2}},
    )
    with pytest.raises(LiveEngineError):
        model.validate()
