"""Bridge automatic acquisition into governed PIT-safe live model inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from .live_acquisition import LiveAcquisitionBundle
from .live_adapters import AdapterResult, adapter_for
from .live_engine import LiveEngineError, LiveGameState
from .live_snapshot import LivePITSnapshot


@dataclass(frozen=True)
class LiveRuntimeInput:
    game_state: LiveGameState
    adapter_result: AdapterResult
    snapshot: LivePITSnapshot


def _clock_seconds(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if ":" in text:
        try:
            minutes, seconds = text.split(":", 1)
            return max(0, int(minutes) * 60 + int(float(seconds)))
        except ValueError:
            return None
    return None


def build_runtime_input(
    bundle: LiveAcquisitionBundle,
    *,
    pregame_features: Mapping[str, object] | None = None,
    retrieved_at: datetime | None = None,
) -> LiveRuntimeInput:
    """Create the exact model-side state snapshot for one live decision.

    Pregame priors may be merged into the state only through this explicit input;
    sportsbook/live-market fields remain rejected later by LIVE market-blindness.
    """
    if bundle.event.status != "LIVE":
        raise LiveEngineError("runtime input requires LIVE event")
    if bundle.state_payload is None or bundle.state_source_as_of is None or not bundle.state_provider:
        raise LiveEngineError("LIVE_STATE_DATA_GAP")

    raw = dict(bundle.state_payload)
    if pregame_features:
        raw.update(dict(pregame_features))

    period_raw = raw.get("period")
    if bundle.event.sport in {"NFL", "CFB"} and isinstance(period_raw, int):
        period = f"Q{period_raw}"
    elif bundle.event.sport == "MLB" and raw.get("inning_half") and raw.get("inning"):
        period = f"{raw.get('inning_half')}_{raw.get('inning')}"
    else:
        period = str(period_raw or "UNKNOWN")

    game_state = LiveGameState(
        sport=bundle.event.sport,
        event_id=bundle.event.event_id,
        observed_at=bundle.state_source_as_of,
        period=period,
        clock_seconds=_clock_seconds(raw.get("clock_display")),
        home_score=int(raw.get("home_score", 0)),
        away_score=int(raw.get("away_score", 0)),
        possession=str(raw.get("possession")) if raw.get("possession") in {"HOME", "AWAY"} else None,
        state=raw,
    )
    adapter_result = adapter_for(bundle.event.sport).transform(game_state)

    retrieved = retrieved_at or datetime.now(timezone.utc)
    sequence = "|".join(
        [
            period,
            str(game_state.clock_seconds),
            str(game_state.home_score),
            str(game_state.away_score),
            str(raw.get("down", "")),
            str(raw.get("distance", "")),
            str(raw.get("outs", "")),
        ]
    )
    snapshot = LivePITSnapshot(
        event_id=bundle.event.event_id,
        sport=bundle.event.sport,
        source_as_of=bundle.state_source_as_of,
        retrieved_at=retrieved,
        pit_cutoff=bundle.state_source_as_of,
        state_sequence=sequence,
        provider=bundle.state_provider,
        raw_state=raw,
        model_features=dict(adapter_result.features),
    )
    snapshot.validate()
    return LiveRuntimeInput(game_state=game_state, adapter_result=adapter_result, snapshot=snapshot)
