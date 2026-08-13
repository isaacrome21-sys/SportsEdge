#!/usr/bin/env python3
"""Emit the eight-family fail-closed SportsEdge Full Model status matrix."""
from __future__ import annotations

import json
from pathlib import Path

from sportsedge.full_model_status import build_required_market_status


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _rows(payload: dict, *keys: str) -> list[dict]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def main() -> int:
    legacy = _load(Path("config/deployments.json"))
    strict = _load(Path("config/statcast_v5_deployments.json"))
    card = _load(Path("artifacts/live_mlb_card.json"))
    game_odds = _load(Path("artifacts/live_game_odds.json"))
    prop_odds = _load(Path("artifacts/live_prop_odds.json"))
    runtime = _load(Path("artifacts/full_model_runtime_blocks.json"))

    quotes = _rows(game_odds, "quotes") + _rows(prop_odds, "quotes")
    cards = _rows(card, "results")
    failures = (
        _rows(game_odds, "failures", "source_failures")
        + _rows(prop_odds, "failures", "source_failures")
        + _rows(card, "source_failures")
    )
    runtime_blocks = runtime.get("markets") if isinstance(runtime.get("markets"), dict) else {}

    payload = build_required_market_status(
        legacy_registry=legacy,
        strict_registry=strict,
        quote_rows=quotes,
        card_rows=cards,
        source_failures=failures,
        runtime_blocks=runtime_blocks,
    )
    out = Path("artifacts/full_model_status.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
