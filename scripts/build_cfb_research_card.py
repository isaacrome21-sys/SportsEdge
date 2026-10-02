#!/usr/bin/env python3
"""Combine canonical CFB game output and research prop candidates into one card."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.research_card import assemble_cfb_research_card


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-report", type=Path, required=True)
    ap.add_argument("--prop-report", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_full_research_card.json"))
    args = ap.parse_args()
    card = assemble_cfb_research_card(
        game_payload=_json(args.game_report),
        prop_payload=_json(args.prop_report),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(card, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": card["run_status"],
        "game_rows": card["summary"]["game_rows"],
        "prop_rows": card["summary"]["prop_rows"],
        "lean_rows": card["summary"]["lean_rows"],
        "official_bets": 0,
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
