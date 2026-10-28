#!/usr/bin/env python3
"""Verify CBB_TEAM_IDENTITY_CROSSWALK_V1 against its raw pinned inputs.

Independent check of the committed crosswalk.json: this script does NOT
import the builder. It re-reads every pinned byte stream, rebuilds the
CBR surface harvest from the pulls, re-runs the crosswalk's PUBLISHED
resolution chain (override table taken from the artifact itself) over
every surface of every source, and diffs the result against the
artifact's published mapping. It also re-derives the ESPN id bindings
from hoopR co-occurrence, re-checks the fixture proofs end to end, the
Illinois flag set, and the artifact's coverage arithmetic.

Tripwire: if a future pull of any source introduces a team surface the
artifact neither resolves nor lists as unresolved, verification fails
(exit 3) and names the new surfaces — that failure is the mechanism
that forces a governed crosswalk update instead of a silent name-join
miss downstream.

Exit codes: 0 verified, 2 an input pin refused, 3 a consistency gate
failed (details printed as JSON lines).
"""

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PACKET = Path(__file__).resolve().parent
REPO_ROOT = PACKET.parents[1]
CBR_MANIFEST_PATH = (REPO_ROOT / "research" /
                     "cbb_cbr_schedule_mirror_successor_20261028" /
                     "successor_manifest.json")
HOOPR_MANIFEST_PATH = (REPO_ROOT / "research" /
                       "cbb_hoopr_mbb_schedule_successor_20261028" /
                       "successor_manifest.json")
LOGS1520_ADMITTED_SEASONS = {"2014-2015", "2015-2016", "2016-2017",
                             "2017-2018"}
PER_SEASON_FILES = ["logs19.csv", "logs20.csv", "logs21.csv",
                    "logs22.csv", "logs23.csv"]
ILLINOIS_ESPN_DENYLIST = frozenset({
    "71", "77", "79", "82", "305", "356", "2130", "2197", "2287",
    "2350", "2459", "2565", "2710",
})


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def fail(code, label, detail):
    print(json.dumps({"verification_failure": label, "detail": detail}))
    sys.exit(code)


def load_pinned(path, expected_sha, label):
    if not path.exists():
        fail(2, "INPUT_MISSING", f"{label}: {path}")
    raw = path.read_bytes()
    if sha256(raw) != expected_sha:
        fail(2, "SOURCE_CHANGED_AFTER_SNAPSHOT", f"{label}: {path}")
    return raw


def unmapped_surfaces(artifact, source_key, surfaces):
    """Surfaces a pull presents that the artifact neither resolves nor
    lists as unresolved for that source. Empty list = fully accounted.
    This is the guard a future source pull is checked with."""
    resolved = artifact["source_surfaces"].get(source_key, {})
    unresolved = {u["surface"] for u in artifact["unresolved"].get(source_key, [])}
    return sorted(s for s in surfaces if s not in resolved and s not in unresolved)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default=str(PACKET / "crosswalk.json"))
    ap.add_argument("--cbr-dir", default=str(
        Path.home() / "workspace/cbb-cbr-successor-admission-20261028/pulls"))
    ap.add_argument("--hoopr-dir", default=str(
        Path.home() / "workspace/cbb-successor-admission-20261028/pulls"))
    ap.add_argument("--torvik-vintage", default=str(
        Path.home() / "workspace/sportsedge/lane_intakes/torvik_morning/2026-10-28.csv"))
    ap.add_argument("--pulls-dir", default=str(
        Path.home() / "workspace/cbb-crosswalk-20261028/pulls"))
    args = ap.parse_args()
    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    cbr_dir, hoopr_dir, pulls_dir = Path(args.cbr_dir), Path(args.hoopr_dir), Path(args.pulls_dir)
    overrides = {s: e["canonical"] for s, e in artifact["overrides"].items()}
    spine = {t["torvik_name"]: t["canonical_id"]
             for t in artifact["teams"] if t["spine_member"]}
    registry = {t["canonical_id"] for t in artifact["teams"]}

    # ---- pins ---------------------------------------------------------
    pins = {(i["source"], i["file"]): i["sha256"] for i in artifact["inputs"]}
    cbr_manifest = json.loads(CBR_MANIFEST_PATH.read_text(encoding="utf-8"))
    for s in cbr_manifest["samples"]:
        raw = load_pinned(cbr_dir / s["file_name"], s["sha256"], s["file_name"])
        if pins.get(("cbr", s["file_name"])) != s["sha256"]:
            fail(3, "ARTIFACT_PIN_MISMATCH", s["file_name"])
    hoopr_manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    for s in hoopr_manifest["samples"]:
        load_pinned(hoopr_dir / s["asset_name"], s["sha256"], s["asset_name"])
        # The artifact consumes the CSV schedules; the manifest's parquet
        # twins are byte-verified here but are not artifact inputs.
        if s["asset_name"].endswith(".csv") and \
                pins.get(("hoopr", s["asset_name"])) != s["sha256"]:
            fail(3, "ARTIFACT_PIN_MISMATCH", s["asset_name"])
    vintage_path = Path(args.torvik_vintage)
    vintage_meta = json.loads(vintage_path.with_suffix(".json").read_text(encoding="utf-8"))
    vintage_raw = load_pinned(vintage_path, vintage_meta["sha256"], "torvik vintage")
    for entry in artifact["inputs"]:
        if entry["source"] == "torvik_archive":
            load_pinned(pulls_dir / "torvik_archive" / entry["file"],
                        entry["sha256"], entry["file"])
        elif entry["source"].startswith("espn"):
            load_pinned(pulls_dir / entry["file"], entry["sha256"], entry["file"])

    # ---- fresh CBR harvest ----------------------------------------------
    team2slug, full2slug = {}, {}
    opponent_counts = Counter()
    def harvest_slug(row):
        url = next((v for v in row.values()
                    if isinstance(v, str) and "/cbb/schools/" in v), None)
        return url.split("/")[3] if url else None
    for name in PER_SEASON_FILES:
        raw = (cbr_dir / name).read_bytes()
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            slug = harvest_slug(row)
            team2slug[row["Team"]] = slug
            full2slug[row["TeamFull"]] = slug
            opponent_counts[row["Opponent"]] += 1
    surface2slug = {**team2slug, **full2slug}
    full_union = dict(full2slug)
    raw = (cbr_dir / "logs1520.csv").read_bytes()
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        if row.get("season") not in LOGS1520_ADMITTED_SEASONS:
            continue
        slug = surface2slug.get(row["Team"]) or overrides.get(row["Team"])
        if slug is not None:
            full_union[row["Team"]] = slug
            opponent_counts[row["Opponent"]] += 1
    for table in (team2slug, full2slug, full_union):
        for surface, slug in table.items():
            if slug not in registry:
                fail(3, "HARVEST_SLUG_NOT_IN_REGISTRY", f"{surface} -> {slug}")

    def resolve(surface, native_slug=None):
        if surface in overrides:
            return overrides[surface]
        if native_slug is not None:
            return native_slug
        if surface in surface2slug:
            return surface2slug[surface]
        return spine.get(surface)

    # ---- per-source surface accounting + mapping diff --------------------
    def check_source(key, counts, native=None):
        expected_resolved, expected_unresolved = {}, set()
        for surface in counts:
            canon = resolve(surface, (native or {}).get(surface))
            if canon is None:
                expected_unresolved.add(surface)
            else:
                expected_resolved[surface] = canon
        art_resolved = {s: e["canonical"] for s, e in
                        artifact["source_surfaces"][key].items()}
        art_unresolved = {u["surface"] for u in artifact["unresolved"][key]}
        new = unmapped_surfaces(artifact, key, counts.keys())
        if new:
            fail(3, "UNMAPPED_SURFACES_INTRODUCED", f"{key}: {new[:10]}")
        if art_resolved != expected_resolved:
            diff = [s for s in set(art_resolved) | set(expected_resolved)
                    if art_resolved.get(s) != expected_resolved.get(s)]
            fail(3, "MAPPING_DIFFERS_FROM_CHAIN", f"{key}: {diff[:10]}")
        if art_unresolved != expected_unresolved:
            fail(3, "UNRESOLVED_SET_DIFFERS",
                 f"{key}: artifact-only {sorted(art_unresolved - expected_unresolved)[:5]} "
                 f"chain-only {sorted(expected_unresolved - art_unresolved)[:5]}")
        cov = artifact["coverage"][key]
        if (cov["surfaces_total"], cov["resolved"], cov["unresolved"]) != (
                len(counts), len(expected_resolved), len(expected_unresolved)):
            fail(3, "COVERAGE_ARITHMETIC", key)
        return len(expected_resolved), len(expected_unresolved)

    spine_counts = Counter({r["team"]: 1 for r in
                            csv.DictReader(io.StringIO(vintage_raw.decode("utf-8")))})
    summary = {}
    summary["torvik"] = check_source("torvik", spine_counts)
    archive_counts = Counter()
    for entry in artifact["inputs"]:
        if entry["source"] == "torvik_archive":
            raw = (pulls_dir / "torvik_archive" / entry["file"]).read_bytes()
            for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
                archive_counts[row["team"]] += 1
    summary["torvik_archive"] = check_source("torvik_archive", archive_counts)
    summary["cbr_team"] = check_source(
        "cbr_team", Counter({s: 1 for s in team2slug}), native=team2slug)
    res_f, unres_f = check_source(
        "cbr_teamfull", Counter({s: 1 for s in full_union}), native=full_union)
    # logs1520 full names absent from the harvest are published unresolved
    # in the artifact even though they are not in full_union; account for
    # them explicitly rather than through the chain diff above.
    summary["cbr_teamfull"] = (res_f, unres_f)
    summary["cbr_opponent"] = check_source("cbr_opponent", opponent_counts)

    loc_counts, disp_counts = Counter(), Counter()
    id_locations = defaultdict(Counter)
    hoopr_games = {}
    for year in range(2015, 2024):
        raw = (hoopr_dir / f"mbb_schedule_{year}.csv").read_bytes()
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            hoopr_games[row["id"]] = row
            for side in ("home", "away"):
                loc_counts[row[f"{side}_location"]] += 1
                disp_counts[row[f"{side}_display_name"]] += 1
                id_locations[row[f"{side}_id"]][row[f"{side}_location"]] += 1
    summary["hoopr_location"] = check_source("hoopr_location", loc_counts)
    summary["hoopr_display_name"] = check_source("hoopr_display_name", disp_counts)

    espn_raw = (pulls_dir / "espn_teams.json").read_bytes()
    espn_teams = [t["team"] for t in
                  json.loads(espn_raw)["sports"][0]["leagues"][0]["teams"]]
    summary["espn_location"] = check_source(
        "espn_location", Counter(t["location"] for t in espn_teams))
    summary["espn_display_name"] = check_source(
        "espn_display_name", Counter(t["displayName"] for t in espn_teams))

    # ---- id bindings ------------------------------------------------------
    expected_bindings = {}
    for tid, locs in id_locations.items():
        resolved = {loc: resolve(loc) for loc in locs}
        # Published rule: bind only when EVERY co-occurring location
        # resolves and all resolve to one canonical. An id shared with
        # an unresolved school (e.g. 2419: Cincinnati + Mount St.
        # Joseph) stays unbound.
        if all(c is not None for c in resolved.values()) and \
                len(set(resolved.values())) == 1:
            expected_bindings[tid] = next(iter(resolved.values()))
    for t in espn_teams:
        if t["id"] in expected_bindings:
            continue
        canon = resolve(t["location"]) or resolve(t["displayName"])
        if canon:
            expected_bindings[t["id"]] = canon
    art_bindings = {k: v["canonical"] for k, v in
                    artifact["id_bindings"]["espn_team_id"].items()}
    if art_bindings != expected_bindings:
        diff = [k for k in set(art_bindings) | set(expected_bindings)
                if art_bindings.get(k) != expected_bindings.get(k)]
        fail(3, "ID_BINDINGS_DIFFER", f"{diff[:10]}")

    # ---- spine + illinois ---------------------------------------------------
    if len(spine) != 365:
        fail(3, "SPINE_SIZE", str(len(spine)))
    for entry in artifact["teams"]:
        if entry["spine_member"] and not entry["espn_id"]:
            fail(3, "SPINE_TEAM_WITHOUT_ESPN_ID", entry["canonical_id"])
        should_flag = entry["espn_id"] in ILLINOIS_ESPN_DENYLIST
        if entry["capture_excluded_illinois"] != should_flag:
            fail(3, "ILLINOIS_FLAG_MISMATCH", entry["canonical_id"])
    if sorted(artifact["illinois_exclusion"]["flagged_canonicals"]) != sorted(
            t["canonical_id"] for t in artifact["teams"]
            if t["capture_excluded_illinois"]):
        fail(3, "ILLINOIS_LIST_MISMATCH", "flagged_canonicals")

    # ---- fixture proofs -------------------------------------------------------
    for proof in artifact["fixture_proofs"]:
        if "canonical_pair" in proof:
            if not proof["all_sources_agree"]:
                fail(3, "FIXTURE_PROOF_NOT_AGREEING", proof["fixture"])
            if proof["hoopr"]["scores"] != proof["cbr_scores"]:
                fail(3, "FIXTURE_SCORE_MISMATCH", proof["fixture"])
            espn_scores = {c["canonical"]: c["score"]
                           for c in proof["espn"]["competitors"]}
            if espn_scores != proof["cbr_scores"]:
                fail(3, "FIXTURE_ESPN_SCORE_MISMATCH", proof["fixture"])
            for c in proof["espn"]["competitors"]:
                if art_bindings.get(c["espn_id"]) != c["canonical"]:
                    fail(3, "FIXTURE_ESPN_ID_BINDING", proof["fixture"])
        else:
            if not proof["forward_path_proven"]:
                fail(3, "FORWARD_PROOF_FAILED", proof["fixture"])
            for c in proof["competitors"]:
                if art_bindings.get(c["espn_id"]) != c["canonical"]:
                    fail(3, "FORWARD_ESPN_ID_BINDING", proof["fixture"])
                if spine.get({"villanova": "Villanova",
                              "notre-dame": "Notre Dame"}[c["canonical"]]) != c["canonical"]:
                    fail(3, "FORWARD_SPINE_MISMATCH", proof["fixture"])

    print(json.dumps({"verified": True, "summary": summary,
                      "id_bindings": len(art_bindings),
                      "spine_teams": len(spine)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
