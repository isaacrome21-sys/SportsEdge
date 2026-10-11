#!/usr/bin/env python3
"""Emit a phone-friendly research card table from scored research JSON.

Output format (research-only):
Game | Market | Selection | Line | Odds | Model P% | Edge % | EV% | Score

Never fabricates edges. Labels RESEARCH ONLY / NOT Model_P / NOT OFFICIAL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _pct(value: Any) -> str:
    try:
        return f"{100.0 * float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


def emit(card: dict[str, Any], *, limit: int = 50) -> str:
    lines = [
        "## Research Card",
        "**RESEARCH ONLY — NOT Model_P / NOT Truth Gate / NOT OFFICIAL / no staking authority.**",
        "Edges are model-vs-quote discrepancies only; not proven positive EV.",
        "",
        "| Game | Market | Selection | Line | Odds | Model P% | Edge % | EV% | Score |",
        "|------|--------|-----------|------|------|----------|--------|-----|-------|",
    ]
    rows = card.get("results") or card.get("rows") or []
    if not isinstance(rows, list):
        return "\n".join(lines + ["| (no rows) | | | | | | | | |"])

    def key(r: dict) -> tuple:
        status = str(r.get("bet_status") or r.get("display_status") or "")
        is_lean = status.upper() in {"LEAN", "RESEARCH_LEAN"}
        edge = abs(float(r.get("edge") or 0))
        return (0 if is_lean else 1, -edge)

    for raw in sorted((r for r in rows if isinstance(r, dict)), key=key)[:limit]:
        matchup = str(raw.get("matchup") or raw.get("game_id") or "")
        market = str(raw.get("market") or "")
        side = str(raw.get("side") or raw.get("selection") or "")
        line = raw.get("line")
        odds = raw.get("american_odds") or raw.get("price_american")
        mp = raw.get("model_p") or raw.get("estimate_p")
        edge = raw.get("edge")
        ev = raw.get("expected_roi") or raw.get("ev_per_dollar")
        score = str(raw.get("bet_status") or raw.get("display_status") or raw.get("reason") or "")[:24]
        lines.append(
            f"| {matchup} | {market} | {side} | {line} | {odds} | {_pct(mp)} | {_pct(edge)} | {_pct(ev)} | {score} |"
        )
    lines.append("")
    lines.append("Full detail and provenance remain in the source JSON. Do not treat as actionable without independent validation.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit phone-friendly research card")
    parser.add_argument("card_json", type=Path)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    card = json.loads(args.card_json.read_text(encoding="utf-8"))
    text = emit(card, limit=args.limit)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
