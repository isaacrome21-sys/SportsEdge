#!/usr/bin/env python3
"""Run the non-authoritative NFL prop role challenger from JSON inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sportsedge.research.nfl_prop_role_challenger import build_prop_card


def _load_collection(path: str, key: str) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, dict) and isinstance(raw.get(key), list):
        values = raw[key]
    else:
        raise SystemExit(f"{path}: expected a JSON list or object with '{key}' list")
    if not all(isinstance(value, dict) for value in values):
        raise SystemExit(f"{path}: every {key} entry must be an object")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roles", required=True, help="JSON list or {'players': [...]} role inputs")
    parser.add_argument("--quotes", required=True, help="JSON list or {'quotes': [...]} paired DraftKings quotes")
    parser.add_argument("--as-of", required=True, help="Offset-aware ISO-8601 evaluation timestamp")
    parser.add_argument("--sims", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument("--prior-strength", type=float, default=8.0)
    parser.add_argument("--output", help="Optional output JSON path; stdout when omitted")
    args = parser.parse_args()

    card = build_prop_card(
        _load_collection(args.roles, "players"),
        _load_collection(args.quotes, "quotes"),
        as_of=args.as_of,
        n_sims=args.sims,
        seed=args.seed,
        prior_strength=args.prior_strength,
    )
    rendered = json.dumps(card, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
