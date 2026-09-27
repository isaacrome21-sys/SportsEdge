#!/usr/bin/env python3
"""Discover current MLB/NFL/CFB games and run automatic acquisition.

Pregame events are retained as explicit data-gap results until a validated,
sport-specific pregame runner is wired. This prevents RUN IT from silently
dropping today's slate while preserving the no-manufactured-Model_P boundary.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.live_dispatcher import dispatch_slate
from sportsedge.live_http_providers import ESPNLiveStateProvider, TheOddsAPILiveProvider


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sports", default="MLB,NFL,CFB")
    parser.add_argument("--output", default="artifacts/live_run_it.json")
    parser.add_argument("--bookmakers", default=None)
    args = parser.parse_args()

    sports = tuple(s.strip().upper() for s in args.sports.split(",") if s.strip())
    state_provider = ESPNLiveStateProvider()
    odds_provider = TheOddsAPILiveProvider(bookmakers=args.bookmakers)

    events = []
    discovery_errors = []
    for sport in sports:
        try:
            events.extend(state_provider.discover_events(sport))
        except Exception as exc:
            discovery_errors.append({"sport": sport, "error": type(exc).__name__, "message": str(exc)})

    actionable_events = tuple(event for event in events if event.status in {"PREGAME", "LIVE"})
    live_events = tuple(event for event in actionable_events if event.status == "LIVE")
    pregame_events = tuple(event for event in actionable_events if event.status == "PREGAME")
    results = dispatch_slate(
        actionable_events,
        live_providers=(state_provider, odds_provider),
    )

    payload = {
        "schema": "SPORTSEDGE_LIVE_RUN_IT_V2",
        "retrieved_at": datetime.now(timezone.utc),
        "sports": sports,
        "events_discovered": len(events),
        "actionable_events": len(actionable_events),
        "pregame_events": len(pregame_events),
        "live_events": len(live_events),
        "discovery_errors": discovery_errors,
        "results": [asdict(result) for result in results],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
