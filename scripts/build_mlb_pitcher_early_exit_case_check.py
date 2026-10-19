"""Build and score the MLB pitcher early-exit case check (research only).

Implements the frozen preregistration in
docs/MLB_PITCHER_EARLY_EXIT_PREREG_V1.md:
  1. Reconstruct the two graded cases' existing-engine pools (last 12
     starts before 2026-10-15, MLB StatsAPI gameLog) and re-verify the
     nine-probability fingerprint gate. Any mismatch stops the run
     before scoring.
  2. Fetch (and cache) all 2023-2025 regular-season starts from MLB
     StatsAPI, build the frozen hook/leash/normal exit model.
  3. Score log score / CRPS of the existing tails vs the component on
     the two realized outcomes and apply the frozen verdict bar.

All fetched data is cached under --data-dir with a manifest recording
source URLs, fetch time, and sha256. Nothing is written into any card,
runner, or protocol path.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sportsedge.mlb_pitcher_early_exit import (
    build_exit_model,
    component_exit_band_mass,
    component_k_distribution,
    crps,
    existing_engine_p_over,
    existing_engine_pmf,
    log_score,
    outs_from_ip,
)

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "SportsEdgeResearch/1.0 (early-exit case check)"}

WINDOWS = {
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-20", "2024-09-29"),
    2025: ("2025-03-18", "2025-09-28"),
}

CASES = [
    {
        "case": "A_unit3_hook",
        "pitcher": "Tyler Glasnow",
        "pitcher_id": 607192,
        "unit": 3,
        "line": 6.5,
        "realized_k": 6,
        "realized_outs": 13,
        "realized_pitches": 79,
    },
    {
        "case": "B_unit4_leash",
        "pitcher": "Shane Drohan",
        "pitcher_id": 675660,
        "unit": 4,
        "line": 2.5,
        "realized_k": 1,
        "realized_outs": 3,
        "realized_pitches": 25,
    },
]

# Frozen fingerprint gate (preregistration section 3): recorded model p
# and the count of 12 pool starts it implies, checked on the pitcher's
# reconstructed pool across five stats.
FINGERPRINTS = [
    # pitcher_id, stat key in pool row, comparison, line, recorded p
    (607192, "strikeouts", "over", 6.5, 0.808),
    (607192, "outs", "over", 14.5, 0.808),
    (607192, "walks", "under", 2.5, 0.731),
    (607192, "hits", "under", 3.5, 0.577),
    (607192, "earned_runs", "over", 1.5, 0.654),
    (675660, "strikeouts", "over", 2.5, 0.8077),
    (675660, "outs", "over", 7.5, 0.962),
    (675660, "hits", "over", 2.5, 0.962),
    (675660, "earned_runs", "over", 0.5, 0.962),
]

TARGET_DATE_BEFORE = "2026-10-15"


def fetch_json(url: str, cache_path: str | None = None,
               retries: int = 3) -> dict:
    if cache_path and os.path.exists(cache_path):
        with open(cache_path) as fh:
            return json.load(fh)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            if cache_path:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "w") as fh:
                    json.dump(data, fh)
            return data
        except Exception as exc:  # noqa: BLE001 - retry with backoff
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def gamelog_rows(data: dict) -> list[dict]:
    rows = []
    for split in data["stats"][0]["splits"]:
        st = split["stat"]
        rows.append({
            "date": split["date"],
            "game_pk": split["game"]["gamePk"],
            "games_started": int(st.get("gamesStarted", 0)),
            "outs": outs_from_ip(st["inningsPitched"]),
            "strikeouts": int(st["strikeOuts"]),
            "hits": int(st["hits"]),
            "runs": int(st["runs"]),
            "earned_runs": int(st["earnedRuns"]),
            "walks": int(st["baseOnBalls"]),
            "pitches": (int(st["numberOfPitches"])
                        if st.get("numberOfPitches") is not None else None),
        })
    return rows


def case_pool(data_dir: str, pitcher_id: int) -> list[dict]:
    url = (f"{API}/people/{pitcher_id}/stats?stats=gameLog"
           f"&season=2026&group=pitching")
    cache = os.path.join(data_dir, f"gamelog_2026_{pitcher_id}.json")
    rows = gamelog_rows(fetch_json(url, cache))
    starts = [r for r in rows
              if r["games_started"] == 1 and r["date"] < TARGET_DATE_BEFORE]
    starts.sort(key=lambda r: r["date"])
    return starts[-12:]


def fingerprint_gate(pools: dict[int, list[dict]]) -> list[dict]:
    results = []
    for pid, stat, side, line, recorded in FINGERPRINTS:
        values = [r[stat] for r in pools[pid]]
        p_over = existing_engine_p_over(values, line)
        p = p_over if side == "over" else 1.0 - p_over
        # recorded values on the cards are rounded to 3-4 decimals
        ok = abs(p - recorded) <= 0.0011
        results.append({
            "pitcher_id": pid, "stat": stat, "side": side, "line": line,
            "recorded_p": recorded, "reconstructed_p": round(p, 6),
            "count": (sum(1 for v in values if v > line) if side == "over"
                      else sum(1 for v in values if v < line)),
            "match": ok,
        })
    return results


def season_starts(data_dir: str, season: int) -> list[dict]:
    """All regular-season starts for one season, cached as one CSV."""
    csv_path = os.path.join(data_dir, f"starts_{season}.csv")
    if os.path.exists(csv_path):
        with open(csv_path) as fh:
            return [{**r,
                     "outs": int(r["outs"]), "runs": int(r["runs"]),
                     "strikeouts": int(r["strikeouts"]),
                     "pitches": (int(r["pitches"]) if r["pitches"] != ""
                                 else None)}
                    for r in csv.DictReader(fh)]
    lo, hi = WINDOWS[season]
    enum_url = (f"{API}/stats?stats=season&season={season}&group=pitching"
                f"&sportId=1&gameType=R&limit=3000&playerPool=ALL")
    enum_cache = os.path.join(data_dir, f"season_pitching_{season}.json")
    enum = fetch_json(enum_url, enum_cache)
    pitcher_ids = sorted({
        s["player"]["id"] for s in enum["stats"][0]["splits"]
        if s["stat"].get("gamesStarted", 0) >= 1
    })
    starts = []
    for i, pid in enumerate(pitcher_ids):
        url = (f"{API}/people/{pid}/stats?stats=gameLog"
               f"&season={season}&group=pitching")
        cache = os.path.join(data_dir, "hist", f"gamelog_{season}_{pid}.json")
        try:
            rows = gamelog_rows(fetch_json(url, cache))
        except RuntimeError:
            continue
        for r in rows:
            if r["games_started"] == 1 and lo <= r["date"] <= hi:
                starts.append({"pitcher_id": pid, **r})
        if (i + 1) % 100 == 0:
            print(f"  {season}: {i + 1}/{len(pitcher_ids)} pitchers",
                  flush=True)
        time.sleep(0.03)
    os.makedirs(data_dir, exist_ok=True)
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pitcher_id", "date", "game_pk", "outs", "runs",
                    "pitches", "strikeouts"])
        for r in starts:
            w.writerow([r["pitcher_id"], r["date"], r["game_pk"],
                        r["outs"], r["runs"],
                        "" if r["pitches"] is None else r["pitches"],
                        r["strikeouts"]])
    return starts


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.data_dir, exist_ok=True)

    results: dict = {
        "build": "MLB_PITCHER_EARLY_EXIT_V1_CASE_CHECK",
        "status": "RESEARCH_ONLY_NOT_WIRED_NO_PRICING_IMPACT",
        "data_source": "MLB StatsAPI (statsapi.mlb.com), free public",
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # 1. Case pools + fingerprint gate (STOP before scoring on failure).
    pools = {c["pitcher_id"]: case_pool(args.data_dir, c["pitcher_id"])
             for c in CASES}
    gate = fingerprint_gate(pools)
    results["fingerprint_gate"] = gate
    if not all(g["match"] for g in gate):
        results["verdict"] = "STOPPED_FINGERPRINT_GATE_FAIL"
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=1)
        print("FINGERPRINT GATE FAIL — stopped before scoring")
        return 2
    print("fingerprint gate: all 9 recorded probabilities reproduced")

    # 2. Historical exit model.
    starts: list[dict] = []
    per_season = {}
    for season in (2023, 2024, 2025):
        rows = season_starts(args.data_dir, season)
        per_season[season] = len(rows)
        starts.extend(rows)
    model = build_exit_model(starts)
    results["historical_pool"] = {
        "seasons": per_season,
        "n_starts": model["n_starts"],
        "state_counts": model["state_counts"],
        "missing_pitches": model["missing_pitches"],
        "weights": model["weights"],
        "lambda_league": model["lambda_league"],
    }
    print(f"historical starts: {model['n_starts']} "
          f"(states {model['state_counts']})")

    # 3. Sanity checks (frozen prereg section 7).
    early = {1, 2, 3, 4}
    band = model["band_dist"]
    sanity = {
        "hook_early_mass": sum(band["HOOK"][c] for c in early),
        "leash_early_mass": sum(band["LEASH"][c] for c in early),
        "hook_band_masses_1_4": {str(c): band["HOOK"][c] for c in sorted(early)},
        "leash_band_masses_1_4": {str(c): band["LEASH"][c] for c in sorted(early)},
        "mixture_early_mass": sum(model["mixture_band_dist"][c] for c in early),
        "pooled_early_mass": sum(model["pooled_band_dist"][c] for c in early),
    }
    sanity["nonzero_early_mass_both"] = (
        sanity["hook_early_mass"] > 0 and sanity["leash_early_mass"] > 0)
    sanity["band_check_within_0_05"] = abs(
        sanity["mixture_early_mass"] - sanity["pooled_early_mass"]) <= 0.05
    results["sanity"] = sanity

    # 4. Score both cases.
    case_results = []
    sum_existing = 0.0
    sum_component = 0.0
    band_ok = True
    for case in CASES:
        pool = pools[case["pitcher_id"]]
        counts = Counter(r["strikeouts"] for r in pool)
        q = existing_engine_pmf(dict(counts), len(pool))
        lam = (sum(r["strikeouts"] for r in pool)
               / sum(r["outs"] for r in pool))
        comp = component_k_distribution(model, lam)
        k = case["realized_k"]
        ls_e = log_score(q, k)
        ls_c = log_score(comp, k)
        band_mass = component_exit_band_mass(model, case["realized_outs"] // 3)
        sum_existing += ls_e
        sum_component += ls_c
        band_ok = band_ok and band_mass > 0
        case_results.append({
            **case,
            "pool": [{kk: r[kk] for kk in
                      ("date", "outs", "strikeouts", "hits", "runs",
                       "earned_runs", "walks", "pitches")} for r in pool],
            "lambda_pitcher": lam,
            "existing_p_at_realized": (q[k] if k < len(q) else 0.0),
            "existing_log_score": (None if math.isinf(ls_e) else ls_e),
            "existing_log_score_is_neg_inf": math.isinf(ls_e),
            "component_p_at_realized": comp[k],
            "component_log_score": ls_c,
            "existing_crps": crps(q, k),
            "component_crps": crps(comp, k),
            "realized_exit_band": case["realized_outs"] // 3,
            "component_exit_band_mass": band_mass,
        })
    results["cases"] = case_results
    results["summed_log_score_existing"] = (
        None if math.isinf(sum_existing) else sum_existing)
    results["summed_log_score_existing_is_neg_inf"] = math.isinf(sum_existing)
    results["summed_log_score_component"] = sum_component
    better = sum_component > sum_existing
    results["verdict"] = ("CASE_CHECK_PASS" if (better and band_ok)
                          else "CASE_CHECK_FAIL")
    results["verdict_basis"] = {
        "summed_log_score_better": better,
        "realized_exit_band_mass_nonzero_both": band_ok,
    }

    # 5. Data-cache manifest (hashes of every cached artifact used).
    manifest = {}
    for name in sorted(os.listdir(args.data_dir)):
        path = os.path.join(args.data_dir, name)
        if os.path.isfile(path):
            manifest[name] = sha256_file(path)
    results["data_cache_sha256"] = manifest

    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=1)
    print(f"verdict: {results['verdict']} "
          f"(existing sum {sum_existing}, component sum {sum_component})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
