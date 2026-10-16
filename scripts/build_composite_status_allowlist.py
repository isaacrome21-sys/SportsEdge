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
from sportsedge.promotion_screen import norm_code, promotion_meaning  # noqa: E402


CODE_LITERAL = re.compile(r"""["']([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)["']""")
SKIP = ("composite_", "promotion_screen")
# Codes added explicitly by owner approval (not found on this branch).
OWNER_APPROVED_CODES = frozenset({
    "EITHER_PITCHER_MARGINAL_TAIL_ERROR",  # owner t207u/t208u; branch 6f5b1ea8
})


def collect_codes() -> tuple[list[str], list[str]]:
    """All UPPER_SNAKE code literals; returns (allowed, excluded-as-promotion)."""
    found = set()
    for src in SOURCES:
        for p in sorted((ROOT / src).rglob("*.py")):
            if p.name.startswith(SKIP):
                continue
            found.update(CODE_LITERAL.findall(p.read_text(encoding="utf-8", errors="replace")))
    allowed = sorted(norm_code(s) for s in found if not promotion_meaning(s))
    excluded = sorted(s for s in found if promotion_meaning(s))
    return sorted(set(allowed)), excluded


def collect() -> list[str]:
    found = set()
    for src in SOURCES:
        for p in sorted((ROOT / src).rglob("*.py")):
            if p.name.startswith(SKIP):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for pat in PATTERNS:
                found.update(pat.findall(text))
    return sorted({norm_code(s) for s in found if not promotion_meaning(s)})


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    doc = {"schema": "SPORTSEDGE_COMPOSITE_STATUS_ALLOWLIST_V1",
           "derived_from": "status and status-code literals in artifacts/ and sportsedge/ (see script)",
           "unknown_status_policy": "REFUSE",
           "curation_state": "PENDING_OWNER_CURATION",
           "curation_note": "machine-derived; the owner must review every entry "
                            "before this list is treated as curated",
           "statuses": collect()}
    codes, excluded = collect_codes()
    doc["owner_approved_codes"] = sorted(OWNER_APPROVED_CODES)
    doc["codes"] = sorted(set(codes) | OWNER_APPROVED_CODES)
    doc["excluded_promotion_codes"] = excluded
    doc["exclusion_rule"] = ("promotion_screen.promotion_meaning: promotion token present, "
                             "not refusal-shaped, not a domain phrase")
    rendered = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        return 0 if OUT.read_text(encoding="utf-8") == rendered else 1
    OUT.write_text(rendered, encoding="utf-8")
    print(f"{len(doc['statuses'])} statuses -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
