#!/usr/bin/env python3
"""Phone render for artifacts/live_nba_card.json.

A row with model_p and positive edge is a bet. This is not Truth Gate and not
official Model_P.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-output", default="artifacts/live_nba_card.json")
    parser.add_argument("--out-dir", default="artifacts/nba_myspari")
    args = parser.parse_args()
    payload = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    lines = [
        "NBA card",
        f"run_status={payload.get('run_status')} family={payload.get('family')}",
        "NOT Truth Gate / NOT official Model_P. User-supplied lines only.",
        "",
        "| game | market | side | line | odds | model_p | edge | call |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("results") or []:
        lines.append(
            "| {game} | {market} | {side} | {line} | {odds} | {model_p} | {edge} | {call} |".format(
                game=row.get("game_id") or "",
                market=row.get("market") or "",
                side=row.get("side") or "",
                line="" if row.get("line") is None else row.get("line"),
                odds="" if row.get("american_odds") is None else row.get("american_odds"),
                model_p="" if row.get("model_p") is None else f"{float(row['model_p']):.3f}",
                edge="" if row.get("edge") is None else f"{float(row['edge']):+.3f}",
                call=row.get("bet_status") or "",
            )
        )
    if not payload.get("results"):
        lines.append("| | | | | | | | No quoted rows |")
    bets = payload.get("bets") or []
    lines += ["", f"Bets emitted: {len(bets)}"]
    for row in bets:
        lines.append(
            f"- {row.get('away')} @ {row.get('home')} {row.get('market')} {row.get('side')} "
            f"{row.get('american_odds')} edge={float(row.get('edge') or 0):+.3f}"
        )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    (out / "card.md").write_text(text, encoding="utf-8")
    (out / "card.json").write_text(json.dumps({"rows": payload.get("results") or [], "bets": bets}, indent=2) + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
