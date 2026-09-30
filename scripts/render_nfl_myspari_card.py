#!/usr/bin/env python3
"""Render the NFL phone card. PRE-CONTEXT heading until context is bound."""
from __future__ import annotations

import argparse
from pathlib import Path
import json

from sportsedge.nfl_attempt9_live_forecast import market_eligibility
from sportsedge.sports.nfl.attempt9_model_p import model_probability
from sportsedge.nfl_attempt9_live_forecast import load_model_p

PRE_CONTEXT = "PRE-CONTEXT · NOT FINAL"
FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-output", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--pre-context", action="store_true")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    engine = json.loads(Path(args.engine_output).read_text(encoding="utf-8"))
    heading = PRE_CONTEXT if args.pre_context or not engine.get("context_bound") else "card"
    lines = [f"NFL — {heading}", ""]
    for game in engine.get("games") or []:
        lines.append(f"{game.get('away')} @ {game.get('home')}")
        for row in game.get("markets") or []:
            reason = row.get("no_model") or market_eligibility(row.get("market"), row.get("line"))
            if reason:
                lines.append(f"- {row.get('raw') or row.get('market')}: {reason}")
                continue
            pick = row.get("pick")
            if not pick:
                lines.append(f"- {row.get('market')}: no pick")
                continue
            lines.append(
                f"- {pick['selection']} {pick.get('line', '')} @ {pick['price_american']}"
                f"  Score-B {pick.get('score_0_100', '—')}"
                f"  EV {pick.get('ev_per_dollar', 0):+.3f}"
            )
        lines.append("")
    if not any(g.get("picks") for g in engine.get("games") or []):
        if engine.get("empty_reason"):
            lines.append(str(engine["empty_reason"]))
    lines.append(FOOTER)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
