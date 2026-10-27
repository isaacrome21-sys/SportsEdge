#!/usr/bin/env python3
"""[CFB LINES] issue body -> board.json for scripts/run_cfb_sdv_card_v2.py.

Muse text format goes through the shared parser (sportsedge.pipeline.intake) and
becomes the compact board the CFB card already accepts:
  {"away", "home", "ml": [a, h], "spread": [away line, a, h], "total": [line, o, u],
   "captured_at": ...}
A fenced JSON board (legacy form) is passed through unchanged.
``season: YYYY`` / ``week: N`` lines are read when present (the card needs them).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.pipeline.intake import SharedIntakeError, parse_issue

_META = re.compile(r"^\s*(season|week)\s*:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def board_from_body(body: str, *, title: str | None = None) -> tuple[list[dict], list[str], dict[str, int]]:
    meta = {k.lower(): int(v) for k, v in _META.findall(body)}
    fence = re.search(r"```(?:json)?\s*(\[.*?)```", body, re.DOTALL)
    if fence:
        return json.loads(fence.group(1)), [], meta
    text = _META.sub("", body)
    parsed = parse_issue(text, "CFB", title=title)
    board: list[dict] = []
    for g in parsed.games:
        row: dict = {"away": g.away, "home": g.home, "captured_at": g.captured_at}
        for m in g.markets:
            key = {"MONEYLINE": "ml", "SPREAD": "spread", "TOTAL": "total"}.get(m.market)
            if key is None:
                parsed.warnings.append(f"CFB_CARD_MARKET_NOT_CONSUMED:{m.market}:{m.raw}")
                continue
            row[key] = [m.price_a, m.price_b] if key == "ml" else [m.line, m.price_a, m.price_b]
        board.append(row)
    return board, parsed.warnings, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", default="board.json")
    args = ap.parse_args()
    try:
        board, warnings, meta = board_from_body(Path(args.body_file).read_text(encoding="utf-8"), title=args.title)
    except (SharedIntakeError, ValueError) as exc:
        Path("intake_error.txt").write_text(str(exc), encoding="utf-8")
        print(f"INTAKE_FAILED: {exc}")
        return 2
    Path(args.out).write_text(json.dumps(board) + "\n", encoding="utf-8")
    for w in warnings:
        print(f"INTAKE_WARNING: {w}", file=sys.stderr)
    for key in ("season", "week"):
        if key in meta:
            print(f"{key}={meta[key]}")
    print(f"path={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
