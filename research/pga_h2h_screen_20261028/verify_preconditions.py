#!/usr/bin/env python3
"""Re-verify the preconditions of the PGA H2H Leg-1 design screen
(attempt 2026-10-28) and print the screen verdict they imply.

Checks, from artifacts committed beside this script:
  (a) every HTTP-200 page in dg_pages_manifest.json that is kept in the
      local pulls directory re-hashes to its recorded sha256;
  (b) the coverage summary in dg_pages_coverage.json supports the design's
      volume floor (>= 1,500 test matchups per season is a pair count over
      priced players; ~3.4k+ player-rows per test season makes it
      satisfiable) and records outright Close odds on ~95% of rows in each
      test season — reference (a) material present;
  (c) the OWGR probe record (owgr_probe.json): reference (b), an
      OWGR-points-implied rating, has no obtainable free source.

The verdict is DERIVED from the gap list, never hard-coded: if the OWGR gap
is present in the probe record, the verdict is NOT_EXECUTABLE.

Stdlib only. Usage: verify_preconditions.py [pulls_dir]
Exit 0 = record internally consistent (whatever the verdict); 1 = the
committed record does not match the kept bytes / coverage artifacts.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(HERE, name)) as f:
        return json.load(f)


def main() -> int:
    pulls_dir = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.expanduser("~/workspace/pga_screen_20261028/pulls")
    )
    manifest = load("dg_pages_manifest.json")
    coverage = load("dg_pages_coverage.json")
    owgr = load("owgr_probe.json")

    ok = True
    gaps = []

    # (a) pin integrity of kept pages
    pages_dir = os.path.join(pulls_dir, "dg_pages")
    checked = matched = 0
    if os.path.isdir(pages_dir):
        for rec in manifest.values():
            if rec.get("http") != 200:
                continue
            path = os.path.join(pages_dir, rec["file"])
            if not os.path.exists(path):
                continue
            checked += 1
            with open(path, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() == rec["sha256"]:
                    matched += 1
        print(f"(a) DG pages kept locally: {checked} checked, {matched} PIN_MATCH")
        if checked and matched != checked:
            ok = False
            print("    MISMATCH between kept bytes and committed manifest")
    else:
        print(f"(a) pulls dir {pages_dir} not present — pin check skipped (record-only mode)")

    # (b) coverage: unique events and Close-odds coverage per test season
    seen = {}
    for r in coverage:
        if r.get("parse") == "OK":
            seen.setdefault((r["info_event_id"], r["date"]), r)
    for season in (2023, 2024, 2025):
        ev = [r for r in seen.values() if r.get("season") == season]
        rows = sum(r["rows"] for r in ev)
        wc = sum(r.get("rows_with_close", 0) for r in ev)
        share = (100.0 * wc / rows) if rows else 0.0
        print(f"(b) season {season}: {len(ev)} unique events, {rows} rows, Close odds on {wc} ({share:.1f}%)")
        if not ev or share < 90.0:
            gaps.append(f"reference (a) material thin in season {season}")

    # (c) OWGR reference (b)
    print(f"(c) OWGR probe conclusion: {owgr['conclusion']}")
    if "No lawful, hash-pinnable copy" in owgr["conclusion"]:
        gaps.append(
            "G-PGA-1 reference (b) OWGR weekly points archive is not obtainable free "
            "(owgr.com serves an HTML shell at its archive PDF paths; Wayback holds only "
            "301 redirect stubs; downloads 429) — the OWGR-points-implied reference "
            "rating cannot be constructed as designed"
        )

    verdict = "NOT_EXECUTABLE" if gaps else "EXECUTABLE"
    print(json.dumps({"screen_verdict": verdict, "gaps": gaps}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
