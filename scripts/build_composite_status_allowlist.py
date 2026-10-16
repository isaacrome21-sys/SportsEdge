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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from sportsedge.promotion_screen import promotes  # noqa: E402


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
           "curation_state": "PENDING_OWNER_CURATION",
           "curation_note": "machine-derived; the owner must review every entry "
                            "before this list is treated as curated",
           "statuses": collect()}
    rendered = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        return 0 if OUT.read_text(encoding="utf-8") == rendered else 1
    OUT.write_text(rendered, encoding="utf-8")
    print(f"{len(doc['statuses'])} statuses -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
