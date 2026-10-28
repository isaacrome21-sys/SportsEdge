#!/usr/bin/env python3
"""Fixture-derivation + three-way agreement proof for the CBR mirror pin.

Companion to successor_manifest.json in this directory (the College
Basketball Reference third leg of the CBB_TORVIK_EFFICIENCY_V1 design
screen, PR #2843 section 2). This script does NOT run the section 3
screen. It proves the pinned CBR mirror bytes can serve as the third
leg, in three steps:

  1. VERIFY every input byte stream against its pin before use: the
     six CBR files against this packet's successor_manifest.json, the
     nine hoopR schedule CSVs against the PR #2867 successor manifest.
     Any drift is a refusal (exit 2), never silent acceptance.
  2. DERIVE fixtures from the CBR team-game rows: resolve each row's
     school to the canonical CBR school slug, dedupe mirror rows
     (one fixture = two team rows with swapped scores) and count what
     does not pair (non-D1 opponents, missing scores, unresolved
     names). Mirror pairs whose scores disagree are discrepancies,
     never silently resolved (design section 2 semantics).
  3. CHECK a declared sample three ways per fixture: CBR-derived
     fixture (date, teams, final scores) vs hoopR substrate (same
     fixture, same date, same final score, ESPN game id recorded) vs
     a morning-of Torvik archive file at the PR #2832 pinned commit
     (file exists for that date and carries both teams). Sample: for
     each of the nine design seasons, the national championship game
     plus the lexicographically-first derived fixture on the season's
     early and mid probe dates (the dates PR #2866's precondition
     check verified against the Torvik route, 26/26). The 2019-20
     season has no championship game (COVID-19 cancellation — the
     true record); its third sample fixture is the late-probe-date
     fixture instead, declared as such.

Name normalization is explicit and table-driven. Canonical keys are
CBR's own school slugs (the /cbb/schools/<slug>/ path each per-season
row carries). Surface -> slug resolution order: (i) the literal
NORMALIZATION_OVERRIDES table below — every non-obvious surface the
sample or the derivation encounters, published here in full; (ii) the
Team / TeamFull surface tables harvested from the pinned per-season
bytes themselves (CBR's own name forms); (iii) mirror inference — an
unresolved opponent surface that appears in exactly one mirror pair
inherits the mirror row's school, and every such resolution is
published in the result JSON as evidence (the design section 2
audited name-join for design evidence only). A surface resolved by
none of these leaves its fixture out of the derived universe and is
counted, never guessed.

Local data layout (bytes live OUTSIDE the repo; the repo stores
hashes, manifests and code only):
  --cbr-dir    the six pinned CBR files (default: the admission
               workspace ~/workspace/cbb-cbr-successor-admission-20261028/pulls)
  --hoopr-dir  the nine pinned hoopR schedule CSVs (default: the
               PR #2867 admission workspace
               ~/workspace/cbb-successor-admission-20261028/pulls)

Stdlib only. Exit codes: 0 proof ran (verdicts in the result JSON),
2 an input pin refused.
"""

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

PACKET = Path(__file__).resolve().parent
REPO_ROOT = PACKET.parents[1]
CBR_MANIFEST_PATH = PACKET / "successor_manifest.json"
HOOPR_MANIFEST_PATH = (REPO_ROOT / "research" /
                       "cbb_hoopr_mbb_schedule_successor_20261028" /
                       "successor_manifest.json")
TORVIK_PINNED_COMMIT = "46d1036443ca452fdd1c6cf25cf5dff50de68337"
TORVIK_URL_PATTERN = ("https://raw.githubusercontent.com/andreweatherman/"
                      "toRvik-data/" + TORVIK_PINNED_COMMIT +
                      "/ratings/archive/by_date/ratings_archive_{date}.csv")

# Ending year -> (CBR file, season scope note). logs1520.csv is admitted
# for 2014-15 -> 2017-18 ONLY (see successor_manifest.json).
PER_SEASON_FILES = {2019: "logs19.csv", 2020: "logs20.csv",
                    2021: "logs21.csv", 2022: "logs22.csv",
                    2023: "logs23.csv"}
SEASON_LABEL = {2015: "2014-2015", 2016: "2015-2016", 2017: "2016-2017",
                2018: "2017-2018", 2019: "2018-2019", 2020: "2019-2020",
                2021: "2020-2021", 2022: "2021-2022", 2023: "2022-2023"}

# The complete non-obvious surface -> CBR-slug table for this proof:
# CBR display variants (UNC, UConn, BYU), CBR historical names (Fort
# Wayne, LIU-Brooklyn), abbreviation forms proven by mirror pairs in
# the pinned bytes (UNLV, LSU, ...), and per-source surfaces of the
# other two legs (hoopR "American University" / "UAlbany" / "Albany";
# Torvik "Cleveland St." / "Texas St." / "Nebraska Omaha" /
# "San Diego St." / "Albany").
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

# Declared championship fixtures (date, canonical pair). The hunt
# report's spot-verification table independently agrees with all eight
# on date and both scores against the pinned hoopR schedules.
CHAMPIONSHIPS = {
    2015: ("2015-04-06", ("duke", "wisconsin")),
    2016: ("2016-04-04", ("north-carolina", "villanova")),
    2017: ("2017-04-03", ("gonzaga", "north-carolina")),
    2018: ("2018-04-02", ("michigan", "villanova")),
    2019: ("2019-04-08", ("texas-tech", "virginia")),
    2021: ("2021-04-05", ("baylor", "gonzaga")),
    2022: ("2022-04-04", ("kansas", "north-carolina")),
    2023: ("2023-04-03", ("connecticut", "san-diego-state")),
}
# Early / mid probe dates per season (PR #2866's verified probes) and
# the late probe date used for 2019-20, which has no championship game.
EARLY_PROBE = {2015: "2014-11-15", 2016: "2015-11-14", 2017: "2016-11-12",
               2018: "2017-11-11", 2019: "2018-11-10", 2020: "2019-11-09",
               2021: "2020-11-28", 2022: "2021-11-13", 2023: "2022-11-12"}
MID_PROBE = {2015: "2015-01-15", 2016: "2016-01-15", 2017: "2017-01-15",
             2018: "2018-01-14", 2019: "2019-01-13", 2020: "2020-01-12",
             2021: "2021-01-17", 2022: "2022-01-16", 2023: "2023-01-15"}
LATE_PROBE_2020 = "2020-03-08"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def load_pinned(path, expected_sha, label):
    raw = path.read_bytes()
    if sha256(raw) != expected_sha:
        print(json.dumps({"refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
                          "input": label, "path": str(path)}))
        sys.exit(2)
    return raw


def build_resolver(cbr_dir, cbr_manifest):
    """Harvest CBR's own surface tables from the pinned per-season bytes."""
    team2slug, full2slug = {}, {}
    pins = {s["file_name"]: s["sha256"] for s in cbr_manifest["samples"]}
    for name in PER_SEASON_FILES.values():
        raw = load_pinned(cbr_dir / name, pins[name], name)
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


def load_cbr_rows(year, cbr_dir, cbr_manifest):
    pins = {s["file_name"]: s["sha256"] for s in cbr_manifest["samples"]}
    if year in PER_SEASON_FILES:
        name = PER_SEASON_FILES[year]
        raw = load_pinned(cbr_dir / name, pins[name], name)
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    raw = load_pinned(cbr_dir / "logs1520.csv", pins["logs1520.csv"],
                      "logs1520.csv")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    return [r for r in rows if r["season"] == SEASON_LABEL[year]]


def derive_fixtures(year, cbr_dir, cbr_manifest, resolve):
    """Dedupe one season's CBR team-game rows to mirror-paired fixtures."""
    rows = load_cbr_rows(year, cbr_dir, cbr_manifest)
    stats = {"team_rows_admitted_scope": len(rows),
             "team_slug_unresolved_rows": 0, "score_missing_rows": 0}
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
    fixtures, used = {}, set()
    mirror_resolved, inconsistent = {}, 0
    for i, p in enumerate(parsed):
        if i in used:
            continue
        opp_slug = resolve(p["opp_surface"])
        mirror_idx = None
        if opp_slug is not None:
            for j in by_key.get((p["date"], opp_slug), []):
                if j != i and resolve(parsed[j]["opp_surface"]) == p["slug"]:
                    mirror_idx = j
                    break
        else:
            for j, q in enumerate(parsed):
                if (j != i and q["date"] == p["date"]
                        and resolve(q["opp_surface"]) == p["slug"]
                        and q["ts"] == p["os"] and q["os"] == p["ts"]):
                    mirror_idx, opp_slug = j, q["slug"]
                    mirror_resolved[p["opp_surface"]] = opp_slug
                    break
        if mirror_idx is None:
            continue
        q = parsed[mirror_idx]
        used.add(i)
        used.add(mirror_idx)
        if q["ts"] == p["os"] and q["os"] == p["ts"]:
            pair = tuple(sorted((p["slug"], opp_slug)))
            key = (p["date"], pair)
            scores = {p["slug"]: p["ts"], opp_slug: p["os"]}
            if key in fixtures and fixtures[key] != scores:
                inconsistent += 1
            fixtures[key] = scores
        else:
            inconsistent += 1
    stats.update({
        "fixtures_derived": len(fixtures),
        "rows_in_fixtures": len(used),
        "single_or_unresolved_rows": len(parsed) - len(used),
        "mirror_inconsistent_pairs": inconsistent,
        "mirror_resolved_variants": mirror_resolved,
    })
    return fixtures, stats


def hoopr_fixture(year, date, pair, hoopr_dir, hoopr_manifest, resolve):
    name = f"mbb_schedule_{year}.csv"
    pin = next(s for s in hoopr_manifest["samples"]
               if s["asset_name"] == name)
    raw = load_pinned(hoopr_dir / name, pin["sha256"], name)
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        if row["game_date"] != date:
            continue
        home, away = resolve(row["home_location"]), resolve(row["away_location"])
        if home is None or away is None:
            continue
        if tuple(sorted((home, away))) == pair:
            return {"game_id": row["id"],
                    "scores": {home: int(row["home_score"]),
                               away: int(row["away_score"])}}
    return None


def torvik_teams(date, resolve):
    url = TORVIK_URL_PATTERN.format(date=date.replace("-", ""))
    req = urllib.request.Request(
        url, headers={"User-Agent": "sportsedge-admission-probe"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    if not rows or any(r["date"] != date for r in rows):
        return None, 0
    return {resolve(r["team"]) for r in rows}, len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cbr-dir", default=str(
        Path.home() / "workspace/cbb-cbr-successor-admission-20261028/pulls"))
    parser.add_argument("--hoopr-dir", default=str(
        Path.home() / "workspace/cbb-successor-admission-20261028/pulls"))
    parser.add_argument("--out", default=str(PACKET / "three_way_proof_result.json"))
    args = parser.parse_args()
    cbr_dir, hoopr_dir = Path(args.cbr_dir), Path(args.hoopr_dir)
    cbr_manifest = json.loads(CBR_MANIFEST_PATH.read_text(encoding="utf-8"))
    hoopr_manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    resolve = build_resolver(cbr_dir, cbr_manifest)

    torvik_cache = {}
    derivation, sample = {}, []
    for year in range(2015, 2024):
        fixtures, stats = derive_fixtures(year, cbr_dir, cbr_manifest, resolve)
        derivation[SEASON_LABEL[year]] = stats
        picks = []
        if year in CHAMPIONSHIPS:
            date, pair = CHAMPIONSHIPS[year]
            picks.append(("CHAMPIONSHIP", date, pair))
        else:
            picks.append(("LATE_PROBE_SUBSTITUTE_NO_CHAMPIONSHIP_COVID",
                          LATE_PROBE_2020, None))
        picks.append(("EARLY_PROBE_DATE", EARLY_PROBE[year], None))
        picks.append(("MID_PROBE_DATE", MID_PROBE[year], None))
        for slot, date, pair in picks:
            if pair is None:
                candidates = sorted(p for (d, p) in fixtures if d == date)
                if not candidates:
                    sample.append({"season": SEASON_LABEL[year], "slot": slot,
                                   "date": date,
                                   "verdict": "SCHEDULE_DISCREPANCY",
                                   "reason": "NO_DERIVED_FIXTURE_ON_DATE"})
                    continue
                pair = candidates[0]
            record = {"season": SEASON_LABEL[year], "slot": slot,
                      "date": date, "pair": list(pair)}
            if (date, pair) not in fixtures:
                record.update(verdict="SCHEDULE_DISCREPANCY",
                              reason="FIXTURE_NOT_DERIVED_FROM_CBR")
                sample.append(record)
                continue
            record["cbr_scores"] = fixtures[(date, pair)]
            record["hoopr"] = hoopr_fixture(year, date, pair, hoopr_dir,
                                            hoopr_manifest, resolve)
            if date not in torvik_cache:
                torvik_cache[date] = torvik_teams(date, resolve)
            team_set, team_rows = torvik_cache[date]
            record["torvik_morning_of"] = {
                "file": f"ratings_archive_{date.replace('-', '')}.csv",
                "team_rows": team_rows,
                "both_teams_present": bool(team_set)
                and all(s in team_set for s in pair),
            }
            if record["hoopr"] is None:
                record.update(verdict="SCHEDULE_DISCREPANCY",
                              reason="HOOPR_FIXTURE_NOT_FOUND")
            elif record["hoopr"]["scores"] != record["cbr_scores"]:
                record.update(verdict="SCHEDULE_DISCREPANCY",
                              reason="SCORE_MISMATCH_CBR_VS_HOOPR")
            elif not record["torvik_morning_of"]["both_teams_present"]:
                record.update(verdict="SCHEDULE_DISCREPANCY",
                              reason="TORVIK_MORNING_OF_MISSING_TEAM")
            else:
                record["verdict"] = "AGREE"
            sample.append(record)

    agreed = sum(1 for r in sample if r["verdict"] == "AGREE")
    result = {
        "proof": "CBR mirror fixture derivation + three-way agreement sample",
        "design_reference": "PR #2843 section 2 (three-way fixture agreement)",
        "cbr_manifest": "successor_manifest.json (this packet)",
        "hoopr_manifest": "research/cbb_hoopr_mbb_schedule_successor_20261028/"
                          "successor_manifest.json (PR #2867)",
        "torvik_route": "PR #2832 pinned commit " + TORVIK_PINNED_COMMIT,
        "normalization_overrides": NORMALIZATION_OVERRIDES,
        "derivation_by_season": derivation,
        "sample": sample,
        "summary": {"fixtures_sampled": len(sample), "agree": agreed,
                    "schedule_discrepancy": len(sample) - agreed},
    }
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                              encoding="utf-8")
    print(json.dumps(result["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
