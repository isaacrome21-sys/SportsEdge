#!/usr/bin/env python3
"""Phone render for artifacts/live_nhl_card.json. No Odds API. No Truth Gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_markdown(payload: dict) -> str:
    lines = [
        "SportsEdge NHL card",
        f"family={payload.get('family')} run_status={payload.get('run_status')} bets={((payload.get('funnel') or {}).get('bets_emitted'))}",
        "",
        "A row with model_p and positive edge is a bet. No-edge is a successful slate. NOT Truth Gate / NOT OFFICIAL.",
        "",
        "| game | market | side | odds | model_p | edge | status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("results") or []:
        lines.append(
            "| {game} | {market} | {side} | {odds} | {model_p} | {edge} | {status} |".format(
                game=row.get("game_id") or "",
                market=row.get("market") or "",
                side=row.get("side") or "",
                odds=row.get("american_odds"),
                model_p=None if row.get("model_p") is None else round(float(row["model_p"]), 4),
                edge=None if row.get("edge") is None else round(float(row["edge"]), 4),
                status=row.get("bet_status"),
            )
        )
    if not payload.get("results"):
        lines.append("|  |  |  |  |  |  | no rows |")
    lines.append("")
    lines.append("Lines are user-supplied. Zero quotes is the only infrastructure block.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-output", default="artifacts/live_nhl_card.json")
    parser.add_argument("--out-dir", default="artifacts/nhl_myspari")
    args = parser.parse_args()
    payload = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    text = render_markdown(payload)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text(text, encoding="utf-8")
    (out / "card.json").write_text(json.dumps({"rows": payload.get("results") or [], "bets": payload.get("bets") or []}, indent=2) + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
