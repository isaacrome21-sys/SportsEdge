#!/usr/bin/env python3
"""RUN IT composite entry point: per-game freshness evaluation (issue #2359).

Same intake contract as ``artifacts/run_it_full.py``, but each game in the
payload is evaluated as of its own recorded operative instant (its final
verification read) and the per-game cards are merged into one composite
card by ``sportsedge.per_game_composite``.  The 180s freshness bound is
unchanged; timestamps are never rewritten; the merge refuses duplicate
selections fail-closed.  The composite card is research-only until the
audit-schema, PIT-context, freshness, deduplication, and grading
regressions pass (owner's release condition, issue #2359).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.per_game_composite import run_composite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--min-ev", type=float, default=0.02)
    parser.add_argument("--lane", choices=("A", "B"), default="A")
    parser.add_argument("--allow-manual-context", action="store_true")
    parser.add_argument("--operative-instant", action="append", default=[],
                        metavar="GAME_KEY=ISO_INSTANT",
                        help="Recorded operative instant for one game, as "
                             "SPORT|AWAY|HOME|KICKOFF_UTC=ISO_INSTANT. Must "
                             "equal that game's own final recorded "
                             "quote_captured_at: an instant no capture row "
                             "evidences is refused, since a declaration "
                             "does not prove a re-read happened. Defaults "
                             "to the game's final recorded stamp.")
    parser.add_argument("--form2-bundles-dir")
    parser.add_argument("--form2-manifest-sha256", action="append", default=[])
    args = parser.parse_args()

    operative_instants = {}
    for item in args.operative_instant:
        key, sep, value = item.partition("=")
        if not sep or not value.strip():
            parser.error(
                f"--operative-instant must be GAME_KEY=ISO_INSTANT, got {item!r}")
        operative_instants[key.strip()] = value.strip()

    payload = json.loads(args.lines.read_text())
    card = run_composite(
        payload,
        operative_instants=operative_instants or None,
        auto_context=not args.no_fetch,
        min_ev=args.min_ev,
        lane=args.lane,
        allow_manual_context=args.allow_manual_context,
        form2_bundles_dir=args.form2_bundles_dir,
        form2_manifest_sha256=args.form2_manifest_sha256 or None,
    )
    rendered = json.dumps(card, indent=2, sort_keys=True, default=str) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
