#!/usr/bin/env python3
"""Acquire the MLB RUN IT pregame stack for one game_pk.

Public sources only: StatsAPI, Baseball Savant, NWS. No Odds API.
Optional DraftKings quotes must be supplied as native/manual JSON and never enter
Model_P or governed evidence merely because they were supplied here.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame


def _load_quotes(path: str | None):
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("quotes"), list):
        payload = payload["quotes"]
    if not isinstance(payload, list):
        raise ValueError("--dk-quotes must contain a JSON list or an object with a quotes list")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_pk", type=int)
    parser.add_argument("--as-of", default=None, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--statcast-html", action="store_true")
    parser.add_argument("--dk-quotes", default=None, help="path to native/manual DraftKings quote JSON")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of else datetime.now(timezone.utc)
    )
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("--as-of must include a timezone")
    bundle = acquire_mlb_run_it_pregame(
        game_pk=int(args.game_pk),
        as_of=as_of,
        include_statcast_html=bool(args.statcast_html),
        dk_quotes=_load_quotes(args.dk_quotes),
    )
    text = json.dumps(bundle, indent=2, sort_keys=False)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(path)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
