#!/usr/bin/env python3
"""CBB TEAM TOTALS design screen — the run.

Executes the third leg of the section 3 design screen of
CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md (PR #2843), as specified
by CBB_TEAM_TOTALS_1H_DESIGN.md section 1: team-points MAE of
CBB_TORVIK_EFFICIENCY_V1 vs (i) a naive team-mean baseline and
(ii) the simple ratings baseline's team points — same pins, same
walk-forward protocol, same DESIGN-evidence label; the leg passes
or fails on its own CI, independently of the spread/total legs.

Data legs (identical to the parent screen):
  (a) BartTorvik T-Rank morning-of archive files at the PR #2832
      pinned commit (46d1036443ca452fdd1c6cf25cf5dff50de68337),
      one file per game date; a missing file for D makes the
      fixture NO_DATA — never substituted (admission rule 4);
  (b) hoopR schedule substrate via the PR #2867 successor manifest
      (kept bytes hash-verified before use);
  (c) College Basketball Reference game logs via the PR #2871
      mirror successor manifest (hash + size + git-blob verified;
      admitted scopes ONLY: logs1520.csv for 2014-15 -> 2017-18,
      2018-19 from logs19.csv, then per-season files).

Fixture universe (design section 2), when reached: the
Illinois-college exclusion is applied FIRST (conservative
over-exclusion on name match, the design's design-screen
expedient); a fixture then enters ONLY on three-way agreement —
hoopR (ESPN game ID, date, teams, final score), Torvik (a
morning-of file exists for that date and carries both teams), CBR
mirror (same fixture, same date, same final score). Disagreements
are excluded and logged as SCHEDULE_DISCREPANCY with a reason code
— never silently resolved. Name resolution uses ONLY the PR #2871
published NORMALIZATION_OVERRIDES table plus the legs' own surface
tables harvested from the pinned bytes (no mirror inference — the
PR #2871 derivation recorded it firing zero times). The fixture
machinery mirrors the parent screen's attempt-3 runner, which
established these conventions on the same pinned bytes.

AS-OF PREMISE AUDIT (run before any fitting or scoring): the
design (parent section 1) takes the archive file for date D as the
rating as of the MORNING of D, and the PR #2832 admission's rule 2
states results of games on D are first reflected in the archive
for D+1 or later. This runner probes that premise with (1)
declared witnesses — teams whose pre-game record on a declared
date is known from the pinned substrates — and (2) a systematic
opening-day audit: for every design season, in the archive file
for the season's first game date (from the pinned hoopR
substrate), EVERY team's record must be 0-0 under morning-of
semantics. If the audit fails, the runner refuses with
AS_OF_PREMISE_FAILURE: scoring team points on file D would be
lookahead (the file already contains the game being forecast),
and silently substituting file D-1 would be the carry-forward
PR #2832 rule 4 forbids without a declared design amendment and
its own review. Sequencing note: the parent screen's attempt 3
built its fixture universe before its (identical) probe failed;
this runner audits first — the same gate, the same refusal, no
fitting or scoring either way.

FIRST-HALF FAMILY: CBB_TEAM_TOTALS_1H_DESIGN.md section 2 names
one prerequisite — hoopR play-by-play release assets (load_mbb_pbp
family) pinned by the full-tuple rule WITH schema verification.
Until such a manifest lands, "the half share cannot be fitted and
1H is not screenable". This runner scans the repo for that
manifest and records the verdict in its output; no share is
borrowed, from the NBA fit, a rule of thumb, or halved finals.

MARKET BASELINE: the design names none for this family's design
screen — its baselines are (i) and (ii) above. The market leg
(CLV > 0 and ROI > 0 vs forward DraftKings team-total captures)
is a FORWARD term of the team-totals design section 1, gated on a
freeze that does not exist; it is not part of this screen and no
market-implied split is computed here.

Stdlib only. Exit codes: 0 = screen ran (verdict in the output
JSON); 2 = an input pin refused or the premise audit failed.
"""

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cbb_team_totals as tt  # noqa: E402

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
TORVIK_ADMISSION_SAMPLES = {
    "20220113": ("4de4761caf3f581c56d9587ac9deeb954556ee5a8529948d8ef5206f9dfe14ad",
                 58716, 358),
    "20230312": ("9524481d69c7b690200299387690654091565ef1d3df774ca858749e5e1cc01c",
                 60010, 363),
}

PER_SEASON_FILES = {2019: "logs19.csv", 2020: "logs20.csv",
                    2021: "logs21.csv", 2022: "logs22.csv",
                    2023: "logs23.csv"}
SEASON_LABEL = tt.SEASON_LABEL
SEASON_LABEL_CBR = {2015: "2014-2015", 2016: "2015-2016", 2017: "2016-2017",
                    2018: "2017-2018", 2019: "2018-2019", 2020: "2019-2020",
                    2021: "2020-2021", 2022: "2021-2022", 2023: "2022-2023"}

# The PR #2871 published table — republished verbatim; the screen uses
# this table ONLY (plus the legs' own harvested surface tables).
NORMALIZATION_OVERRIDES = {
    "Albany": "albany-ny",
    "American University": "american",
    "BYU": "brigham-young",
    "Central Connecticut": "central-connecticut-state",
    "Cleveland St.": "cleveland-state",
    "Detroit": "detroit-mercy",
    "ETSU": "east-tennessee-state",
    "Fort Wayne": "ipfw",
    "Fort Wayne Mastodons": "ipfw",
    "LIU": "long-island-university",
    "LIU-Brooklyn": "long-island-university",
    "LIU-Brooklyn Blackbirds": "long-island-university",
    "LSU": "louisiana-state",
    "Nebraska Omaha": "nebraska-omaha",
    "Ole Miss": "mississippi",
    "Oregon St.": "oregon-state",
    "Penn": "pennsylvania",
    "Pitt": "pittsburgh",
    "Saint Mary's": "saint-marys-ca",
    "San Diego St.": "san-diego-state",
    "SIU-Edwardsville": "southern-illinois-edwardsville",
    "SMU": "southern-methodist",
    "Southern Miss": "southern-mississippi",
    "St. Joseph's": "saint-josephs",
    "St. Peter's": "saint-peters",
    "Texas St.": "texas-state",
    "UAlbany": "albany-ny",
    "UConn": "connecticut",
    "UIC": "illinois-chicago",
    "UMass": "massachusetts",
    "UMass-Lowell": "massachusetts-lowell",
    "UMBC": "maryland-baltimore-county",
    "UMKC": "missouri-kansas-city",
    "UNC": "north-carolina",
    "UNLV": "nevada-las-vegas",
    "USC": "southern-california",
    "USC Upstate": "south-carolina-upstate",
    "UCSB": "california-santa-barbara",
    "UT-Martin": "tennessee-martin",
    "VCU": "virginia-commonwealth",
    "Youngstown St.": "youngstown-state",
}

# Illinois D1 programs in the design window, as CBR school slugs
# (design section 2: conservative over-exclusion on name match).
ILLINOIS_SLUGS = {
    "bradley", "chicago-state", "depaul", "eastern-illinois", "illinois",
    "illinois-chicago", "illinois-state", "loyola-il", "northern-illinois",
    "northwestern", "southern-illinois", "southern-illinois-edwardsville",
    "western-illinois",
}

# Declared as-of witnesses: (archive date, Torvik team surface,
# record the substrate proves the team held BEFORE that date's
# games). 2014-11-14 was the 2014-15 opening day (every team 0-0
# before it); Purdue entered the 2023-03-12 Big Ten final at 28-5
# and won it that day; Connecticut / San Diego St. entered the
# 2023-04-03 national final at 30-8 / 32-6 (their records in the
# 2023-04-01 file) and the final was played that evening.
DECLARED_WITNESSES = [
    ("2014-11-14", "Duke", "0-0"),
    ("2014-11-14", "Kentucky", "0-0"),
    ("2014-11-14", "Wisconsin", "0-0"),
    ("2014-11-14", "Kansas", "0-0"),
    ("2014-11-14", "Michigan St.", "0-0"),
    ("2014-11-14", "North Carolina", "0-0"),
    ("2014-11-14", "UCLA", "0-0"),
    ("2023-03-12", "Purdue", "28-5"),
    ("2023-04-03", "Connecticut", "30-8"),
    ("2023-04-03", "San Diego St.", "32-6"),
]


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def refuse(label, path):
    print(json.dumps({"refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
                      "input": label, "path": str(path)}))
    sys.exit(2)


def load_pinned(path, expected_sha, label):
    raw = path.read_bytes()
    if sha256(raw) != expected_sha:
        refuse(label, path)
    return raw


# ---------------------------------------------------------------- pins

def verify_all_pins(hoopr_manifest, cbr_manifest, torvik_cache):
    """Hash-verify every kept byte stream; re-verify Torvik samples."""
    for sample in hoopr_manifest["samples"]:
        path = HOOPR_DIR / sample["asset_name"]
        raw = load_pinned(path, sample["sha256"], sample["asset_name"])
        if len(raw) != sample["bytes"]:
            refuse(sample["asset_name"], path)
    for sample in cbr_manifest["samples"]:
        path = CBR_DIR / sample["file_name"]
        raw = load_pinned(path, sample["sha256"], sample["file_name"])
        if len(raw) != sample["bytes"] or git_blob_sha(raw) != sample["git_blob_sha"]:
            refuse(sample["file_name"], path)
    for date, (pin_sha, pin_bytes, pin_rows) in TORVIK_ADMISSION_SAMPLES.items():
        raw = fetch_torvik(date, torvik_cache)
        rows = sum(1 for _ in raw.decode("utf-8").splitlines()) - 1
        if sha256(raw) != pin_sha or len(raw) != pin_bytes or rows != pin_rows:
            refuse(f"torvik admission sample {date}", date)
    return {"hoopr_assets_verified": len(hoopr_manifest["samples"]),
            "cbr_files_verified": len(cbr_manifest["samples"]),
            "torvik_admission_samples_verified": len(TORVIK_ADMISSION_SAMPLES)}


# ------------------------------------------------------------- resolver

def build_resolver(cbr_manifest):
    """Harvest CBR's own surface tables from the pinned per-season bytes."""
    team2slug, full2slug = {}, {}
    pins = {s["file_name"]: s["sha256"] for s in cbr_manifest["samples"]}
    for name in PER_SEASON_FILES.values():
        raw = load_pinned(CBR_DIR / name, pins[name], name)
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            slug = row["URL"].split("/")[3]
            team2slug[row["Team"]] = slug
            full2slug[row["TeamFull"]] = slug

    def resolve(surface):
        if surface in NORMALIZATION_OVERRIDES:
            return NORMALIZATION_OVERRIDES[surface]
        if surface in team2slug:
            return team2slug[surface]
        return full2slug.get(surface)

    return resolve


# ------------------------------------------------------------ CBR leg

def load_cbr_rows(year, cbr_manifest):
    pins = {s["file_name"]: s["sha256"] for s in cbr_manifest["samples"]}
    if year in PER_SEASON_FILES:
        name = PER_SEASON_FILES[year]
        raw = load_pinned(CBR_DIR / name, pins[name], name)
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    raw = load_pinned(CBR_DIR / "logs1520.csv", pins["logs1520.csv"],
                      "logs1520.csv")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    return [r for r in rows if r["season"] == SEASON_LABEL_CBR[year]]


def derive_cbr_fixtures(year, cbr_manifest, resolve):
    """Dedupe one season's CBR team-game rows to mirror-paired fixtures.

    Same derivation as PR #2871's proof, minus mirror inference (which
    fired zero times in the PR #2871 full derivation).
    Returns (fixtures, conflicts, stats): fixtures maps
    (date, pair) -> {slug: score}; conflicts holds (date, pair) keys
    whose mirror rows disagree on scores.
    """
    rows = load_cbr_rows(year, cbr_manifest)
    stats = {"team_rows_admitted_scope": len(rows),
             "team_slug_unresolved_rows": 0, "score_missing_rows": 0,
             "opponent_unresolved_rows": 0}
    parsed = []
    for row in rows:
        slug = resolve(row["Team"])
        if slug is None:
            stats["team_slug_unresolved_rows"] += 1
            continue
        try:
            team_score = int(row["TeamScore"])
            opp_score = int(row["OpponentScore"])
        except (TypeError, ValueError):
            stats["score_missing_rows"] += 1
            continue
        parsed.append({"date": row["Date"], "slug": slug,
                       "opp_surface": row["Opponent"],
                       "ts": team_score, "os": opp_score})
    by_key = defaultdict(list)
    for idx, p in enumerate(parsed):
        by_key[(p["date"], p["slug"])].append(idx)
    fixtures, conflicts, used = {}, set(), set()
    inconsistent = 0
    for i, p in enumerate(parsed):
        if i in used:
            continue
        opp_slug = resolve(p["opp_surface"])
        if opp_slug is None:
            stats["opponent_unresolved_rows"] += 1
            continue
        mirror_idx = None
        for j in by_key.get((p["date"], opp_slug), []):
            if j != i and resolve(parsed[j]["opp_surface"]) == p["slug"]:
                mirror_idx = j
                break
        if mirror_idx is None:
            continue
        q = parsed[mirror_idx]
        used.add(i)
        used.add(mirror_idx)
        pair = tuple(sorted((p["slug"], opp_slug)))
        key = (p["date"], pair)
        if q["ts"] == p["os"] and q["os"] == p["ts"]:
            scores = {p["slug"]: p["ts"], opp_slug: p["os"]}
            if key in fixtures and fixtures[key] != scores:
                conflicts.add(key)
                inconsistent += 1
            fixtures.setdefault(key, scores)
        else:
            conflicts.add(key)
            inconsistent += 1
    for key in conflicts:
        fixtures.pop(key, None)
    stats.update({"fixtures_derived": len(fixtures),
                  "rows_in_fixtures": len(used),
                  "single_or_unpaired_rows": len(parsed) - len(used),
                  "mirror_inconsistent_pairs": inconsistent,
                  "conflicted_fixture_keys": len(conflicts)})
    return fixtures, conflicts, stats


# ----------------------------------------------------------- hoopR leg

def load_hoopr_rows(year, hoopr_manifest):
    name = f"mbb_schedule_{year}.csv"
    pin = next(s for s in hoopr_manifest["samples"] if s["asset_name"] == name)
    raw = load_pinned(HOOPR_DIR / name, pin["sha256"], name)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


# ---------------------------------------------------------- Torvik leg

def fetch_torvik(date_iso, cache_dir):
    """Fetch (or read cached) the archive file for a YYYY-MM-DD date.

    Returns raw bytes, or None on HTTP 404 (archive file missing ->
    NO_DATA per the PR #2832 as-of rule). Files are addressed at the
    pinned commit, so cached bytes are commit-anchored.
    """
    stamp = date_iso.replace("-", "")
    path = cache_dir / f"ratings_archive_{stamp}.csv"
    if path.exists():
        return path.read_bytes()
    url = TORVIK_URL_PATTERN.format(date=stamp)
    req = urllib.request.Request(
        url, headers={"User-Agent": "sportsedge-cbb-team-totals-screen"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    path.write_bytes(raw)
    return raw


def parse_torvik(raw, date_iso, resolve):
    """Parse an archive file: slug -> (adj_o, adj_d, adj_tempo),
    plus league aggregates over the file as published."""
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    if not rows or any(r.get("date") != date_iso for r in rows):
        return None
    by_slug, collisions = {}, set()
    unresolved = 0
    adj_o_all, tempo_all = [], []
    for r in rows:
        try:
            adj_o = float(r["adj_o"])
            adj_d = float(r["adj_d"])
            tempo = float(r["adj_tempo"])
        except (TypeError, ValueError, KeyError):
            return None
        adj_o_all.append(adj_o)
        tempo_all.append(tempo)
        slug = resolve(r["team"])
        if slug is None:
            unresolved += 1
            continue
        if slug in by_slug and by_slug[slug] != (adj_o, adj_d, tempo):
            collisions.add(slug)
        by_slug[slug] = (adj_o, adj_d, tempo)
    return {"by_slug": by_slug, "collisions": collisions,
            "unresolved_team_surfaces": unresolved,
            "team_rows": len(rows),
            "league_mean_eff": sum(adj_o_all) / len(adj_o_all),
            "league_mean_tempo": sum(tempo_all) / len(tempo_all)}


# ------------------------------------------------------- premise audit

def record_of(row):
    """A row's W-L record under either published column name.

    The mirror's schema drifts (PR #2832 admission section 4):
    most files carry 'record'; some (e.g. 2022-11-07) carry 'rec'
    instead. The audit reads whichever the file publishes.
    """
    if row.get("record") is not None:
        return row.get("record")
    return row.get("rec")


def team_record(raw, team):
    if raw is None:
        return None
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        if row.get("team") == team:
            return record_of(row)
    return None


def opening_date(year, hoopr_manifest):
    """The season's first game date in the pinned hoopR substrate."""
    rows = load_hoopr_rows(year, hoopr_manifest)
    dates = [r["game_date"] for r in rows
             if r.get("status_type_completed") == "TRUE"]
    return min(dates)


def as_of_audit(hoopr_manifest, torvik_cache):
    """Probe the PR #2832 binding as-of rule (see module docstring).

    Returns (passed, declared_witnesses, opening_day_audit).
    """
    declared = []
    for date, team, expected in DECLARED_WITNESSES:
        raw = fetch_torvik(date, torvik_cache)
        declared.append({
            "case": f"{team} record in the {date} archive file",
            "expected_if_morning_of": expected,
            "observed": team_record(raw, team)})
    opening = []
    for year in range(2015, 2024):
        date = opening_date(year, hoopr_manifest)
        raw = fetch_torvik(date, torvik_cache)
        non_preseason = []
        record_column = None
        if raw is not None:
            for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
                if record_column is None:
                    record_column = ("record" if row.get("record") is not None
                                     else "rec")
                if record_of(row) != "0-0":
                    non_preseason.append(
                        {"team": row.get("team"), "record": record_of(row)})
        opening.append({
            "season": SEASON_LABEL[year],
            "opening_date": date,
            "record_column": record_column,
            "teams_in_file": (len(raw.decode("utf-8").splitlines()) - 1
                              if raw is not None else 0),
            "teams_not_0_0": len(non_preseason),
            "examples": non_preseason[:5],
            "expected_if_morning_of": 0})
    passed = (all(w["observed"] == w["expected_if_morning_of"]
                  for w in declared)
              and all(o["teams_not_0_0"] == o["expected_if_morning_of"]
                      for o in opening))
    return passed, declared, opening


# ------------------------------------------------------------ 1H check

def find_pbp_manifest(repo_root):
    """Scan the repo's manifests for a pinned CBB play-by-play asset.

    The 1H prerequisite (team-totals design section 2) is a hoopR
    PBP (load_mbb_pbp family) manifest pinned by the full-tuple rule
    with schema verification. Returns the list of manifest paths
    whose samples pin an asset naming the PBP family; empty when no
    such manifest exists.
    """
    hits = []
    for path in sorted((repo_root / "research").rglob("*manifest*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        samples = data.get("samples") if isinstance(data, dict) else None
        if not isinstance(samples, list):
            continue
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            name = str(sample.get("asset_name") or sample.get("file_name") or "")
            if "pbp" in name.lower() or "play_by_play" in name.lower():
                hits.append(str(path.relative_to(repo_root)))
                break
    return hits


# ---------------------------------------------------------------- main

def pins_block():
    return {
        "torvik": "PR #2832 pinned commit " + TORVIK_PINNED_COMMIT +
                  " (admission samples re-verified byte-identical "
                  "before use)",
        "hoopr": "PR #2867 successor manifest (18/18 assets "
                 "hash-verified before use)",
        "cbr": "PR #2871 successor manifest (6/6 files hash + size + "
               "git-blob verified before use; admitted scopes only)",
    }


def first_half_block(repo_root):
    found = find_pbp_manifest(repo_root)
    if found:
        return {"family": "CBB first-half lines (1H spread / 1H total)",
                "verdict": "PREREQUISITE_PRESENT — NOT RUN BY THIS PACKET",
                "pbp_manifests_found": found}
    return {
        "family": "CBB first-half lines (1H spread / 1H total)",
        "verdict": "NOT_EXECUTABLE",
        "refusal": {
            "code": "PBP_PREREQUISITE_MISSING",
            "detail": "CBB_TEAM_TOTALS_1H_DESIGN.md section 2 names "
                      "the prerequisite: hoopR play-by-play release "
                      "assets (load_mbb_pbp family) pinned by the "
                      "full-tuple rule of draft PR #2835 WITH schema "
                      "verification. No such manifest exists in the "
                      "repo (scan of research/**/*manifest*.json "
                      "samples: no PBP asset pinned). Until it lands, "
                      "the first-half share cannot be fitted and 1H "
                      "is not screenable. No share is borrowed from "
                      "the NBA fit, from a rule of thumb, or from "
                      "halving final scores.",
        },
    }


def is_illinois_fixture(home_surface, away_surface, home_slug, away_slug):
    """Design section 2 design-screen expedient: conservative
    over-exclusion — a fixture is refused if either side's surface
    names Illinois or resolves to an Illinois program's slug. The
    expedient can only remove games, never admit one."""
    return ("illinois" in home_surface.lower()
            or "illinois" in away_surface.lower()
            or home_slug in ILLINOIS_SLUGS
            or away_slug in ILLINOIS_SLUGS)


def build_universe(hoopr_manifest, cbr_manifest, resolve, torvik_cache):
    """Three-way fixture universe (design section 2). Mirrors the
    parent screen attempt-3 accounting on the same pinned bytes."""
    universe = {}
    season_log = {}
    torvik_dates_needed = {}

    for year in range(2015, 2024):
        log = {"season": SEASON_LABEL[year]}
        cbr_fixtures, cbr_conflicts, cbr_stats = derive_cbr_fixtures(
            year, cbr_manifest, resolve)
        log["cbr_derivation"] = cbr_stats
        rows = load_hoopr_rows(year, hoopr_manifest)
        log["hoopr_rows_total"] = len(rows)
        counts = defaultdict(int)
        illinois_surfaces = set()
        pending = []
        for row in rows:
            home_surface, away_surface = row["home_location"], row["away_location"]
            home_slug, away_slug = resolve(home_surface), resolve(away_surface)
            # Illinois exclusion FIRST (design section 2 expedient).
            if is_illinois_fixture(home_surface, away_surface,
                                   home_slug, away_slug):
                counts["illinois_excluded"] += 1
                for surface, slug in ((home_surface, home_slug),
                                      (away_surface, away_slug)):
                    if ("illinois" in surface.lower()
                            or slug in ILLINOIS_SLUGS):
                        illinois_surfaces.add(surface)
                continue
            try:
                home_score = int(row["home_score"])
                away_score = int(row["away_score"])
            except (TypeError, ValueError):
                counts["SCHEDULE_DISCREPANCY:HOOPR_SCORE_MISSING"] += 1
                continue
            if home_slug is None or away_slug is None:
                counts["SCHEDULE_DISCREPANCY:NAME_UNRESOLVED"] += 1
                continue
            date = row["game_date"]
            pair = tuple(sorted((home_slug, away_slug)))
            key = (date, pair)
            if key in cbr_conflicts:
                counts["SCHEDULE_DISCREPANCY:CBR_MIRROR_CONFLICT"] += 1
                continue
            if key not in cbr_fixtures:
                counts["SCHEDULE_DISCREPANCY:CBR_FIXTURE_NOT_FOUND"] += 1
                continue
            if cbr_fixtures[key] != {home_slug: home_score,
                                     away_slug: away_score}:
                counts["SCHEDULE_DISCREPANCY:SCORE_MISMATCH_CBR_VS_HOOPR"] += 1
                continue
            pending.append({"espn_game_id": row["id"], "date": date,
                            "home_slug": home_slug, "away_slug": away_slug,
                            "home_score": home_score, "away_score": away_score,
                            "neutral_site": row["neutral_site"] == "TRUE"})
            torvik_dates_needed.setdefault(date, None)
        log["illinois_excluded_team_surfaces"] = sorted(illinois_surfaces)
        log["agreement_counts_before_torvik"] = dict(counts)
        log["fixtures_passing_cbr_leg"] = len(pending)
        season_log[SEASON_LABEL[year]] = (log, pending)

    dates = sorted(torvik_dates_needed)
    with ThreadPoolExecutor(max_workers=10) as pool:
        raws = list(pool.map(lambda d: fetch_torvik(d, torvik_cache), dates))
    torvik_by_date = {}
    torvik_fetch_log = {"files_fetched_or_cached": 0, "files_missing_404": 0,
                        "files_schema_invalid": 0}
    for date, raw in zip(dates, raws):
        if raw is None:
            torvik_by_date[date] = None
            torvik_fetch_log["files_missing_404"] += 1
            continue
        parsed = parse_torvik(raw, date, resolve)
        if parsed is None:
            torvik_by_date[date] = None
            torvik_fetch_log["files_schema_invalid"] += 1
            continue
        torvik_by_date[date] = parsed
        torvik_fetch_log["files_fetched_or_cached"] += 1

    for year in range(2015, 2024):
        log, pending = season_log[SEASON_LABEL[year]]
        counts = defaultdict(int)
        agreed = []
        for fx in pending:
            tor = torvik_by_date[fx["date"]]
            if tor is None:
                counts["SCHEDULE_DISCREPANCY:TORVIK_MORNING_OF_NO_DATA"] += 1
                continue
            home_row = tor["by_slug"].get(fx["home_slug"])
            away_row = tor["by_slug"].get(fx["away_slug"])
            if (home_row is None or away_row is None
                    or fx["home_slug"] in tor["collisions"]
                    or fx["away_slug"] in tor["collisions"]):
                counts["SCHEDULE_DISCREPANCY:TORVIK_TEAM_NOT_CARRIED"] += 1
                continue
            fx.update({
                "adj_o_home": home_row[0], "adj_d_home": home_row[1],
                "tempo_home": home_row[2],
                "adj_o_away": away_row[0], "adj_d_away": away_row[1],
                "tempo_away": away_row[2],
                "league_mean_eff": tor["league_mean_eff"],
                "league_mean_tempo": tor["league_mean_tempo"],
            })
            agreed.append(fx)
        log["agreement_counts_torvik_leg"] = dict(counts)
        log["fixtures_agreed_three_way"] = len(agreed)
        universe[year] = agreed
    return universe, season_log, torvik_fetch_log


def score_team_points(universe):
    """Walk-forward team-points scoring (the third leg).

    Scored seasons 2015-16 -> 2022-23; the naive team-mean history
    for a scored season is the agreed fixtures of seasons strictly
    before it (2014-15 is the initial window, never scored). The
    candidate and the simple baseline carry no fitted parameters
    on this leg — their walk-forward discipline is the morning-of
    ratings rule itself.
    """
    per_season = {}
    diffs = {"vs_naive": defaultdict(list), "vs_simple": defaultdict(list)}
    for year in tt.SCORED_YEARS:
        prior = [fx for y in range(tt.FIRST_WINDOW_YEAR, year)
                 for fx in universe[y]]
        team_mean, league_fallback = tt.naive_team_mean(prior)
        errs = {"candidate": [], "naive": [], "simple": []}
        for fx in universe[year]:
            for obs in tt.team_game_errors(fx, team_mean, league_fallback):
                errs["candidate"].append(obs["candidate_err"])
                errs["naive"].append(obs["naive_err"])
                errs["simple"].append(obs["simple_err"])
                label = SEASON_LABEL[year]
                diffs["vs_naive"][label].append(
                    obs["candidate_err"] - obs["naive_err"])
                diffs["vs_simple"][label].append(
                    obs["candidate_err"] - obs["simple_err"])
        per_season[SEASON_LABEL[year]] = {
            "fixtures_scored": len(universe[year]),
            "team_games_scored": len(errs["candidate"]),
            "mae": {m: tt.mae(v) for m, v in errs.items()},
            "naive_fit_window_fixtures": len(prior),
        }
    pooled = {}
    for model in ("candidate", "naive", "simple"):
        total, n = 0.0, 0
        for year in tt.SCORED_YEARS:
            label = SEASON_LABEL[year]
            total += (per_season[label]["mae"][model]
                      * per_season[label]["team_games_scored"])
            n += per_season[label]["team_games_scored"]
        pooled[f"{model}_team_points_mae"] = total / n
    pooled["team_games_scored_total"] = sum(
        per_season[SEASON_LABEL[y]]["team_games_scored"]
        for y in tt.SCORED_YEARS)
    criteria = {}
    for name, key in (("team_points_vs_naive_team_mean", "vs_naive"),
                      ("team_points_vs_simple_ratings_baseline", "vs_simple")):
        boot = tt.season_block_bootstrap(diffs[key])
        criteria[name] = {**boot, "criterion": "CI upper bound < 0",
                          "pass": tt.leg_criterion(boot)}
    return per_season, pooled, criteria


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--torvik-cache", default=str(
        Path.home() / "workspace/cbb_team_totals_run_20261028/torvik_cache"))
    parser.add_argument("--out", default=str(PACKET / "screen_result.json"))
    args = parser.parse_args()
    torvik_cache = Path(args.torvik_cache)
    torvik_cache.mkdir(parents=True, exist_ok=True)

    hoopr_manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    cbr_manifest = json.loads(CBR_MANIFEST_PATH.read_text(encoding="utf-8"))

    pin_counts = verify_all_pins(hoopr_manifest, cbr_manifest, torvik_cache)

    # ------------------------- AS-OF PREMISE AUDIT (before any fitting)
    passed, declared, opening = as_of_audit(hoopr_manifest, torvik_cache)
    if not passed:
        result = {
            "screen": "CBB team totals — third leg of the "
                      "CBB_TORVIK_EFFICIENCY_V1 design screen",
            "design_reference": "PR #2843 CBB_TEAM_TOTALS_1H_DESIGN.md "
                                "section 1; CBB_SIDES_TOTALS_DESIGN_AND_"
                                "PREREG_DRAFT.md sections 1-3",
            "evidence_class": "DESIGN EVIDENCE ONLY — not validation",
            "family": "CBB team totals",
            "verdict": "NOT_EXECUTABLE",
            "refusal": {
                "code": "AS_OF_PREMISE_FAILURE",
                "detail": "The PR #2832 pinned Torvik archive files "
                          "are end-of-day, not morning-of: the file "
                          "for D already reflects games played on D, "
                          "contradicting design section 1 and the "
                          "admission's as-of rule 2. The team-totals "
                          "leg reads the same expected team points "
                          "from the same files, so the failure is "
                          "identical for this family. No fitting or "
                          "scoring was performed. Governed unblocks: "
                          "a design amendment declaring the input "
                          "convention (admission rule 4) with its own "
                          "review, or an admitted genuinely "
                          "morning-of source.",
                "declared_witnesses": declared,
                "opening_day_audit": opening,
            },
            "pins": pins_block(),
            "pin_verification_counts": pin_counts,
            "criteria": {
                name: {"result": "NOT_RUN",
                       "reason": "AS_OF_PREMISE_FAILURE — scoring "
                                 "refused before any fitting"}
                for name in ("team_points_vs_naive_team_mean",
                             "team_points_vs_simple_ratings_baseline")},
            "first_half": first_half_block(REPO_ROOT),
            "market_baseline_note": "The design names no market "
                                    "baseline for this family's design "
                                    "screen; the market leg (CLV/ROI "
                                    "vs forward DK captures) is a "
                                    "forward term gated on a freeze "
                                    "that does not exist.",
        }
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                                  encoding="utf-8")
        print(json.dumps({"verdict": "NOT_EXECUTABLE",
                          "refusal": "AS_OF_PREMISE_FAILURE",
                          "declared_witnesses_failed":
                          sum(1 for w in declared
                              if w["observed"] != w["expected_if_morning_of"]),
                          "seasons_failing_opening_day_audit":
                          sum(1 for o in opening if o["teams_not_0_0"] != 0)},
                         indent=1))
        return 2

    # ------------------------------ scoring path (premise holds)
    resolve = build_resolver(cbr_manifest)
    universe, season_log, torvik_fetch_log = build_universe(
        hoopr_manifest, cbr_manifest, resolve, torvik_cache)
    per_season, pooled, criteria = score_team_points(universe)
    design_pass = all(c["pass"] for c in criteria.values())
    result = {
        "screen": "CBB team totals — third leg of the "
                  "CBB_TORVIK_EFFICIENCY_V1 design screen",
        "design_reference": "PR #2843 CBB_TEAM_TOTALS_1H_DESIGN.md "
                            "section 1; CBB_SIDES_TOTALS_DESIGN_AND_"
                            "PREREG_DRAFT.md sections 1-3",
        "evidence_class": "DESIGN EVIDENCE ONLY — not validation",
        "family": "CBB team totals",
        "pins": pins_block(),
        "pin_verification_counts": pin_counts,
        "torvik_fetch_log": torvik_fetch_log,
        "fixture_universe_by_season": {
            SEASON_LABEL[y]: season_log[SEASON_LABEL[y]][0]
            for y in range(2015, 2024)},
        "per_season_mae": per_season,
        "pooled_mae": pooled,
        "criteria": criteria,
        "verdict": "DESIGN_PASS" if design_pass else "DESIGN_FAIL",
        "verdict_rule": "The leg passes or fails on its own CI "
                        "(team-totals design section 1): CI upper "
                        "bound < 0 against BOTH baselines on the "
                        "team-points leg.",
        "first_half": first_half_block(REPO_ROOT),
        "market_baseline_note": "The design names no market baseline "
                                "for this family's design screen.",
    }
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                              encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "pooled_mae": pooled,
                      "criteria_upper_bounds":
                      {k: v["ci95_upper"] for k, v in criteria.items()}},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
