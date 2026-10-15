"""EITHER_PITCHER dependence audit, HA / BB / ER (Stage 2, item M31).

Construction under measurement: sportsedge/pitcher_joint_engine.py
price_pitcher_market either-branch at main
83e0c396a4761ea3de80583be5e61e8ca2e07f9a (engine blob
00cba6f664e313b53ab0084e6f3f471a9d85b566, identical to the Phase 2
pin 12999fc22 blob), canonical raw-pool configuration
features = {"pitcher_a_history": [...], "pitcher_b_history": [...]}.

Governing spec: mlb_market_legs_20261014/SPEC_M31_EITHER_DEPENDENCE.md
SHA-256 5e0eb54368b35094e58de4300185e5f28d0e48bb1dfb9cda1c02b02917d65153
(verified at runtime; a mismatch stops the run before scoring),
as amended by AMENDMENT_M31_ULP_DISPOSITION.md (SHA-256
f1b55887489710d87d7d1ecd7b152d0ebfb12021129733742055e54fd189585f,
also verified at runtime): where the engine refuses an either-call
and an independent math.fsum recomputation of the Cartesian masses
shows the event mass within 1e-12 of a boundary (a pure
float-summation artifact), the probability is recovered from the
pinned module's own _posterior evaluated at the fsum masses
(category fsum masses expressed as proportions of the fsum total
weight, over/under/push assigned exactly as the either branch
assigns them, eff = min effective sample size as the branch
computes it). Every recovered call is flagged
ENGINE_ULP_DISPOSITION in the audit CSV and counted by cell in the
results, beside the original failure census. Any refusal not
meeting the boundary test stops the run. The first run under the
parent spec alone stopped with verdict
STOPPED_ENGINE_EITHER_MASS_ERROR (110 of 51,840 calls refused, all
full-coverage, total weight sum 1.0000000000000002); that census is
preserved in this run's results.

Label of output: RESEARCH_EVIDENCE -- retrospective measurement of a
construction's calibration error. NOT a market verdict, NOT
validation, NOT a promotion input. Verdict form: DEPENDENCE_MEASURED
(a measurement, not a pass/fail); the family stays behind
EITHER_PITCHER_DEPENDENCE_UNMEASURED regardless of outcome.

Population / pool lineage: identical to M29 / the Phase 2 undercard
evaluator -- the pool-construction functions (parse_starts,
production_order, engine_pool, all_prior) are copied verbatim from
eval_pitcher_undercard.py, their source identity is hashed and
recorded, and pool parity is inherited from the M29 evaluator's
fresh 25/25 run on this identical lineage (spec M31 section 6); the
M29 parity artifact is read and its status recorded here -- if it is
missing or not PASSED, this run stops.

Pairs: fixtures paired by game_pk within season; both starters must
independently be in the undercard population. The away starter
(gameLog isHome == False) is pitcher_a; pair entity "<away>|<home>".
Measurements per spec section 4: per-(stat, form, threshold)
calibration error with ISO-week block-bootstrap CIs (2000 resamples,
seed 20261015); joint-exceedance ratios at X+ thresholds; residual
correlations (Pearson + Spearman) of (realized - posterior mean)
across the two starters, posterior means from the swept
single-pitcher CDFs over the undercard grids (HA m=0..14, BB m=0..9,
ER m=0..11; E[X] = sum_m (1 - F(m)), truncated at the grid bound);
per-pair Brier (descriptive); Frechet bounds beside the independence
point value. Event-semantics hand-check (spec section 6) on >= 10
pairs re-derives the engine either-probability from the raw pools.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

HOME = os.path.expanduser("~")
REPO = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO / "mlb_market_legs_20261014" / "SPEC_M31_EITHER_DEPENDENCE.md"
SPEC_SHA256 = "5e0eb54368b35094e58de4300185e5f28d0e48bb1dfb9cda1c02b02917d65153"
AMENDMENT_PATH = REPO / "mlb_market_legs_20261014" / "AMENDMENT_M31_ULP_DISPOSITION.md"
AMENDMENT_SHA256 = "f1b55887489710d87d7d1ecd7b152d0ebfb12021129733742055e54fd189585f"
M29_RESULTS = REPO / "mlb_market_legs_20261014" / "results_m29_pitcher_pitches.json"
EXPECTED_MAIN = "83e0c396a4761ea3de80583be5e61e8ca2e07f9a"
EXPECTED_ENGINE_BLOB = "00cba6f664e313b53ab0084e6f3f471a9d85b566"
UNDERCARD_SCRIPT = os.path.join(
    HOME, "workspace/sportsedge/backtest_program_20261014/scripts/eval_pitcher_undercard.py")
CACHE = os.path.join(HOME, "workspace/tmp/bt_data/statsapi_cache")
DONE_PATH = os.path.join(HOME, "workspace/tmp/bt_data/ACQUISITION_DONE.json")
DEFAULT_OUT = str(REPO / "mlb_market_legs_20261014" / "results_m31_either_dependence.json")
DEFAULT_AUDIT = os.path.join(
    HOME, "workspace/sportsedge/mlb_market_legs_20261014/results/audit_m31_either_dependence.csv")
ROOT = "https://statsapi.mlb.com/api/v1"
SEED = 20261015
SEALED_START = date(2024, 7, 1)
SEALED_END = date(2024, 9, 1)

sys.path.insert(0, str(REPO))
from sportsedge.pitcher_joint_engine import ENGINE_VERSION, price_pitcher_market  # noqa: E402
from sportsedge.pitcher_joint_engine import (  # noqa: E402
    _normalize_pool as _engine_normalize_pool,
    _posterior as _engine_posterior,
    _value as _engine_value,
    _weights as _engine_weights,
)
from sportsedge.mlb_empirical_bayes import effective_sample_size as _engine_ess  # noqa: E402
from sportsedge.mlb_public_pitcher_history import MissingMLBHistory, _int, _outs  # noqa: E402

# stat key -> (single market, either market, field, grid m_max, X+ grid, or-fewer grid)
STATS = {
    "HA": {"single": "PITCHER_HITS_ALLOWED", "either": "EITHER_PITCHER_HITS_ALLOWED",
           "field": "hits_allowed", "m_max": 14,
           "xplus": [5, 6, 7, 8, 9, 10], "orfewer": [2, 3, 4, 5]},
    "BB": {"single": "PITCHER_BB", "either": "EITHER_PITCHER_BB",
           "field": "walks_allowed", "m_max": 9,
           "xplus": [3, 4, 5, 6], "orfewer": [0, 1, 2]},
    "ER": {"single": "PITCHER_ER", "either": "EITHER_PITCHER_ER",
           "field": "earned_runs", "m_max": 11,
           "xplus": [3, 4, 5, 6], "orfewer": [0, 1, 2]},
}
MID = {"HA": (6, 3), "BB": (4, 1), "ER": (4, 1)}


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
    names = ["parse_starts", "production_order", "engine_pool", "all_prior"]

    def grab(path):
        with open(path) as f:
            src = f.read()
        tree = ast.parse(src)
        out = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                out[node.name] = ast.get_source_segment(src, node)
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


def parse_sides(payload) -> dict:
    """{game_pk: is_home} for gamesStarted == 1 rows (audit/pairing
    only; never touches pool rows)."""
    out = {}
    if not isinstance(payload, dict) or not isinstance(payload.get("stats"), list):
        return out
    splits = [v for stat in payload["stats"]
              if isinstance(stat, dict) and isinstance(stat.get("splits"), list)
              for v in stat["splits"]]
    for row in splits:
        try:
            if _int(row["stat"]["gamesStarted"], "GAMES_STARTED") != 1:
                continue
            game_id = _int((row.get("game") or {})["gamePk"], "HISTORY_GAME_PK")
        except (ValueError, KeyError, TypeError, MissingMLBHistory):
            continue
        if isinstance(row.get("isHome"), bool):
            out[game_id] = row["isHome"]
    return out


# ---------------------------------------------------------------- bootstrap
def _block_index(block_keys: list[str]):
    blocks = sorted(set(block_keys))
    bidx = {b: i for i, b in enumerate(blocks)}
    return blocks, np.array([bidx[k] for k in block_keys])


def block_bootstrap_mean_ci(values: np.ndarray, block_keys: list[str],
                            seed: int = SEED, resamples: int = 2000) -> dict:
    values = np.asarray(values, dtype=float)
    blocks, bi = _block_index(block_keys)
    nb = len(blocks)
    bsums = np.zeros(nb)
    bcounts = np.zeros(nb)
    np.add.at(bsums, bi, values)
    np.add.at(bcounts, bi, 1.0)
    rng = np.random.default_rng(seed)
    samp = rng.integers(0, nb, size=(resamples, nb))
    means = (bsums[samp].sum(axis=1) / bcounts[samp].sum(axis=1))
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": float(values.mean()), "ci95_lo": float(lo), "ci95_hi": float(hi),
            "n_blocks": nb, "resamples": resamples}


def block_bootstrap_ratio_ci(num: np.ndarray, den: np.ndarray,
                             block_keys: list[str],
                             seed: int = SEED, resamples: int = 2000) -> dict:
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    blocks, bi = _block_index(block_keys)
    nb = len(blocks)
    ns = np.zeros(nb)
    ds = np.zeros(nb)
    np.add.at(ns, bi, num)
    np.add.at(ds, bi, den)
    rng = np.random.default_rng(seed)
    samp = rng.integers(0, nb, size=(resamples, nb))
    ratios = (ns[samp].sum(axis=1) / ds[samp].sum(axis=1))
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return {"ratio": float(num.sum() / den.sum()), "ci95_lo": float(lo),
            "ci95_hi": float(hi), "n_blocks": nb, "resamples": resamples,
            "realized_joint_rate": float(num.mean()),
            "mean_independence_product": float(den.mean())}


def _avg_ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    sx = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def block_bootstrap_corr_ci(a: np.ndarray, b: np.ndarray,
                            block_keys: list[str],
                            seed: int = SEED, resamples: int = 2000) -> dict:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    blocks, bi = _block_index(block_keys)
    nb = len(blocks)
    members = [np.where(bi == k)[0] for k in range(nb)]
    rng = np.random.default_rng(seed)
    pear, spear = [], []
    ra_all = _avg_ranks(a)
    rb_all = _avg_ranks(b)
    for _ in range(resamples):
        pick = rng.integers(0, nb, size=nb)
        idx = np.concatenate([members[k] for k in pick])
        pear.append(_pearson(a[idx], b[idx]))
        spear.append(_pearson(_avg_ranks(a[idx]), _avg_ranks(b[idx])))
    pear = np.array([v for v in pear if v == v])
    spear = np.array([v for v in spear if v == v])
    return {
        "pearson": {"value": _pearson(a, b),
                    "ci95_lo": float(np.percentile(pear, 2.5)),
                    "ci95_hi": float(np.percentile(pear, 97.5))},
        "spearman": {"value": _pearson(ra_all, rb_all),
                     "ci95_lo": float(np.percentile(spear, 2.5)),
                     "ci95_hi": float(np.percentile(spear, 97.5))},
        "n_blocks": nb, "resamples": resamples,
    }


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
    return {"done": done, "index": index, "pitcher_ids": pitcher_ids}


def build_population(universe: dict) -> dict:
    """Undercard population fixtures (identical definition to M29),
    each carrying is_home for pairing."""
    seasons = {}
    missing_gamelogs = []
    for season in (2024, 2025):
        by_pitcher = {}
        sides_by_pitcher = {}
        for pid in sorted(universe["pitcher_ids"][season]):
            payload = load_cache(gamelog_url(pid, season))
            if payload is None:
                missing_gamelogs.append({"pitcher_id": pid, "season": season})
                continue
            starts = parse_starts(payload)
            if starts:
                by_pitcher[pid] = production_order(starts)
            sides_by_pitcher[pid] = parse_sides(payload)
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
                    "is_home": sides_by_pitcher[pid].get(s["game_pk"]),
                })
        fixtures.sort(key=lambda x: (x["date"], x["pitcher_id"], x["game_pk"]))
        seasons[season] = {"fixtures": fixtures, "exclusions": dict(exclusions),
                           "candidate_regular_starts": cand_regular}
    return {"seasons": seasons, "missing_gamelogs": missing_gamelogs}


def assemble_pairs(population: dict) -> tuple[list[dict], dict]:
    pairs = []
    counts: dict = {}
    for season in (2024, 2025):
        by_game: dict[int, list[dict]] = defaultdict(list)
        for fx in population["seasons"][season]["fixtures"]:
            by_game[fx["game_pk"]].append(fx)
        c = {"distinct_game_pks_with_qualifying_fixture": len(by_game),
             "PAIR_SIDE_MISSING": 0, "PAIR_ANOMALY": 0, "pairs_scored": 0}
        for game_pk, fxs in sorted(by_game.items()):
            if len(fxs) == 1:
                c["PAIR_SIDE_MISSING"] += 1
                continue
            if len(fxs) != 2:
                c["PAIR_ANOMALY"] += 1
                continue
            f1, f2 = fxs
            if f1["date"] != f2["date"] or f1["is_home"] is None \
                    or f2["is_home"] is None or f1["is_home"] == f2["is_home"]:
                c["PAIR_ANOMALY"] += 1
                continue
            away, home = (f1, f2) if f1["is_home"] is False else (f2, f1)
            pairs.append({
                "season": season, "date": f1["date"], "game_pk": game_pk,
                "entity": f"{away['pitcher_id']}|{home['pitcher_id']}",
                "a": away, "b": home,
                "block": f"{season}-{f1['date'].isocalendar()[0]}W{f1['date'].isocalendar()[1]:02d}",
            })
            c["pairs_scored"] += 1
        counts[str(season)] = c
    pairs.sort(key=lambda p: (p["date"], p["game_pk"]))
    counts["pooled"] = {
        k: sum(v[k] for v in counts.values())
        for k in ("distinct_game_pks_with_qualifying_fixture",
                  "PAIR_SIDE_MISSING", "PAIR_ANOMALY", "pairs_scored")}
    return pairs, counts


# ---------------------------------------------------------------- engine helpers
def sweep_single(pool: list[dict], stat_key: str) -> dict:
    """Swept single-pitcher CDF over the undercard grid for one stat.
    Returns {m: F(m)} for m = 0..m_max; monotonicity asserted."""
    cfg = STATS[stat_key]
    cdf = {}
    for m in range(0, cfg["m_max"] + 1):
        res = price_pitcher_market({
            "market": cfg["single"], "side": "OVER", "line": m + 0.5,
            "features": {"history_pool": pool},
        })
        cdf[m] = 1.0 - float(res["model_p"])
    ms = sorted(cdf)
    for a, b in zip(ms, ms[1:]):
        if cdf[b] < cdf[a] - 1e-12:
            raise StopRun(f"CDF monotonicity violation {stat_key}")
    return cdf


def _dispositioned_prob(pool_a: list[dict], pool_b: list[dict],
                        stat_key: str, side: str, line: float) -> float:
    """Amendment 1 disposition: recover a refused either-call ONLY if
    an independent math.fsum recomputation of the Cartesian masses
    over the same raw pools shows the event mass within 1e-12 of a
    boundary (event ~= 1 with complement ~= 0, or the symmetric
    event ~= 0 case; push ~= 0 in both). The probability is the
    pinned module's own _posterior evaluated at the fsum masses:
    category masses are math.fsum sums of the branch's own Cartesian
    state weights (wx * wy over the _weights outputs), expressed as
    proportions of the fsum total weight, with over/under/push
    assigned exactly as the either branch assigns them and eff the
    min of the two pools' effective sample sizes as the branch
    computes it. Raises StopRun if the boundary test fails."""
    a = _engine_normalize_pool(pool_a, "pitcher_a_history")
    b = _engine_normalize_pool(pool_b, "pitcher_b_history")
    wa = _engine_weights(None, len(a), "pitcher_a_weights")
    wb = _engine_weights(None, len(b), "pitcher_b_weights")
    base = STATS[stat_key]["single"]
    states = [(_engine_value(x, base), _engine_value(y, base), wx * wy)
              for x, wx in zip(a, wa) for y, wy in zip(b, wb)]

    def is_event(x, y):
        return (x > line or y > line) if side == "OVER" else (x < line or y < line)

    def is_push(x, y):
        if not float(line).is_integer() or is_event(x, y):
            return False
        return x == line or y == line

    event_w = [w for x, y, w in states if is_event(x, y)]
    push_w = [w for x, y, w in states if is_push(x, y)]
    comp_w = [w for x, y, w in states if not is_event(x, y) and not is_push(x, y)]
    total = math.fsum([w for _, _, w in states])
    p_event = math.fsum(event_w) / total
    p_push = math.fsum(push_w) / total
    p_comp = math.fsum(comp_w) / total
    boundary = ((abs(p_event - 1.0) <= 1e-12 and abs(p_comp) <= 1e-12
                 and abs(p_push) <= 1e-12)
                or (abs(p_event) <= 1e-12 and abs(p_comp - 1.0) <= 1e-12
                    and abs(p_push) <= 1e-12))
    if not boundary:
        raise StopRun(
            f"engine either refusal NOT a ulp boundary artifact "
            f"({stat_key} {side} {line}): fsum masses event={p_event!r} "
            f"comp={p_comp!r} push={p_push!r}")
    eff = min(_engine_ess(wa, len(wa)), _engine_ess(wb, len(wb)))
    over, under = (p_event, p_comp) if side == "OVER" else (p_comp, p_event)
    post = _engine_posterior(over, under, p_push, eff, line, base)
    return float(post["p_over"] if side == "OVER" else post["p_under"])


def either_prob(pool_a: list[dict], pool_b: list[dict], stat_key: str,
                side: str, line: float,
                tracker: list | None = None) -> float:
    """Engine either-probability in the canonical configuration. On
    an engine refusal, Amendment 1's disposition is attempted (and
    recorded in tracker when one is supplied); a refusal that fails
    the amendment's boundary test raises StopRun."""
    try:
        res = price_pitcher_market({
            "market": STATS[stat_key]["either"], "side": side, "line": line,
            "features": {"pitcher_a_history": pool_a, "pitcher_b_history": pool_b},
        })
        return float(res["model_p"])
    except Exception:
        p = _dispositioned_prob(pool_a, pool_b, stat_key, side, line)
        if tracker is not None:
            tracker.append({"stat": stat_key, "side": side, "line": line})
        return p


def hand_either_prob(vals_a: list[int], vals_b: list[int],
                     side: str, line: float) -> float:
    """Independent re-derivation (spec section 6): Cartesian product of
    the raw pool values, uniform weights, effective N = min(nA, nB),
    Jeffreys 0.5-per-category posterior on the two settlement
    categories of a half-line (no push possible)."""
    n_a, n_b = len(vals_a), len(vals_b)
    hits = 0
    for x in vals_a:
        for y in vals_b:
            if side == "OVER":
                hits += 1 if (x > line or y > line) else 0
            else:
                hits += 1 if (x < line or y < line) else 0
    raw = hits / (n_a * n_b)
    eff = float(min(n_a, n_b))
    return (0.5 + eff * raw) / (1.0 + eff)


# ---------------------------------------------------------------- scoring
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--audit", default=DEFAULT_AUDIT)
    ap.add_argument("--limit-pairs", type=int, default=0,
                    help="smoke-test only; writes to --out with smoke flag")
    args = ap.parse_args()

    with open(SPEC_PATH, "rb") as f:
        spec_hash = hashlib.sha256(f.read()).hexdigest()
    if spec_hash != SPEC_SHA256:
        raise StopRun(f"spec hash mismatch: {spec_hash}")
    with open(AMENDMENT_PATH, "rb") as f:
        amendment_hash = hashlib.sha256(f.read()).hexdigest()
    if amendment_hash != AMENDMENT_SHA256:
        raise StopRun(f"amendment hash mismatch: {amendment_hash}")
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

    # Spec section 6: pool parity is covered by the M29 evaluator's
    # fresh 25/25 run on this identical lineage -- require its artifact.
    if not os.path.exists(M29_RESULTS):
        raise StopRun("M29 results artifact missing: parity lineage unverified")
    with open(M29_RESULTS) as f:
        m29 = json.load(f)
    m29_parity = (m29.get("parity") or {}).get("status")
    m29_identity = (m29.get("pool_code_identity_vs_undercard_evaluator") or {}).get("all_identical")
    if m29_parity != "PASSED" or m29_identity is not True:
        raise StopRun(f"M29 parity lineage not clean: parity={m29_parity} identity={m29_identity}")

    universe = load_universe()
    population = build_population(universe)
    identity = pool_code_identity()
    if not identity["all_identical"]:
        raise StopRun("pool code differs from undercard evaluator: parity lineage broken")

    pairs, pair_counts = assemble_pairs(population)
    pop_counts = {str(s): {"candidate_regular_starts": population["seasons"][s]["candidate_regular_starts"],
                           "undercard_exclusions": population["seasons"][s]["exclusions"],
                           "undercard_population_fixtures": len(population["seasons"][s]["fixtures"])}
                  for s in (2024, 2025)}

    results: dict = {
        "item": "M31_EITHER_PITCHER_DEPENDENCE",
        "label": "RESEARCH_EVIDENCE",
        "evidence_class": ("RETROSPECTIVE_MEASUREMENT of the independence "
                           "construction's calibration error. NOT a market "
                           "verdict, NOT validation, NOT a promotion input. "
                           "Family state unchanged: EITHER_PITCHER_DEPENDENCE_UNMEASURED."),
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
            "config": "price_pitcher_market either-branch, features={'pitcher_a_history': [...], 'pitcher_b_history': [...]} raw pools only",
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
        "parity_lineage": {
            "source": "M29 evaluator fresh run on the identical pool lineage (spec M31 section 6)",
            "m29_results_file": str(M29_RESULTS),
            "m29_parity_status": m29_parity,
            "m29_parity_successes": (m29.get("parity") or {}).get("successes"),
            "m29_pool_code_identity_all_identical": m29_identity,
        },
        "population": pop_counts,
        "counts": pair_counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "bootstrap": {"blocks": "ISO calendar weeks", "resamples": 2000, "seed": SEED},
    }
    if args.limit_pairs:
        pairs = pairs[: args.limit_pairs]
        results["smoke_test_limit_pairs"] = args.limit_pairs

    # ---- engine either-branch census (gate before scoring)
    # Every (pair, stat, form, threshold) either-call is attempted in
    # the canonical configuration. Refusals are dispositioned per
    # Amendment 1 (fsum boundary test + the pinned module's own
    # _posterior); a refusal that fails the boundary test stops the
    # run, as before. The census below is the ORIGINAL failure census
    # of the stopped first run, regenerated identically and preserved
    # beside the disposition counts (amendment requirement 3).
    census_failures = []
    census_dispositions = []
    census_undispositionable = []
    census_total = 0
    for pair in pairs:
        for sk, cfg in STATS.items():
            field = cfg["field"]
            va = [r[field] for r in pair["a"]["pool"]]
            vb = [r[field] for r in pair["b"]["pool"]]
            wa = [1.0 / len(va)] * len(va)
            wb = [1.0 / len(vb)] * len(vb)
            tot = sum(wx * wy for wx in wa for wy in wb)
            for form, side, thr in (
                    [("XPLUS", "OVER", x) for x in cfg["xplus"]]
                    + [("ORFEWER", "UNDER", n_) for n_ in cfg["orfewer"]]):
                line = thr - 0.5 if side == "OVER" else thr + 0.5
                census_total += 1
                try:
                    price_pitcher_market({
                        "market": cfg["either"], "side": side, "line": line,
                        "features": {"pitcher_a_history": pair["a"]["pool"],
                                     "pitcher_b_history": pair["b"]["pool"]}})
                except Exception as exc:  # engine refusal: census + disposition
                    if side == "OVER":
                        hits = sum(1 for x in va for y in vb if x > line or y > line)
                    else:
                        hits = sum(1 for x in va for y in vb if x < line or y < line)
                    census_failures.append({
                        "season": pair["season"], "date": pair["date"].isoformat(),
                        "game_pk": pair["game_pk"], "pair_entity": pair["entity"],
                        "stat": sk, "form": form, "threshold": thr, "line": line,
                        "error_type": type(exc).__name__, "error": str(exc),
                        "cartesian_states": len(va) * len(vb),
                        "event_states": hits,
                        "full_coverage": hits == len(va) * len(vb),
                        "total_weight_sum": tot})
                    try:
                        _dispositioned_prob(pair["a"]["pool"], pair["b"]["pool"],
                                            sk, side, line)
                        census_dispositions.append(f"{sk}|{form}|{thr}")
                    except StopRun as stop_exc:
                        census_undispositionable.append({
                            "game_pk": pair["game_pk"], "stat": sk, "form": form,
                            "threshold": thr, "reason": str(stop_exc)})
    census_by_cell = dict(Counter(
        f"{f['stat']}|{f['form']}|{f['threshold']}" for f in census_failures))
    results["amendment"] = {"path": str(AMENDMENT_PATH), "sha256": amendment_hash}
    results["engine_either_census"] = {
        "total_either_calls": census_total,
        "failures": len(census_failures),
        "pairs_affected": len({f["game_pk"] for f in census_failures}),
        "all_failures_full_coverage": all(f["full_coverage"] for f in census_failures),
        "failure_total_weight_sums": sorted({f["total_weight_sum"] for f in census_failures}),
        "failures_by_cell": census_by_cell,
        "note": ("Original failure census, preserved per Amendment 1: "
                 "every failure is a full-coverage event whose "
                 "uniform-weight Cartesian sum is 1.0000000000000002, "
                 "so the raw event mass exceeds 1 by one floating-point "
                 "ulp (or its complement is -2.2e-16) and "
                 "posterior_settlement_mass refuses it. The stopped "
                 "first run (verdict STOPPED_ENGINE_EITHER_MASS_ERROR) "
                 "reported this census with no measurements; this "
                 "re-run under Amendment 1 dispositions each refusal "
                 "as declared there and proceeds to the section 4 "
                 "measurements."),
    }
    results["ulp_disposition"] = {
        "amendment": "AMENDMENT_M31_ULP_DISPOSITION.md",
        "dispositioned_calls": len(census_dispositions),
        "dispositioned_by_cell": dict(Counter(census_dispositions)),
        "pairs_affected": len({f["game_pk"] for f in census_failures
                               if f"{f['stat']}|{f['form']}|{f['threshold']}"
                               in set(census_dispositions)}),
        "undispositionable_refusals": census_undispositionable,
        "method": ("math.fsum category masses over the branch's "
                   "Cartesian state weights, expressed as proportions "
                   "of the fsum total weight; boundary test 1e-12; "
                   "probability from the pinned module's own "
                   "_posterior with branch assignment and eff."),
    }
    if census_undispositionable:
        results["verdict"] = "STOPPED_ENGINE_EITHER_MASS_ERROR"
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
        print("M31 STOPPED: refusal(s) failing the Amendment 1 boundary test: "
              f"{census_undispositionable}")
        return 2

    # ---- event-semantics hand-check (spec section 6 + Amendment 1:
    # >= 10 pairs and >= 3 dispositioned calls, all < 1e-9)
    hand_checks = []
    hand_pairs: set = set()
    hand_disp = 0
    for pair in pairs:
        if len(hand_pairs) >= 10 and hand_disp >= 3:
            break
        pool_a, pool_b = pair["a"]["pool"], pair["b"]["pool"]
        vals_a = [r["hits_allowed"] for r in pool_a]
        vals_b = [r["hits_allowed"] for r in pool_b]
        for form, side, line in (("XPLUS", "OVER", MID["HA"][0] - 0.5),
                                 ("ORFEWER", "UNDER", MID["HA"][1] + 0.5)):
            trk: list = []
            p_eng = either_prob(pool_a, pool_b, "HA", side, line, trk)
            p_hand = hand_either_prob(vals_a, vals_b, side, line)
            hand_checks.append({
                "game_pk": pair["game_pk"], "date": pair["date"].isoformat(),
                "stat": "HA", "form": form, "line": line,
                "engine_p": p_eng, "hand_p": p_hand,
                "abs_diff": abs(p_eng - p_hand),
                "dispositioned": bool(trk)})
            hand_disp += 1 if trk else 0
        hand_pairs.add(pair["game_pk"])
    hand_max = max((h["abs_diff"] for h in hand_checks), default=None)
    results["event_semantics_hand_check"] = {
        "n_pairs": len(hand_pairs),
        "n_checks": len(hand_checks),
        "n_dispositioned_checks": hand_disp,
        "max_abs_diff": hand_max,
        "checks": hand_checks,
        "note": ("Independent Cartesian-product re-derivation with the "
                 "Jeffreys posterior re-derived from the single-pitcher "
                 "path formula; HA at X+ 6 (line 5.5) and or-fewer 3 "
                 "(line 3.5); pairs scanned in (date, game_pk) order "
                 "until >= 10 pairs and >= 3 dispositioned calls are "
                 "covered (Amendment 1 additional verification)."),
    }
    if hand_max is None or hand_max >= 1e-9 or len(hand_pairs) < 10 or hand_disp < 3:
        results["verdict"] = "STOPPED_EVENT_SEMANTICS_CHECK"
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
        print("EVENT-SEMANTICS HAND CHECK FAILED; stopped")
        return 2

    # ---- per-pair computation
    # store[stat][form][thr] -> lists aligned with pairs
    store: dict = {sk: {"XPLUS": defaultdict(lambda: {"p": [], "y": [], "brier": [],
                                                       "flo": [], "fhi": [],
                                                       "both": [], "prod": []}),
                        "ORFEWER": defaultdict(lambda: {"p": [], "y": [], "brier": [],
                                                        "flo": [], "fhi": []})}
                   for sk in STATS}
    resid: dict = {sk: {"a": [], "b": []} for sk in STATS}
    audit_rows = []
    scoring_dispositions: list = []
    for i, pair in enumerate(pairs):
        disp_tracker: list = []
        pool_a, pool_b = pair["a"]["pool"], pair["b"]["pool"]
        audit = {"season": pair["season"], "date": pair["date"].isoformat(),
                 "game_pk": pair["game_pk"], "pair_entity": pair["entity"],
                 "pitcher_a_id": pair["a"]["pitcher_id"],
                 "pitcher_b_id": pair["b"]["pitcher_id"],
                 "pool_a_n": len(pool_a), "pool_b_n": len(pool_b)}
        for sk, cfg in STATS.items():
            field = cfg["field"]
            cdf_a = sweep_single(pool_a, sk)
            cdf_b = sweep_single(pool_b, sk)
            mean_a = sum(1.0 - cdf_a[m] for m in range(0, cfg["m_max"] + 1))
            mean_b = sum(1.0 - cdf_b[m] for m in range(0, cfg["m_max"] + 1))
            y_a = pair["a"]["outcome"][field]
            y_b = pair["b"]["outcome"][field]
            resid[sk]["a"].append(y_a - mean_a)
            resid[sk]["b"].append(y_b - mean_b)
            audit[f"{sk}_y_a"] = y_a
            audit[f"{sk}_y_b"] = y_b
            audit[f"{sk}_mean_a"] = mean_a
            audit[f"{sk}_mean_b"] = mean_b
            audit[f"{sk}_resid_a"] = y_a - mean_a
            audit[f"{sk}_resid_b"] = y_b - mean_b
            for x in cfg["xplus"]:
                p_e = either_prob(pool_a, pool_b, sk, "OVER", x - 0.5, disp_tracker)
                p_a = 1.0 - cdf_a[x - 1]
                p_b = 1.0 - cdf_b[x - 1]
                ev = 1.0 if (y_a >= x or y_b >= x) else 0.0
                cell = store[sk]["XPLUS"][x]
                cell["p"].append(p_e)
                cell["y"].append(ev)
                cell["brier"].append((p_e - ev) ** 2)
                cell["flo"].append(max(p_a, p_b))
                cell["fhi"].append(min(1.0, p_a + p_b))
                cell["both"].append(1.0 if (y_a >= x and y_b >= x) else 0.0)
                cell["prod"].append(p_a * p_b)
                if x == MID[sk][0]:
                    audit[f"{sk}_p_xplus_mid"] = p_e
                    audit[f"{sk}_ev_xplus_mid"] = int(ev)
            for n_ in cfg["orfewer"]:
                p_e = either_prob(pool_a, pool_b, sk, "UNDER", n_ + 0.5, disp_tracker)
                q_a = cdf_a[n_]
                q_b = cdf_b[n_]
                ev = 1.0 if (y_a <= n_ or y_b <= n_) else 0.0
                cell = store[sk]["ORFEWER"][n_]
                cell["p"].append(p_e)
                cell["y"].append(ev)
                cell["brier"].append((p_e - ev) ** 2)
                cell["flo"].append(max(q_a, q_b))
                cell["fhi"].append(min(1.0, q_a + q_b))
                if n_ == MID[sk][1]:
                    audit[f"{sk}_p_orfewer_mid"] = p_e
                    audit[f"{sk}_ev_orfewer_mid"] = int(ev)
        # flag this pair's dispositioned cells (Amendment 1 req. 3)
        disp_labels = []
        for t in disp_tracker:
            thr = int(t["line"] + 0.5) if t["side"] == "OVER" else int(t["line"] - 0.5)
            form = "XPLUS" if t["side"] == "OVER" else "ORFEWER"
            label = f"{t['stat']}|{form}|{thr}"
            disp_labels.append(label)
            scoring_dispositions.append(label)
        audit["engine_ulp_disposition"] = ";".join(
            f"ENGINE_ULP_DISPOSITION:{lbl}" for lbl in disp_labels)
        audit_rows.append(audit)
        if (i + 1) % 250 == 0:
            print(f"paired {i + 1}/{len(pairs)} games", flush=True)

    results["ulp_disposition"]["scoring_dispositioned_calls"] = len(scoring_dispositions)
    results["ulp_disposition"]["scoring_dispositioned_by_cell"] = dict(
        Counter(scoring_dispositions))
    results["ulp_disposition"]["census_matches_scoring"] = (
        dict(Counter(scoring_dispositions))
        == results["ulp_disposition"]["dispositioned_by_cell"])

    blocks = [p["block"] for p in pairs]
    season_arr = np.array([p["season"] for p in pairs])
    stats_out: dict = {}
    materiality: dict = {}
    for sk, cfg in STATS.items():
        forms_out: dict = {}
        mat_forms: dict = {}
        for form, grid in (("XPLUS", cfg["xplus"]), ("ORFEWER", cfg["orfewer"])):
            per_thr: dict = {}
            pair_contrib = np.zeros(len(pairs))
            for thr in grid:
                cell = store[sk][form][thr]
                p_arr = np.array(cell["p"])
                y_arr = np.array(cell["y"])
                d = p_arr - y_arr
                ci = block_bootstrap_mean_ci(d, blocks)
                entry = {
                    "threshold": thr, "n": len(pairs),
                    "mean_predicted": float(p_arr.mean()),
                    "observed_rate": float(y_arr.mean()),
                    "mean_signed_error": ci["mean"],
                    "error_ci95": [ci["ci95_lo"], ci["ci95_hi"]],
                    "n_blocks": ci["n_blocks"],
                    "brier_mean": float(np.mean(cell["brier"])),
                    "frechet_lo_mean": float(np.mean(cell["flo"])),
                    "frechet_hi_mean": float(np.mean(cell["fhi"])),
                    "per_season_mean_signed_error": {
                        str(s): float(d[season_arr == s].mean())
                        for s in (2024, 2025) if (season_arr == s).any()},
                    "material_overstatement_ci_lo_gt_plus_2pp": bool(ci["ci95_lo"] > 0.02),
                }
                if form == "XPLUS":
                    ratio = block_bootstrap_ratio_ci(
                        np.array(cell["both"]), np.array(cell["prod"]), blocks)
                    entry["joint_exceedance"] = ratio
                per_thr[str(thr)] = entry
                pair_contrib += d
            pair_contrib /= len(grid)
            pooled_ci = block_bootstrap_mean_ci(pair_contrib, blocks)
            material_thrs = [t for t, e in per_thr.items()
                              if e["material_overstatement_ci_lo_gt_plus_2pp"]]
            forms_out[form] = {
                "thresholds": per_thr,
                "pooled_mean_signed_error": {
                    "mean": pooled_ci["mean"],
                    "ci95": [pooled_ci["ci95_lo"], pooled_ci["ci95_hi"]],
                    "definition": "average across the form's grid thresholds of the per-threshold mean signed errors (equal weight per threshold)"},
            }
            mat_forms[form] = (
                "MATERIAL_OVERSTATEMENT at thresholds " + ", ".join(material_thrs)
                if material_thrs else
                "No threshold with 95% CI lower bound above +2pp; errors not "
                "shown material at the declared +2pp standard on this grid.")
        corr = block_bootstrap_corr_ci(np.array(resid[sk]["a"]),
                                       np.array(resid[sk]["b"]), blocks)
        corr["per_season_point_estimates"] = {}
        for s in (2024, 2025):
            m = season_arr == s
            if m.any():
                ra = np.array(resid[sk]["a"])[m]
                rb = np.array(resid[sk]["b"])[m]
                corr["per_season_point_estimates"][str(s)] = {
                    "pearson": _pearson(ra, rb),
                    "spearman": _pearson(_avg_ranks(ra), _avg_ranks(rb)),
                    "n": int(m.sum())}
        stats_out[sk] = {"forms": forms_out, "residual_correlation": corr}
        materiality[sk] = mat_forms
    results["stats"] = stats_out
    results["materiality_reading_spec_s5"] = materiality
    results["methodology_notes"] = [
        "Calibration error = predicted - observed (probability points); positive = the independence construction overstates the buyable yes-only side.",
        "Materiality (spec section 5, declared before results): a threshold is material iff the 95% CI lower bound of its signed error exceeds +0.02. CIs including 0 are reported as not distinguishable from zero on this sample, not as proof of independence.",
        "Posterior means for residuals: E[X] = sum_{m=0}^{m_max} (1 - F(m)) from the swept single-pitcher CDFs, truncated at the undercard grid bound (HA 14, BB 9, ER 11); identical construction for both starters.",
        "Frechet bounds: max(pA, pB) <= P(either) <= min(1, pA + pB) with pA/pB the engine single-pitcher posterior probabilities for the same event form; reported as per-pair means.",
        "Per-season calibration errors are point estimates (descriptive); CIs are pooled only. Residual-correlation CIs are pooled; per-season correlations are point estimates.",
        "Pair assembly: away starter (gameLog isHome == False) is pitcher_a; measurements are symmetric in A/B (max/min events).",
    ]
    results["verdict"] = "DEPENDENCE_MEASURED"

    os.makedirs(os.path.dirname(args.audit), exist_ok=True)
    fields = ["season", "date", "game_pk", "pair_entity", "pitcher_a_id",
              "pitcher_b_id", "pool_a_n", "pool_b_n", "engine_ulp_disposition"]
    for sk in STATS:
        fields += [f"{sk}_y_a", f"{sk}_y_b", f"{sk}_mean_a", f"{sk}_mean_b",
                   f"{sk}_resid_a", f"{sk}_resid_b", f"{sk}_p_xplus_mid",
                   f"{sk}_ev_xplus_mid", f"{sk}_p_orfewer_mid",
                   f"{sk}_ev_orfewer_mid"]
    with open(args.audit, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in audit_rows:
            w.writerow(r)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=1)
    print(f"wrote {args.out}")
    print("M31 DEPENDENCE_MEASURED pairs=", len(pairs),
          "handcheck max diff=", hand_max)
    for sk in STATS:
        so = stats_out[sk]
        print(sk,
              "X+ pooled err", round(so["forms"]["XPLUS"]["pooled_mean_signed_error"]["mean"], 4),
              "or-fewer pooled err", round(so["forms"]["ORFEWER"]["pooled_mean_signed_error"]["mean"], 4),
              "pearson", round(so["residual_correlation"]["pearson"]["value"], 4),
              "spearman", round(so["residual_correlation"]["spearman"]["value"], 4))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StopRun as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(3)
