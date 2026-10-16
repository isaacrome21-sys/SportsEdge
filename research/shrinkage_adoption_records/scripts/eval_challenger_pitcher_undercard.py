"""MLB pitcher undercard CHALLENGER evaluation — Model Fix Lane, family 2.

Implements PREREG_PITCHER_UNDERCARD.md exactly (SHA-256
9628b9626ccd42ed04f836f32ed51aa62d0eeca6b72deac782e1ef8622c5a41c,
verified at runtime). Test split: 2026 MLB regular season ONLY
(SINGLE_SPLIT). Label: RESEARCH_EVIDENCE. Production FROZEN.

Challenger (prereg section 3): uncapped raw pool distribution shrunk
toward the league distribution,
  P(v) = (count_pool(v) + K * L_m(d)(v)) / (n + K), K = 10,
markets OUTS / HITS_ALLOWED / BB / ER. Frozen arm = production joint
engine via the Phase 2 CDF sweep. CRPS uses the identical
support/truncation convention Phase 2 applied to B1/B2: sum over
m = 0..crps_m_max of (F(m) - 1{y <= m})^2 with F(m) = 1 - p_over(m+0.5).

Phases (single entry, gates in order):
  verify   parity (25/25) + sweep sanity (10 fixtures, <1e-12) +
           challenger unit checks -> verification JSON; stops on failure
  score    asserts verification passed, then full scoring -> results JSON
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "workspace/tmpgit/sportsedge-ci")
PREREG_PATH = os.path.join(
    HOME, "workspace/sportsedge/model_fix_20261014/specs/PREREG_PITCHER_UNDERCARD.md")
PREREG_SHA256 = "9628b9626ccd42ed04f836f32ed51aa62d0eeca6b72deac782e1ef8622c5a41c"
MAIN_SHA = "2a713380c7d49733577c238a126f487382634040"
PHASE2_MAIN = "12999fc227b6bce3f781749f99918d52c2080b9d"
BASE = os.path.join(HOME, "workspace/sportsedge/model_fix_20261014")
RESULTS_DIR = os.path.join(BASE, "results")
DEFAULT_OUT = os.path.join(RESULTS_DIR, "challenger_pitcher_undercard_results.json")
VERIFY_OUT = os.path.join(RESULTS_DIR, "challenger_pitcher_undercard_verification.json")
CACHE = os.path.join(HOME, "workspace/tmp/bt_data/statsapi_cache")
DONE_PATH = os.path.join(HOME, "workspace/tmp/bt_data/ACQUISITION_2026_DONE.json")
ROOT = "https://statsapi.mlb.com/api/v1"
SEED = 20261015
K_CHALLENGER = 10
SEALED_START = date(2024, 7, 1)  # never contains 2026 dates
SEALED_END = date(2024, 9, 1)
LOG_EPS = 1e-15
SEASON = 2026

sys.path.insert(0, REPO)
from sportsedge.pitcher_joint_engine import ENGINE_VERSION, price_pitcher_market  # noqa: E402
from sportsedge.mlb_public_pitcher_history import (  # noqa: E402
    MLBPitcherPublicSource, MissingMLBHistory, _int, _outs)

MARKETS = {
    "OUTS": {
        "engine_market": "PITCHER_OUTS", "field": "outs",
        "grid_lines": [i + 0.5 for i in range(0, 27)],
        "typical_lines": [14.5, 15.5, 16.5, 17.5, 18.5],
        "crps_m_max": 27,
    },
    "HITS_ALLOWED": {
        "engine_market": "PITCHER_HITS_ALLOWED", "field": "hits_allowed",
        "grid_lines": [i + 0.5 for i in range(0, 15)],
        "typical_lines": [4.5, 5.5, 6.5],
        "crps_m_max": 14,
    },
    "BB": {
        "engine_market": "PITCHER_BB", "field": "walks_allowed",
        "grid_lines": [i + 0.5 for i in range(0, 10)],
        "typical_lines": [1.5, 2.5],
        "crps_m_max": 9,
    },
    "ER": {
        "engine_market": "PITCHER_ER", "field": "earned_runs",
        "grid_lines": [i + 0.5 for i in range(0, 12)],
        "typical_lines": [1.5, 2.5],
        "crps_m_max": 11,
    },
}


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


def check_prereg():
    with open(PREREG_PATH, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    if h != PREREG_SHA256:
        raise StopRun(f"prereg hash mismatch: {h}")
    hashes = open(os.path.join(BASE, "specs", "SPEC_HASHES.txt")).read()
    assert PREREG_SHA256 in hashes
    return h


def evaluand_identity():
    files = ["sportsedge/mlb_batter_empirical.py",
             "sportsedge/mlb_public_batter_history.py",
             "sportsedge/pitcher_joint_engine.py",
             "sportsedge/mlb_public_pitcher_history.py"]
    out = {}
    for f in files:
        hs = {}
        for sha in (PHASE2_MAIN, MAIN_SHA):
            blob = subprocess.check_output(
                ["git", "-C", REPO, "show", f"{sha}:{f}"])
            hs[sha] = hashlib.sha256(blob).hexdigest()
        out[f] = {"phase2_12999fc22_sha256": hs[PHASE2_MAIN],
                  "main_2a713380c_sha256": hs[MAIN_SHA],
                  "byte_identical": hs[PHASE2_MAIN] == hs[MAIN_SHA]}
    return out


# ---------------------------------------------------------------- pools
def parse_starts(payload) -> list[dict]:
    """Phase 2 parse_starts, verbatim semantics."""
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
    ordered = sorted(starts, key=lambda x: (x["date"], x["game_pk"]), reverse=True)
    seen, latest = set(), []
    for s in ordered:
        if s["game_pk"] not in seen:
            seen.add(s["game_pk"])
            latest.append(s)
    return latest


def engine_pool(pitcher_starts_desc: list[dict], fixture_date: date) -> list[dict]:
    cand = [s for s in pitcher_starts_desc
            if s["date"] < fixture_date and not sealed(s["date"])]
    return [s["stats"] for s in cand[:12]]


def all_prior(pitcher_starts_desc: list[dict], fixture_date: date) -> list[dict]:
    return [s for s in pitcher_starts_desc
            if s["date"] < fixture_date and not sealed(s["date"])]


# ---------------------------------------------------------------- challenger
def challenger_pmf(pool_counts: Counter, n: int, league_counts: Counter,
                   league_n: int, K: float) -> dict:
    """Prereg section 3: P(v) = (count_pool(v) + K*L(v)) / (n + K)."""
    assert league_n > 0, "league distribution empty"
    support = set(pool_counts) | set(league_counts)
    return {v: (pool_counts.get(v, 0)
                + K * (league_counts.get(v, 0) / league_n)) / (n + K)
            for v in support}


def pmf_cdf_getter(pmf: dict):
    cum = {}
    total = 0.0
    for v in sorted(pmf):
        total += pmf[v]
        cum[v] = total

    def get(m: int) -> float:
        lo = None
        for v in cum:
            if v <= m:
                lo = v
            else:
                break
        if lo is None:
            return 0.0
        return cum[lo]
    return get


# ---------------------------------------------------------------- engine sweep
def sweep_engine(pool: list[dict], market_key: str) -> dict:
    cfg = MARKETS[market_key]
    lines = list(cfg["grid_lines"])
    if market_key == "OUTS":
        lines = lines + [27.5]
    p_over = {}
    for line in lines:
        res = price_pitcher_market({
            "market": cfg["engine_market"], "side": "OVER", "line": line,
            "features": {"history_pool": pool},
        })
        p_over[line] = float(res["model_p"])
    cdf = {}
    for m in range(0, cfg["crps_m_max"] + 1):
        cdf[m] = 1.0 - p_over[m + 0.5]
    ms = sorted(cdf)
    for a, b in zip(ms, ms[1:]):
        if cdf[b] < cdf[a] - 1e-12:
            raise StopRun(
                f"CDF monotonicity violation {market_key}: F({a})={cdf[a]} > F({b})={cdf[b]}")
    return {"p_over": p_over, "cdf": cdf}


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
        raise StopRun("ACQUISITION_2026_DONE.json missing: scoring is prohibited")
    with open(DONE_PATH) as f:
        done = json.load(f)
    if done.get("failures"):
        raise StopRun(f"acquisition failures present: {done['failures']}")
    index_path = os.path.join(CACHE, "index.json")
    with open(index_path) as f:
        index = json.load(f)
    pitcher_ids = set()
    for url in index:
        if "/people/" in url and "group=pitching" in url:
            pid = int(url.split("/people/")[1].split("/")[0])
            season = int(url.rsplit("season=", 1)[1])
            if season == SEASON:
                pitcher_ids.add(pid)
    players = {}
    payload = load_cache(f"{ROOT}/sports/1/players?season={SEASON}")
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
    gametype_counts = Counter()
    missing_gamelogs = []
    by_pitcher = {}
    for pid in sorted(universe["pitcher_ids"]):
        payload = load_cache(gamelog_url(pid, SEASON))
        if payload is None:
            missing_gamelogs.append({"pitcher_id": pid, "season": SEASON})
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
                "season": SEASON, "outcome": s["stats"], "pool": pool,
                "prior_all": all_prior(starts_desc, d),
            })
    fixtures.sort(key=lambda x: (x["date"], x["pitcher_id"], x["game_pk"]))
    events = []
    for pid, starts_desc in by_pitcher.items():
        for s in starts_desc:
            if not sealed(s["date"]):
                events.append(s)
    events.sort(key=lambda x: x["date"])
    counts = {mk: Counter() for mk in MARKETS}
    totals = 0
    ei = 0
    b2_by_id = {}
    for fx in fixtures:
        while ei < len(events) and events[ei]["date"] < fx["date"]:
            ev = events[ei]
            for mk, cfg in MARKETS.items():
                counts[mk][ev["stats"][cfg["field"]]] += 1
            totals += 1
            ei += 1
        b2_by_id[id(fx)] = ({mk: Counter(counts[mk]) for mk in MARKETS}, totals)
    return {"fixtures": fixtures, "exclusions": dict(exclusions),
            "candidate_regular_starts": cand_regular,
            "b2": b2_by_id, "by_pitcher": by_pitcher,
            "gametype_counts": dict(gametype_counts),
            "missing_gamelogs": missing_gamelogs}


# ---------------------------------------------------------------- parity
def run_parity(universe: dict, population: dict) -> dict:
    live_fetches: list[str] = []

    def hybrid_getter(url: str):
        if "/people/" in url and "gameLog" in url:
            data = load_cache(url)
            if data is None:
                raise StopRun(f"parity gameLog cache MISS (stop): {url}")
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
    for fx in population["fixtures"]:
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
            "sampling_note": ("Phase 2 sampling rule transposed to 2026: "
                              "candidates restricted to fixtures where the "
                              "sealed filter is inactive (automatic in 2026), "
                              "schedule gameDate UTC date == gameLog date, "
                              "kickoff >= 01:00 UTC; production resolves the "
                              "fixture via schedule probablePitcher; refusals "
                              "counted and replaced; as_of = kickoff - 30 min.")}


def sweep_sanity(scored: list[dict]) -> dict:
    sanity_idx = [i for i, _ in sorted(
        enumerate(scored), key=lambda t: (t[1]["date"], t[1]["pitcher_id"]))[:10]]
    sanity = {"n_fixtures": len(sanity_idx), "checks": {}, "max_abs_diff": 0.0}
    for mk, cfg in MARKETS.items():
        med_line = sorted(cfg["typical_lines"])[(len(cfg["typical_lines"]) - 1) // 2]
        diffs = []
        for i in sanity_idx:
            fx = scored[i]
            sw = sweep_engine(fx["pool"], mk)
            direct = price_pitcher_market({
                "market": cfg["engine_market"], "side": "OVER", "line": med_line,
                "features": {"history_pool": fx["pool"]}})["model_p"]
            swept_cdf_val = sw["cdf"][int(med_line - 0.5)]
            diffs.append(abs(float(direct) - (1.0 - swept_cdf_val)))
            diffs.append(abs(float(direct) - sw["p_over"][med_line]))
        sanity["checks"][mk] = {
            "median_typical_line_lower_median": med_line,
            "max_abs_diff": max(diffs) if diffs else None,
            "note": ("identity checked: direct model_p(OVER, L) == swept "
                     "p_over(L) == 1 - F(L-0.5)")}
        sanity["max_abs_diff"] = max(sanity["max_abs_diff"],
                                     max(diffs) if diffs else 0.0)
    sanity["passed"] = sanity["max_abs_diff"] < 1e-12
    return sanity


def unit_checks() -> dict:
    rng = random.Random(SEED)
    worst_sum = 0.0
    worst_k0 = 0.0
    trials = 0
    for _ in range(300):
        n = rng.randint(5, 30)
        vals = [rng.choice([0, 1, 2, 3, 4, 5]) for _ in range(n)]
        counts = Counter(vals)
        ln = rng.randint(200, 5000)
        lvals = [rng.choice([0, 1, 1, 2, 2, 3, 4]) for _ in range(ln)]
        lcounts = Counter(lvals)
        pmf = challenger_pmf(counts, n, lcounts, ln, K_CHALLENGER)
        worst_sum = max(worst_sum, abs(sum(pmf.values()) - 1.0))
        pmf0 = challenger_pmf(counts, n, lcounts, ln, 0)
        emp = {v: c / n for v, c in counts.items()}
        worst_k0 = max(worst_k0, max(abs(pmf0.get(v, 0) - emp.get(v, 0))
                                     for v in set(pmf0) | set(emp)))
        trials += 1
    return {
        "pmf_sums_to_1": {"trials": trials, "max_abs_dev": worst_sum,
                          "tol": 1e-12, "passed": worst_sum < 1e-12},
        "k_to_0_reduces_to_B1_distribution": {
            "trials": trials, "max_abs_dev": worst_k0,
            "passed": worst_k0 < 1e-15},
        "all_passed": worst_sum < 1e-12 and worst_k0 < 1e-15,
    }


def assemble_scored(universe, population):
    b2map = population["b2"]
    scored = []
    for fx in population["fixtures"]:
        counts, total = b2map[id(fx)]
        scored.append({"season": SEASON, "pitcher_id": fx["pitcher_id"],
                       "date": fx["date"], "game_pk": fx["game_pk"],
                       "outcome": fx["outcome"], "pool": fx["pool"],
                       "prior_all": fx["prior_all"],
                       "b2_counts": counts, "b2_total": total})
    return scored


# ---------------------------------------------------------------- phases
def phase_verify() -> int:
    prereg_hash = check_prereg()
    universe = load_universe()
    population = build_population(universe)
    parity = run_parity(universe, population)
    out = {"prereg_sha256": prereg_hash, "parity": parity,
           "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    if parity["status"] != "PASSED":
        out["status"] = "STOPPED_PARITY_GATE"
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(VERIFY_OUT, "w") as f:
            json.dump(out, f, indent=1)
        print("PARITY GATE FAILED; stopped before scoring")
        return 2
    scored = assemble_scored(universe, population)
    sanity = sweep_sanity(scored)
    out["sweep_sanity"] = sanity
    if not sanity["passed"]:
        out["status"] = "STOPPED_SWEEP_SANITY"
        with open(VERIFY_OUT, "w") as f:
            json.dump(out, f, indent=1)
        print("SWEEP SANITY FAILED; stopped before scoring")
        return 2
    units = unit_checks()
    out["unit_checks"] = units
    out["status"] = "PASSED" if units["all_passed"] else "STOPPED_UNIT_CHECKS"
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(VERIFY_OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"VERIFY {out['status']}: parity {parity['successes']}/25, "
          f"sweep max_abs_diff={sanity['max_abs_diff']}, units={units['all_passed']}")
    return 0 if out["status"] == "PASSED" else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["verify", "score"])
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    if args.phase == "verify":
        return phase_verify()

    prereg_hash = check_prereg()
    if not os.path.exists(VERIFY_OUT):
        raise StopRun("verification file missing: run verify first")
    ver = json.load(open(VERIFY_OUT))
    if ver.get("status") != "PASSED":
        raise StopRun(f"verification not PASSED: {ver.get('status')}")
    universe = load_universe()
    population = build_population(universe)
    scored = assemble_scored(universe, population)

    results: dict = {
        "label": "RESEARCH_EVIDENCE — retrospective calibration evaluation. NOT a market verdict, NOT validation, NOT a promotion input.",
        "family": "MLB pitcher undercard challenger (Model Fix Lane, family 2)",
        "evaluation": "MLB pitcher undercard calibration, 2026 test split",
        "prereg": {"path": PREREG_PATH, "sha256": prereg_hash},
        "repo": {"main": MAIN_SHA, "phase2_main": PHASE2_MAIN,
                 "evaluand_identity": evaluand_identity()},
        "engine_version": ENGINE_VERSION,
        "engine_config": "price_pitcher_market, features={'history_pool': [...]} only (canonical phone-path configuration)",
        "challenger": {
            "construction": "P(v) = (count_pool(v) + K * L_m(d)(v)) / (n + K), K=10; pool = ALL prior same-season starts (gamesStarted==1, strictly prior dates, no 12-start cap = B1's pool); L = pooled empirical distribution over all starters' prior starts season-to-date (Phase 2 B2 construction)",
            "K": K_CHALLENGER},
        "split": {"case": "SINGLE_SPLIT", "test_season": 2026,
                  "design_seasons": [2024, 2025],
                  "sealed_window": "not applicable to 2026 (prereg section 4)"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "acquisition": {
            "manifest": DONE_PATH,
            "failures": universe["done"].get("failures", []),
            "players_2026": universe["done"].get("players_2026"),
            "gamelog_urls": universe["done"].get("gamelog_urls"),
            "missing_pitcher_gamelog_payloads_in_cache": population["missing_gamelogs"],
        },
        "population": {
            "gametype_distribution_all_parsed_starts": population["gametype_counts"],
            "candidate_regular_starts": population["candidate_regular_starts"],
            "exclusions": population["exclusions"],
            "scored_fixtures": len(population["fixtures"]),
        },
        "parity": ver["parity"],
        "sweep_sanity": ver["sweep_sanity"],
        "unit_checks": ver["unit_checks"],
    }

    sweep_cache: dict = {}

    def get_sweep(i: int, mk: str):
        key = (i, mk)
        if key not in sweep_cache:
            sweep_cache[key] = sweep_engine(scored[i]["pool"], mk)
        return sweep_cache[key]

    per_market_rows: dict = {mk: [] for mk in MARKETS}
    tail_mass = {mk: [] for mk in MARKETS}
    beyond_grid = Counter()
    pmf_sum_worst = 0.0
    for i, fx in enumerate(scored):
        for mk, cfg in MARKETS.items():
            y = fx["outcome"][cfg["field"]]
            sw = get_sweep(i, mk)
            m_max = cfg["crps_m_max"]
            crps_eng = crps_from_cdf(lambda m, c=sw["cdf"]: c[m], m_max, y)
            b1_counts = Counter(s["stats"][cfg["field"]] for s in fx["prior_all"])
            n_b1 = sum(b1_counts.values())
            b1_get = emp_cdf_getter(b1_counts, n_b1)
            crps_b1 = crps_from_cdf(b1_get, m_max, y)
            b2_get = emp_cdf_getter(fx["b2_counts"][mk], fx["b2_total"])
            crps_b2 = crps_from_cdf(b2_get, m_max, y)
            pmf_ch = challenger_pmf(b1_counts, n_b1, fx["b2_counts"][mk],
                                    fx["b2_total"], K_CHALLENGER)
            pmf_sum_worst = max(pmf_sum_worst,
                                abs(sum(pmf_ch.values()) - 1.0))
            ch_get = pmf_cdf_getter(pmf_ch)
            crps_ch = crps_from_cdf(ch_get, m_max, y)
            tail_mass[mk].append(1.0 - sw["cdf"][m_max])
            if y > m_max:
                beyond_grid[mk] += 1
            row = {"season": fx["season"], "date": fx["date"].isoformat(),
                   "pitcher_id": fx["pitcher_id"], "game_pk": fx["game_pk"],
                   "block": f"{fx['season']}-{fx['date'].isocalendar()[0]}W{fx['date'].isocalendar()[1]:02d}",
                   "y": y, "crps_engine": crps_eng, "crps_ch": crps_ch,
                   "crps_b1": crps_b1, "crps_b2": crps_b2, "lines": {}}
            for line in cfg["typical_lines"]:
                ind = 1.0 if y > line else 0.0
                m = int(line - 0.5)
                p_eng = sw["p_over"][line]
                p_b1 = 1.0 - b1_get(m)
                p_b2 = 1.0 - b2_get(m)
                p_ch = 1.0 - ch_get(m)

                def brier(p): return (p - ind) ** 2

                def logloss(p):
                    pc = min(max(p, LOG_EPS), 1.0 - LOG_EPS)
                    return -(ind * math.log(pc) + (1 - ind) * math.log(1 - pc))
                row["lines"][str(line)] = {
                    "engine": {"p_over": p_eng, "brier": brier(p_eng),
                               "logloss": logloss(p_eng)},
                    "challenger": {"p_over": p_ch, "brier": brier(p_ch),
                                   "logloss": logloss(p_ch)},
                    "b1": {"p_over": p_b1, "brier": brier(p_b1),
                           "logloss": logloss(p_b1)},
                    "b2": {"p_over": p_b2, "brier": brier(p_b2),
                           "logloss": logloss(p_b2)},
                    "outcome_over": bool(ind),
                }
            per_market_rows[mk].append(row)
        if (i + 1) % 500 == 0:
            print(f"scored {i + 1}/{len(scored)} fixtures", flush=True)
    assert pmf_sum_worst < 1e-12, f"challenger PMF sum dev {pmf_sum_worst}"
    results["challenger_pmf_sum_max_abs_dev_over_scored_fixtures"] = pmf_sum_worst

    markets_out = {}
    for mk, cfg in MARKETS.items():
        rows = per_market_rows[mk]
        blocks = [r["block"] for r in rows]

        def d(key_a, key_b):
            return np.array([r[key_a] - r[key_b] for r in rows])
        ci_ch_frozen = block_bootstrap_ci(d("crps_ch", "crps_engine"), blocks)
        ci_ch_b1 = block_bootstrap_ci(d("crps_ch", "crps_b1"), blocks)
        ci_ch_b2 = block_bootstrap_ci(d("crps_ch", "crps_b2"), blocks)
        ci_fr_b1 = block_bootstrap_ci(d("crps_engine", "crps_b1"), blocks)
        ci_fr_b2 = block_bootstrap_ci(d("crps_engine", "crps_b2"), blocks)
        per_line = {}
        for line in cfg["typical_lines"]:
            entry = {}
            for who in ("engine", "challenger", "b1", "b2"):
                entry[who] = {
                    "brier_mean": float(np.mean([r["lines"][str(line)][who]["brier"] for r in rows])),
                    "logloss_mean": float(np.mean([r["lines"][str(line)][who]["logloss"] for r in rows])),
                    "p_over_mean": float(np.mean([r["lines"][str(line)][who]["p_over"] for r in rows])),
                }
            entry["n"] = len(rows)
            entry["outcome_over_rate"] = float(
                np.mean([r["lines"][str(line)]["outcome_over"] for r in rows]))
            per_line[str(line)] = entry
        verdict = ("ADOPT-CANDIDATE"
                   if (ci_ch_frozen["entirely_below_zero"]
                       and ci_ch_b1["entirely_below_zero"]
                       and ci_ch_b2["entirely_below_zero"])
                   else "KEEP FROZEN")
        markets_out[mk] = {
            "engine_market": cfg["engine_market"], "n": len(rows),
            "crps_engine_mean": float(np.mean([r["crps_engine"] for r in rows])),
            "crps_challenger_mean": float(np.mean([r["crps_ch"] for r in rows])),
            "crps_b1_mean": float(np.mean([r["crps_b1"] for r in rows])),
            "crps_b2_mean": float(np.mean([r["crps_b2"] for r in rows])),
            "delta_crps_challenger_vs_FROZEN": ci_ch_frozen,
            "delta_crps_challenger_vs_B1": ci_ch_b1,
            "delta_crps_challenger_vs_B2": ci_ch_b2,
            "delta_crps_FROZEN_vs_B1_descriptive": ci_fr_b1,
            "delta_crps_FROZEN_vs_B2_descriptive": ci_fr_b2,
            "per_line_brier_logloss_descriptive": per_line,
            "verdict": verdict,
        }
    results["markets"] = markets_out
    results["tail_treatment"] = {
        "rule": ("CRPS convention restated (identical to Phase 2's "
                 "application to B1/B2, now applied to all four arms): "
                 "CRPS = sum over m = 0..crps_m_max of (F(m) - 1{y <= m})^2 "
                 "with F(m) = 1 - p_over(m + 0.5) for the engine sweep and "
                 "F(m) = predictive PMF mass at values <= m for challenger, "
                 "B1 and B2. Bounds: OUTS m=0..27 (engine support; F(27)=1 "
                 "via line 27.5), HITS_ALLOWED m=0..14, BB m=0..9, "
                 "ER m=0..11 (Phase 2 spec grid bounds). Truncation omits a "
                 "non-negative tail penalty for every scorer."),
        "per_market": {mk: {"crps_m_range": [0, MARKETS[mk]["crps_m_max"]],
                            "engine_residual_tail_mass_mean": float(np.mean(tail_mass[mk])),
                            "engine_residual_tail_mass_max": float(np.max(tail_mass[mk])),
                            "fixtures_with_outcome_beyond_crps_bound": int(beyond_grid[mk])}
                       for mk in MARKETS},
    }
    results["methodology_notes"] = [
        "Gate (prereg section 6): ADOPT-CANDIDATE per market iff challenger paired dCRPS 95% CI (ISO-week block bootstrap, 2000 resamples, seed 20261015) is entirely < 0 against FROZEN and B1 and B2. Otherwise KEEP FROZEN.",
        "Log loss clipped at 1e-15 for all scorers (Phase 2 convention; descriptive only).",
        "BB/ER median typical line for sweep sanity: lower median (1.5).",
        "Exclusion precedence: POOL_STARTS_LT_5 only (sealed window not applicable to 2026).",
        "Fixtures are regular-season (gameType == 'R') starts only.",
        "CDF monotonicity asserted per fixture per market during sweeps; any violation raises StopRun.",
        "Challenger vs B1 isolates the league shrinkage alone: the challenger's base pool equals B1's pool (prereg section 5).",
    ]
    results["status"] = "COMPLETED"
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=1)
    print(f"wrote {args.out}")
    for mk in MARKETS:
        mo = markets_out[mk]
        print(mk, mo["verdict"], "n=", mo["n"],
              "ch", round(mo["crps_challenger_mean"], 4),
              "fr", round(mo["crps_engine_mean"], 4),
              "b1", round(mo["crps_b1_mean"], 4),
              "b2", round(mo["crps_b2_mean"], 4))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StopRun as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(3)
