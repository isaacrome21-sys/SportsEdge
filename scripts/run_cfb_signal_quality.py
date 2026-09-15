#!/usr/bin/env python3
"""Run the CFB signal-quality layer over an already-captured slate JSON.

Input is deliberately capture-only. This runner never fetches odds/news, never creates
Model_P, and never promotes a row by itself. It exists so RUN IT can expose the full
slate funnel even while the genuine CFB model remains fail-closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.cfb_signal_quality import evaluate_signal, funnel_counts


DEFAULT_POLICY = Path("config/cfb_signal_quality_policy_v1.json")


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        rows = payload["rows"]
    else:
        raise ValueError("input must be a JSON array or an object containing rows[]")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("every row must be a JSON object")
    return rows


def build_card(rows: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    rendered: list[dict[str, Any]] = []
    results = []
    for index, row in enumerate(rows):
        result = evaluate_signal(row, policy)
        results.append(result)
        rendered.append(
            {
                "row_index": index,
                "game_id": row.get("game_id"),
                "market_id": row.get("market_id"),
                "market_type": row.get("market_type"),
                "selection": row.get("selection"),
                "sportsbook": row.get("sportsbook"),
                "current_odds": row.get("current_odds"),
                "current_market_value": row.get("current_market_value"),
                "reference_market_value": row.get("reference_market_value"),
                "tickets_pct": row.get("tickets_pct"),
                "money_pct": row.get("money_pct"),
                "lane": result.lane,
                "tier": result.tier,
                "model_authorized": result.model_authorized,
                "official_eligible": result.official_eligible,
                "material_line_move": result.material_line_move,
                "boosted_break_even": result.boosted_break_even,
                "reason_codes": list(result.reason_codes),
                "source_provenance": row.get("sources", []),
                "captured_at": row.get("captured_at"),
            }
        )

    tier_order = {"CORE": 0, "SECONDARY": 1, "WATCH": 2, "PASS": 3}
    rendered.sort(key=lambda item: (tier_order.get(item["tier"], 99), item["row_index"]))
    return {
        "schema_version": "CFB_SIGNAL_QUALITY_CARD_V1",
        "policy_id": policy.get("policy_id"),
        "funnel": funnel_counts(results),
        "rows": rendered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="captured slate JSON")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, help="optional output path; stdout otherwise")
    args = parser.parse_args()

    policy = _load_json(args.policy)
    card = build_card(_rows(_load_json(args.input)), policy)
    text = json.dumps(card, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
