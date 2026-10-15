#!/usr/bin/env python3
"""Read-only NFL score-simulation question over a research engine or score paths.

Examples:
    PYTHONPATH=. python scripts/ask_nfl_sims.py --engine-json output.json \
      --home DEN --away SEA --alias Seahawks=SEA --question 'Seahawks win by 7+' \
      --price 180

    PYTHONPATH=. python scripts/ask_nfl_sims.py --paths-json paths.json \
      --home DEN --away SEA --question 'SEA wins by 7+'

Does not fetch odds, verify model inputs, or grant any betting authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sportsedge.sports.nfl.ask_sims import AskSimsError, ask_score_paths, ask_unified_score_sims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inp = parser.add_mutually_exclusive_group(required=True)
    inp.add_argument("--engine-json", type=Path, help="Native NFL unified research engine result JSON")
    inp.add_argument("--paths-json", type=Path, help="JSON array of game score paths (research only)")
    parser.add_argument("--question", required=True, help="Constrained score-market question")
    parser.add_argument("--home", required=True, help="Exact home team identifier")
    parser.add_argument("--away", required=True, help="Exact away team identifier")
    parser.add_argument("--alias", action="append", default=[], metavar="NAME=TEAM",
                        help="Optional accepted team name mapping; repeatable")
    parser.add_argument("--price", type=int, default=None,
                        help="Optional caller-supplied, unverified American odds")
    args = parser.parse_args(argv)
    try:
        aliases = {}
        for entry in args.alias:
            if "=" not in entry:
                raise AskSimsError("ASK_SIMS_ALIAS_FORMAT_INVALID")
            key, value = entry.split("=", 1)
            if not key.strip() or not value.strip() or key.strip().casefold() in (x.casefold() for x in aliases):
                raise AskSimsError("ASK_SIMS_ALIAS_FORMAT_INVALID")
            aliases[key.strip()] = value.strip()
        path = args.engine_json if args.engine_json is not None else args.paths_json
        data = json.loads(path.read_text(encoding="utf-8"))
        common = {"home_team": args.home, "away_team": args.away,
                  "aliases": aliases, "price_american": args.price}
        if args.engine_json is not None:
            result = ask_unified_score_sims(data, args.question, **common)
        else:
            result = ask_score_paths(data, args.question, **common)
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    except (AskSimsError, ValueError, TypeError, OSError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc), "picks": []}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
