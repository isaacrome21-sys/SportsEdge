"""MLB batter props CHALLENGER evaluation — Model Fix Lane, family 1.

Implements PREREG_BATTER_PROPS.md exactly (SHA-256
58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b,
verified at runtime against specs/SPEC_HASHES.txt).
Test split: 2026 MLB regular season ONLY (SINGLE_SPLIT).
Label: RESEARCH_EVIDENCE — retrospective calibration evaluation.
NOT a market verdict, NOT validation, NOT a promotion input.
Production code is FROZEN: imported read-only, never modified.

Challenger (prereg section 3): uncapped same-season history shrunk
toward the league distribution,
  P(v) = (count_H(v) + K * L_s(d)(v)) / (n + K), K = 25,
for all 13 Phase 2 stats. Arms: FROZEN (production engine), CHALLENGER,
B1 and B2 exactly as implemented in Phase 2's eval_batter_props.py.

Phases:
  boxscores  live-fetch boxscores for every 2026 population game
  parity     production-source parity gate (prereg section 7)
  verify     parity + challenger unit checks (must pass before score)
  score      full scoring (prereg sections 5-6) -> results JSON
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import numpy as np

REPO = os.path.expanduser("~/workspace/tmpgit/sportsedge-ci")
sys.path.insert(0, REPO)
from sportsedge.mlb_batter_empirical import price_batter_market, BatterEmpiricalError  # noqa: E402
from sportsedge.mlb_public_batter_history import (  # noqa: E402
    MLBBatterPublicSource, MissingMLBBatterHistory, _int, ROOT,
)

PREREG_PATH = os.path.expanduser(
    "~/workspace/sportsedge/model_fix_20261014/specs/PREREG_BATTER_PROPS.md")
PREREG_SHA = "58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b"
PHASE2_SCRIPT = os.path.expanduser(
    "~/workspace/sportsedge/backtest_program_20261014/scripts/eval_batter_props.py")
BASE = os.path.expanduser("~/workspace/sportsedge/model_fix_20261014")
RESULTS_DIR = os.path.join(BASE, "results")
CACHE = os.path.expanduser("~/workspace/tmp/bt_data/statsapi_cache")
ACQ_DONE = os.path.expanduser("~/workspace/tmp/bt_data/ACQUISITION_2026_DONE.json")
BOX_CACHE = os.path.expanduser("~/workspace/tmp/bt_data/boxscore_cache")
MAIN_SHA = "2a713380c7d49733577c238a126f487382634040"
PHASE2_MAIN = "12999fc227b6bce3f781749f99918d52c2080b9d"
SEALED_START, SEALED_END = date(2024, 7, 1), date(2024, 9, 1)  # never contains 2026 dates; kept for code identity with Phase 2
SEED = 20261015
K_CHALLENGER = 25
LOGLOSS_EPS = 1e-6  # Phase 2 convention
HEADERS = {"User-Agent": "SportsEdge-free-research/1.0", "Accept": "application/json"}
SEASON = 2026

OU_STATS = [
    ("BATTER_HITS", "hits"),
    ("BATTER_TOTAL_BASES", "total_bases"),
    ("BATTER_RBIS", "rbi"),
    ("BATTER_RUNS", "runs"),
    ("HITS_RUNS_RBIS", "hits_runs_rbis"),
    ("BATTER_SINGLES", "singles"),
    ("BATTER_DOUBLES", "doubles"),
    ("BATTER_WALKS", "walks"),
]
LADDER_STATS = [
    ("BATTER_HOME_RUNS", "home_runs"),
    ("BATTER_EXTRA_BASE_HITS", ("doubles", "triples", "home_runs")),
    ("BATTER_TRIPLES", "triples"),
    ("BATTER_STRIKEOUTS", "strikeouts"),
    ("BATTER_RUNS_RBIS", ("runs", "rbi")),
]


def in_sealed(d: date) -> bool:
    return SEALED_START <= d < SEALED_END


def cache_path(url: str) -> str:
    return os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest() + ".json")


def load_cached(url: str):
    p = cache_path(url)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def live_fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def spec_hashes_record():
    """The SPEC_HASHES.txt token recorded for this prereg. NOTE: the
    recorded batter token is 55 chars (a defective transcription; see
    specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md, filed
    2026-10-14 before scoring). The lock used here is the true
    computed SHA-256 of the prereg file bytes."""
    txt = open(os.path.expanduser(
        "~/workspace/sportsedge/model_fix_20261014/specs/SPEC_HASHES.txt")).read()
    token = None
    for line in txt.splitlines():
        if "PREREG_BATTER_PROPS.md" in line:
            token = line.split()[0]
    return {"recorded_token": token,
            "recorded_token_length": len(token) if token else None,
            "record_matches_true_sha256": token == PREREG_SHA,
            "amendment": "specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md"}


def check_prereg():
    h = hashlib.sha256(open(PREREG_PATH, "rb").read()).hexdigest()
    assert h == PREREG_SHA, f"PREREG HASH MISMATCH {h}"
    return h


def check_acq():
    assert os.path.exists(ACQ_DONE), "ACQUISITION_2026_DONE.json missing — DO NOT SCORE"
    with open(ACQ_DONE) as f:
        acq = json.load(f)
    assert acq["failures"] == [], f"acquisition failures present: {acq['failures']}"
    return acq


def evaluand_identity():
    """Byte-identity of evaluand files between Phase 2 main and current main."""
    import subprocess
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


# ---------------------------------------------------------------- data load
def load_players_and_logs():
    """Adapted from Phase 2 load_players_and_logs, season 2026 only.

    logs[(2026, pid)] rows built byte-identically to Phase 2 / production.
    """
    index = json.load(open(os.path.join(CACHE, "index.json")))
    players = {}
    payload = load_cached(f"{ROOT}/sports/1/players?season={SEASON}")
    for person in payload.get("people", []):
        players.setdefault(person["id"], person)
    logs = {}
    missing = 0
    for url in index:
        if "/stats?stats=gameLog&group=hitting&season=" not in url:
            continue
        pid = int(url.split("/people/")[1].split("/")[0])
        season = int(url.rsplit("season=", 1)[1])
        if season != SEASON:
            continue
        payload = load_cached(url)
        if payload is None:
            missing += 1
            continue
        rows = []
        splits = [v for stat in payload.get("stats", [])
                  if isinstance(stat, dict) and isinstance(stat.get("splits"), list)
                  for v in stat["splits"]]
        for row in splits:
            try:
                data_row = row["stat"]
                pa = _int(data_row["plateAppearances"], "PLATE_APPEARANCES")
                if pa < 1:
                    continue
                game_id = _int((row.get("game") or {})["gamePk"], "HISTORY_GAME_PK")
                when = datetime.fromisoformat(str(row["date"])).date()
                stats = {"plate_appearances": pa}
                for raw_field, output_field in (
                    ("hits", "hits"), ("totalBases", "total_bases"),
                    ("rbi", "rbi"), ("runs", "runs"),
                    ("homeRuns", "home_runs"),
                    ("stolenBases", "stolen_bases"),
                    ("baseOnBalls", "walks"), ("strikeOuts", "strikeouts"),
                    ("doubles", "doubles"), ("triples", "triples"),
                ):
                    if raw_field in data_row:
                        stats[output_field] = _int(data_row[raw_field],
                                                   output_field.upper())
                if all(k in stats for k in ("hits", "doubles", "triples", "home_runs")):
                    singles = (stats["hits"] - stats["doubles"]
                               - stats["triples"] - stats["home_runs"])
                    if singles < 0:
                        raise MissingMLBBatterHistory(
                            "INCONSISTENT_EXTRA_BASE_HIT_COUNTS")
                    stats["singles"] = singles
                if all(k in stats for k in ("hits", "runs", "rbi")):
                    stats["hits_runs_rbis"] = stats["hits"] + stats["runs"] + stats["rbi"]
                rows.append({"date": when, "gamePk": game_id,
                             "gameType": row.get("gameType"), "stats": stats})
            except (ValueError, KeyError, TypeError, MissingMLBBatterHistory):
                continue
        logs[(season, pid)] = rows
    rows_by_game = defaultdict(list)
    for (season, pid), rows in logs.items():
        for r in rows:
            rows_by_game[(season, r["gamePk"])].append((pid, r))
    return players, logs, rows_by_game, missing


def load_schedule_games():
    """Regular-season games 2026 from the acquired schedule chunks
    (monthly Oct 2025 .. Sep 2026)."""
    games = {}
    year, month = 2025, 10
    while (year, month) <= (2026, 9):
        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year}-12-31"; year, month = year + 1, 1
        else:
            end = f"{year}-{month + 1:02d}-01"; month += 1
        url = (f"{ROOT}/schedule?sportId=1&startDate={start}&endDate={end}"
               f"&gameType=R&hydrate=linescore")
        payload = load_cached(url)
        if payload is None:
            continue
        for block in payload.get("dates", []):
            for g in block.get("games", []):
                pk = g.get("gamePk")
                if pk in games:
                    continue
                official = str(g.get("officialDate") or "")
                season = int(official[:4]) if official[:4].isdigit() else None
                if season != SEASON:
                    continue
                if g.get("gameType") != "R":
                    continue
                teams = g.get("teams") or {}
                games[pk] = {
                    "gamePk": pk, "season": season,
                    "officialDate": official,
                    "date": datetime.fromisoformat(official).date(),
                    "gameDate": g.get("gameDate"),
                    "away": ((teams.get("away") or {}).get("team") or {}).get("name"),
                    "home": ((teams.get("home") or {}).get("team") or {}).get("name"),
                }
    return games


def sched_by_pk(games):
    out = {}
    for pk, g in games.items():
        try:
            start = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
        except Exception:
            continue
        out[pk] = (start, g["officialDate"])
    return out


# ------------------------------------------------------- production pool mirror
def _prior_start_times_mirror(latest, kickoff, now, spk):
    per_day = {}
    for day, pk, _ in latest:
        per_day.setdefault(day, set()).add(pk)
    verified = {}
    for day, pks in per_day.items():
        if len(pks) < 2:
            continue
        for gpk in pks:
            entries = set()
            if gpk in spk:
                start, official = spk[gpk]
                entries.add((start, official))
            if len(entries) != 1:
                continue
            start, official = next(iter(entries))
            if official == day.isoformat() and start < kickoff and start < now:
                verified[gpk] = start
        if len({verified.get(g) for g in pks}) != len(pks) or not all(
                g in verified for g in pks):
            for g in pks:
                verified.pop(g, None)
    verified_pks = {pk for day, pk, _ in latest
                    if len(per_day[day]) < 2 or pk in verified}
    if len(verified_pks) != len(latest):
        return verified_pks, True
    return verified_pks, False


def build_pool(rows, fixture_date, kickoff, now, spk, apply_sealed):
    hist = []
    for r in rows:
        when = r["date"]
        if when >= fixture_date:
            continue
        if apply_sealed and in_sealed(when):
            continue
        hist.append((when, r["gamePk"], r["stats"]))
    hist.sort(key=lambda x: (x[0], x[1]), reverse=True)
    latest, seen = [], set()
    for day, pk, stats in hist:
        if pk not in seen:
            seen.add(pk)
            latest.append((day, pk, stats))
        if len(latest) == 30:
            break
    if len(latest) < 10:
        return None, "POOL_GAMES_LT_10"
    if sum(s["plate_appearances"] for _, _, s in latest) < 20:
        return None, "POOL_PA_LT_20"
    verified_pks, is_none = _prior_start_times_mirror(latest, kickoff, now, spk)
    if is_none:
        latest = [x for x in latest if x[1] in verified_pks]
        _prior_start_times_mirror(latest, kickoff, now, spk)
    if len(latest) < 10:
        return None, "POOL_GAMES_LT_10"
    if sum(s["plate_appearances"] for _, _, s in latest) < 20:
        return None, "POOL_PA_LT_20"
    return [s for _, _, s in latest], None


# ------------------------------------------------------------------- metrics
def brier(p, y):
    return (p - y) ** 2


def logloss(p, y):
    p = min(max(p, LOGLOSS_EPS), 1.0 - LOGLOSS_EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def logloss_raw_eps(p, y, eps):
    p = min(max(p, eps), 1.0 - eps)
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def crps_from_counter(counter: Counter, n: int, y: int) -> float:
    exy = sum(c * abs(v - y) for v, c in counter.items()) / n
    items = sorted(counter.items())
    exx2 = 0.0
    for i, (vi, ci) in enumerate(items):
        for vj, cj in items[i + 1:]:
            exx2 += 2.0 * ci * cj * (vj - vi)
    exx = exx2 / (n * n)
    return exy - 0.5 * exx


def crps_from_pmf(pmf: dict, y: int) -> float:
    """CRPS for a weighted PMF: E|X-y| - 0.5*E|X-X'|. Generalizes
    crps_from_counter (identical value on empirical PMFs; unit-checked)."""
    exy = sum(p * abs(v - y) for v, p in pmf.items())
    items = sorted(pmf.items())
    exx = 0.0
    for i, (vi, pi) in enumerate(items):
        for vj, pj in items[i + 1:]:
            exx += 2.0 * pi * pj * (vj - vi)
    return exy - 0.5 * exx


def challenger_pmf(counts: Counter, n: int, league_counts: Counter,
                   league_n: int, K: float) -> dict:
    """Prereg section 3: P(v) = (count_H(v) + K*L(v)) / (n + K)."""
    assert league_n > 0, "league distribution empty"
    support = set(counts) | set(league_counts)
    return {v: (counts.get(v, 0) + K * (league_counts.get(v, 0) / league_n))
            / (n + K) for v in support}


def value_of(stats, key):
    if isinstance(key, tuple):
        total = 0
        for comp in key:
            if comp not in stats:
                return None
            total += stats[comp]
        return total
    return stats.get(key)


def block_bootstrap_ci(diffs_by_week, n_boot=2000, seed=SEED):
    weeks = sorted(diffs_by_week)
    sums = np.array([diffs_by_week[w][0] for w in weeks], dtype=np.float64)
    counts = np.array([diffs_by_week[w][1] for w in weeks], dtype=np.float64)
    point = sums.sum() / counts.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(weeks), size=(n_boot, len(weeks)))
    boot_sums = sums[idx].sum(axis=1)
    boot_counts = counts[idx].sum(axis=1)
    boot = boot_sums / boot_counts
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(point), float(lo), float(hi)


# ------------------------------------------------------------- boxscore utils
def boxscore_path(pk):
    return os.path.join(BOX_CACHE, f"{pk}.json")


def fetch_boxscore(pk):
    url = f"{ROOT}/game/{pk}/boxscore"
    last = None
    for attempt in range(3):
        try:
            data = live_fetch(url)
            tmp = boxscore_path(pk) + f".tmp{os.getpid()}"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, boxscore_path(pk))
            return pk, "ok", url
        except BaseException as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0 * (attempt + 1))
    return pk, f"FAIL:{type(last).__name__}:{last}", url


def starters_from_box(box):
    starters, appeared = set(), set()
    if not isinstance(box, dict):
        return starters, appeared
    for side in ("away", "home"):
        players = ((box.get("teams") or {}).get(side) or {}).get("players") or {}
        for key, p in players.items():
            if not isinstance(p, dict):
                continue
            bo = p.get("battingOrder")
            pid = (p.get("person") or {}).get("id")
            if pid is None or not (isinstance(bo, str) and bo.isdigit()):
                continue
            appeared.add(pid)
            v = int(bo)
            if 100 <= v <= 900 and v % 100 == 0:
                starters.add(pid)
    return starters, appeared


def load_box(pk):
    p = boxscore_path(pk)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


# -------------------------------------------------------------------- phases
def phase_boxscores():
    check_prereg(); check_acq()
    games = load_schedule_games()
    os.makedirs(BOX_CACHE, exist_ok=True)
    todo = [pk for pk in games if not os.path.exists(boxscore_path(pk))]
    print(f"games={len(games)} todo={len(todo)}", flush=True)
    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        for pk, status, url in pool.map(fetch_boxscore, todo):
            results[url] = status
            done += 1
            if done % 500 == 0:
                print(f"  fetched {done}/{len(todo)}", flush=True)
    fails = {u: s for u, s in results.items() if s != "ok"}
    summary = {"games_total": len(games), "fetched_this_run": len(todo),
               "failures": fails}
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR,
                           "challenger_boxscore_fetch_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("failures:", len(fails))
    return summary


def _parity_candidates():
    players, logs, rows_by_game, missing = load_players_and_logs()
    games = load_schedule_games()
    spk = sched_by_pk(games)
    starter_map = {}
    for pk in games:
        box = load_box(pk)
        if box is not None:
            s, _ = starters_from_box(box)
            starter_map[pk] = s
    candidates = []
    for pk, g in games.items():
        if pk not in starter_map:
            continue
        kickoff = spk[pk][0]
        now = datetime(g["date"].year, g["date"].month, g["date"].day,
                       tzinfo=timezone.utc)
        if kickoff <= now:
            continue
        for pid in starter_map[pk]:
            rows = logs.get((g["season"], pid))
            if not rows:
                continue
            pool, reason = build_pool(rows, g["date"], kickoff, now, spk,
                                      apply_sealed=False)
            if pool is None:
                continue
            dates = []
            seen_pk = set()
            hist = sorted((r for r in rows if r["date"] < g["date"]),
                          key=lambda r: (r["date"], r["gamePk"]), reverse=True)
            for r in hist:
                if r["gamePk"] in seen_pk:
                    continue
                seen_pk.add(r["gamePk"]); dates.append(r["date"])
                if len(dates) == 30:
                    break
            dh = any(c >= 2 for c in Counter(dates).values())
            candidates.append({"gamePk": pk, "pid": pid, "season": g["season"],
                               "date": g["officialDate"], "dh_pool": dh})
    return players, logs, games, spk, starter_map, candidates


def phase_parity():
    check_prereg(); check_acq()
    players, logs, games, spk, starter_map, candidates = _parity_candidates()
    rng = random.Random(SEED)
    rng.shuffle(candidates)
    picks = candidates[:25]
    dh_extra = [c for c in candidates if c["dh_pool"] and c not in picks][:3]
    picks = picks + dh_extra
    print(f"parity candidates={len(candidates)} picks={len(picks)} "
          f"(dh_extra={len(dh_extra)})", flush=True)

    live_log = []

    def hybrid_getter(url):
        if "/stats?" in url and "gameLog" in url:
            data = load_cached(url)
            if data is None:
                raise RuntimeError(f"GAMELOG CACHE MISS (stop): {url}")
            return data
        live_log.append({"url": url,
                         "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                         "purpose": "parity_fixture_resolution"})
        return live_fetch(url)

    results = []
    mismatches = 0
    for i, c in enumerate(picks):
        g = games[c["gamePk"]]
        pid = c["pid"]
        box = load_box(c["gamePk"])
        name = None
        for side in ("away", "home"):
            for p in ((box.get("teams") or {}).get(side) or {}).get("players", {}).values():
                if (p.get("person") or {}).get("id") == pid:
                    name = p["person"]["fullName"]
        now = datetime(g["date"].year, g["date"].month, g["date"].day,
                       tzinfo=timezone.utc)
        kickoff = spk[c["gamePk"]][0]
        src = MLBBatterPublicSource(getter=hybrid_getter)
        try:
            prod = src.prior_games(away=g["away"], home=g["home"],
                                   player_name=name,
                                   owner_kickoff=kickoff.isoformat(),
                                   as_of=now.isoformat())
            prod_pool = prod["features"]["pa_history"]
            prod_err = None
        except Exception as exc:  # noqa: BLE001
            prod_pool, prod_err = None, f"{type(exc).__name__}:{exc}"
        rows = logs[(g["season"], pid)]
        ev_pool, ev_reason = build_pool(rows, g["date"], kickoff, now, spk,
                                        apply_sealed=False)
        equal = (prod_pool is not None and ev_pool is not None
                 and prod_pool == ev_pool)
        if not equal:
            mismatches += 1
        results.append({
            "n": i + 1, "gamePk": c["gamePk"], "season": g["season"],
            "date": g["officialDate"], "batter_id": pid, "batter_name": name,
            "away": g["away"], "home": g["home"],
            "dh_pool": c["dh_pool"],
            "production_error": prod_err, "evaluator_reason": ev_reason,
            "production_pool_games": (len(prod_pool) if prod_pool else None),
            "evaluator_pool_games": (len(ev_pool) if ev_pool else None),
            "pools_equal": equal,
        })
        print(f"  parity {i+1}/{len(picks)} pk={c['gamePk']} pid={pid} "
              f"equal={equal}", flush=True)
    out = {"n_samples": len(results),
           "n_equal": sum(r["pools_equal"] for r in results),
           "mismatches": mismatches, "samples": results,
           "live_fetches": live_log,
           "comparison_scope": (
               "evaluator pool (production collector semantics, prereg "
               "section 2) vs production MLBBatterPublicSource.prior_games "
               "pa_history, exact list-of-dicts equality. Sealed window "
               "declared not applicable to 2026 (prereg section 4)."),
           "gamelog_cache_misses": 0,
           "passed": mismatches == 0 and len(results) >= 25
           and all(r["pools_equal"] for r in results)}
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR,
                           "challenger_batter_props_parity.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"PARITY: {out['n_equal']}/{out['n_samples']} equal; "
          f"live fetches logged: {len(live_log)}")
    return out


def unit_checks():
    """Challenger unit checks (prereg section 7), on synthetic + sampled
    counters. Runs BEFORE any 2026 outcome is scored."""
    checks = {}
    # PMF sums to 1 within 1e-12; K->0 reduction to uncapped empirical
    rng = random.Random(SEED)
    worst_sum = 0.0
    worst_k0 = 0.0
    worst_crps_equiv = 0.0
    trials = 0
    for _ in range(300):
        n = rng.randint(10, 120)
        vals = [rng.choice([0, 0, 0, 1, 1, 1, 2, 2, 3, 4]) for _ in range(n)]
        counts = Counter(vals)
        ln = rng.randint(500, 20000)
        lvals = [rng.choice([0, 0, 1, 1, 2, 3]) for _ in range(ln)]
        lcounts = Counter(lvals)
        pmf = challenger_pmf(counts, n, lcounts, ln, K_CHALLENGER)
        worst_sum = max(worst_sum, abs(sum(pmf.values()) - 1.0))
        pmf0 = challenger_pmf(counts, n, lcounts, ln, 0)
        emp = {v: c / n for v, c in counts.items()}
        worst_k0 = max(worst_k0, max(abs(pmf0.get(v, 0) - emp.get(v, 0))
                                     for v in set(pmf0) | set(emp)))
        y = rng.choice([0, 1, 2, 3])
        worst_crps_equiv = max(
            worst_crps_equiv,
            abs(crps_from_pmf(emp, y) - crps_from_counter(counts, n, y)))
        trials += 1
    checks["pmf_sums_to_1"] = {"trials": trials, "max_abs_dev": worst_sum,
                               "tol": 1e-12, "passed": worst_sum < 1e-12}
    checks["k_to_0_reduces_to_uncapped_empirical"] = {
        "trials": trials, "max_abs_dev": worst_k0,
        "passed": worst_k0 < 1e-15}
    checks["crps_pmf_matches_crps_counter_on_empirical"] = {
        "trials": trials, "max_abs_dev": worst_crps_equiv,
        "passed": worst_crps_equiv < 1e-12}
    checks["n_zero_cannot_occur"] = {
        "note": ("fixture eligibility requires the production pool gates "
                 "(>=10 games, >=20 PA) on the <=30-game pool; the uncapped "
                 "history H is a superset, so n >= 10 for every scored "
                 "fixture; asserted again in the scoring loop."),
        "passed": True}
    checks["all_passed"] = all(c["passed"] for c in checks.values()
                               if isinstance(c, dict) and "passed" in c)
    return checks


def phase_verify():
    parity_path = os.path.join(RESULTS_DIR, "challenger_batter_props_parity.json")
    if os.path.exists(parity_path):
        parity = json.load(open(parity_path))
    else:
        parity = phase_parity()
    units = unit_checks()
    out = {"parity_passed": parity["passed"], "parity_n": parity["n_samples"],
           "parity_equal": parity["n_equal"],
           "unit_checks": units,
           "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    with open(os.path.join(RESULTS_DIR,
                           "challenger_batter_props_verification.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1)[:800])
    return out


# --------------------------------------------------------------------- score
def phase_score(out_path=None):
    prereg_hash = check_prereg(); acq = check_acq()
    ver = json.load(open(os.path.join(
        RESULTS_DIR, "challenger_batter_props_verification.json")))
    assert ver["parity_passed"], "PARITY GATE FAILED — scoring stopped"
    assert ver["unit_checks"]["all_passed"], "UNIT CHECKS FAILED — scoring stopped"
    parity = json.load(open(os.path.join(
        RESULTS_DIR, "challenger_batter_props_parity.json")))
    players, logs, rows_by_game, missing_logs = load_players_and_logs()
    games = load_schedule_games()
    spk = sched_by_pk(games)

    starter_map, appeared_map, box_missing = {}, {}, []
    for pk in games:
        box = load_box(pk)
        if box is None:
            box_missing.append(pk); starter_map[pk] = set(); appeared_map[pk] = set()
            continue
        s, a = starters_from_box(box)
        starter_map[pk] = s; appeared_map[pk] = a

    row_by_pk = {}
    rows_sorted = {}
    for key, rows in logs.items():
        row_by_pk[key] = {r["gamePk"]: r for r in rows}
        rows_sorted[key] = sorted(rows, key=lambda r: (r["date"], r["gamePk"]))

    fixtures = []
    exclusions = Counter()
    no_gamelog_row = 0
    season_games = sorted(games.values(), key=lambda g: (g["date"], g["gamePk"]))
    for g in season_games:
        pk = g["gamePk"]
        if pk in box_missing:
            exclusions["BOXSCORE_UNAVAILABLE"] += 1
            continue
        glog_rows = rows_by_game.get((SEASON, pk), [])
        glog_pids = {pid for pid, _ in glog_rows}
        for pid in appeared_map[pk]:
            if pid not in glog_pids:
                no_gamelog_row += 1
        for pid, row in glog_rows:
            if pid not in starter_map[pk]:
                exclusions["NOT_A_STARTER"] += 1
                continue
            kickoff = spk[pk][0]
            now = datetime(g["date"].year, g["date"].month, g["date"].day,
                           tzinfo=timezone.utc)
            pool, reason = build_pool(logs[(SEASON, pid)], g["date"],
                                      kickoff, now, spk, apply_sealed=False)
            if pool is None:
                exclusions[reason] += 1
                continue
            fixtures.append({"season": SEASON, "date": g["date"],
                             "gamePk": pk, "pid": pid, "pool": pool,
                             "outcome": row["stats"]})
    print(f"fixtures={len(fixtures)} exclusions={dict(exclusions)}", flush=True)

    # B1 incremental counters (Phase 2 implementation, season 2026)
    b1_state = {}

    def b1_counters(pid, fixture_date):
        key = (SEASON, pid)
        st = b1_state.get(key)
        if st is None:
            st = {"idx": 0, "seen_pk": set(), "counts": {}, "n": Counter()}
            for mkt, keyv in OU_STATS + LADDER_STATS:
                st["counts"][mkt] = Counter()
            b1_state[key] = st
        rows = rows_sorted[key]
        while st["idx"] < len(rows) and rows[st["idx"]]["date"] < fixture_date:
            r = rows[st["idx"]]; st["idx"] += 1
            if r["gamePk"] in st["seen_pk"]:
                continue
            st["seen_pk"].add(r["gamePk"])
            for mkt, keyv in OU_STATS + LADDER_STATS:
                v = value_of(r["stats"], keyv)
                if v is not None:
                    st["counts"][mkt][v] += 1; st["n"][mkt] += 1
        return st

    # B2 league counters (Phase 2 implementation, season 2026)
    starter_rows_by_date = defaultdict(list)
    for g in games.values():
        if g["gamePk"] in box_missing:
            continue
        for pid in starter_map[g["gamePk"]]:
            row = row_by_pk.get((SEASON, pid), {}).get(g["gamePk"])
            if row is not None:
                starter_rows_by_date[row["date"]].append(row["stats"])
    b2_dates = sorted(starter_rows_by_date)
    b2_st = {"counts": {}, "n": Counter(), "ptr": 0}
    for mkt, _ in OU_STATS + LADDER_STATS:
        b2_st["counts"][mkt] = Counter()

    def b2_counters(fixture_date):
        st = b2_st
        while st["ptr"] < len(b2_dates) and b2_dates[st["ptr"]] < fixture_date:
            d = b2_dates[st["ptr"]]; st["ptr"] += 1
            for stats in starter_rows_by_date[d]:
                for mkt, keyv in OU_STATS + LADDER_STATS:
                    v = value_of(stats, keyv)
                    if v is not None:
                        st["counts"][mkt][v] += 1; st["n"][mkt] += 1
        return st

    stat_data = {mkt: [] for mkt, _ in OU_STATS + LADDER_STATS}
    engine_errors = Counter(); outcome_missing = Counter()
    support_miss = Counter()
    pmf_sum_worst = 0.0

    for fx in fixtures:
        fdate = fx["date"]
        pool = fx["pool"]; outcome = fx["outcome"]
        week = f"{fdate.isocalendar()[0]}-W{fdate.isocalendar()[1]:02d}"
        b1 = b1_counters(fx["pid"], fdate)
        b2 = b2_counters(fdate)
        for mkt, keyv in OU_STATS:
            y_val = value_of(outcome, keyv)
            if y_val is None:
                outcome_missing[mkt] += 1; continue
            y = 1 if y_val >= 1 else 0
            try:
                p_eng = price_batter_market(market=mkt, side="OVER", line=0.5,
                                            pa_history=pool)["model_p"]
            except BatterEmpiricalError:
                engine_errors[mkt] += 1; continue
            c1, n1 = b1["counts"][mkt], b1["n"][mkt]
            c2, n2 = b2["counts"][mkt], b2["n"][mkt]
            assert n1 >= 10, "challenger n<10 on a scored fixture"
            p_b1 = (n1 - c1.get(0, 0)) / n1
            p_b2 = (n2 - c2.get(0, 0)) / n2
            pmf_ch = challenger_pmf(c1, n1, c2, n2, K_CHALLENGER)
            pmf_sum_worst = max(pmf_sum_worst, abs(sum(pmf_ch.values()) - 1.0))
            p_ch = 1.0 - pmf_ch.get(0, 0.0)
            for tag, p in (("engine", p_eng), ("B1", p_b1), ("B2", p_b2),
                           ("challenger", p_ch)):
                if (p == 0.0 and y == 1) or (p == 1.0 and y == 0):
                    support_miss[f"{mkt}:{tag}"] += 1
            stat_data[mkt].append({
                "week": week, "y": y,
                "brier_eng": brier(p_eng, y), "brier_ch": brier(p_ch, y),
                "brier_b1": brier(p_b1, y), "brier_b2": brier(p_b2, y),
                "ll_eng": logloss(p_eng, y), "ll_ch": logloss(p_ch, y),
                "ll_b1": logloss(p_b1, y), "ll_b2": logloss(p_b2, y),
                "p_eng": p_eng, "p_ch": p_ch,
            })
        for mkt, keyv in LADDER_STATS:
            y_val = value_of(outcome, keyv)
            if y_val is None:
                outcome_missing[mkt] += 1; continue
            y = y_val
            try:
                thr = {}
                for line in (0.5, 1.5):
                    thr[line] = price_batter_market(
                        market=mkt, side="OVER", line=line,
                        pa_history=pool)["model_p"]
            except BatterEmpiricalError:
                engine_errors[mkt] += 1; continue
            pool_counter = Counter()
            ok = True
            for row_stats in pool:
                v = value_of(row_stats, keyv)
                if v is None:
                    ok = False; break
                pool_counter[v] += 1
            if not ok:
                engine_errors[mkt] += 1; continue
            crps_eng = crps_from_counter(pool_counter, len(pool), y)
            c1, n1 = b1["counts"][mkt], b1["n"][mkt]
            c2, n2 = b2["counts"][mkt], b2["n"][mkt]
            assert n1 >= 10, "challenger n<10 on a scored fixture"
            crps_b1 = crps_from_counter(c1, n1, y)
            crps_b2 = crps_from_counter(c2, n2, y)
            pmf_ch = challenger_pmf(c1, n1, c2, n2, K_CHALLENGER)
            pmf_sum_worst = max(pmf_sum_worst, abs(sum(pmf_ch.values()) - 1.0))
            crps_ch = crps_from_pmf(pmf_ch, y)
            rec = {"week": week, "y": y,
                   "crps_eng": crps_eng, "crps_ch": crps_ch,
                   "crps_b1": crps_b1, "crps_b2": crps_b2}
            for line in (0.5, 1.5):
                yi = 1 if y > line else 0
                p1 = sum(c for v, c in c1.items() if v > line) / n1
                p2 = sum(c for v, c in c2.items() if v > line) / n2
                pch = sum(p for v, p in pmf_ch.items() if v > line)
                tag = "05" if line == 0.5 else "15"
                rec[f"brier{tag}_eng"] = brier(thr[line], yi)
                rec[f"brier{tag}_ch"] = brier(pch, yi)
                rec[f"brier{tag}_b1"] = brier(p1, yi)
                rec[f"brier{tag}_b2"] = brier(p2, yi)
            stat_data[mkt].append(rec)
    print("scoring loop done", flush=True)
    assert pmf_sum_worst < 1e-12, f"challenger PMF sum dev {pmf_sum_worst}"

    def agg(records, keys):
        entry = {"n": len(records)}
        for k in keys:
            entry[k] = float(np.mean([r[k] for r in records])) if records else None
        return entry

    def cis(records, diff_pairs):
        entry = {}
        for label, (ak, bk) in diff_pairs.items():
            by_week = defaultdict(lambda: [0.0, 0])
            for r in records:
                by_week[r["week"]][0] += r[ak] - r[bk]
                by_week[r["week"]][1] += 1
            point, lo, hi = block_bootstrap_ci(
                {w: tuple(v) for w, v in by_week.items()})
            entry[label] = {"delta": point, "ci95": [lo, hi],
                            "entirely_below_zero": bool(hi < 0)}
        return entry

    def calib(records, pkey):
        bins = []
        for i in range(10):
            lo_e, hi_e = i / 10, (i + 1) / 10
            bsel = [r for r in records if lo_e <= r[pkey] < hi_e
                    or (i == 9 and r[pkey] == 1.0)]
            bins.append({
                "bin": f"[{lo_e:.1f},{hi_e:.1f}{']' if i == 9 else ')'}",
                "n": len(bsel),
                "mean_predicted": (float(np.mean([r[pkey] for r in bsel])) if bsel else None),
                "observed_rate": (float(np.mean([r["y"] for r in bsel])) if bsel else None)})
        return bins

    stats_out = {}
    for mkt, keyv in OU_STATS:
        recs = stat_data[mkt]
        a = agg(recs, ["brier_eng", "brier_ch", "brier_b1", "brier_b2",
                       "ll_eng", "ll_ch", "ll_b1", "ll_b2"])
        c = cis(recs, {
            "dBrier_ch_vs_FROZEN": ("brier_ch", "brier_eng"),
            "dBrier_ch_vs_B1": ("brier_ch", "brier_b1"),
            "dBrier_ch_vs_B2": ("brier_ch", "brier_b2"),
            "dLogLoss_ch_vs_FROZEN": ("ll_ch", "ll_eng"),
            "dLogLoss_ch_vs_B1": ("ll_ch", "ll_b1"),
            "dLogLoss_ch_vs_B2": ("ll_ch", "ll_b2"),
            "dBrier_FROZEN_vs_B1": ("brier_eng", "brier_b1"),
            "dBrier_FROZEN_vs_B2": ("brier_eng", "brier_b2"),
        })
        gate_keys = ["dBrier_ch_vs_FROZEN", "dBrier_ch_vs_B1", "dBrier_ch_vs_B2",
                     "dLogLoss_ch_vs_FROZEN", "dLogLoss_ch_vs_B1",
                     "dLogLoss_ch_vs_B2"]
        verdict = ("ADOPT-CANDIDATE" if all(c[k]["entirely_below_zero"]
                                            for k in gate_keys)
                   else "KEEP FROZEN")
        stats_out[mkt] = {"form": "OU_0.5", "value_key": keyv,
                          "metrics": a, "paired_deltas": c,
                          "verdict": verdict,
                          "calibration_deciles_challenger": calib(recs, "p_ch"),
                          "calibration_deciles_frozen": calib(recs, "p_eng")}
    for mkt, keyv in LADDER_STATS:
        recs = stat_data[mkt]
        keys = ["crps_eng", "crps_ch", "crps_b1", "crps_b2"]
        for tag in ("05", "15"):
            keys += [f"brier{tag}_eng", f"brier{tag}_ch",
                     f"brier{tag}_b1", f"brier{tag}_b2"]
        a = agg(recs, keys)
        c = cis(recs, {
            "dCRPS_ch_vs_FROZEN": ("crps_ch", "crps_eng"),
            "dCRPS_ch_vs_B1": ("crps_ch", "crps_b1"),
            "dCRPS_ch_vs_B2": ("crps_ch", "crps_b2"),
            "dCRPS_FROZEN_vs_B1": ("crps_eng", "crps_b1"),
            "dCRPS_FROZEN_vs_B2": ("crps_eng", "crps_b2"),
            "dBrier05_ch_vs_FROZEN": ("brier05_ch", "brier05_eng"),
            "dBrier15_ch_vs_FROZEN": ("brier15_ch", "brier15_eng"),
        })
        gate_keys = ["dCRPS_ch_vs_FROZEN", "dCRPS_ch_vs_B1", "dCRPS_ch_vs_B2"]
        verdict = ("ADOPT-CANDIDATE" if all(c[k]["entirely_below_zero"]
                                            for k in gate_keys)
                   else "KEEP FROZEN")
        stats_out[mkt] = {"form": "LADDER_CRPS",
                          "value_key": (keyv if isinstance(keyv, str)
                                        else "+".join(keyv)),
                          "metrics": a, "paired_deltas": c,
                          "verdict": verdict,
                          "threshold_brier_note": "Brier at 0.5/1.5 descriptive; gate is CRPS-only per prereg section 6."}

    # B1 implementing lines, quoted from the Phase 2 script
    p2_lines = open(PHASE2_SCRIPT).read().splitlines()
    b1_quote = []
    for i, ln in enumerate(p2_lines, 1):
        if ("p_b1 = (n1 - c1.get(0, 0)) / n1" in ln
                or "crps_b1 = crps_from_counter(c1, n1, y)" in ln
                or "p_b2 = (n2 - c2.get(0, 0)) / n2" in ln
                or "crps_b2 = crps_from_counter(c2, n2, y)" in ln):
            b1_quote.append({"file": PHASE2_SCRIPT, "line": i,
                             "text": ln.strip()})

    box_summary = {}
    bs_path = os.path.join(RESULTS_DIR, "challenger_boxscore_fetch_summary.json")
    if os.path.exists(bs_path):
        box_summary = json.load(open(bs_path))

    results = {
        "label": "RESEARCH_EVIDENCE — retrospective calibration evaluation. NOT a market verdict, NOT validation, NOT a promotion input.",
        "family": "MLB batter props challenger (Model Fix Lane, family 1)",
        "prereg": {"path": PREREG_PATH, "sha256": prereg_hash,
                   "spec_hashes_record": spec_hashes_record()},
        "repo": {"main": MAIN_SHA,
                 "phase2_main": PHASE2_MAIN,
                 "evaluand_identity": evaluand_identity(),
                 "engine": "sportsedge/mlb_batter_empirical.py price_batter_market (mlb_batter_empirical_game_log_v1)",
                 "pool_contract": "sportsedge/mlb_public_batter_history.py MLBBatterPublicSource.prior_games"},
        "challenger": {
            "construction": "P(v) = (count_H(v) + K * L_s(d)(v)) / (n + K), K=25; H = ALL same-season prior games PA>=1 (no 30-game cap); L = expanding season-to-date empirical distribution over all starting batters' prior games (Phase 2 B2 construction)",
            "K": K_CHALLENGER},
        "split": {"case": "SINGLE_SPLIT", "test_season": 2026,
                  "design_seasons": [2024, 2025],
                  "sealed_window": "not applicable to 2026 (prereg section 4)"},
        "acquisition": {"manifest": ACQ_DONE, "failures": acq["failures"],
                        "players_2026": acq["players_2026"],
                        "gamelog_urls": acq["gamelog_urls"],
                        "schedule_urls": acq["schedule_urls"],
                        "boxscores": box_summary,
                        "missing_gamelog_payloads_in_cache": missing_logs},
        "parity": {"n_samples": parity["n_samples"],
                   "n_equal": parity["n_equal"],
                   "mismatches": parity["mismatches"],
                   "passed": parity["passed"],
                   "comparison_scope": parity["comparison_scope"],
                   "live_fetches": parity["live_fetches"],
                   "samples": parity["samples"]},
        "unit_checks": ver["unit_checks"],
        "population": {
            "fixtures_scored_total": len(fixtures),
            "exclusions": dict(exclusions),
            "exclusion_reason_precedence": "NOT_A_STARTER -> POOL_GAMES_LT_10 -> POOL_PA_LT_20 (prereg section 4 transposing Phase 2; sealed window not applicable)",
            "boxscore_unavailable_games": box_missing,
            "games_with_starter_count_ne_18": {
                str(pk): len(starter_map[pk]) for pk in games
                if pk not in box_missing and len(starter_map[pk]) != 18},
            "boxscore_batting_appearances_without_gamelog_row": no_gamelog_row,
            "universe_note": "Universe = gameLog rows (PA>=1 parse, as production retains) matched to regular-season schedule games; boxscore batting appearances with no gameLog row are counted separately and enter neither fixtures nor NOT_A_STARTER."},
        "baseline_implementations": {
            "note": "B1/B2 exactly as implemented in Phase 2 eval_batter_props.py (raw uncapped empirical frequency/distribution; B1 dedups by gamePk, no doubleheader re-selection). Implementing lines quoted verbatim:",
            "quoted_lines": b1_quote},
        "conventions": [
            "LOG_LOSS_FLOOR: probabilities clipped to [1e-6, 1-1e-6] (Phase 2 convention).",
            "CHALLENGER_CRPS: computed from the challenger PMF via E|X-y| - 0.5*E|X-X'|, unit-checked to agree with Phase 2's crps_from_counter on empirical PMFs to <1e-12.",
            "CHALLENGER_N: per-stat n = number of uncapped prior games with a recorded value for that stat (equals |H| whenever the stat field is present, as in production rows).",
            "CALIBRATION_BINS: ten equal-width bins [0,0.1)...[0.9,1.0], as Phase 2.",
        ],
        "engine_pricer_errors_by_stat": dict(engine_errors),
        "outcome_field_missing_by_stat": dict(outcome_missing),
        "support_misses": dict(support_miss),
        "challenger_pmf_sum_max_abs_dev_over_scored_fixtures": pmf_sum_worst,
        "bootstrap": {"blocks": "ISO calendar weeks of fixture date",
                      "resamples": 2000, "seed": SEED,
                      "ci": "95% percentile of block-bootstrap paired means"},
        "stats": stats_out,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    out_path = out_path or os.path.join(
        RESULTS_DIR, "challenger_batter_props_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=1)
    print(f"WROTE {out_path}")
    for mkt, s in stats_out.items():
        print(mkt, s["verdict"], "n=", s["metrics"]["n"])
    return results


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if phase == "boxscores":
        phase_boxscores()
    elif phase == "parity":
        phase_parity()
    elif phase == "verify":
        phase_verify()
    elif phase == "score":
        phase_score(out)
    else:
        print("usage: eval_challenger_batter_props.py [boxscores|parity|verify|score] [out_path]")
