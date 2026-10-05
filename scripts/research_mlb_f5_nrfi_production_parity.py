#!/usr/bin/env python3
"""2026 confirmation of the frozen MLB F5/NRFI m30 league prior.

This is a no-retuning production-parity study. Team history reproduces the
current live 240-day/no-gameType-filter surface; the already-selected challenger
adds only the frozen 30-pseudo-game regular-season league prior.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import research_mlb_f5_nrfi_tightening as R  # noqa: E402

SEASONS = (2025, 2026)
MONTHS = ((2, 1, 2, 28),) + R.MONTHS + ((11, 1, 11, 30),)
TEST = 2026
PRODUCTION_LOOKBACK_DAYS = 240
LEAGUE_LOOKBACK_DAYS = 370
TEAM_WINDOW = 30
MIN_TEAM_HISTORY = 10
MIN_LEAGUE_HALVES = 200
MIN_TEST_GAMES = 1000
PRIOR_STRENGTH = 30
BOOT_REPS = 2000
BOOT_SEED = 20261005
BASE_F5 = "production_m0"
CAND_F5 = "candidate_m30"
BASE_NRFI = "production_empirical_jeffreys"
CAND_NRFI = "candidate_m30"


def _fetch_one(cache: Path, season: int, month: tuple[int, int, int, int], regular_only: bool):
    m1, d1, m2, d2 = month
    flavor = "regular" if regular_only else "all"
    path = cache / f"schedule_{flavor}_{season}_{m1:02d}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        query = {
            "sportId": 1,
            "hydrate": "linescore",
            "startDate": f"{season}-{m1:02d}-{d1:02d}",
            "endDate": f"{season}-{m2:02d}-{d2:02d}",
        }
        if regular_only:
            query["gameType"] = "R"
        payload = R._get(f"{R.API}/schedule?{urlencode(query)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return R._parse(payload)


def fetch(cache: Path, workers: int):
    jobs = [
        (season, month, regular)
        for season in SEASONS
        for month in MONTHS
        for regular in (False, True)
    ]
    all_by_pk = {}
    regular_by_pk = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (season, month, regular), rows in zip(
            jobs,
            pool.map(lambda job: _fetch_one(cache, *job), jobs),
        ):
            target = regular_by_pk if regular else all_by_pk
            for row in rows:
                target[row["game_pk"]] = row
    return (
        sorted(all_by_pk.values(), key=lambda x: (x["day"], x["game_pk"])),
        sorted(regular_by_pk.values(), key=lambda x: (x["day"], x["game_pk"])),
    )


def indexes(all_games, regular_games):
    teams = defaultdict(list)
    for g in all_games:
        teams[g["away_id"]].append({
            "day": g["day"],
            "i1_for": g["away_i1"],
            "i1_against": g["home_i1"],
            "f5_for": g["away_f5"],
            "f5_against": g["home_f5"],
        })
        teams[g["home_id"]].append({
            "day": g["day"],
            "i1_for": g["home_i1"],
            "i1_against": g["away_i1"],
            "f5_for": g["home_f5"],
            "f5_against": g["away_f5"],
        })
    halves = []
    for g in regular_games:
        halves.append((g["day"], g["away_f5"], int(g["away_i1"] == 0)))
        halves.append((g["day"], g["home_f5"], int(g["home_i1"] == 0)))
    return teams, sorted(halves, key=lambda x: x[0])


def prior_team(rows, target: date):
    cutoff = target - timedelta(days=PRODUCTION_LOOKBACK_DAYS)
    return [r for r in rows if cutoff <= r["day"] < target][-TEAM_WINDOW:]


def prior_halves(rows, target: date):
    cutoff = target - timedelta(days=LEAGUE_LOOKBACK_DAYS)
    return [r for r in rows if cutoff <= r[0] < target]


def evaluate(all_games, regular_games):
    teams, halves = indexes(all_games, regular_games)
    league_cache = {}
    f5_rows = []
    nrfi_rows = []

    targets = [g for g in regular_games if g["day"].year == TEST]
    for g in targets:
        away = prior_team(teams[g["away_id"]], g["day"])
        home = prior_team(teams[g["home_id"]], g["day"])
        if min(len(away), len(home)) < MIN_TEAM_HISTORY:
            continue

        if g["day"] not in league_cache:
            lh = prior_halves(halves, g["day"])
            if len(lh) < MIN_LEAGUE_HALVES:
                continue
            league_cache[g["day"]] = (
                R.pmf([row[1] for row in lh]),
                fmean(row[2] for row in lh),
            )
        league_f5, league_zero = league_cache[g["day"]]
        effective_n = min(len(away), len(home))

        frow = {"date": g["day"].isoformat()}
        for name, strength in ((BASE_F5, 0), (CAND_F5, PRIOR_STRENGTH)):
            away_p = R.blend(
                R.smoothed_pmf([r["f5_for"] for r in away], league_f5, strength),
                R.smoothed_pmf([r["f5_against"] for r in home], league_f5, strength),
            )
            home_p = R.blend(
                R.smoothed_pmf([r["f5_for"] for r in home], league_f5, strength),
                R.smoothed_pmf([r["f5_against"] for r in away], league_f5, strength),
            )
            frow[name] = R.f5_metrics(
                away_p,
                home_p,
                g["away_f5"],
                g["home_f5"],
                effective_n=effective_n,
            )
        f5_rows.append(frow)

        y = int(g["away_i1"] == 0 and g["home_i1"] == 0)
        nrow = {"date": g["day"].isoformat(), "nrfi": y}
        for name, strength in ((BASE_NRFI, 0), (CAND_NRFI, PRIOR_STRENGTH)):
            p = R.direct_nrfi(away, home, league_zero, strength)
            nrow[name] = {
                "p": p,
                "logloss": R.logloss(p, y),
                "brier": (p - y) ** 2,
            }
        nrfi_rows.append(nrow)

    return f5_rows, nrfi_rows


def _mean(rows, candidate, metric):
    return fmean(float(row[candidate][metric]) for row in rows)


def bootstrap(rows, selected, baseline, metric):
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row[selected][metric] - row[baseline][metric])
    keys = sorted(by_date)
    sums = {key: sum(by_date[key]) for key in keys}
    counts = {key: len(by_date[key]) for key in keys}
    point = sum(sums.values()) / sum(counts.values())
    rng = random.Random(BOOT_SEED)
    values = []
    for _ in range(BOOT_REPS):
        total = 0.0
        n = 0
        for _j in keys:
            key = keys[rng.randrange(len(keys))]
            total += sums[key]
            n += counts[key]
        values.append(total / n)
    return {
        "diff": point,
        "lo": R.quantile(values, 0.025),
        "hi": R.quantile(values, 0.975),
    }


def summarize(f5_rows, nrfi_rows):
    if min(len(f5_rows), len(nrfi_rows)) < MIN_TEST_GAMES:
        raise RuntimeError(
            f"INSUFFICIENT_2026_GAMES:f5={len(f5_rows)}:nrfi={len(nrfi_rows)}"
        )

    fboot = bootstrap(f5_rows, CAND_F5, BASE_F5, "nll")
    f5 = {
        "n": len(f5_rows),
        "production": {
            metric: _mean(f5_rows, BASE_F5, metric)
            for metric in ("nll", "state_brier", "total45_brier")
        },
        "candidate": {
            metric: _mean(f5_rows, CAND_F5, metric)
            for metric in ("nll", "state_brier", "total45_brier")
        },
        "nll_bootstrap": fboot,
    }
    f5["beats_production"] = fboot["hi"] < 0
    f5["state_brier_ok"] = (
        f5["candidate"]["state_brier"] <= f5["production"]["state_brier"] + 0.002
    )
    f5["total45_brier_ok"] = (
        f5["candidate"]["total45_brier"] <= f5["production"]["total45_brier"] + 0.002
    )
    f5["ships"] = (
        f5["n"] >= MIN_TEST_GAMES
        and f5["beats_production"]
        and f5["state_brier_ok"]
        and f5["total45_brier_ok"]
    )

    nboot = bootstrap(nrfi_rows, CAND_NRFI, BASE_NRFI, "logloss")
    nrfi = {
        "n": len(nrfi_rows),
        "production": {
            "logloss": _mean(nrfi_rows, BASE_NRFI, "logloss"),
            "brier": _mean(nrfi_rows, BASE_NRFI, "brier"),
            "ece": R.ece(nrfi_rows, BASE_NRFI),
        },
        "candidate": {
            "logloss": _mean(nrfi_rows, CAND_NRFI, "logloss"),
            "brier": _mean(nrfi_rows, CAND_NRFI, "brier"),
            "ece": R.ece(nrfi_rows, CAND_NRFI),
        },
        "logloss_bootstrap": nboot,
    }
    nrfi["beats_production"] = nboot["hi"] < 0
    nrfi["brier_ok"] = nrfi["candidate"]["brier"] <= nrfi["production"]["brier"]
    nrfi["ece_ok"] = nrfi["candidate"]["ece"] <= nrfi["production"]["ece"] + 0.005
    nrfi["ships"] = (
        nrfi["n"] >= MIN_TEST_GAMES
        and nrfi["beats_production"]
        and nrfi["brier_ok"]
        and nrfi["ece_ok"]
    )

    return {
        "schema": "MLB_F5_NRFI_PRODUCTION_PARITY_2026_V1",
        "candidate": {"prior_strength": PRIOR_STRENGTH, "retuned": False},
        "history_surface": {
            "team_lookback_days": PRODUCTION_LOOKBACK_DAYS,
            "team_window_games": TEAM_WINDOW,
            "team_game_type_filter": None,
            "league_lookback_days": LEAGUE_LOOKBACK_DAYS,
            "league_game_type": "R",
        },
        "f5": f5,
        "nrfi": nrfi,
        "authority": {
            "changes_model_p": False,
            "promotes_market": False,
            "grants_official": False,
            "grants_staking": False,
        },
    }


def report(result):
    f5 = result["f5"]
    nrfi = result["nrfi"]
    fb = f5["nll_bootstrap"]
    nb = nrfi["logloss_bootstrap"]
    lines = [
        "## MLB F5 + NRFI/YRFI 2026 production-parity confirmation",
        "",
        "Fixed candidate: m30. No retuning. Research only.",
        "",
        f"Eligible 2026 games: F5={f5['n']}, NRFI={nrfi['n']}.",
        "",
        "### F5",
        "| model | NLL | W/T/L Brier | O4.5 Brier |",
        "|---|---:|---:|---:|",
        (
            f"| production_m0 | {f5['production']['nll']:.4f} | "
            f"{f5['production']['state_brier']:.4f} | "
            f"{f5['production']['total45_brier']:.4f} |"
        ),
        (
            f"| candidate_m30 | {f5['candidate']['nll']:.4f} | "
            f"{f5['candidate']['state_brier']:.4f} | "
            f"{f5['candidate']['total45_brier']:.4f} |"
        ),
        "",
        (
            f"F5 delta NLL vs actual production-history baseline: "
            f"{fb['diff']:.4f} [{fb['lo']:.4f}, {fb['hi']:.4f}]. "
            f"Decision: {'SHIP' if f5['ships'] else 'DO NOT SHIP'}."
        ),
        "",
        "### NRFI/YRFI",
        "| model | logloss | Brier | ECE |",
        "|---|---:|---:|---:|",
        (
            f"| production_empirical_jeffreys | "
            f"{nrfi['production']['logloss']:.4f} | "
            f"{nrfi['production']['brier']:.4f} | "
            f"{nrfi['production']['ece']:.4f} |"
        ),
        (
            f"| candidate_m30 | {nrfi['candidate']['logloss']:.4f} | "
            f"{nrfi['candidate']['brier']:.4f} | "
            f"{nrfi['candidate']['ece']:.4f} |"
        ),
        "",
        (
            f"NRFI delta logloss vs actual production-history baseline: "
            f"{nb['diff']:.4f} [{nb['lo']:.4f}, {nb['hi']:.4f}]. "
            f"Decision: {'SHIP' if nrfi['ships'] else 'DO NOT SHIP'}."
        ),
        "",
        "A SHIP result authorizes only a separate production implementation with parity tests.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cache",
        type=Path,
        default=Path(".cache/mlb-f5-nrfi-production-parity"),
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/mlb_research_f5_nrfi_production_parity"),
    )
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args(argv)

    started = time.time()
    all_games, regular_games = fetch(args.cache, args.workers)
    result = summarize(*evaluate(all_games, regular_games))
    result["all_games_loaded"] = len(all_games)
    result["regular_games_loaded"] = len(regular_games)
    result["runtime_seconds"] = time.time() - started
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md = report(result)
    (args.out_dir / "report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
