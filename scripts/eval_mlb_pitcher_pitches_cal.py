"""MLB pitcher pitches-thrown calibration backtest (Stage 2, item M29).

Evaluand: sportsedge/pitcher_joint_engine.py price_pitcher_market,
market PITCHER_PITCHES, at main 83e0c396a4761ea3de80583be5e61e8ca2e07f9a
(engine blob 00cba6f664e313b53ab0084e6f3f471a9d85b566, identical to the
Phase 2 pin 12999fc22 blob), canonical configuration
features = {"history_pool": [...]} only.

Governing spec: mlb_market_legs_20261014/SPEC_M29_PITCHER_PITCHES.md
SHA-256 8299481c72609023a899f416959ee45b62a254b137ce4262e3a7a502130a1723
(verified at runtime; a mismatch stops the run before scoring).

Label of output: RESEARCH_EVIDENCE (retrospective calibration only;
NOT a market verdict, NOT validation, NOT a promotion input).

Population / pool lineage: the pool-construction functions
(parse_starts, production_order, engine_pool, all_prior) are copied
verbatim from the Phase 2 undercard evaluator
(backtest_program_20261014/scripts/eval_pitcher_undercard.py); their
source identity against that file is hashed and recorded in the
results, and the spec section 6 parity check (25/25 pool equality vs
MLBPitcherPublicSource.prior_starts) runs fresh in this evaluator
before any scoring.

Method notes (per spec):
- Sealed window [2024-07-01, 2024-09-01): fixtures in the window are
  excluded (SEALED_WINDOW, counted in the undercard population build)
  and starts in the window are removed from every pool (engine pool,
  B1, B2) before the <=12 cap.
- Distribution reconstruction: sweep price_pitcher_market
  (PITCHER_PITCHES, OVER) over half-lines m + 0.5 for m = 0..170,
  F(m) = 1 - p_over(m + 0.5). Monotonicity asserted per fixture.
- CRPS = sum_m (F(m) - 1{y <= m})^2 over m = 0..170, identical for
  engine, B1 (pitcher's own trailing raw frequency over ALL prior
  same-season starts, measured pitch counts only) and B2 (league
  climatology over measured pitch counts, expanding season-to-date,
  strictly prior dates). Mean residual tail mass 1 - F(170) reported.
- Pitches-specific exclusions, counted per season, in this order:
  PITCHES_NOT_MEASURED (fixture outcome has no measured pitch count),
  then POOL_PITCH_COUNT_MISSING (a pool row lacks a measured pitch
  count -- the engine's own fail-closed rule for PITCHER_PITCHES).
- Gate: BEATS_BASELINE iff the pooled paired dCRPS 95% CI (block
  bootstrap over ISO calendar weeks, 2000 resamples, seed 20261015)
  is entirely < 0 against BOTH baselines.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import random
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HOME = os.path.expanduser("~")
REPO = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO / "mlb_market_legs_20261014" / "SPEC_M29_PITCHER_PITCHES.md"
SPEC_SHA256 = "8299481c72609023a899f416959ee45b62a254b137ce4262e3a7a502130a1723"
EXPECTED_MAIN = "83e0c396a4761ea3de80583be5e61e8ca2e07f9a"
EXPECTED_ENGINE_BLOB = "00cba6f664e313b53ab0084e6f3f471a9d85b566"
UNDERCARD_SCRIPT = os.path.join(
    HOME, "workspace/sportsedge/backtest_program_20261014/scripts/eval_pitcher_undercard.py")
CACHE = os.path.join(HOME, "workspace/tmp/bt_data/statsapi_cache")
DONE_PATH = os.path.join(HOME, "workspace/tmp/bt_data/ACQUISITION_DONE.json")
DEFAULT_OUT = str(REPO / "mlb_market_legs_20261014" / "results_m29_pitcher_pitches.json")
DEFAULT_AUDIT = os.path.join(
    HOME, "workspace/sportsedge/mlb_market_legs_20261014/results/audit_m29_pitcher_pitches.csv")
ROOT = "https://statsapi.mlb.com/api/v1"
SEED = 20261015
SEALED_START = date(2024, 7, 1)
SEALED_END = date(2024, 9, 1)
CRPS_M_MAX = 170

sys.path.insert(0, str(REPO))
from sportsedge.pitcher_joint_engine import ENGINE_VERSION, price_pitcher_market  # noqa: E402
from sportsedge.mlb_public_pitcher_history import (  # noqa: E402
    MLBPitcherPublicSource, MissingMLBHistory, _int, _outs)


class StopRun(RuntimeError):
    pass


def sealed(d: date) -> bool:
    return SEALED_START <= d < SEALED_END


def cache_path(url: str) -> str:
    return os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest() + ".json")


def load_cache(url: str):
    p = cache_path(url)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def gamelog_url(pid: int, season: int) -> str:
    return f"{ROOT}/people/{pid}/stats?stats=gameLog&group=pitching&season={season}"


# ---------------------------------------------------------------- pools
# The four functions below are copied verbatim from the Phase 2
# undercard evaluator (see module docstring); source identity is
# verified at runtime by pool_code_identity().
def parse_starts(payload) -> list[dict]:
    """Parse a pitching gameLog payload into production-shaped starts.

    Mirrors MLBPitcherPublicSource.prior_starts row handling exactly:
    gamesStarted == 1 only, strict _int/_outs conversions, malformed
    rows skipped, pitches carried only when present in the raw row.
    Returned in payload order; callers apply production ordering.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("stats"), list):
        return []
    splits = [v for stat in payload["stats"]
              if isinstance(stat, dict) and isinstance(stat.get("splits"), list)
              for v in stat["splits"]]
    out = []
    for row in splits:
        try:
            data_row = row["stat"]
            if _int(data_row["gamesStarted"], "GAMES_STARTED") != 1:
                continue
            game_id = _int((row.get("game") or {})["gamePk"], "HISTORY_GAME_PK")
            when = datetime.fromisoformat(str(row["date"])).date()
            stats = {
                "strikeouts": _int(data_row["strikeOuts"], "STRIKEOUTS"),
                "outs": _outs(data_row["inningsPitched"]),
                "earned_runs": _int(data_row["earnedRuns"], "EARNED_RUNS"),
                "hits_allowed": _int(data_row["hits"], "HITS"),
                "walks_allowed": _int(data_row["baseOnBalls"], "WALKS"),
            }
            if "numberOfPitches" in data_row:
                stats["pitches"] = _int(data_row["numberOfPitches"], "PITCHES")
        except (ValueError, KeyError, TypeError, MissingMLBHistory):
            continue
        out.append({"date": when, "game_pk": game_id, "stats": stats,
                    "game_type": row.get("gameType")})
    return out


def production_order(starts: list[dict]) -> list[dict]:
    """Production ordering: sort (date, gamePk) descending, dedupe by
    gamePk keeping the first in that order."""
    ordered = sorted(starts, key=lambda x: (x["date"], x["game_pk"]), reverse=True)
    seen, latest = set(), []
    for s in ordered:
        if s["game_pk"] not in seen:
            seen.add(s["game_pk"])
            latest.append(s)
    return latest


def engine_pool(pitcher_starts_desc: list[dict], fixture_date: date) -> list[dict]:
    """Scoring pool: strictly-prior dates, sealed starts removed (before
    the cap), most recent <= 12, production row order."""
    cand = [s for s in pitcher_starts_desc
            if s["date"] < fixture_date and not sealed(s["date"])]
    return [s["stats"] for s in cand[:12]]


def all_prior(pitcher_starts_desc: list[dict], fixture_date: date) -> list[dict]:
    """B1 source rows: ALL strictly-prior same-season starts, sealed
    removed, no cap."""
    return [s for s in pitcher_starts_desc
            if s["date"] < fixture_date and not sealed(s["date"])]


def pool_code_identity() -> dict:
    """Hash the source of the shared pool functions in this file and in
    the undercard evaluator; report whether they are identical."""
    names = ["parse_starts", "production_order", "engine_pool", "all_prior"]

    def grab(path):
        with open(path) as f:
            tree = ast.parse(f.read())
        out = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                out[node.name] = ast.get_source_segment(open(path).read(), node)
        return out

    mine = grab(__file__)
    ref = grab(UNDERCARD_SCRIPT)
    per = {}
    for n in names:
        per[n] = {
            "this_file_sha256": hashlib.sha256((mine.get(n) or "").encode()).hexdigest(),
            "undercard_sha256": hashlib.sha256((ref.get(n) or "").encode()).hexdigest(),
            "identical": mine.get(n) == ref.get(n),
        }
    return {"functions": per,
            "all_identical": all(v["identical"] for v in per.values())}


# ---------------------------------------------------------------- engine sweep
def sweep_engine_pitches(pool: list[dict]) -> dict:
    """Sweep PITCHER_PITCHES OVER over m + 0.5 for m = 0..170.
    Returns {m: F(m)}. Monotonicity asserted; violation stops the run."""
    cdf = {}
    for m in range(0, CRPS_M_MAX + 1):
        res = price_pitcher_market({
            "market": "PITCHER_PITCHES", "side": "OVER", "line": m + 0.5,
            "features": {"history_pool": pool},
        })
        cdf[m] = 1.0 - float(res["model_p"])
    ms = sorted(cdf)
    for a, b in zip(ms, ms[1:]):
        if cdf[b] < cdf[a] - 1e-12:
            raise StopRun(
                f"CDF monotonicity violation PITCHES: F({a})={cdf[a]} > F({b})={cdf[b]}")
    return cdf


def crps_from_cdf(cdf_get, m_max: int, y: int) -> float:
    total = 0.0
    for m in range(0, m_max + 1):
        ind = 1.0 if y <= m else 0.0
        total += (cdf_get(m) - ind) ** 2
    return total


def emp_cdf_getter(counts: Counter, total: int):
    vals = sorted(counts.items())
    cum, table = 0, {}
    for v, c in vals:
        cum += c
        table[v] = cum

    def get(m: int) -> float:
        lo = None
        for v in table:
            if v <= m:
                lo = v
            else:
                break
        if lo is None:
            return 0.0
        return table[lo] / total
    return get


# ---------------------------------------------------------------- bootstrap
def block_bootstrap_ci(diffs: np.ndarray, block_keys: list[str],
                       seed: int = SEED, resamples: int = 2000) -> dict:
    diffs = np.asarray(diffs, dtype=float)
    blocks = sorted(set(block_keys))
    bidx = {b: i for i, b in enumerate(blocks)}
    bi = np.array([bidx[k] for k in block_keys])
    nb = len(blocks)
    bsums = np.zeros(nb)
    bcounts = np.zeros(nb)
    np.add.at(bsums, bi, diffs)
    np.add.at(bcounts, bi, 1.0)
    rng = np.random.default_rng(seed)
    samp = rng.integers(0, nb, size=(resamples, nb))
    means = (bsums[samp].sum(axis=1) / bcounts[samp].sum(axis=1))
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean_delta": float(diffs.mean()), "ci95_lo": float(lo),
            "ci95_hi": float(hi), "n_blocks": nb, "resamples": resamples,
            "entirely_below_zero": bool(hi < 0)}


# ---------------------------------------------------------------- data loading
def load_universe() -> dict:
    if not os.path.exists(DONE_PATH):
        raise StopRun("ACQUISITION_DONE.json missing: scoring is prohibited")
    with open(DONE_PATH) as f:
        done = json.load(f)
    index_path = os.path.join(CACHE, "index.json")
    if not os.path.exists(index_path):
        raise StopRun("cache index.json missing")
    with open(index_path) as f:
        index = json.load(f)
    pitcher_ids = {2024: set(), 2025: set()}
    for url in index:
        if "/people/" in url and "group=pitching" in url:
            pid = int(url.split("/people/")[1].split("/")[0])
            season = int(url.rsplit("season=", 1)[1])
            if season in pitcher_ids:
                pitcher_ids[season].add(pid)
    players = {}
    for s in (2024, 2025):
        payload = load_cache(f"{ROOT}/sports/1/players?season={s}")
        if payload:
            for person in payload.get("people", []):
                players.setdefault(person["id"], person.get("fullName"))
    schedule = {}
    for url in index:
        if "/schedule?" in url and "gameType=R" in url:
            payload = load_cache(url)
            if not payload:
                continue
            for block in payload.get("dates", []):
                for g in block.get("games", []):
                    schedule[g.get("gamePk")] = {
                        "gameDate": g.get("gameDate"),
                        "gameType": g.get("gameType"),
                        "away": ((g.get("teams") or {}).get("away") or {}).get("team", {}).get("name"),
                        "home": ((g.get("teams") or {}).get("home") or {}).get("team", {}).get("name"),
                    }
    return {"done": done, "index": index, "pitcher_ids": pitcher_ids,
            "players": players, "schedule": schedule}


def build_population(universe: dict) -> dict:
    """Undercard population (identical fixture definition) plus a
    pitches-only B2 climatology snapshot per fixture."""
    seasons = {}
    gametype_counts = Counter()
    missing_gamelogs = []
    for season in (2024, 2025):
        by_pitcher = {}
        for pid in sorted(universe["pitcher_ids"][season]):
            payload = load_cache(gamelog_url(pid, season))
            if payload is None:
                missing_gamelogs.append({"pitcher_id": pid, "season": season})
                continue
            starts = parse_starts(payload)
            for s in starts:
                gametype_counts[str(s["game_type"])] += 1
            if starts:
                by_pitcher[pid] = production_order(starts)
        fixtures, exclusions = [], Counter()
        cand_regular = 0
        for pid, starts_desc in by_pitcher.items():
            for s in starts_desc:
                if s["game_type"] != "R":
                    continue
                cand_regular += 1
                d = s["date"]
                if sealed(d):
                    exclusions["SEALED_WINDOW"] += 1
                    continue
                pool = engine_pool(starts_desc, d)
                if len(pool) < 5:
                    exclusions["POOL_STARTS_LT_5"] += 1
                    continue
                fixtures.append({
                    "pitcher_id": pid, "date": d, "game_pk": s["game_pk"],
                    "season": season, "outcome": s["stats"], "pool": pool,
                    "prior_all": all_prior(starts_desc, d),
                })
        fixtures.sort(key=lambda x: (x["date"], x["pitcher_id"], x["game_pk"]))
        events = []
        for pid, starts_desc in by_pitcher.items():
            for s in starts_desc:
                if not sealed(s["date"]):
                    events.append(s)
        events.sort(key=lambda x: x["date"])
        counts = Counter()
        totals = 0
        ei = 0
        b2_by_id = {}
        for fx in fixtures:
            while ei < len(events) and events[ei]["date"] < fx["date"]:
                ev = events[ei]
                if "pitches" in ev["stats"]:
                    counts[ev["stats"]["pitches"]] += 1
                    totals += 1
                ei += 1
            b2_by_id[id(fx)] = (Counter(counts), totals)
        seasons[season] = {"fixtures": fixtures, "exclusions": dict(exclusions),
                           "candidate_regular_starts": cand_regular,
                           "b2": b2_by_id, "by_pitcher": by_pitcher}
    return {"seasons": seasons, "gametype_counts": dict(gametype_counts),
            "missing_gamelogs": missing_gamelogs}


# ---------------------------------------------------------------- parity
def run_parity(universe: dict, population: dict) -> dict:
    """Spec section 6 parity, identical construction to the undercard
    evaluator (fresh run; shuffle seed is the Stage 2 seed)."""
    live_fetches: list[str] = []

    def hybrid_getter(url: str):
        if "/people/" in url and "gameLog" in url:
            data = load_cache(url)
            if data is None:
                raise StopRun(f"parity gameLog cache MISS (stop per brief): {url}")
            return data
        if url.startswith(ROOT + "/schedule?") and "probablePitcher" in url:
            live_fetches.append(url)
            req = urllib.request.Request(
                url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                              "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read(5_000_000))
        raise StopRun(f"parity getter: unexpected URL {url}")

    candidates = []
    for season in (2024, 2025):
        for fx in population["seasons"][season]["fixtures"]:
            if not (season == 2025 or fx["date"] < SEALED_START):
                continue
            sched = universe["schedule"].get(fx["game_pk"])
            if not sched or not sched.get("gameDate"):
                continue
            kickoff = datetime.fromisoformat(sched["gameDate"].replace("Z", "+00:00"))
            if kickoff.date() != fx["date"]:
                continue
            if kickoff.hour < 1:
                continue
            candidates.append((fx, sched, kickoff))
    rng = random.Random(SEED)
    rng.shuffle(candidates)
    source = MLBPitcherPublicSource(getter=hybrid_getter)
    successes, refusals, attempts = [], Counter(), 0
    for fx, sched, kickoff in candidates:
        if len(successes) >= 25:
            break
        attempts += 1
        name = universe["players"].get(fx["pitcher_id"])
        as_of = (kickoff - timedelta(minutes=30)).astimezone(timezone.utc)
        try:
            prod = source.prior_starts(
                away=sched["away"], home=sched["home"], player_name=name,
                owner_kickoff=kickoff.isoformat(),
                as_of=as_of.isoformat())
        except MissingMLBHistory as exc:
            refusals[str(exc)] += 1
            continue
        prod_pool = prod["features"]["history_pool"]
        ok = (prod_pool == fx["pool"]
              and prod["pitcher_id"] == str(fx["pitcher_id"])
              and prod["game_id"] == str(fx["game_pk"]))
        if not ok:
            return {"status": "FAILED", "attempts": attempts,
                    "successes": len(successes), "refusals": dict(refusals),
                    "live_schedule_fetches": live_fetches,
                    "mismatch": {"pitcher_id": fx["pitcher_id"],
                                 "date": fx["date"].isoformat(),
                                 "game_pk": fx["game_pk"],
                                 "production_pool": prod_pool,
                                 "evaluator_pool": fx["pool"]}}
        successes.append({"pitcher_id": fx["pitcher_id"],
                          "date": fx["date"].isoformat(),
                          "game_pk": fx["game_pk"]})
    return {"status": "PASSED" if len(successes) == 25 else "FAILED",
            "required": 25, "successes": len(successes), "attempts": attempts,
            "production_refusals_counted_and_replaced": dict(refusals),
            "live_schedule_fetches": live_fetches,
            "pairs": successes,
            "sampling_note": ("Candidates restricted to fixtures where the sealed "
                              "filter is inactive (2025, or date < 2024-07-01), "
                              "schedule gameDate UTC date == gameLog date, and "
                              "kickoff >= 01:00 UTC; as_of = kickoff - 30 min.")}


# ---------------------------------------------------------------- scoring
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--audit", default=DEFAULT_AUDIT)
    ap.add_argument("--limit-fixtures", type=int, default=0,
                    help="smoke-test only; writes to --out with smoke flag")
    args = ap.parse_args()

    with open(SPEC_PATH, "rb") as f:
        spec_hash = hashlib.sha256(f.read()).hexdigest()
    if spec_hash != SPEC_SHA256:
        raise StopRun(f"spec hash mismatch: {spec_hash}")
    blob = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse",
         f"{EXPECTED_MAIN}:sportsedge/pitcher_joint_engine.py"],
        text=True).strip()
    if blob != EXPECTED_ENGINE_BLOB:
        raise StopRun(f"engine blob at pin {blob} != {EXPECTED_ENGINE_BLOB}")
    head = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    head_blob = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse",
         "HEAD:sportsedge/pitcher_joint_engine.py"], text=True).strip()
    if head_blob != EXPECTED_ENGINE_BLOB:
        raise StopRun(f"worktree engine blob {head_blob} != {EXPECTED_ENGINE_BLOB}")
    if not os.path.exists(DONE_PATH):
        raise StopRun("ACQUISITION_DONE.json missing: do not score")

    universe = load_universe()
    population = build_population(universe)
    identity = pool_code_identity()

    results: dict = {
        "item": "M29_PITCHER_PITCHES_CALIBRATION",
        "label": "RESEARCH_EVIDENCE",
        "evidence_class": ("RETROSPECTIVE_CALIBRATION — no historical paired DK "
                           "lines for this family; market leg FORWARD_ONLY_BY_DESIGN. "
                           "NOT validation, NOT a promotion input."),
        "spec_sha256": spec_hash,
        "spec_path": str(SPEC_PATH),
        "model_identity": {
            "file": "sportsedge/pitcher_joint_engine.py",
            "main_commit": EXPECTED_MAIN,
            "engine_blob_at_pin": blob,
            "engine_blob_check": "MATCHES spec blob 00cba6f664e313b53ab0084e6f3f471a9d85b566 (identical at Phase 2 pin 12999fc22)",
            "worktree_head": head,
            "engine_blob_at_worktree_head": head_blob,
            "engine_version": ENGINE_VERSION,
            "config": "price_pitcher_market market=PITCHER_PITCHES, features={'history_pool': [...]} only",
        },
        "dataset": {
            "transport": "MLB StatsAPI disk cache (public endpoints)",
            "cache_dir": CACHE,
            "manifest": "mlb_market_legs_20261014/DATASET_MANIFEST_STAGE2.md section 2",
            "manifest_combined_identity_sha256": "87841854d03f8e65686503b1ee19c011d66604d6501bc9c96fee1b6d18cea55e",
            "acquisition_done": universe["done"],
            "in_repo": False,
        },
        "pool_code_identity_vs_undercard_evaluator": identity,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "bootstrap": {"blocks": "ISO calendar weeks", "resamples": 2000, "seed": SEED},
    }

    # ---- parity gate (before scoring)
    parity = run_parity(universe, population)
    results["parity"] = parity
    if parity["status"] != "PASSED":
        results["verdict"] = "STOPPED_PARITY_GATE"
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
        print("PARITY GATE FAILED; stopped before scoring")
        return 2

    # ---- pitches-specific exclusions + scored set
    scored = []
    counts: dict = {}
    audit_rows = []
    for season in (2024, 2025):
        s = population["seasons"][season]
        b2map = s["b2"]
        c = {"candidate_regular_starts": s["candidate_regular_starts"],
             "undercard_exclusions": s["exclusions"],
             "undercard_population": len(s["fixtures"]),
             "PITCHES_NOT_MEASURED": 0, "POOL_PITCH_COUNT_MISSING": 0,
             "scored": 0}
        for fx in s["fixtures"]:
            base = {"season": season, "date": fx["date"].isoformat(),
                    "pitcher_id": fx["pitcher_id"], "game_pk": fx["game_pk"],
                    "pool_n": len(fx["pool"])}
            if "pitches" not in fx["outcome"]:
                c["PITCHES_NOT_MEASURED"] += 1
                audit_rows.append({**base, "status": "EXCLUDED_PITCHES_NOT_MEASURED",
                                   "y_pitches": "", "pred_mean": "", "p10": "",
                                   "p90": "", "covered80": "", "crps_engine": "",
                                   "crps_b1": "", "crps_b2": "", "tail_mass": ""})
                continue
            if any("pitches" not in row for row in fx["pool"]):
                c["POOL_PITCH_COUNT_MISSING"] += 1
                audit_rows.append({**base, "status": "EXCLUDED_POOL_PITCH_COUNT_MISSING",
                                   "y_pitches": fx["outcome"]["pitches"],
                                   "pred_mean": "", "p10": "", "p90": "",
                                   "covered80": "", "crps_engine": "",
                                   "crps_b1": "", "crps_b2": "", "tail_mass": ""})
                continue
            counts_b2, total_b2 = b2map[id(fx)]
            scored.append({"season": season, "pitcher_id": fx["pitcher_id"],
                           "date": fx["date"], "game_pk": fx["game_pk"],
                           "y": fx["outcome"]["pitches"], "pool": fx["pool"],
                           "prior_all": fx["prior_all"],
                           "b2_counts": counts_b2, "b2_total": total_b2,
                           "audit_base": base})
            c["scored"] += 1
        counts[str(season)] = c
    results["counts"] = counts
    results["counts"]["pooled"] = {
        "undercard_population": sum(v["undercard_population"] for v in counts.values()),
        "PITCHES_NOT_MEASURED": sum(v["PITCHES_NOT_MEASURED"] for v in counts.values()),
        "POOL_PITCH_COUNT_MISSING": sum(v["POOL_PITCH_COUNT_MISSING"] for v in counts.values()),
        "scored": sum(v["scored"] for v in counts.values()),
    }
    if args.limit_fixtures:
        scored = scored[: args.limit_fixtures]
        results["smoke_test_limit_fixtures"] = args.limit_fixtures

    # ---- sweep sanity on first 10 scored fixtures (date, pitcher order)
    sanity_order = sorted(range(len(scored)),
                          key=lambda i: (scored[i]["date"], scored[i]["pitcher_id"]))[:10]
    cdf_cache: dict = {}

    def get_cdf(i: int):
        if i not in cdf_cache:
            cdf_cache[i] = sweep_engine_pitches(scored[i]["pool"])
        return cdf_cache[i]

    diffs = []
    for i in sanity_order:
        fx = scored[i]
        cdf = get_cdf(i)
        direct = price_pitcher_market({
            "market": "PITCHER_PITCHES", "side": "OVER", "line": 85.5,
            "features": {"history_pool": fx["pool"]}})["model_p"]
        diffs.append(abs(float(direct) - (1.0 - cdf[85])))
    results["sweep_sanity"] = {
        "n_fixtures": len(sanity_order), "line": 85.5,
        "max_abs_diff": max(diffs) if diffs else None,
        "note": "direct model_p(OVER, 85.5) == 1 - F(85) from the sweep"}
    if diffs and max(diffs) >= 1e-12:
        results["verdict"] = "STOPPED_SWEEP_SANITY"
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
        print("SWEEP SANITY FAILED; stopped before scoring")
        return 2

    # ---- full scoring
    rows = []
    audit_by_key = {}
    for i, fx in enumerate(scored):
        cdf = get_cdf(i)
        y = fx["y"]
        crps_eng = crps_from_cdf(lambda m, c=cdf: c[m], CRPS_M_MAX, y)
        b1_counts = Counter(s["stats"]["pitches"] for s in fx["prior_all"]
                            if "pitches" in s["stats"])
        b1_get = emp_cdf_getter(b1_counts, sum(b1_counts.values()))
        crps_b1 = crps_from_cdf(b1_get, CRPS_M_MAX, y)
        b2_get = emp_cdf_getter(fx["b2_counts"], fx["b2_total"])
        crps_b2 = crps_from_cdf(b2_get, CRPS_M_MAX, y)
        pred_mean = sum(1.0 - cdf[m] for m in range(0, CRPS_M_MAX + 1))
        p10 = next(m for m in range(0, CRPS_M_MAX + 1) if cdf[m] >= 0.10)
        p90 = next(m for m in range(0, CRPS_M_MAX + 1) if cdf[m] >= 0.90)
        row = {"season": fx["season"], "date": fx["date"].isoformat(),
               "pitcher_id": fx["pitcher_id"], "game_pk": fx["game_pk"],
               "block": f"{fx['season']}-{fx['date'].isocalendar()[0]}W{fx['date'].isocalendar()[1]:02d}",
               "y": y, "pred_mean": pred_mean, "p10": p10, "p90": p90,
               "covered80": bool(p10 <= y <= p90),
               "tail_mass": 1.0 - cdf[CRPS_M_MAX],
               "crps_engine": crps_eng, "crps_b1": crps_b1, "crps_b2": crps_b2}
        rows.append(row)
        audit_by_key[(fx["season"], fx["pitcher_id"], fx["game_pk"], fx["date"].isoformat())] = row
        if (i + 1) % 500 == 0:
            print(f"scored {i + 1}/{len(scored)} fixtures", flush=True)

    for ar in audit_rows:
        pass  # excluded rows already appended
    scored_audit = []
    for fx in scored:
        r = audit_by_key[(fx["season"], fx["pitcher_id"], fx["game_pk"], fx["date"].isoformat())]
        scored_audit.append({**fx["audit_base"], "status": "SCORED",
                             "y_pitches": r["y"], "pred_mean": r["pred_mean"],
                             "p10": r["p10"], "p90": r["p90"],
                             "covered80": int(r["covered80"]),
                             "crps_engine": r["crps_engine"], "crps_b1": r["crps_b1"],
                             "crps_b2": r["crps_b2"], "tail_mass": r["tail_mass"]})
    all_audit = sorted(audit_rows + scored_audit,
                       key=lambda r: (r["date"], r["pitcher_id"], r["game_pk"]))
    os.makedirs(os.path.dirname(args.audit), exist_ok=True)
    with open(args.audit, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["season", "date", "pitcher_id", "game_pk",
                                          "pool_n", "status", "y_pitches", "pred_mean",
                                          "p10", "p90", "covered80", "crps_engine",
                                          "crps_b1", "crps_b2", "tail_mass"])
        w.writeheader()
        for r in all_audit:
            w.writerow(r)

    def summarize(sub_rows, all_rows_for_blocks=None):
        blocks = [r["block"] for r in sub_rows]
        d_b1 = np.array([r["crps_engine"] - r["crps_b1"] for r in sub_rows])
        d_b2 = np.array([r["crps_engine"] - r["crps_b2"] for r in sub_rows])
        return {
            "n": len(sub_rows),
            "crps_engine_mean": float(np.mean([r["crps_engine"] for r in sub_rows])),
            "crps_b1_mean": float(np.mean([r["crps_b1"] for r in sub_rows])),
            "crps_b2_mean": float(np.mean([r["crps_b2"] for r in sub_rows])),
            "delta_crps_vs_b1": block_bootstrap_ci(d_b1, blocks),
            "delta_crps_vs_b2": block_bootstrap_ci(d_b2, blocks),
            "mean_predicted": float(np.mean([r["pred_mean"] for r in sub_rows])),
            "mean_realized": float(np.mean([r["y"] for r in sub_rows])),
            "coverage80_empirical": float(np.mean([r["covered80"] for r in sub_rows])),
            "residual_tail_mass_mean": float(np.mean([r["tail_mass"] for r in sub_rows])),
            "residual_tail_mass_max": float(np.max([r["tail_mass"] for r in sub_rows])),
        }

    pooled = summarize(rows)
    per_season = {str(season): summarize(sub)
                  for season in (2024, 2025)
                  if (sub := [r for r in rows if r["season"] == season])}
    verdict = ("BEATS_BASELINE" if (pooled["delta_crps_vs_b1"]["entirely_below_zero"]
                                    and pooled["delta_crps_vs_b2"]["entirely_below_zero"])
               else "DOES_NOT_BEAT_BASELINE")
    results["metrics"] = {"pooled": pooled, "per_season": per_season}
    results["crps_truncation"] = {
        "m_range": [0, CRPS_M_MAX],
        "note": ("CRPS truncated at m=170 for engine/B1/B2 identically; mean "
                 "residual tail mass 1 - F(170) reported in metrics."),
    }
    results["methodology_notes"] = [
        "Gate applied to pooled paired dCRPS CIs vs both baselines; per-season CIs reported alongside.",
        "Exclusion precedence: SEALED_WINDOW and POOL_STARTS_LT_5 (undercard population), then PITCHES_NOT_MEASURED, then POOL_PITCH_COUNT_MISSING.",
        "B1 uses measured pitch counts over ALL prior same-season starts (no cap); B2 uses measured pitch counts over all starters' prior starts in the season to date; sealed-window starts removed from both.",
        "Predicted mean = sum_{m=0}^{170} (1 - F(m)); central 80% interval = [smallest m with F(m)>=0.10, smallest m with F(m)>=0.90].",
        "No per-line Brier table (spec section 5): DK hangs pitches at starter-specific lines; no canonical line set exists.",
    ]
    results["verdict"] = verdict
    with open(args.out, "w") as f:
        json.dump(results, f, indent=1)
    print(f"wrote {args.out}")
    print("M29", verdict, "n=", pooled["n"],
          "CRPS eng/b1/b2", round(pooled["crps_engine_mean"], 4),
          round(pooled["crps_b1_mean"], 4), round(pooled["crps_b2_mean"], 4),
          "dB1", round(pooled["delta_crps_vs_b1"]["mean_delta"], 4),
          (round(pooled["delta_crps_vs_b1"]["ci95_lo"], 4),
           round(pooled["delta_crps_vs_b1"]["ci95_hi"], 4)),
          "dB2", round(pooled["delta_crps_vs_b2"]["mean_delta"], 4),
          (round(pooled["delta_crps_vs_b2"]["ci95_lo"], 4),
           round(pooled["delta_crps_vs_b2"]["ci95_hi"], 4)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StopRun as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(3)
