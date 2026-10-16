#!/usr/bin/env python3
"""Build the owner-reviewable composite status ALLOWLIST (#2359 audit t211).

Source of truth: status string literals the pricing path actually emits
(``"status": "X"``, ``status="X"``, ``["status"] = "X"``) in ``artifacts/``
and ``sportsedge/``. Any literal carrying a promotion token (PLAY, BET, PICK,
LOCK, BUY, OFFICIAL, STAKE, WAGER ...) is excluded unless the token is negated
(NO_/NOT_/NOT_A_). Unknown statuses are refused by the composite guard.
Usage: python scripts/build_composite_status_allowlist.py [--check]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sportsedge" / "composite_status_allowlist.json"
SOURCES = ("artifacts", "sportsedge")
PATTERNS = (re.compile(r"""["']status["']\s*:\s*["']([A-Z][A-Z0-9_]*)["']"""),
            re.compile(r"""\bstatus\s*=\s*["']([A-Z][A-Z0-9_]*)["']"""),
            re.compile(r"""\[["']status["']\]\s*=\s*["']([A-Z][A-Z0-9_]*)["']"""),
            # Status/blocker code literals routed into rows through variables.
            re.compile(r"""["']((?:BLOCKED|WATCH|NO|NOT|RESEARCH|PRICED|REFRESH|STALE|QUOTE|"""
                       r"""GOVERNANCE|MISSING|UNVERIFIED|VERIFIED|REFUSED|DIAGNOSTIC|UNPRICED)"""
                       r"""_[A-Z0-9_]+)["']"""))
PROMOTION = {"PLAY", "PLAYS", "PLAYABLE", "BET", "BETS", "WAGER", "PICK", "PICKS", "LOCK",
             "BUY", "OFFICIAL", "OFFICIALPICK", "STAKE", "STAKED", "PROMOTED", "ACTIVATED"}
NEGATORS = {"NO", "NOT", "NON"}


def promotes(status: str) -> bool:
    toks = status.upper().split("_")
    for i, t in enumerate(toks):
        if t in PROMOTION:
            prev = toks[max(0, i - 2):i]
            if not any(p in NEGATORS for p in prev):
                return True
    return False


def collect() -> list[str]:
    found = set()
    for src in SOURCES:
        for p in sorted((ROOT / src).rglob("*.py")):
            if p.name.startswith("composite_"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for pat in PATTERNS:
                found.update(pat.findall(text))
    return sorted(s for s in found if not promotes(s))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    doc = {"schema": "SPORTSEDGE_COMPOSITE_STATUS_ALLOWLIST_V1",
           "derived_from": "status and status-code literals in artifacts/ and sportsedge/ (see script)",
           "unknown_status_policy": "REFUSE",
           "statuses": collect()}
    rendered = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        return 0 if OUT.read_text(encoding="utf-8") == rendered else 1
    OUT.write_text(rendered, encoding="utf-8")
    print(f"{len(doc['statuses'])} statuses -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
