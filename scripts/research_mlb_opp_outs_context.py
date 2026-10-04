#!/usr/bin/env python3
"""Run the pre-registered opponent-profile -> pitcher outs validation (#1482 D2a).

Fetches StatsAPI pitching game logs (2023-2025 starters) and team hitting game logs
(2022-2025), selects one (index, beta) candidate on 2024, evaluates it once on 2025,
and writes a markdown report. Research only: changes no picks.
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
from sportsedge import mlb_opp_outs_context_research as R  # noqa: E402
from sportsedge.mlb_opp_k_context_research import production_window  # noqa: E402

PITCHER_SEASONS = (2023, 2024, 2025)
TEAM_SEASONS = (2022, 2023, 2024, 2025)
TUNE, TEST = 2024, 2025


def fetch(cache: Path, workers: int) -> tuple[list[R.OStart], dict[tuple[int, int], dict[str, list]]]:
    cache.mkdir(parents=True, exist_ok=True)

    def cached(name: str, url: str) -> dict:
        f = cache / name
        if f.exists():
            return json.loads(f.read_text())
        payload = _get(url)
        f.write_text(json.dumps(payload))
        return payload

    pjobs = [(pid, season) for season in PITCHER_SEASONS for pid in season_starters(season)]
    tjobs = [(tid, season) for season in TEAM_SEASONS for tid in team_ids(season)]

    def pone(job):
        pid, season = job
        q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
        return R.ostarts_from_gamelog(cached(f"p{pid}_{season}.json", f"{API}/people/{pid}/stats?{q}"), pitcher_id=pid, season=season)

    def tone(job):
        tid, season = job
        q = urlencode({"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
        return job, R.team_rows_from_gamelog(cached(f"t{tid}_{season}.json", f"{API}/teams/{tid}/stats?{q}"))

    starts: list[R.OStart] = []
    teams: dict[tuple[int, int], dict[str, list]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for job, rows in ex.map(tone, tjobs):
            if min(len(v) for v in rows.values()) < 100:
                raise RuntimeError(f"team gameLog {job} looks incomplete: {len(rows['kidx'])} games")
            teams[job] = rows
        for rows in ex.map(pone, pjobs):
            starts.extend(rows)
    return starts, teams


def f4(x: float) -> str:
    return f"{x:.4f}"


def run(starts: list[R.OStart], teams: dict) -> tuple[dict, str]:
    indices = R.build_indices(teams)
    window = production_window(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in PITCHER_SEASONS}
    tune_rows = R.evaluate(by_season[TUNE], window, indices)
    tune = R.rps_table(tune_rows)
    cand = R.select(tune)
    test_rows = R.evaluate(by_season[TEST], window, indices)
    test = R.rps_table(test_rows)
    decision = R.ship_decision(test_rows, cand)

    terciles = {}
    if cand != R.BASELINE:
        rels = np.array([r["rel"][cand[0]] for r in test_rows])
        cuts = np.quantile(rels, [1 / 3, 2 / 3])
        for name, mask in (("low", rels <= cuts[0]), ("mid", (rels > cuts[0]) & (rels <= cuts[1])), ("high", rels > cuts[1])):
            sub = [r for r, m in zip(test_rows, mask) if m]
            if sub:
                t = R.rps_table(sub)
                terciles[name] = {"n": len(sub), "mean_y": float(np.mean([r["y_outs"] for r in sub])),
                                  "base": t[R.BASELINE], "selected": t[cand]}
    spread = {}
    for n in R.INDICES:
        v = np.array([r["rel"][n] for r in test_rows])
        spread[n] = {"p10": float(np.quantile(v, 0.1)), "p90": float(np.quantile(v, 0.9))}

    result = {
        "prereg_sha256": R.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "team_seasons": len(teams),
        "index_spread_2025": spread,
        "tune": {"season": TUNE, "units": len(tune_rows), "rps": {R.label(c): v for c, v in tune.items()}, "selected": R.label(cand)},
        "test": {"season": TEST, "units": len(test_rows), "rps": {R.label(c): v for c, v in test.items()}, "terciles": terciles},
        "decision": decision,
    }
    d = decision
    L = ["## MLB context lane 2a (opponent profile → pitcher outs): held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_OPP_OUTS_CONTEXT_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items()) + f"; team-seasons: {len(teams)}.")
    L.append("2025 index spread (p10–p90): " + "; ".join(f"{n} {v['p10']:.3f}–{v['p90']:.3f}" for n, v in spread.items()) + ".")
    L.append("")
    L.append(f"### Mean outs RPS, k≥5 path (tune {TUNE}: {len(tune_rows)} starts · held-out {TEST}: {len(test_rows)} starts)")
    L.append("| candidate | tune 2024 | held-out 2025 |")
    L.append("|---|---|---|")
    for c in R.CANDIDATES:
        tag = " ← selected" if c == cand and c != R.BASELINE else ""
        L.append(f"| {R.label(c)}{tag} | {f4(tune[c])} | {f4(test[c])} |")
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
    L.append("")
    if terciles:
        L.append(f"By {cand[0]} tercile (2025, info only): " + "; ".join(
            f"{k} n={v['n']} mean outs {v['mean_y']:.2f}: base {f4(v['base'])} → sel {f4(v['selected'])}" for k, v in terciles.items()))
        L.append("")
    L.append(f"**Decision (pre-registered rules): {'SHIPS — wire ' + R.label(cand) + ' into PITCHER_OUTS (k≥5, lean-tier)' if d['ships'] else 'DOES NOT SHIP — pitcher outs stay own-history only'}.**")
    return result, "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-oppouts-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_oppouts_research"))
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args(argv)
    t0 = time.time()
    starts, teams = fetch(args.cache, args.workers)
    result, md = run(starts, teams)
    md += f"\n_runtime {time.time() - t0:.0f}s_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
