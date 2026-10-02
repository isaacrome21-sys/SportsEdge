#!/usr/bin/env python3
"""NBA phone card. PRE-CONTEXT until a frozen owner exists."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PRE_CONTEXT = "PRE-CONTEXT · NOT FINAL"
FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
NO_OWNER = "NO_MODEL:FROZEN_OWNER_MISSING"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--pre-context", action="store_true")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    ticket = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    heading = PRE_CONTEXT if args.pre_context else "card"
    lines = [f"NBA — {heading}", ""]
    for game in ticket.get("games") or []:
        lines.append(f"{game.get('away')} @ {game.get('home')}")
        for row in game.get("markets") or []:
            lines.append(f"- {row.get('raw') or row.get('market')}: {NO_OWNER}")
        lines.append("")
    lines.append("No frozen NBA owner is on main, so nothing is priced.")
    lines.append(FOOTER)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
