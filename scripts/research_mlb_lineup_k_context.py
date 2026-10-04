#!/usr/bin/env python3
"""Run the pre-registered announced-lineup K -> pitcher K validation (#1482 D2c).

Fetches StatsAPI schedules (2022-2025), every final regular-season boxscore (batting
orders and batter K/PA), team hitting game logs (2022-2025) and pitching game logs
(2023-2025 starters). Selects one (W_b, gamma) candidate on 2024, evaluates it once on
2025, and writes a markdown report. Research only: changes no picks.
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
from sportsedge import mlb_lineup_k_context_research as R  # noqa: E402
from sportsedge.mlb_opp_k_context_research import OppIndex, production_window  # noqa: E402
from sportsedge.mlb_umpire_context_research import UStart, team_game_rows, ustarts_from_gamelog  # noqa: E402

PITCHER_SEASONS = (2023, 2024, 2025)
TEAM_SEASONS = (2022, 2023, 2024, 2025)
TUNE, TEST = 2024, 2025
MONTHS = ((3, 1, 3, 31), (4, 1, 4, 30), (5, 1, 5, 31), (6, 1, 6, 30), (7, 1, 7, 31), (8, 1, 8, 31), (9, 1, 9, 30), (10, 1, 10, 31))
MIN_LINEUP_SHARE = 0.9


def fetch(cache: Path, workers: int):
    cache.mkdir(parents=True, exist_ok=True)

    def cached(name: str, url: str, compact=None) -> dict:
        f = cache / name
        if f.exists():
            return json.loads(f.read_text())
        payload = _get(url)
        if compact is not None:
            payload = compact(payload)
        f.write_text(json.dumps(payload))
        return payload

    def sone(job):
        season, (m1, d1, m2, d2) = job
        q = urlencode({"sportId": 1, "gameType": "R", "startDate": f"{season}-{m1:02d}-{d1:02d}", "endDate": f"{season}-{m2:02d}-{d2:02d}"})
        return R.final_games_from_schedule(cached(f"s{season}_{m1:02d}.json", f"{API}/schedule?{q}"))

    def bcompact(payload):
        box = R.parse_boxscore(payload)
        return {"orders": [[t, list(o) if o else None] for t, o in box["orders"].items()],
                "lines": [[p, k, pa] for p, (k, pa) in box["lines"].items()]}

    def bone(pk):
        return pk, cached(f"b{pk}.json", f"{API}/game/{pk}/boxscore", bcompact)

    def tone(job):
        tid, season = job
        q = urlencode({"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
        return job, team_game_rows(cached(f"t{tid}_{season}.json", f"{API}/teams/{tid}/stats?{q}"))

    def pone(job):
        pid, season = job
        q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
        return ustarts_from_gamelog(cached(f"p{pid}_{season}.json", f"{API}/people/{pid}/stats?{q}"), pitcher_id=pid, season=season)

    games: dict[int, str] = {}
    teams: dict[tuple[int, int], list] = {}
    starts: list[UStart] = []
    boxes: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(sone, [(s, m) for s in TEAM_SEASONS for m in MONTHS]):
            games.update(got)
        for job, rows in ex.map(tone, [(tid, s) for s in TEAM_SEASONS for tid in team_ids(s)]):
            if len(rows) < 100:
                raise RuntimeError(f"team gameLog {job} looks incomplete (rows with gamePk: {len(rows)})")
            teams[job] = rows
        for rows in ex.map(pone, [(pid, s) for s in PITCHER_SEASONS for pid in season_starters(s)]):
            starts.extend(rows)
        for pk, box in ex.map(bone, sorted(games)):
            boxes[pk] = box
    return games, boxes, teams, starts


def assemble(games: dict[int, str], boxes: dict[int, dict]):
    """lineups[pk][team] = order|None and batter_rows[b] = [(date, K, PA)]."""
    lineups: dict[int, dict[int, tuple[int, ...] | None]] = {}
    batters: dict[int, list[tuple[str, int, int]]] = {}
    for pk, d in games.items():
        box = boxes.get(pk)
        if not box:
            continue
        lineups[pk] = {int(t): (tuple(int(x) for x in o) if o else None) for t, o in box["orders"]}
        for p, k, pa in box["lines"]:
            batters.setdefault(int(p), []).append((d, int(k), int(pa)))
    return lineups, batters


def f4(x: float) -> str:
    return f"{x:.4f}"


def run(games: dict[int, str], boxes: dict[int, dict], teams: dict, starts: list[UStart]) -> tuple[dict, str]:
    lineups, batters = assemble(games, boxes)
    both = sum(1 for v in lineups.values() if len(v) == 2 and all(o is not None for o in v.values()))
    share = both / max(1, len(games))
    if share < MIN_LINEUP_SHARE:
        raise RuntimeError(f"only {share:.1%} of final games have both batting orders; boxscores look incomplete")
    team_k = {key: sorted((d, k, pa) for _pk, d, k, _bb, pa in rows) for key, rows in teams.items()}
    opp = OppIndex(team_k)
    lidx = R.LineupIndex(team_k, batters)
    window = production_window(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in PITCHER_SEASONS}

    tune_rows, tune_counts = R.evaluate(by_season[TUNE], window, lineups, lidx, opp)
    tune = R.rps_table(tune_rows)
    cand = R.select(tune)
    test_rows, test_counts = R.evaluate(by_season[TEST], window, lineups, lidx, opp)
    test = R.rps_table(test_rows)
    decision = R.ship_decision(test_rows, cand)

    devs = np.array([r["dev"] for r in test_rows])
    cuts = np.quantile(devs, [1 / 3, 2 / 3])
    terciles = {}
    if cand != R.BASELINE:
        for name, mask in (("low", devs <= cuts[0]), ("mid", (devs > cuts[0]) & (devs <= cuts[1])), ("high", devs > cuts[1])):
            sub = [r for r, m in zip(test_rows, mask) if m]
            if sub:
                t = R.rps_table(sub)
                terciles[name] = {"n": len(sub), "mean_y": float(np.mean([r["y"] for r in sub])), "base": t[R.BASELINE], "selected": t[cand]}

    result = {
        "prereg_sha256": R.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "final_games": len(games), "games_with_both_lineups": both, "batters": len(batters),
        "selected": R.label(cand), "tune_units": len(tune_rows), "test_units": len(test_rows),
        "counts": {"tune": tune_counts, "test": test_counts},
        "tune_rps": {R.label(c): v for c, v in tune.items()}, "test_rps": {R.label(c): v for c, v in test.items()},
        "dev_spread_w200": {"p10": float(np.quantile(devs, 0.1)), "p90": float(np.quantile(devs, 0.9))},
        "terciles": terciles, "decision": decision,
    }
    L = ["## MLB context lane 2c (announced-lineup K → pitcher K, on top of opp-K): held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_LINEUP_K_CONTEXT_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items())
             + f"; final games: {len(games)}, with both batting orders: {both} ({share:.1%}); batters: {len(batters)}.")
    L.append(f"Units k≥5 with a known target lineup: tune {TUNE} {len(tune_rows)} (dropped, no lineup: {tune_counts['no_target_lineup']}) · "
             f"held-out {TEST} {len(test_rows)} (dropped: {test_counts['no_target_lineup']}). History starts with an unknown lineup: "
             f"{tune_counts['history_unknown_lineup']}/{tune_counts['history_starts']} (tune), {test_counts['history_unknown_lineup']}/{test_counts['history_starts']} (test). "
             f"2025 target D (W_b=200) p10–p90: {result['dev_spread_w200']['p10']:.3f}–{result['dev_spread_w200']['p90']:.3f}.")
    L.append("")
    L.append("| candidate | tune 2024 RPS | held-out 2025 RPS |")
    L.append("|---|---|---|")
    for c in R.CANDIDATES:
        tag = " ← selected" if c == cand and c != R.BASELINE else ""
        L.append(f"| {R.label(c)}{tag} | {f4(tune[c])} | {f4(test[c])} |")
    d = decision
    L.append("")
    L.append("| check (2025) | value | result |")
    L.append("|---|---|---|")
    L.append(f"| rule 1: selected ≠ baseline | {R.label(cand)} | {'PASS' if d['rule1_not_baseline'] else 'FAIL'} |")
    if d["bootstrap_vs_base"]:
        bb = d["bootstrap_vs_base"]
        L.append(f"| rule 2: RPS diff vs production [95% CI] | {f4(bb['diff'])} [{f4(bb['lo'])}, {f4(bb['hi'])}] | {'PASS' if d['rule2_beats_base'] else 'FAIL'} |")
    else:
        L.append("| rule 2: RPS diff vs production | n/a (baseline selected) | FAIL |")
    L.append(f"| rule 3: typical-line ECE ≤ base + 0.005 | {f4(d['typical_selected']['ece'])} vs {f4(d['typical_base']['ece'])} | {'PASS' if d['rule3_calibrated'] else 'FAIL'} |")
    L.append(f"| typical-line log loss (info) | {f4(d['typical_selected']['logloss'])} vs {f4(d['typical_base']['logloss'])} | |")
    if terciles:
        L.append("")
        L.append("By target lineup-deviation tercile (2025, info only): " + "; ".join(
            f"{k} n={v['n']} mean {v['mean_y']:.2f}: base {f4(v['base'])} → sel {f4(v['selected'])}" for k, v in terciles.items()))
    L.append("")
    L.append("**Decision (pre-registered rules): "
             + (f"SHIPS — wire {R.label(cand)} into PITCHER_K when the lineup is posted (k≥5, lean-tier)" if d["ships"] else "DOES NOT SHIP — PITCHER_K keeps its current price") + ".**")
    return result, "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-lineup-k-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_lineup_k_research"))
    ap.add_argument("--workers", type=int, default=24)
    args = ap.parse_args(argv)
    t0 = time.time()
    games, boxes, teams, starts = fetch(args.cache, args.workers)
    t_fetch = time.time() - t0
    result, md = run(games, boxes, teams, starts)
    md += f"\n_runtime {time.time() - t0:.0f}s (fetch {t_fetch:.0f}s)_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
