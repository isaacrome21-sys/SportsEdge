#!/usr/bin/env python3
"""Held-out MLB F5 and NRFI/YRFI tightening research.

Research only. Reproduces current baselines, tunes a small candidate grid on
2024, and evaluates the selected candidates once on untouched 2025 games.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_empirical_bayes import posterior_settlement_mass

API = "https://statsapi.mlb.com/api/v1"
SEASONS = (2023, 2024, 2025)
TUNE = 2024
TEST = 2025
MONTHS = ((3, 1, 3, 31), (4, 1, 4, 30), (5, 1, 5, 31), (6, 1, 6, 30),
          (7, 1, 7, 31), (8, 1, 8, 31), (9, 1, 9, 30), (10, 1, 10, 31))
LOOKBACK_DAYS = 370
TEAM_WINDOW = 30
MIN_TEAM_HISTORY = 10
MIN_LEAGUE_HALVES = 200
MIN_TEST_GAMES = 1000
F5_STRENGTHS = (0, 5, 15, 30)
NRFI_STRENGTHS = (5, 15, 30)
NRFI_BASE = "production_empirical_jeffreys"
BOOT_REPS = 2000
BOOT_SEED = 20261004
EPS = 1e-12


def _get(url: str) -> dict:
    last = None
    for attempt in range(4):
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"})
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(attempt + 1)
    raise RuntimeError(f"MLB_FETCH_FAILED:{url}") from last


def _inning_runs(inning: dict, side: str):
    row = inning.get(side)
    if not isinstance(row, dict):
        teams = inning.get("teams")
        row = teams.get(side) if isinstance(teams, dict) else None
    if not isinstance(row, dict) or row.get("runs") is None:
        return None
    try:
        value = int(row["runs"])
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _parse(payload: dict) -> list[dict]:
    out = []
    for block in payload.get("dates") or []:
        for game in block.get("games") or []:
            if str((game.get("status") or {}).get("abstractGameState") or "").lower() != "final":
                continue
            try:
                day = date.fromisoformat(str(game.get("officialDate") or block.get("date"))[:10])
                away_id = int(game["teams"]["away"]["team"]["id"])
                home_id = int(game["teams"]["home"]["team"]["id"])
                away_final = int(game["teams"]["away"]["score"])
                home_final = int(game["teams"]["home"]["score"])
                game_pk = int(game["gamePk"])
            except (KeyError, TypeError, ValueError):
                continue
            first = {}
            for inning in ((game.get("linescore") or {}).get("innings") or []):
                if not isinstance(inning, dict):
                    continue
                try:
                    number = int(inning.get("num"))
                except (TypeError, ValueError):
                    continue
                if number not in {1, 2, 3, 4, 5} or number in first:
                    continue
                away = _inning_runs(inning, "away")
                home = _inning_runs(inning, "home")
                if away is not None and home is not None:
                    first[number] = (away, home)
            if set(first) != {1, 2, 3, 4, 5}:
                continue
            out.append({
                "game_pk": game_pk,
                "day": day,
                "away_id": away_id,
                "home_id": home_id,
                "away_final": away_final,
                "home_final": home_final,
                "away_i1": first[1][0],
                "home_i1": first[1][1],
                "away_f5": sum(first[i][0] for i in range(1, 6)),
                "home_f5": sum(first[i][1] for i in range(1, 6)),
            })
    return out


def fetch(cache: Path, workers: int) -> list[dict]:
    cache.mkdir(parents=True, exist_ok=True)

    def one(job):
        season, month = job
        m1, d1, m2, d2 = month
        path = cache / f"schedule_{season}_{m1:02d}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            query = urlencode({
                "sportId": 1,
                "gameType": "R",
                "hydrate": "linescore",
                "startDate": f"{season}-{m1:02d}-{d1:02d}",
                "endDate": f"{season}-{m2:02d}-{d2:02d}",
            })
            payload = _get(f"{API}/schedule?{query}")
            path.write_text(json.dumps(payload), encoding="utf-8")
        return _parse(payload)

    by_pk = {}
    jobs = [(season, month) for season in SEASONS for month in MONTHS]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(one, jobs):
            for row in rows:
                by_pk[row["game_pk"]] = row
    return sorted(by_pk.values(), key=lambda x: (x["day"], x["game_pk"]))


def indexes(games: list[dict]):
    teams = defaultdict(list)
    halves = []
    for g in games:
        teams[g["away_id"]].append({
            "day": g["day"], "runs_for": g["away_final"], "runs_against": g["home_final"],
            "i1_for": g["away_i1"], "i1_against": g["home_i1"],
            "f5_for": g["away_f5"], "f5_against": g["home_f5"],
        })
        teams[g["home_id"]].append({
            "day": g["day"], "runs_for": g["home_final"], "runs_against": g["away_final"],
            "i1_for": g["home_i1"], "i1_against": g["away_i1"],
            "f5_for": g["home_f5"], "f5_against": g["away_f5"],
        })
        halves.append((g["day"], g["away_f5"], int(g["away_i1"] == 0)))
        halves.append((g["day"], g["home_f5"], int(g["home_i1"] == 0)))
    return teams, sorted(halves, key=lambda x: x[0])


def prior_team(rows: list[dict], target: date) -> list[dict]:
    cutoff = target - timedelta(days=LOOKBACK_DAYS)
    return [r for r in rows if cutoff <= r["day"] < target][-TEAM_WINDOW:]


def prior_halves(rows: list[tuple], target: date) -> list[tuple]:
    cutoff = target - timedelta(days=LOOKBACK_DAYS)
    return [r for r in rows if cutoff <= r[0] < target]


def pmf(values: list[int]) -> dict[int, float]:
    counts = defaultdict(int)
    for value in values:
        counts[int(value)] += 1
    n = len(values)
    return {key: count / n for key, count in counts.items()}


def smoothed_pmf(values: list[int], league: dict[int, float], strength: int) -> dict[int, float]:
    if not values:
        raise ValueError("EMPTY_VALUES")
    counts = defaultdict(float)
    for value in values:
        counts[int(value)] += 1.0
    keys = set(counts) | set(league)
    denom = len(values) + strength
    out = {k: (counts[k] + strength * league.get(k, 0.0)) / denom for k in keys}
    if abs(sum(out.values()) - 1.0) > 1e-9:
        raise ValueError("PMF_MASS")
    return out


def blend(a: dict[int, float], b: dict[int, float]) -> dict[int, float]:
    keys = set(a) | set(b)
    out = {k: 0.5 * a.get(k, 0.0) + 0.5 * b.get(k, 0.0) for k in keys}
    if abs(sum(out.values()) - 1.0) > 1e-9:
        raise ValueError("BLEND_MASS")
    return out


def f5_metrics(
    away: dict[int, float],
    home: dict[int, float],
    ar_obs: int,
    hr_obs: int,
    *,
    effective_n: int,
) -> dict:
    """Distribution NLL plus market metrics after the current production readout."""
    observed = away.get(ar_obs, 0.0) * home.get(hr_obs, 0.0)
    p_away = p_tie = p_home = p_over45 = 0.0
    for ar, ap in away.items():
        for hr, hp in home.items():
            p = ap * hp
            if ar > hr:
                p_away += p
            elif hr > ar:
                p_home += p
            else:
                p_tie += p
            if ar + hr > 4.5:
                p_over45 += p

    state = posterior_settlement_mass(
        over_mass=p_away,
        under_mass=p_home,
        push_mass=p_tie,
        effective_n=float(effective_n),
        has_push=True,
    )
    total45 = posterior_settlement_mass(
        over_mass=p_over45,
        under_mass=1.0 - p_over45,
        push_mass=0.0,
        effective_n=float(effective_n),
        has_push=False,
    )
    y = (int(ar_obs > hr_obs), int(ar_obs == hr_obs), int(hr_obs > ar_obs))
    return {
        "nll": -math.log(max(EPS, observed)),
        "state_brier": (
            (state["p_over"]-y[0])**2
            + (state["p_push"]-y[1])**2
            + (state["p_under"]-y[2])**2
        ),
        "total45_brier": (total45["p_over"]-int(ar_obs+hr_obs > 4.5))**2,
    }


def shrink_zero(values: list[int], league_zero: float, strength: int) -> float:
    """Jeffreys production baseline plus optional strictly-prior league pseudo-games."""
    return (sum(values) + 0.5 + strength * league_zero) / (len(values) + 1.0 + strength)


def direct_nrfi(away: list[dict], home: list[dict], league_zero: float, strength: int) -> float:
    away_off = shrink_zero([int(r["i1_for"] == 0) for r in away], league_zero, strength)
    home_def = shrink_zero([int(r["i1_against"] == 0) for r in home], league_zero, strength)
    home_off = shrink_zero([int(r["i1_for"] == 0) for r in home], league_zero, strength)
    away_def = shrink_zero([int(r["i1_against"] == 0) for r in away], league_zero, strength)
    return (0.5 * away_off + 0.5 * home_def) * (0.5 * home_off + 0.5 * away_def)


def logloss(p: float, y: int) -> float:
    p = min(1-EPS, max(EPS, p))
    return -(y*math.log(p) + (1-y)*math.log(1-p))


def evaluate(games: list[dict]):
    teams, halves = indexes(games)
    league_cache = {}
    f5_rows, nrfi_rows = [], []
    for g in games:
        season = g["day"].year
        if season not in {TUNE, TEST}:
            continue
        away = prior_team(teams[g["away_id"]], g["day"])
        home = prior_team(teams[g["home_id"]], g["day"])
        if min(len(away), len(home)) < MIN_TEAM_HISTORY:
            continue
        if g["day"] not in league_cache:
            lh = prior_halves(halves, g["day"])
            if len(lh) < MIN_LEAGUE_HALVES:
                continue
            league_cache[g["day"]] = (
                pmf([r[1] for r in lh]),
                fmean(r[2] for r in lh),
            )
        league_f5, league_zero = league_cache[g["day"]]

        frow = {"date": g["day"].isoformat(), "season": season}
        for strength in F5_STRENGTHS:
            name = f"m{strength}"
            away_p = blend(
                smoothed_pmf([r["f5_for"] for r in away], league_f5, strength),
                smoothed_pmf([r["f5_against"] for r in home], league_f5, strength),
            )
            home_p = blend(
                smoothed_pmf([r["f5_for"] for r in home], league_f5, strength),
                smoothed_pmf([r["f5_against"] for r in away], league_f5, strength),
            )
            frow[name] = f5_metrics(
                away_p, home_p, g["away_f5"], g["home_f5"],
                effective_n=min(len(away), len(home)),
            )
        f5_rows.append(frow)

        y = int(g["away_i1"] == 0 and g["home_i1"] == 0)
        p = direct_nrfi(away, home, league_zero, 0)
        nrow = {
            "date": g["day"].isoformat(), "season": season, "nrfi": y,
            NRFI_BASE: {"p": p, "logloss": logloss(p, y), "brier": (p-y)**2},
        }
        for strength in NRFI_STRENGTHS:
            name = f"direct_m{strength}"
            p = direct_nrfi(away, home, league_zero, strength)
            nrow[name] = {"p": p, "logloss": logloss(p, y), "brier": (p-y)**2}
        nrfi_rows.append(nrow)
    return f5_rows, nrfi_rows


def mean(rows: list[dict], candidate: str, metric: str) -> float:
    return fmean(float(r[candidate][metric]) for r in rows)


def quantile(values: list[float], q: float) -> float:
    xs = sorted(values)
    pos = (len(xs)-1)*q
    lo = int(math.floor(pos))
    hi = min(lo+1, len(xs)-1)
    frac = pos-lo
    return xs[lo]*(1-frac) + xs[hi]*frac


def bootstrap(rows: list[dict], selected: str, baseline: str, metric: str) -> dict:
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row[selected][metric] - row[baseline][metric])
    keys = sorted(by_date)
    sums = {k: sum(by_date[k]) for k in keys}
    counts = {k: len(by_date[k]) for k in keys}
    point = sum(sums.values()) / sum(counts.values())
    rng = random.Random(BOOT_SEED)
    vals = []
    for _ in range(BOOT_REPS):
        total = n = 0
        for _j in keys:
            key = keys[rng.randrange(len(keys))]
            total += sums[key]
            n += counts[key]
        vals.append(total/n)
    return {"diff": point, "lo": quantile(vals, 0.025), "hi": quantile(vals, 0.975)}


def ece(rows: list[dict], candidate: str) -> float:
    bins = [[] for _ in range(10)]
    for row in rows:
        p = row[candidate]["p"]
        bins[min(9, int(max(0.0, min(0.999999999, p))*10))].append((p, row["nrfi"]))
    n = len(rows)
    return sum(
        len(b)/n * abs(fmean(x[0] for x in b)-fmean(x[1] for x in b))
        for b in bins if b
    )


def summarize(f5_rows: list[dict], nrfi_rows: list[dict]) -> dict:
    ft = [r for r in f5_rows if r["season"] == TUNE]
    fh = [r for r in f5_rows if r["season"] == TEST]
    nt = [r for r in nrfi_rows if r["season"] == TUNE]
    nh = [r for r in nrfi_rows if r["season"] == TEST]
    if min(len(ft), len(fh), len(nt), len(nh)) < MIN_TEST_GAMES:
        raise RuntimeError("INSUFFICIENT_HELD_OUT_GAMES")

    f5_names = [f"m{x}" for x in F5_STRENGTHS]
    fsel = min(f5_names, key=lambda x: (mean(ft, x, "nll"), f5_names.index(x)))
    fboot = bootstrap(fh, fsel, "m0", "nll")
    fdecision = {
        "selected": fsel,
        "nll_bootstrap": fboot,
        "not_baseline": fsel != "m0",
        "beats_baseline": fboot["hi"] < 0,
        "state_brier_ok": mean(fh, fsel, "state_brier") <= mean(fh, "m0", "state_brier") + 0.002,
        "total45_brier_ok": mean(fh, fsel, "total45_brier") <= mean(fh, "m0", "total45_brier") + 0.002,
    }
    fdecision["ships"] = all(fdecision[k] for k in ("not_baseline","beats_baseline","state_brier_ok","total45_brier_ok"))

    nrfi_names = [NRFI_BASE] + [f"direct_m{x}" for x in NRFI_STRENGTHS]
    nsel = min(nrfi_names, key=lambda x: (mean(nt, x, "logloss"), nrfi_names.index(x)))
    nboot = bootstrap(nh, nsel, NRFI_BASE, "logloss")
    ndecision = {
        "selected": nsel,
        "logloss_bootstrap": nboot,
        "not_baseline": nsel != NRFI_BASE,
        "beats_baseline": nboot["hi"] < 0,
        "brier_ok": mean(nh, nsel, "brier") <= mean(nh, NRFI_BASE, "brier"),
        "ece_selected": ece(nh, nsel),
        "ece_baseline": ece(nh, NRFI_BASE),
    }
    ndecision["ece_ok"] = ndecision["ece_selected"] <= ndecision["ece_baseline"] + 0.005
    ndecision["ships"] = all(ndecision[k] for k in ("not_baseline","beats_baseline","brier_ok","ece_ok"))

    def f5_table(rows):
        return {name: {metric: mean(rows, name, metric) for metric in ("nll","state_brier","total45_brier")} for name in f5_names}

    def nrfi_table(rows):
        return {name: {"logloss": mean(rows,name,"logloss"), "brier": mean(rows,name,"brier"), "ece": ece(rows,name)} for name in nrfi_names}

    return {
        "schema": "MLB_F5_NRFI_TIGHTENING_RESEARCH_V1",
        "games": {"f5_tune":len(ft),"f5_test":len(fh),"nrfi_tune":len(nt),"nrfi_test":len(nh)},
        "f5": {"tune":f5_table(ft),"test":f5_table(fh),"decision":fdecision},
        "nrfi": {"tune":nrfi_table(nt),"test":nrfi_table(nh),"decision":ndecision},
        "authority": {"changes_model_p":False,"promotes_market":False,"grants_official":False,"grants_staking":False},
    }


def report(result: dict) -> str:
    lines = [
        "## MLB F5 + NRFI/YRFI tightening held-out research",
        "",
        "Research only: no production probability or betting authority changes.",
        "",
        f"Units: {result['games']}.",
        "",
        "### F5",
        "| candidate | 2024 NLL | 2025 NLL | 2025 state Brier | 2025 O4.5 Brier |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, tune in result["f5"]["tune"].items():
        test = result["f5"]["test"][name]
        tag = " SELECTED" if name == result["f5"]["decision"]["selected"] else ""
        lines.append(f"| {name}{tag} | {tune['nll']:.4f} | {test['nll']:.4f} | {test['state_brier']:.4f} | {test['total45_brier']:.4f} |")
    d = result["f5"]["decision"]
    b = d["nll_bootstrap"]
    lines += ["", f"F5 delta NLL vs m0: {b['diff']:.4f} [{b['lo']:.4f}, {b['hi']:.4f}]. Decision: {'SHIP SEPARATELY' if d['ships'] else 'DO NOT SHIP'}.", "",
              "### NRFI/YRFI",
              "| candidate | 2024 logloss | 2025 logloss | 2025 Brier | 2025 ECE |",
              "|---|---:|---:|---:|---:|"]
    for name, tune in result["nrfi"]["tune"].items():
        test = result["nrfi"]["test"][name]
        tag = " SELECTED" if name == result["nrfi"]["decision"]["selected"] else ""
        lines.append(f"| {name}{tag} | {tune['logloss']:.4f} | {test['logloss']:.4f} | {test['brier']:.4f} | {test['ece']:.4f} |")
    d = result["nrfi"]["decision"]
    b = d["logloss_bootstrap"]
    lines += ["", f"NRFI delta logloss vs production: {b['diff']:.4f} [{b['lo']:.4f}, {b['hi']:.4f}]. Decision: {'SHIP SEPARATELY' if d['ships'] else 'DO NOT SHIP'}.",
              "", "A passing lane still requires a separate production PR with parity tests.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-f5-nrfi-tightening"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_research_f5_nrfi_tightening"))
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args(argv)
    started = time.time()
    games = fetch(args.cache, args.workers)
    result = summarize(*evaluate(games))
    result["games_loaded"] = len(games)
    result["runtime_seconds"] = time.time()-started
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir/"result.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    md = report(result)
    (args.out_dir/"report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
