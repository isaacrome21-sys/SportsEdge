#!/usr/bin/env python3
"""Precondition verification for the CBB_TORVIK_EFFICIENCY_V1 design
screen — ATTEMPT 4.

Supersedes verify_preconditions.py (attempt 1) and
verify_preconditions_attempt2.py (attempt 2) in this directory, and
verify_preconditions_attempt3.py (attempt 3, PR #2873 — its record;
not edited). The attempt-1 script's printed verdict is WRONG on
current main: its verdict keys only on precondition (b) while its
own precondition (c) section reports met: false, so it prints
"EXECUTABLE" with (c) unmet. This script's verdict is EXECUTABLE
only if (a) AND (b) AND (c) are all met. Attempt 4 runs under
AMENDMENT_1.md (merged PR #2883): the PRIOR-SNAPSHOT convention —
for games on date D the Torvik input is the archive file dated D-1;
if file D-1 does not exist, the fixture is NO_DATA, never
substituted from D-2 or D.

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
      PRIOR-SNAPSHOT SEMANTICS (Amendment 1, PR #2883 — the governed
      declaration PR #2832 rule 4 required, after attempt 3 proved
      the files are END-OF-DAY, not morning-of). The probe checks
      the convention's declared witnesses on the D-1 side, game
      dates and results independently known from the pinned hoopR
      substrate: Duke / Kentucky / Wisconsin must show 0-0 in the
      2014-11-13 file (their openers were played ON 2014-11-14) and
      Purdue must show 28-5 in the 2023-03-11 file (the Big Ten
      final was played ON 2023-03-12 at 28-5 before the game); AND
      the D-1 file for each season's opening game date must exist
      on the admitted route (nine opener probes). Amendment 1's own
      probe suite verified the convention 19/19
      (PRIOR_SNAPSHOT_VERIFIED); this check re-verifies the witness
      core plus opener existence for the amended run. See
      SCREEN_REPORT_ATTEMPT4.md;
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
exit 2 = NOT_EXECUTABLE (a pin refused, or the prior-snapshot probe failed) —
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

# D-1 (prior-snapshot) file stamps for each design season's OPENING
# game date (opening dates from the pinned hoopR substrate):
# 2014-11-14, 2015-11-13, 2016-11-11, 2017-11-10, 2018-11-06,
# 2019-11-05, 2020-11-25, 2021-11-09, 2022-11-07. Under Amendment 1
# these are the first files the amended screen reads each season;
# existence is existence only — a file without adj_tempo (the
# 2022-11-06 drift layout) still makes its fixtures NO_DATA in the
# runner, exactly as the amendment's section 5 declares.
OPENER_PRIOR_SNAPSHOT_PROBES = [
    "20141113", "20151112", "20161110", "20171109", "20181105",
    "20191104", "20201124", "20211108", "20221106",
]

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


def check_prior_snapshot_semantics():
    """Probe the Amendment 1 prior-snapshot convention on witnesses.

    For games on date D the model's input is the file dated D-1.
    Witnesses (game dates/scores from the pinned hoopR substrate):
      - Duke, Kentucky, Wisconsin played their season openers ON
        2014-11-14, so the D-1 file (20141113, preseason) must
        show 0-0 for each;
      - Purdue entered the Big Ten final ON 2023-03-12 at 28-5
        (29-5 after winning it), so the D-1 file (20230311) must
        show 28-5.
    Returns (passed, witnesses) — passed only if EVERY witness
    shows the prior-snapshot value.
    """
    def team_row(stamp, team):
        raw = fetch(TORVIK_URL_PATTERN.format(date=stamp))
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            if row.get("team") == team:
                return row
        return None

    witnesses = []
    for team in ("Duke", "Kentucky", "Wisconsin"):
        row = team_row("20141113", team)
        witnesses.append({
            "case": f"{team} record in the 20141113 archive file "
                    f"(D-1 prior snapshot for games on 2014-11-14)",
            "game_on_game_date": "season opener played ON 2014-11-14",
            "expected_if_prior_snapshot": "0-0",
            "observed": (row.get("record") or row.get("rec")) if row else None,
        })
    row = team_row("20230311", "Purdue")
    witnesses.append({
        "case": "Purdue record in the 20230311 archive file "
                "(D-1 prior snapshot for games on 2023-03-12)",
        "game_on_game_date": "Big Ten final played ON 2023-03-12 "
                             "(Purdue won; 28-5 before, 29-5 after)",
        "expected_if_prior_snapshot": "28-5",
        "observed": (row.get("record") or row.get("rec")) if row else None,
    })
    passed = all(w["observed"] == w["expected_if_prior_snapshot"]
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
    ps_passed, witnesses = check_prior_snapshot_semantics()
    opener_probes = {}
    for stamp in OPENER_PRIOR_SNAPSHOT_PROBES:
        ok, detail = probe_torvik(stamp)
        opener_probes[stamp] = {"ok": ok, "detail": detail}
    met = (all(s["match"] for s in samples.values())
           and all(p["ok"] for p in probes.values())
           and all(p["ok"] for p in opener_probes.values())
           and ps_passed)
    return {"met": met, "admission_samples_reverified": samples,
            "season_probes_ok": sum(1 for p in probes.values() if p["ok"]),
            "season_probes_total": len(probes), "probes": probes,
            "opener_prior_snapshot_probes": opener_probes,
            "prior_snapshot_semantics": {
                "rule": "AMENDMENT_1.md (PR #2883), declaring the "
                        "convention PR #2832 rule 4 reserves: for "
                        "games on date D, the model's Torvik input "
                        "is the archive file dated D-1 — the last "
                        "end-of-day snapshot strictly before D; a "
                        "missing D-1 file is NO_DATA, never "
                        "substituted from D-2 or D. (Attempt 3 "
                        "proved the files are end-of-day: file D "
                        "already reflects games played ON D.)",
                "probe_passed": ps_passed,
                "amendment_suite": "AMENDMENT_1.md probe suite: "
                                   "19/19 PASS — "
                                   "PRIOR_SNAPSHOT_VERIFIED (PR #2883)",
                "finding": None if ps_passed else
                "The D-1 witness probe FAILED on the pinned bytes: "
                "the prior-snapshot files do not show the entering "
                "records the convention requires.",
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
        "attempt": 4,
        "supersedes": ["verify_preconditions.py (attempt 1 — its verdict "
                       "line keys on (b) alone and is WRONG on current "
                       "main; do not act on it)",
                       "verify_preconditions_attempt2.py (attempt 2)",
                       "verify_preconditions_attempt3.py (attempt 3, "
                       "PR #2873 — morning-of probe; the convention it "
                       "lacked is now declared by Amendment 1)"],
        "precondition_a_torvik_archive": a,
        "precondition_b_hoopr_schedule_successor_manifest": b,
        "precondition_c_cbr_mirror_successor_manifest": c,
        "screen_verdict": ("EXECUTABLE" if (a["met"] and b["met"] and c["met"])
                           else "NOT_EXECUTABLE"),
        "missing_piece": None if (a["met"] and b["met"] and c["met"]) else
        "A precondition is unmet — see the per-precondition sections "
        "above (for (a): admission samples, season probes, opener "
        "D-1 existence probes, and the prior-snapshot witness probe "
        "under AMENDMENT_1.md / PR #2883). No substitution or "
        "workaround is authorized; see SCREEN_REPORT_ATTEMPT4.md.",
    }
    print(json.dumps(verdict, indent=2))
    if verdict["screen_verdict"] != "EXECUTABLE":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
