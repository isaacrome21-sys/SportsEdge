#!/usr/bin/env python3
"""Build one same-day CFB research card from available game/prop lanes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.today_research_card import assemble_cfb_today_research_card


def _optional_json(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-model-report", type=Path)
    ap.add_argument("--paper-market-card", type=Path)
    ap.add_argument("--prop-report", type=Path)
    ap.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_today_research_card.json"))
    args = ap.parse_args()
    card = assemble_cfb_today_research_card(
        game_model_payload=_optional_json(args.game_model_report),
        paper_market_payload=_optional_json(args.paper_market_card),
        prop_payload=_optional_json(args.prop_report),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(card, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": card["run_status"],
        "game_lane": card["game_lane"],
        "prop_lane": card["prop_lane"],
        "game_rows": card["summary"]["game_rows"],
        "prop_rows": card["summary"]["prop_rows"],
        "lean_rows": card["summary"]["lean_rows"],
        "paper_rows": card["summary"]["paper_rows"],
        "official_bets": 0,
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
