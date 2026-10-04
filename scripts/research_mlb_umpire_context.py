#!/usr/bin/env python3
"""Run the pre-registered home-plate umpire -> pitcher K / BB validation (#1482 D2b).

Fetches StatsAPI schedules with officials (2022-2025), team hitting game logs
(2022-2025) and pitching game logs (2023-2025 starters). For each sub-lane (K, BB) it
selects one (W, beta) candidate on 2024, evaluates it once on 2025, and writes a
markdown report. Research only: changes no picks.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research_mlb_opp_k_context import team_ids  # noqa: E402
from scripts.research_mlb_pitcher_prior_fallback import API, _get, season_starters  # noqa: E402
from sportsedge import mlb_umpire_context_research as R  # noqa: E402
from sportsedge.mlb_opp_k_context_research import OppIndex, production_window  # noqa: E402

PITCHER_SEASONS = (2023, 2024, 2025)
TEAM_SEASONS = (2022, 2023, 2024, 2025)
TUNE, TEST = 2024, 2025
MONTHS = ((3, 1, 3, 31), (4, 1, 4, 30), (5, 1, 5, 31), (6, 1, 6, 30), (7, 1, 7, 31), (8, 1, 8, 31), (9, 1, 9, 30), (10, 1, 10, 31))
MIN_USABLE_SHARE = 0.9


def fetch(cache: Path, workers: int):
    cache.mkdir(parents=True, exist_ok=True)

    def cached(name: str, url: str) -> dict:
        f = cache / name
        if f.exists():
            return json.loads(f.read_text())
        payload = _get(url)
        f.write_text(json.dumps(payload))
        return payload

    sjobs = [(season, m) for season in TEAM_SEASONS for m in MONTHS]
    tjobs = [(tid, season) for season in TEAM_SEASONS for tid in team_ids(season)]
    pjobs = [(pid, season) for season in PITCHER_SEASONS for pid in season_starters(season)]

    def sone(job):
        season, (m1, d1, m2, d2) = job
        q = urlencode({"sportId": 1, "gameType": "R", "hydrate": "officials",
                       "startDate": f"{season}-{m1:02d}-{d1:02d}", "endDate": f"{season}-{m2:02d}-{d2:02d}"})
        return R.home_plate_by_game(cached(f"s{season}_{m1:02d}.json", f"{API}/schedule?{q}"))

    def tone(job):
        tid, season = job
        q = urlencode({"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
        return job, R.team_game_rows(cached(f"t{tid}_{season}.json", f"{API}/teams/{tid}/stats?{q}"))

    def pone(job):
        pid, season = job
        q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
        return R.ustarts_from_gamelog(cached(f"p{pid}_{season}.json", f"{API}/people/{pid}/stats?{q}"), pitcher_id=pid, season=season)

    umps: dict[int, int] = {}
    teams: dict[tuple[int, int], list] = {}
    starts: list[R.UStart] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(sone, sjobs):
            umps.update(got)
        for job, rows in ex.map(tone, tjobs):
            if len(rows) < 100:
                raise RuntimeError(f"team gameLog {job} looks incomplete (rows with gamePk: {len(rows)})")
            teams[job] = rows
        for rows in ex.map(pone, pjobs):
            starts.extend(rows)
    return starts, teams, umps


def f4(x: float) -> str:
    return f"{x:.4f}"


def _lane(stat: str, by_season, window, umps, uidx, opp) -> dict:
    tune_rows, tune_drop = R.evaluate(stat, by_season[TUNE], window, umps, uidx, opp)
    tune = R.rps_table(tune_rows, stat)
    cand = R.select(tune)
    test_rows, test_drop = R.evaluate(stat, by_season[TEST], window, umps, uidx, opp)
    test = R.rps_table(test_rows, stat)
    decision = R.ship_decision(test_rows, cand, stat)
    terciles = {}
    if cand != R.BASELINE:
        rels = np.array([uidx.rel(r["ump"], r["date"], stat, cand[0]) for r in test_rows])
        cuts = np.quantile(rels, [1 / 3, 2 / 3])
        for name, mask in (("low", rels <= cuts[0]), ("mid", (rels > cuts[0]) & (rels <= cuts[1])), ("high", rels > cuts[1])):
            sub = [r for r, m in zip(test_rows, mask) if m]
            if sub:
                t = R.rps_table(sub, stat)
                terciles[name] = {"n": len(sub), "mean_y": float(np.mean([r["y"] for r in sub])), "base": t[R.BASELINE], "selected": t[cand]}
    spread = np.array([r["rel"] for r in test_rows])
    return {"stat": stat, "cand": cand, "tune": tune, "test": test, "tune_units": len(tune_rows), "test_units": len(test_rows),
            "tune_dropped_no_ump": tune_drop, "test_dropped_no_ump": test_drop, "decision": decision, "terciles": terciles,
            "spread_w2000": {"p10": float(np.quantile(spread, 0.1)), "p90": float(np.quantile(spread, 0.9))}}


def run(starts: list[R.UStart], teams: dict, umps: dict[int, int]) -> tuple[dict, str]:
    flat = [row for rows in teams.values() for row in rows]
    games = R.game_totals(flat)
    uidx = R.UmpIndex(games, umps)
    share = uidx.usable_games / max(1, len(games))
    if share < MIN_USABLE_SHARE:
        raise RuntimeError(f"only {share:.1%} of games have a home-plate umpire; schedule officials look incomplete")
    opp = OppIndex({key: sorted((d, k, pa) for _pk, d, k, _bb, pa in rows) for key, rows in teams.items()})
    window = production_window(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in PITCHER_SEASONS}
    lanes = {stat: _lane(stat, by_season, window, umps, uidx, opp) for stat in R.STATS}

    result = {
        "prereg_sha256": R.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "games_with_both_team_rows": len(games), "games_with_hp_umpire": uidx.usable_games,
        "lanes": {stat: {"selected": R.label(l["cand"]), "tune_units": l["tune_units"], "test_units": l["test_units"],
                         "dropped_no_ump": {"tune": l["tune_dropped_no_ump"], "test": l["test_dropped_no_ump"]},
                         "tune_rps": {R.label(c): v for c, v in l["tune"].items()},
                         "test_rps": {R.label(c): v for c, v in l["test"].items()},
                         "terciles": l["terciles"], "spread_w2000": l["spread_w2000"], "decision": l["decision"]}
                  for stat, l in lanes.items()},
    }
    L = ["## MLB context lane 2b (home-plate umpire → pitcher K / BB): held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_UMPIRE_CONTEXT_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items())
             + f"; games with both team rows: {len(games)}, with a home-plate umpire: {uidx.usable_games} ({share:.1%}).")
    for stat, l in lanes.items():
        name = {"k": "2b-K (umpire K index → PITCHER_K; baseline = production opp-K lane)", "bb": "2b-BB (umpire BB index → PITCHER_BB; baseline = own history)"}[stat]
        d = l["decision"]
        L.append("")
        L.append(f"### {name}")
        L.append(f"Units k≥5 with a known umpire: tune {TUNE} {l['tune_units']} (dropped, no umpire: {l['tune_dropped_no_ump']}) · "
                 f"held-out {TEST} {l['test_units']} (dropped: {l['test_dropped_no_ump']}). "
                 f"2025 target index (W=2000) p10–p90: {l['spread_w2000']['p10']:.3f}–{l['spread_w2000']['p90']:.3f}.")
        L.append("")
        L.append("| candidate | tune 2024 RPS | held-out 2025 RPS |")
        L.append("|---|---|---|")
        for c in R.CANDIDATES:
            tag = " ← selected" if c == l["cand"] and c != R.BASELINE else ""
            L.append(f"| {R.label(c)}{tag} | {f4(l['tune'][c])} | {f4(l['test'][c])} |")
        L.append("")
        L.append("| check (2025) | value | result |")
        L.append("|---|---|---|")
        L.append(f"| rule 1: selected ≠ baseline | {R.label(l['cand'])} | {'PASS' if d['rule1_not_baseline'] else 'FAIL'} |")
        if d["bootstrap_vs_base"]:
            bb = d["bootstrap_vs_base"]
            L.append(f"| rule 2: RPS diff vs production [95% CI] | {f4(bb['diff'])} [{f4(bb['lo'])}, {f4(bb['hi'])}] | {'PASS' if d['rule2_beats_base'] else 'FAIL'} |")
        else:
            L.append("| rule 2: RPS diff vs production | n/a (baseline selected) | FAIL |")
        L.append(f"| rule 3: typical-line ECE ≤ base + 0.005 | {f4(d['typical_selected']['ece'])} vs {f4(d['typical_base']['ece'])} | {'PASS' if d['rule3_calibrated'] else 'FAIL'} |")
        L.append(f"| typical-line log loss (info) | {f4(d['typical_selected']['logloss'])} vs {f4(d['typical_base']['logloss'])} | |")
        if l["terciles"]:
            L.append("")
            L.append("By target-umpire tercile (2025, info only): " + "; ".join(
                f"{k} n={v['n']} mean {v['mean_y']:.2f}: base {f4(v['base'])} → sel {f4(v['selected'])}" for k, v in l["terciles"].items()))
        mk = "PITCHER_K" if stat == "k" else "PITCHER_BB"
        L.append("")
        L.append(f"**Decision {name.split(' ')[0]} (pre-registered rules): "
                 + (f"SHIPS — wire {R.label(l['cand'])} into {mk} (k≥5, lean-tier)" if d["ships"] else f"DOES NOT SHIP — {mk} keeps its current price") + ".**")
    return result, "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-umpire-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_umpire_research"))
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args(argv)
    t0 = time.time()
    starts, teams, umps = fetch(args.cache, args.workers)
    result, md = run(starts, teams, umps)
    md += f"\n_runtime {time.time() - t0:.0f}s_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
