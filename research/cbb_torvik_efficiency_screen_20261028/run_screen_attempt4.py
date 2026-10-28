#!/usr/bin/env python3
"""CBB_TORVIK_EFFICIENCY_V1 design screen — ATTEMPT 4 (the run).

Executes the screen specified in research/nba_cbb_activation_20261028/
CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md section 3, AS AMENDED by
AMENDMENT_1.md in that directory (merged PR #2883): the PRIOR-SNAPSHOT
convention. For games played on date D, the model's BartTorvik input
is the archive file dated D-1 — the last end-of-day snapshot strictly
before D. If the file dated D-1 does not exist on the admitted route,
the fixture is NO_DATA — never substituted from D-2 or D (fail-closed).
Every other term of the design is unchanged: same construction,
same baselines, same screen criteria, same seasons, same section 2
three-way fixture gate structure, same Illinois-college exclusion.
Attempt 3 (run_screen_attempt3.py, SCREEN_REPORT_ATTEMPT3.md) is
left unedited as its attempt's record; it returned NOT_EXECUTABLE —
AS_OF_PREMISE_FAILURE because the archive files are END-OF-DAY, not
morning-of. Amendment 1's witness probes verified the D-1 side
19/19 — PRIOR_SNAPSHOT_VERIFIED — before this attempt was run.

Data legs (all pinned, hash-verified before use):
  (a) BartTorvik T-Rank archive files at the PR #2832 pinned commit
      (46d1036443ca452fdd1c6cf25cf5dff50de68337), read under the
      prior-snapshot convention above;
  (b) hoopR schedule substrate via the PR #2867 successor manifest;
  (c) College Basketball Reference game logs via the PR #2871 mirror
      successor manifest (admitted scopes ONLY: logs1520.csv for
      2014-15 -> 2017-18, 2018-19 from logs19.csv, per-season after).

Fixture universe (design section 2): the Illinois-college exclusion
is applied FIRST; a fixture then enters ONLY on three-way agreement
— hoopR (ESPN game ID, date, teams, final score), Torvik (the
prior-snapshot file for the game date exists on the admitted route
and carries both teams — Amendment 1 section 5), CBR mirror (same
fixture, same date, same final score). Every disagreement is
excluded and logged as SCHEDULE_DISCREPANCY with a reason code.

Name resolution is table-driven and uses ONLY the PR #2871 published
NORMALIZATION_OVERRIDES table (41 entries) plus the legs' own surface
tables harvested from the pinned bytes. No new normalization is
invented: a fixture needing a mapping the published table lacks is
excluded and logged (the attempt-3 selection disclosure carries
unchanged — the agreed universe is the name-stable subset).

Construction (design section 1), exactly as specified:
  expected possessions = blend (arithmetic mean — attempt-3 reading 2)
    of the two teams' adj_tempo, each from the prior-snapshot file;
  expected team points = (team adj_o + opponent adj_d - league mean
    efficiency) / 100 * expected possessions, with the league mean
    over the prior-snapshot file as published (reading 3);
  margin = expected-points difference + home-court term (zero for
    neutral-site fixtures, venue flag from the hoopR substrate);
  game total = sum of expected team points.
Parameters fitted strictly walk-forward on seasons before the scored
season; 2014-15 is the initial fitting window and is not scored
(reading 1). Baselines: (i) naive league-mean (prior seasons' mean
actual margin / mean actual total); (ii) the section 1 simple
ratings baseline — same formula with league-mean tempo and a FIXED
home-court constant estimated once on the 2014-15 window (reading 4).

Metrics: spread MAE and total MAE, candidate vs both baselines,
paired per fixture; season-block bootstrap (10,000 resamples of the
scored seasons, seed 20261028), percentile 95% CI on the mean paired
difference. DESIGN PASS = CI upper bound < 0 against BOTH baselines
on BOTH legs (all four criteria). A failure of any criterion is
recorded FAILED_SCREEN (the design's DESIGN_FAIL). No criterion,
threshold, or leg was edited, lowered, or reinterpreted for this
attempt; attempt 3's ten recorded readings are inherited unchanged
except where Amendment 1 supersedes a vintage assumption.

Drift-schema window (Amendment 1 section 5): the archive files for
2022-11-06/07/08/09 use a drift layout with NO adj_tempo column.
Under the convention the files actually read for game dates
2022-11-07..10 are exactly those four files, so fixtures on those
game dates are NO_DATA (a totals input cannot be supplied) — the
attempt-3 NO_DATA treatment, shifted one day as the amendment
declares. No tempo is substituted or imputed.

PRIOR-SNAPSHOT GUARD: before any fitting or scoring, this runner
re-probes the convention's declared witnesses on the D-1 side
(prior_snapshot_probe): Duke / Kentucky / Wisconsin must show 0-0
in the 2014-11-13 file (their openers were played ON 2014-11-14),
and Purdue must show 28-5 in the 2023-03-11 file (the Big Ten final
was played ON 2023-03-12 at 28-5 before the game). While the probe
fails the runner refuses with PRIOR_SNAPSHOT_PREMISE_FAILURE after
building the (leak-free) fixture universe, before any fitting.

Stdlib only. Exit codes: 0 = screen ran (verdict in the output JSON);
2 = an input pin refused or the prior-snapshot guard failed.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import random
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date as _date, timedelta as _timedelta
from concurrent.futures import ThreadPoolExecutor
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
TORVIK_ADMISSION_SAMPLES = {
    "20220113": ("4de4761caf3f581c56d9587ac9deeb954556ee5a8529948d8ef5206f9dfe14ad",
                 58716, 358),
    "20230312": ("9524481d69c7b690200299387690654091565ef1d3df774ca858749e5e1cc01c",
                 60010, 363),
}

PER_SEASON_FILES = {2019: "logs19.csv", 2020: "logs20.csv",
                    2021: "logs21.csv", 2022: "logs22.csv",
                    2023: "logs23.csv"}
SEASON_LABEL = {2015: "2014-15", 2016: "2015-16", 2017: "2016-17",
                2018: "2017-18", 2019: "2018-19", 2020: "2019-20",
                2021: "2020-21", 2022: "2021-22", 2023: "2022-23"}
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

BOOTSTRAP_REPS = 10000
BOOTSTRAP_SEED = 20261028


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


def prior_date_iso(date_iso):
    """The prior-snapshot file date for a game date: D-1 (Amendment 1).

    Pure calendar arithmetic on the ISO game date; never a
    substitution chain — the caller treats a missing D-1 file as
    NO_DATA and never falls back to D-2 or D.
    """
    return (_date.fromisoformat(date_iso) - _timedelta(days=1)).isoformat()


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
    """Fetch (or read cached) the archive file for a YYYY-MM-DD FILE date.

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
        url, headers={"User-Agent": "sportsedge-design-screen-attempt4"})
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
    """Parse one archive file (addressed by its own FILE date): slug -> (adj_o, adj_d, adj_tempo),
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


# ------------------------------------------------------- model pieces

def expected_points(adj_o, adj_d_opp, league_mean_eff, possessions):
    return (adj_o + adj_d_opp - league_mean_eff) / 100.0 * possessions


def candidate_points(fx):
    poss = (fx["tempo_home"] + fx["tempo_away"]) / 2.0
    pts_home = expected_points(fx["adj_o_home"], fx["adj_d_away"],
                               fx["league_mean_eff"], poss)
    pts_away = expected_points(fx["adj_o_away"], fx["adj_d_home"],
                               fx["league_mean_eff"], poss)
    return pts_home, pts_away


def baseline_points(fx):
    poss = fx["league_mean_tempo"]
    pts_home = expected_points(fx["adj_o_home"], fx["adj_d_away"],
                               fx["league_mean_eff"], poss)
    pts_away = expected_points(fx["adj_o_away"], fx["adj_d_home"],
                               fx["league_mean_eff"], poss)
    return pts_home, pts_away


def fit_logistic_map(pairs):
    """Logistic P(home win) = sigmoid(a + b * predicted margin),
    Newton-Raphson on (a, b). pairs = [(margin, home_win_bool)]."""
    a, b = 0.0, 0.1
    for _ in range(100):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in pairs:
            z = a + b * x
            p = 1.0 / (1.0 + math.exp(-z)) if z > -35 else 0.0
            w = p * (1.0 - p)
            d = (1.0 if y else 0.0) - p
            ga += d
            gb += d * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a += da
        b += db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    return a, b


def prior_snapshot_probe(torvik_cache):
    """Declared-witness probe of the PRIOR-SNAPSHOT convention.

    Amendment 1 (PR #2883) declares: for games on date D, the model's
    Torvik input is the archive file dated D-1 — the last end-of-day
    snapshot strictly before D. The convention's witnesses (dates and
    results from the pinned hoopR substrate; the same games attempt 3
    used against file D):
      - Duke / Kentucky / Wisconsin played their openers ON
        2014-11-14, so the D-1 file (2014-11-13, preseason) must
        show each at 0-0;
      - Purdue entered the Big Ten final ON 2023-03-12 at 28-5 and
        won it (29-5 after), so the D-1 file (2023-03-11) must
        show 28-5.
    Returns (passed, witnesses). This is the D-1 side of attempt 3's
    failed morning-of probe; Amendment 1's full probe suite (19/19,
    PRIOR_SNAPSHOT_VERIFIED) is the amendment's own record.
    """
    def team_record(file_date_iso, team):
        raw = fetch_torvik(file_date_iso, torvik_cache)
        if raw is None:
            return None
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            if row.get("team") == team:
                return row.get("record") or row.get("rec")
        return None

    witnesses = []
    for team in ("Duke", "Kentucky", "Wisconsin"):
        witnesses.append({
            "case": f"{team} record in the 2014-11-13 archive file "
                    f"(the D-1 prior snapshot for games on 2014-11-14)",
            "expected_if_prior_snapshot": "0-0",
            "observed": team_record("2014-11-13", team)})
    witnesses.append({
        "case": "Purdue record in the 2023-03-11 archive file "
                "(the D-1 prior snapshot for games on 2023-03-12)",
        "expected_if_prior_snapshot": "28-5",
        "observed": team_record("2023-03-11", "Purdue")})
    passed = all(w["observed"] == w["expected_if_prior_snapshot"]
                 for w in witnesses)
    return passed, witnesses


def season_block_bootstrap(diffs_by_season):
    """Percentile 95% CI for the pooled mean paired difference,
    resampling scored seasons (blocks) with replacement. Computed
    from per-season (sum, n) aggregates — algebraically identical to
    resampling the pooled fixture diffs block-wise."""
    seasons = sorted(diffs_by_season)
    agg = {s: (sum(diffs_by_season[s]), len(diffs_by_season[s]))
           for s in seasons}
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        total, n = 0.0, 0
        for _ in seasons:
            block_sum, block_n = agg[rng.choice(seasons)]
            total += block_sum
            n += block_n
        means.append(total / n)
    means.sort()
    lo = means[int(0.025 * BOOTSTRAP_REPS)]
    hi = means[min(BOOTSTRAP_REPS - 1, int(0.975 * BOOTSTRAP_REPS))]
    pooled = [d for s in seasons for d in diffs_by_season[s]]
    return {"mean_paired_diff": sum(pooled) / len(pooled),
            "ci95_lower": lo, "ci95_upper": hi,
            "reps": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED,
            "blocks": len(seasons)}


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--torvik-cache", default=str(
        Path.home() / "workspace/cbb-screen-attempt4-20261028/torvik_cache"))
    parser.add_argument("--out", default=str(
        PACKET / "screen_result_attempt4.json"))
    args = parser.parse_args()
    torvik_cache = Path(args.torvik_cache)
    torvik_cache.mkdir(parents=True, exist_ok=True)

    hoopr_manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    cbr_manifest = json.loads(CBR_MANIFEST_PATH.read_text(encoding="utf-8"))

    verify_all_pins(hoopr_manifest, cbr_manifest, torvik_cache)
    resolve = build_resolver(cbr_manifest)

    universe = {}          # season year -> [fixture dicts]
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
            if ("illinois" in home_surface.lower()
                    or "illinois" in away_surface.lower()
                    or home_slug in ILLINOIS_SLUGS
                    or away_slug in ILLINOIS_SLUGS):
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

    # Torvik leg (AMENDED — Amendment 1 prior-snapshot convention):
    # for game date D the input file is dated D-1. Fetch every needed
    # D-1 file in parallel; a missing D-1 file makes its fixtures
    # NO_DATA — never substituted from D-2 or D (fail-closed).
    file_dates = sorted({prior_date_iso(d) for d in torvik_dates_needed})
    with ThreadPoolExecutor(max_workers=10) as pool:
        raws = list(pool.map(lambda d: fetch_torvik(d, torvik_cache),
                             file_dates))
    torvik_by_file_date = {}
    torvik_fetch_log = {"convention": "PRIOR_SNAPSHOT (Amendment 1): "
                        "Torvik input for game date D is the archive "
                        "file dated D-1",
                        "game_dates_needing_input": len(torvik_dates_needed),
                        "prior_snapshot_files_needed": len(file_dates),
                        "files_fetched_or_cached": 0,
                        "files_missing_404": 0,
                        "files_schema_invalid": 0}
    for fdate, raw in zip(file_dates, raws):
        if raw is None:
            torvik_by_file_date[fdate] = None
            torvik_fetch_log["files_missing_404"] += 1
            continue
        parsed = parse_torvik(raw, fdate, resolve)
        if parsed is None:
            torvik_by_file_date[fdate] = None
            torvik_fetch_log["files_schema_invalid"] += 1
            continue
        torvik_by_file_date[fdate] = parsed
        torvik_fetch_log["files_fetched_or_cached"] += 1
    # Keyed by GAME date for the fixture loop below: the value is the
    # parsed D-1 file for that game date (None = NO_DATA).
    torvik_by_date = {d: torvik_by_file_date.get(prior_date_iso(d))
                      for d in torvik_dates_needed}

    for year in range(2015, 2024):
        log, pending = season_log[SEASON_LABEL[year]]
        counts = defaultdict(int)
        agreed = []
        for fx in pending:
            tor = torvik_by_date[fx["date"]]
            if tor is None:
                counts["SCHEDULE_DISCREPANCY:TORVIK_PRIOR_SNAPSHOT_NO_DATA"] += 1
                continue
            home_row = tor["by_slug"].get(fx["home_slug"])
            away_row = tor["by_slug"].get(fx["away_slug"])
            if (home_row is None or away_row is None
                    or fx["home_slug"] in tor["collisions"]
                    or fx["away_slug"] in tor["collisions"]):
                counts["SCHEDULE_DISCREPANCY:TORVIK_TEAM_NOT_CARRIED"] += 1
                continue
            fx.update({
                "torvik_file_date": prior_date_iso(fx["date"]),
                "adj_o_home": home_row[0], "adj_d_home": home_row[1],
                "tempo_home": home_row[2],
                "adj_o_away": away_row[0], "adj_d_away": away_row[1],
                "tempo_away": away_row[2],
                "league_mean_eff": tor["league_mean_eff"],
                "league_mean_tempo": tor["league_mean_tempo"],
                "margin_actual": fx["home_score"] - fx["away_score"],
                "total_actual": fx["home_score"] + fx["away_score"],
            })
            agreed.append(fx)
        log["agreement_counts_torvik_leg"] = dict(counts)
        log["fixtures_agreed_three_way"] = len(agreed)
        universe[year] = agreed

    # --------------------------------- PRIOR-SNAPSHOT GUARD (attempt 4)
    # The fixture universe above is leak-free accounting (the gate
    # never touches ratings). Before ANY fitting or scoring, probe
    # the amended convention's declared witnesses on the D-1 side.
    # Amendment 1's own probe suite verified the convention 19/19
    # (PRIOR_SNAPSHOT_VERIFIED); this guard re-checks the attempt-3
    # witness games against the files this run actually reads. While
    # it fails, scoring is refused — no substitution, no tuning.
    ps_passed, ps_witnesses = prior_snapshot_probe(torvik_cache)
    if not ps_passed:
        result = {
            "screen": "CBB_TORVIK_EFFICIENCY_V1 design screen — ATTEMPT 4",
            "design_reference": "PR #2843 "
                                "CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md "
                                "sections 1-3, as amended by AMENDMENT_1.md "
                                "(PR #2883) — prior-snapshot convention",
            "evidence_class": "DESIGN EVIDENCE ONLY — not validation",
            "verdict": "NOT_EXECUTABLE",
            "refusal": {
                "code": "PRIOR_SNAPSHOT_PREMISE_FAILURE",
                "detail": "The prior-snapshot witness probe failed on "
                          "the pinned bytes: the D-1 archive files do "
                          "not show the entering records the convention "
                          "requires. No fitting or scoring was "
                          "performed.",
                "witnesses": ps_witnesses,
            },
            "pins": {
                "torvik": "PR #2832 pinned commit " + TORVIK_PINNED_COMMIT +
                          " (admission samples re-verified "
                          "byte-identical before use; read under the "
                          "Amendment 1 prior-snapshot convention)",
                "hoopr": "PR #2867 successor manifest (18/18 assets "
                         "hash-verified before use)",
                "cbr": "PR #2871 successor manifest (6/6 files hash + "
                       "size + git-blob verified before use; admitted "
                       "scopes only)",
            },
            "torvik_fetch_log": torvik_fetch_log,
            "fixture_universe_by_season": {
                SEASON_LABEL[y]: season_log[SEASON_LABEL[y]][0]
                for y in range(2015, 2024)},
            "criteria": {
                name: {"result": "NOT_RUN",
                       "reason": "PRIOR_SNAPSHOT_PREMISE_FAILURE — "
                                 "scoring refused before any fitting"}
                for name in ("spread_vs_naive_league_mean",
                             "spread_vs_simple_ratings_baseline",
                             "total_vs_naive_league_mean",
                             "total_vs_simple_ratings_baseline")},
        }
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                                  encoding="utf-8")
        print(json.dumps({"verdict": "NOT_EXECUTABLE",
                          "refusal": "PRIOR_SNAPSHOT_PREMISE_FAILURE",
                          "witnesses": ps_witnesses,
                          "agreed_by_season":
                          {SEASON_LABEL[y]: len(universe[y])
                           for y in range(2015, 2024)}}, indent=1))
        return 2


    # ------------------------------------------- walk-forward scoring
    scored_years = list(range(2016, 2024))
    # Fixed baseline home-court constant: estimated ONCE on 2014-15.
    def neutral_margin_c(fx):
        pts_home, pts_away = candidate_points(fx)
        return pts_home - pts_away

    window_2015 = universe[2015]
    hc_fixed = (sum(fx["margin_actual"] - neutral_margin_c(fx)
                    for fx in window_2015 if not fx["neutral_site"])
                / max(1, sum(1 for fx in window_2015
                             if not fx["neutral_site"])))

    per_season = {}
    diffs = {"spread_vs_naive": defaultdict(list),
             "spread_vs_simple": defaultdict(list),
             "total_vs_naive": defaultdict(list),
             "total_vs_simple": defaultdict(list)}
    fitted = {}
    for year in scored_years:
        prior = [fx for y in range(2015, year) for fx in universe[y]]
        non_neutral = [fx for fx in prior if not fx["neutral_site"]]
        hc = (sum(fx["margin_actual"] - neutral_margin_c(fx)
                  for fx in non_neutral) / len(non_neutral))
        naive_margin = sum(fx["margin_actual"] for fx in prior) / len(prior)
        naive_total = sum(fx["total_actual"] for fx in prior) / len(prior)
        map_pairs = []
        for fx in prior:
            m = neutral_margin_c(fx) + (0.0 if fx["neutral_site"] else hc)
            map_pairs.append((m, fx["margin_actual"] > 0))
        map_a, map_b = fit_logistic_map(map_pairs)
        fitted[SEASON_LABEL[year]] = {
            "home_court_term_candidate": hc,
            "home_court_constant_simple_baseline_fixed": hc_fixed,
            "naive_margin_mean": naive_margin,
            "naive_total_mean": naive_total,
            "ml_map_intercept": map_a, "ml_map_slope": map_b,
            "fit_window_fixtures": len(prior),
        }
        errs = {"candidate": {"spread": [], "total": []},
                "naive": {"spread": [], "total": []},
                "simple": {"spread": [], "total": []}}
        for fx in universe[year]:
            pts_hc, pts_ac = candidate_points(fx)
            margin_c = (pts_hc - pts_ac) + (0.0 if fx["neutral_site"] else hc)
            total_c = pts_hc + pts_ac
            pts_hb, pts_ab = baseline_points(fx)
            margin_b = (pts_hb - pts_ab) + (0.0 if fx["neutral_site"]
                                            else hc_fixed)
            total_b = pts_hb + pts_ab
            e = {
                "candidate": (abs(margin_c - fx["margin_actual"]),
                              abs(total_c - fx["total_actual"])),
                "naive": (abs(naive_margin - fx["margin_actual"]),
                          abs(naive_total - fx["total_actual"])),
                "simple": (abs(margin_b - fx["margin_actual"]),
                           abs(total_b - fx["total_actual"])),
            }
            for model in errs:
                errs[model]["spread"].append(e[model][0])
                errs[model]["total"].append(e[model][1])
            label = SEASON_LABEL[year]
            diffs["spread_vs_naive"][label].append(
                e["candidate"][0] - e["naive"][0])
            diffs["spread_vs_simple"][label].append(
                e["candidate"][0] - e["simple"][0])
            diffs["total_vs_naive"][label].append(
                e["candidate"][1] - e["naive"][1])
            diffs["total_vs_simple"][label].append(
                e["candidate"][1] - e["simple"][1])
        mae = {model: {leg: sum(v) / len(v) for leg, v in legs.items()}
               for model, legs in errs.items()}
        per_season[SEASON_LABEL[year]] = {
            "fixtures_scored": len(universe[year]), "mae": mae}

    pooled = {}
    for model in ("candidate", "naive", "simple"):
        for leg in ("spread", "total"):
            vals = []
            for year in scored_years:
                vals.append(per_season[SEASON_LABEL[year]]["mae"][model][leg]
                            * per_season[SEASON_LABEL[year]]["fixtures_scored"])
            n = sum(per_season[SEASON_LABEL[year]]["fixtures_scored"]
                    for year in scored_years)
            pooled[f"{model}_{leg}_mae"] = sum(vals) / n
    pooled["fixtures_scored_total"] = sum(
        per_season[SEASON_LABEL[year]]["fixtures_scored"]
        for year in scored_years)

    criteria = {}
    for name, key in (("spread_vs_naive_league_mean", "spread_vs_naive"),
                      ("spread_vs_simple_ratings_baseline", "spread_vs_simple"),
                      ("total_vs_naive_league_mean", "total_vs_naive"),
                      ("total_vs_simple_ratings_baseline", "total_vs_simple")):
        boot = season_block_bootstrap(diffs[key])
        criteria[name] = {**boot, "criterion": "CI upper bound < 0",
                          "pass": boot["ci95_upper"] < 0}
    design_pass = all(c["pass"] for c in criteria.values())

    result = {
        "screen": "CBB_TORVIK_EFFICIENCY_V1 design screen — ATTEMPT 4",
        "design_reference": "PR #2843 CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md "
                            "sections 1-3, as amended by AMENDMENT_1.md "
                            "(PR #2883) — prior-snapshot convention",
        "evidence_class": "DESIGN EVIDENCE ONLY — not validation",
        "pins": {
            "torvik": "PR #2832 pinned commit " + TORVIK_PINNED_COMMIT +
                      " (admission samples re-verified byte-identical "
                      "before use; read under the Amendment 1 "
                      "prior-snapshot convention)",
            "hoopr": "PR #2867 successor manifest (18/18 assets "
                     "hash-verified before use)",
            "cbr": "PR #2871 successor manifest (6/6 files hash + size + "
                   "git-blob verified before use; admitted scopes only)",
        },
        "torvik_fetch_log": torvik_fetch_log,
        "prior_snapshot_probe": {"passed": ps_passed,
                                 "witnesses": ps_witnesses,
                                 "amendment_suite": "AMENDMENT_1.md "
                                 "probe suite: 19/19 PASS — "
                                 "PRIOR_SNAPSHOT_VERIFIED (PR #2883)"},
        "fixture_universe_by_season": {
            SEASON_LABEL[y]: season_log[SEASON_LABEL[y]][0]
            for y in range(2015, 2024)},
        "fitted_parameters_by_scored_season": fitted,
        "per_season_mae": per_season,
        "pooled_mae": pooled,
        "criteria": criteria,
        "verdict": "DESIGN_PASS" if design_pass else "FAILED_SCREEN",
        "verdict_rule": "Design pass = CI upper bound < 0 against BOTH "
                        "baselines on BOTH legs (all four criteria); "
                        "any failure is recorded FAILED_SCREEN (the "
                        "design's DESIGN_FAIL).",
    }
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                              encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"],
                      "pooled_mae": pooled,
                      "criteria_upper_bounds":
                      {k: v["ci95_upper"] for k, v in criteria.items()},
                      "agreed_by_season":
                      {SEASON_LABEL[y]: len(universe[y])
                       for y in range(2015, 2024)}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
