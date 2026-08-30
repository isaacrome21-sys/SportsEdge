"""Unified RUN IT routing for pregame, live, and completed events.

The dispatcher is intentionally orchestration-only. It does not manufacture a
LIVE Model_P and it never treats market context as model input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .live_acquisition import LiveAcquisitionBundle, LiveEventRef, LiveSourceProvider, build_live_bundle


@dataclass(frozen=True)
class RunItEventResult:
    event: LiveEventRef
    lane: str
    status: str
    live_bundle: LiveAcquisitionBundle | None = None
    pregame_payload: Mapping[str, object] | None = None
    reason: str | None = None


PregameRunner = Callable[[LiveEventRef], Mapping[str, object]]


def dispatch_event(
    event: LiveEventRef,
    *,
    live_providers: Sequence[LiveSourceProvider] = (),
    pregame_runner: PregameRunner | None = None,
) -> RunItEventResult:
    """Route one event by current status using the same RUN IT command semantics."""
    event.validate()

    if event.status == "LIVE":
        bundle = build_live_bundle(event, live_providers)
        return RunItEventResult(
            event=event,
            lane="LIVE",
            status="READY" if bundle.state_payload is not None else "DATA_GAP",
            live_bundle=bundle,
            reason=None if bundle.state_payload is not None else "LIVE_STATE_DATA_GAP",
        )

    if event.status == "PREGAME":
        if pregame_runner is None:
            return RunItEventResult(
                event=event,
                lane="PREGAME",
                status="DATA_GAP",
                reason="PREGAME_RUNNER_UNAVAILABLE",
            )
        return RunItEventResult(
            event=event,
            lane="PREGAME",
            status="READY",
            pregame_payload=dict(pregame_runner(event)),
        )

    if event.status == "FINAL":
        return RunItEventResult(
            event=event,
            lane="SETTLEMENT",
            status="NO_NEW_BET",
            reason="EVENT_FINAL",
        )

    return RunItEventResult(
        event=event,
        lane="LIVE",
        status="BLOCKED",
        reason="EVENT_SUSPENDED",
    )


def dispatch_slate(
    events: Sequence[LiveEventRef],
    *,
    live_providers: Sequence[LiveSourceProvider] = (),
    pregame_runner: PregameRunner | None = None,
) -> tuple[RunItEventResult, ...]:
    """Route a mixed slate; live games are included automatically."""
    return tuple(
        dispatch_event(event, live_providers=live_providers, pregame_runner=pregame_runner)
        for event in events
    )
