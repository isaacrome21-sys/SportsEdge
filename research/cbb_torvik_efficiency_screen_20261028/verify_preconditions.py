#!/usr/bin/env python3
"""Precondition verification for the CBB_TORVIK_EFFICIENCY_V1 design screen.

Reproduces the NOT_EXECUTABLE finding of SCREEN_REPORT.md in this directory.
The design (research/nba_cbb_activation_20261028/
CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md, section 3) requires three data
pins BEFORE any run:

  (a) BartTorvik T-Rank archive files via the PR #2832 retrieval route at
      its pinned commit, one file per game date;
  (b) historical schedule/results assets from the sportsdataverse-data
      releases pinned by the full-tuple rule of PR #2835 (tag + release ID
      + asset ID + size + updated_at + SHA-256) under a SUCCESSOR manifest
      (PR #2835 pinned the 2027 schedule and 2026 player box only);
  (c) the section 2 three-way fixture agreement (hoopR substrate / Torvik
      archive / College Basketball Reference), applied before any fitting.

This script verifies, with evidence states:
  (a) by re-pulling the two admission-pinned Torvik sample files at the
      pinned commit and comparing SHA-256 / bytes / team rows to the
      admission record, and by probing one early / mid / late date per
      design season 2014-15 -> 2022-23 through the admitted route;
  (b) by scanning the PR #2835 sample manifest and the whole repo tree for
      any full-tuple pin of a historical-season schedule asset
      (mbb_schedule_YYYY for YYYY in 2015..2023).

Stdlib only. Exit 0 = checks ran (verdict is in the printed JSON);
the screen verdict itself is NOT_EXECUTABLE while (b) is unmet.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

PINNED_COMMIT = "46d1036443ca452fdd1c6cf25cf5dff50de68337"
URL_PATTERN = (
    "https://raw.githubusercontent.com/andreweatherman/toRvik-data/"
    + PINNED_COMMIT
    + "/ratings/archive/by_date/ratings_archive_{date}.csv"
)

# The two samples hash-pinned by the PR #2832 admission record.
ADMISSION_SAMPLES = {
    "20220113": {
        "sha256": "4de4761caf3f581c56d9587ac9deeb954556ee5a8529948d8ef5206f9dfe14ad",
        "bytes": 58716,
        "team_rows": 358,
    },
    "20230312": {
        "sha256": "9524481d69c7b690200299387690654091565ef1d3df774ca858749e5e1cc01c",
        "bytes": 60010,
        "team_rows": 363,
    },
}

# Early / mid / late probes for each design season 2014-15 -> 2022-23.
SEASON_PROBES = [
    "20141115", "20150115", "20150315",
    "20151114", "20160115", "20160313",
    "20161112", "20170115", "20170312",
    "20171111", "20180114", "20180311",
    "20181110", "20190113", "20190317",
    "20191109", "20200112", "20200308",
    "20201128", "20210117", "20210314",
    "20211113", "20220116", "20220313",
    "20221112", "20230115",
]

HISTORICAL_SCHEDULE_RE = re.compile(r"mbb_schedule_(201[5-9]|202[0-3])\b")


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "sportsedge-screen-precondition-check"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def probe_torvik(date):
    """Return (ok, team_rows or refusal) using the admitted route semantics."""
    import csv
    import io

    url = URL_PATTERN.format(date=date)
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        return False, ("ARCHIVE_DATE_MISSING" if exc.code == 404 else "SOURCE_UNAVAILABLE")
    except urllib.error.URLError:
        return False, "SOURCE_UNAVAILABLE"
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    expected = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    if not rows or any(r.get("date") != expected for r in rows):
        return False, "DATE_MISMATCH_OR_SCHEMA_INVALID"
    return True, len(rows)


def check_torvik_samples():
    out = {}
    for date, pin in ADMISSION_SAMPLES.items():
        raw = fetch(URL_PATTERN.format(date=date))
        got = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        got["team_rows"] = sum(1 for _ in raw.decode("utf-8").splitlines()) - 1
        got["match"] = (
            got["sha256"] == pin["sha256"]
            and got["bytes"] == pin["bytes"]
            and got["team_rows"] == pin["team_rows"]
        )
        out[date] = got
    return out


def scan_repo_for_historical_schedule_pins(repo_root):
    """Walk the tree for any pin of a 2015..2023 mbb schedule asset."""
    hits = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        if ".git" in dirpath.split(os.sep):
            continue
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            if not name.endswith((".json", ".md", ".py", ".txt")):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", errors="strict") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for m in HISTORICAL_SCHEDULE_RE.finditer(text):
                hits.append({"file": os.path.relpath(path, repo_root), "asset_year": m.group(1)})
    return hits


def load_2835_manifest(repo_root):
    path = os.path.join(
        repo_root,
        "research/cbb_hoopr_mbb_data_admission_20261027/sample_manifest.json",
    )
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    return [s["asset_name"] for s in manifest["samples"]]


def main():
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    samples = check_torvik_samples()
    probes = {}
    for date in SEASON_PROBES:
        ok, detail = probe_torvik(date)
        probes[date] = {"ok": ok, "detail": detail}

    manifest_assets = load_2835_manifest(repo_root)
    manifest_historical = [a for a in manifest_assets if HISTORICAL_SCHEDULE_RE.search(a)]
    repo_hits = scan_repo_for_historical_schedule_pins(repo_root)
    # Hits inside the design documents are references to the requirement,
    # not pins; a pin must live in a manifest. Report both, classified.
    manifest_hits = [h for h in repo_hits if "manifest" in h["file"]]

    pin_b_met = bool(manifest_historical) or bool(manifest_hits)
    verdict = {
        "precondition_a_torvik_archive": {
            "met": all(s["match"] for s in samples.values())
            and all(p["ok"] for p in probes.values()),
            "admission_samples_reverified": samples,
            "season_probes_ok": sum(1 for p in probes.values() if p["ok"]),
            "season_probes_total": len(probes),
        },
        "precondition_b_historical_schedule_full_tuple_pin": {
            "met": pin_b_met,
            "pr_2835_manifest_assets": manifest_assets,
            "historical_assets_in_pr_2835_manifest": manifest_historical,
            "repo_wide_manifest_hits": manifest_hits,
        },
        "precondition_c_three_way_agreement": {
            "met": False,
            "reason": "Not applicable until (b) provides a pinned fixture "
            "universe; College Basketball Reference is documented-only "
            "in the design (no bytes pulled, no pin).",
        },
        "screen_verdict": "EXECUTABLE" if pin_b_met else "NOT_EXECUTABLE",
        "missing_piece": None
        if pin_b_met
        else "Successor full-tuple manifest (PR #2835 pin rule) pinning the "
        "historical sportsdataverse-data schedule/results assets "
        "mbb_schedule_2015..mbb_schedule_2023 (CSV or parquet, each pinned "
        "independently) for seasons 2014-15 -> 2022-23.",
    }
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
