#!/usr/bin/env python3
"""Phone render for artifacts/live_cfb_card.json. No Odds API. No Truth Gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_markdown(payload: dict) -> str:
    lines = [
        "SportsEdge CFB card",
        f"family={payload.get('family')} alpha={payload.get('ridge_alpha')} sigma={payload.get('residual_sigma')} bakeoff={payload.get('bakeoff_run')}",
        f"run_status={payload.get('run_status')} bets={((payload.get('funnel') or {}).get('bets_emitted'))}",
        "",
        "Positive calculated edge is not sufficient for a bet: only a BET status is actionable. LEAN is unvalidated, TRACK is market-only/unpaired, and PASS is rejected. NOT Truth Gate / NOT OFFICIAL.",
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
    parser.add_argument("--engine-output", default="artifacts/live_cfb_card.json")
    parser.add_argument("--out-dir", default="artifacts/cfb_myspari")
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
