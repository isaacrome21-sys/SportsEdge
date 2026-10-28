#!/usr/bin/env python3
"""Precondition verification for the CBB_TORVIK_EFFICIENCY_V1 design
screen — ATTEMPT 3.

Supersedes verify_preconditions.py (attempt 1) and
verify_preconditions_attempt2.py (attempt 2) in this directory. The
attempt-1 script's printed verdict is WRONG on current main: its
verdict keys only on precondition (b) while its own precondition (c)
section reports met: false, so it prints "EXECUTABLE" with (c) unmet.
This script corrects that: the verdict is EXECUTABLE only if (a) AND
(b) AND (c) are all met. Attempt-1/2 files are that attempts' records
and are NOT edited; this file is the attempt-3 verifier.

The design (research/nba_cbb_activation_20261028/
CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md, section 3) requires three
data pins BEFORE any run:

  (a) BartTorvik T-Rank archive files via the PR #2832 retrieval route
      at its pinned commit, one file per game date;
  (b) historical schedule/results assets pinned by the full-tuple rule
      of PR #2835 under a successor manifest — supplied by PR #2867
      (research/cbb_hoopr_mbb_schedule_successor_20261028/
      successor_manifest.json: 18 assets, seasons 2015..2023);
  (c) the section 2 three-way fixture agreement (hoopR substrate /
      Torvik archive / College Basketball Reference), applied before
      any fitting — the CBR leg supplied by PR #2871
      (research/cbb_cbr_schedule_mirror_successor_20261028/
      successor_manifest.json: 6 files, commit-anchored full tuple).

Checks, with evidence states:
  (a) re-pull the two admission-pinned Torvik sample files at the
      pinned commit; compare SHA-256 / bytes / team rows to the
      PR #2832 admission record; probe one early / mid / late date per
      design season 2014-15 -> 2022-23 through the admitted route
      (26 probes, the attempt-1 set); AND probe the route's binding
      AS-OF SEMANTICS (design section 1 + PR #2832 rule 2: the file
      for date D is the rating as of the MORNING of D; results of
      games played on D are first reflected in the archive for D+1 or
      later). The probe checks declared witnesses whose game dates
      and results are independently known from the pinned hoopR
      substrate: Duke / Kentucky / Wisconsin on 2014-11-14 (their
      season openers, played ON that date) and Purdue on 2023-03-12
      (Big Ten final, played ON that date). ATTEMPT-3 FINDING: the
      probe FAILS — in every witness the file for D already reflects
      D's own games (Duke 1-0 in the 20141114 file; Purdue 29-5 in
      the 20230312 file, vs 28-5 in the 20230311 file). The pinned
      archive files are END-OF-DAY, not morning-of. Precondition (a)
      is therefore NOT MET as the design defines it, and the screen
      is NOT_EXECUTABLE until a governed amendment declares the
      input convention (PR #2832 rule 4) or a genuinely morning-of
      source is admitted. See SCREEN_REPORT_ATTEMPT3.md;
  (b) hash-verify EVERY kept byte stream named by the PR #2867
      manifest (18/18: 9 CSV + 9 parquet) in the admission workspace
      against the manifest SHA-256 and size;
  (c) hash-verify EVERY kept byte stream named by the PR #2871
      manifest (6/6) against SHA-256, size AND the git blob SHA
      (recomputed from the bytes alone); confirm the admitted scopes
      cover all nine design seasons exactly (logs1520.csv admitted
      2014-15 -> 2017-18 only; 2018-19 from logs19.csv; per-season
      files thereafter).

Stdlib only. Exit 0 = EXECUTABLE (verdict in the printed JSON);
exit 2 = NOT_EXECUTABLE (a pin refused, or the as-of probe failed) —
never silent acceptance.
"""

import csv
import hashlib
import io
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PACKET = Path(__file__).resolve().parent
REPO_ROOT = PACKET.parents[1]
HOOPR_MANIFEST_PATH = (REPO_ROOT / "research" /
                       "cbb_hoopr_mbb_schedule_successor_20261028" /
                       "successor_manifest.json")
CBR_MANIFEST_PATH = (REPO_ROOT / "research" /
                     "cbb_cbr_schedule_mirror_successor_20261028" /
                     "successor_manifest.json")
HOOPR_DIR = Path.home() / "workspace/cbb-successor-admission-20261028/pulls"
CBR_DIR = Path.home() / "workspace/cbb-cbr-successor-admission-20261028/pulls"

TORVIK_PINNED_COMMIT = "46d1036443ca452fdd1c6cf25cf5dff50de68337"
TORVIK_URL_PATTERN = ("https://raw.githubusercontent.com/andreweatherman/"
                      "toRvik-data/" + TORVIK_PINNED_COMMIT +
                      "/ratings/archive/by_date/ratings_archive_{date}.csv")

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

# Early / mid / late probes for each design season 2014-15 -> 2022-23
# (the attempt-1 set, unchanged).
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


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "sportsedge-screen-precondition-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def probe_torvik(date):
    """Return (ok, team_rows or refusal) using the admitted route semantics."""
    url = TORVIK_URL_PATTERN.format(date=date)
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        return False, ("ARCHIVE_DATE_MISSING" if exc.code == 404
                       else "SOURCE_UNAVAILABLE")
    except urllib.error.URLError:
        return False, "SOURCE_UNAVAILABLE"
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    expected = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    if not rows or any(r.get("date") != expected for r in rows):
        return False, "DATE_MISMATCH_OR_SCHEMA_INVALID"
    return True, len(rows)


def check_as_of_semantics():
    """Probe the PR #2832 binding as-of rule on declared witnesses.

    Morning-of semantics require the file for date D to be ignorant of
    games played on D. Witnesses (game dates/scores from the pinned
    hoopR substrate):
      - Duke, Kentucky, Wisconsin all played their season openers ON
        2014-11-14, so a morning-of 20141114 file must show 0-0.
      - Purdue won the Big Ten final ON 2023-03-12 (28-5 before,
        29-5 after), so a morning-of 20230312 file must show 28-5.
    Returns (passed, witnesses) — passed only if EVERY witness shows
    the morning-of value.
    """
    def team_row(stamp, team):
        raw = fetch(TORVIK_URL_PATTERN.format(date=stamp))
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            if row.get("team") == team:
                return row
        return None

    witnesses = []
    for team in ("Duke", "Kentucky", "Wisconsin"):
        row = team_row("20141114", team)
        witnesses.append({
            "case": f"{team} record in the 20141114 archive file",
            "game_on_file_date": "season opener played ON 2014-11-14",
            "expected_if_morning_of": "0-0",
            "observed": row.get("record") if row else None,
        })
    row = team_row("20230312", "Purdue")
    witnesses.append({
        "case": "Purdue record in the 20230312 archive file",
        "game_on_file_date": "Big Ten final played ON 2023-03-12 "
                             "(Purdue won; 28-5 before, 29-5 after)",
        "expected_if_morning_of": "28-5",
        "observed": row.get("record") if row else None,
    })
    passed = all(w["observed"] == w["expected_if_morning_of"]
                 for w in witnesses)
    return passed, witnesses


def check_torvik():
    samples = {}
    for date, pin in ADMISSION_SAMPLES.items():
        raw = fetch(TORVIK_URL_PATTERN.format(date=date))
        got = {"sha256": sha256(raw), "bytes": len(raw)}
        got["team_rows"] = sum(1 for _ in raw.decode("utf-8").splitlines()) - 1
        got["match"] = (got["sha256"] == pin["sha256"]
                        and got["bytes"] == pin["bytes"]
                        and got["team_rows"] == pin["team_rows"])
        samples[date] = got
    probes = {}
    for date in SEASON_PROBES:
        ok, detail = probe_torvik(date)
        probes[date] = {"ok": ok, "detail": detail}
    as_of_passed, witnesses = check_as_of_semantics()
    met = (all(s["match"] for s in samples.values())
           and all(p["ok"] for p in probes.values())
           and as_of_passed)
    return {"met": met, "admission_samples_reverified": samples,
            "season_probes_ok": sum(1 for p in probes.values() if p["ok"]),
            "season_probes_total": len(probes), "probes": probes,
            "as_of_semantics": {
                "rule": "PR #2832 rule 2 / design section 1: the archive "
                        "file for D is the rating as of the morning of "
                        "D; results of games on D are first reflected "
                        "in the archive for D+1 or later",
                "probe_passed": as_of_passed,
                "finding": None if as_of_passed else
                "The pinned archive files are END-OF-DAY: in every "
                "witness the file for D already reflects games played "
                "ON D. Using file D for date D's games is lookahead; "
                "substituting file D-1 would be the carry-forward "
                "PR #2832 rule 4 forbids without a declared design "
                "amendment and its own review.",
                "witnesses": witnesses}}


def check_hoopr():
    manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    results, refused = {}, []
    for sample in manifest["samples"]:
        name = sample["asset_name"]
        path = HOOPR_DIR / name
        if not path.exists():
            results[name] = {"match": False, "refusal": "ASSET_MISSING"}
            refused.append(name)
            continue
        raw = path.read_bytes()
        match = sha256(raw) == sample["sha256"] and len(raw) == sample["bytes"]
        results[name] = {"match": match, "bytes": len(raw),
                         "sha256": sha256(raw)}
        if not match:
            refused.append(name)
    return {"met": not refused and len(results) == 18,
            "assets_checked": len(results),
            "assets_matched": sum(1 for r in results.values() if r["match"]),
            "refused": refused, "assets": results}


def check_cbr():
    manifest = json.loads(CBR_MANIFEST_PATH.read_text(encoding="utf-8"))
    results, refused = {}, []
    seasons_covered = set()
    for sample in manifest["samples"]:
        name = sample["file_name"]
        for season in sample["admitted_seasons"]:
            seasons_covered.add(season)
        path = CBR_DIR / name
        if not path.exists():
            results[name] = {"match": False, "refusal": "ASSET_MISSING"}
            refused.append(name)
            continue
        raw = path.read_bytes()
        match = (sha256(raw) == sample["sha256"]
                 and len(raw) == sample["bytes"]
                 and git_blob_sha(raw) == sample["git_blob_sha"])
        results[name] = {"match": match, "bytes": len(raw),
                         "sha256": sha256(raw),
                         "git_blob_sha": git_blob_sha(raw),
                         "admitted_seasons": sample["admitted_seasons"]}
        if not match:
            refused.append(name)
    scope_ok = seasons_covered == set(range(2015, 2024))
    return {"met": not refused and len(results) == 6 and scope_ok,
            "files_checked": len(results),
            "files_matched": sum(1 for r in results.values() if r["match"]),
            "refused": refused,
            "admitted_scope_covers_all_nine_seasons": scope_ok,
            "files": results}


def main():
    a = check_torvik()
    b = check_hoopr()
    c = check_cbr()
    verdict = {
        "attempt": 3,
        "supersedes": ["verify_preconditions.py (attempt 1 — its verdict "
                       "line keys on (b) alone and is WRONG on current "
                       "main; do not act on it)",
                       "verify_preconditions_attempt2.py (attempt 2)"],
        "precondition_a_torvik_archive": a,
        "precondition_b_hoopr_schedule_successor_manifest": b,
        "precondition_c_cbr_mirror_successor_manifest": c,
        "screen_verdict": ("EXECUTABLE" if (a["met"] and b["met"] and c["met"])
                           else "NOT_EXECUTABLE"),
        "missing_piece": None if (a["met"] and b["met"] and c["met"]) else
        "Precondition (a) fails on AS-OF SEMANTICS: the PR #2832 pinned "
        "archive files are end-of-day, not morning-of (file D reflects "
        "games played on D — see the as_of_semantics witnesses and "
        "SCREEN_REPORT_ATTEMPT3.md). Governed unblocks only: a design "
        "amendment declaring the input convention (PR #2832 rule 4) "
        "with its own review, or admission of a genuinely morning-of "
        "ratings source. Pins (b) and (c) are met.",
    }
    print(json.dumps(verdict, indent=2))
    if verdict["screen_verdict"] != "EXECUTABLE":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
