#!/usr/bin/env python3
"""Run the pre-registered opponent-K context lane validation (#1482 item D, lane 1).

Fetches StatsAPI pitching game logs (2023-2025 starters) and team hitting game logs
(2022-2025), tunes beta on 2024, evaluates once on 2025, writes a markdown report.
Research only: changes no picks.
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

from scripts.research_mlb_pitcher_prior_fallback import API, _get, season_starters  # noqa: E402
from sportsedge import mlb_opp_k_context_research as O  # noqa: E402

PITCHER_SEASONS = (2023, 2024, 2025)
TEAM_SEASONS = (2022, 2023, 2024, 2025)
TUNE, TEST = 2024, 2025


def team_ids(season: int) -> list[int]:
    payload = _get(f"{API}/teams?{urlencode({'sportId': 1, 'season': season})}")
    ids = sorted(int(t["id"]) for t in payload.get("teams") or [] if t.get("id"))
    if len(ids) != 30:
        raise RuntimeError(f"expected 30 MLB teams for {season}, got {len(ids)}")
    return ids


def fetch(cache: Path, workers: int) -> tuple[list[O.KStart], dict[tuple[int, int], list[tuple[str, int, int]]]]:
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
        return O.kstarts_from_gamelog(cached(f"p{pid}_{season}.json", f"{API}/people/{pid}/stats?{q}"), pitcher_id=pid, season=season)

    def tone(job):
        tid, season = job
        q = urlencode({"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
        return job, O.team_games_from_gamelog(cached(f"t{tid}_{season}.json", f"{API}/teams/{tid}/stats?{q}"))

    starts: list[O.KStart] = []
    teams: dict[tuple[int, int], list[tuple[str, int, int]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for job, rows in ex.map(tone, tjobs):
            if len(rows) < 100:
                raise RuntimeError(f"team gameLog {job} looks incomplete: {len(rows)} games")
            teams[job] = rows
        for rows in ex.map(pone, pjobs):
            starts.extend(rows)
    return starts, teams


def f4(x: float) -> str:
    return f"{x:.4f}"


def run(starts: list[O.KStart], teams: dict) -> tuple[dict, str]:
    index = O.OppIndex(teams)
    window = O.production_window(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in PITCHER_SEASONS}
    tune_rows = O.evaluate(by_season[TUNE], window, index)
    tune = O.rps_table(tune_rows)
    beta = O.select_beta(tune)
    test_rows = O.evaluate(by_season[TEST], window, index)
    test = O.rps_table(test_rows)
    decision = O.ship_decision(test_rows, beta)

    rels = np.array([r["opp_rel"] for r in test_rows])
    cuts = np.quantile(rels, [1 / 3, 2 / 3])
    terciles = {}
    for name, mask in (("low-K opp", rels <= cuts[0]), ("mid", (rels > cuts[0]) & (rels <= cuts[1])), ("high-K opp", rels > cuts[1])):
        sub = [r for r, m in zip(test_rows, mask) if m]
        if sub:
            t = O.rps_table(sub)
            terciles[name] = {"n": len(sub), "mean_y": float(np.mean([r["y_k"] for r in sub])), "base": t[0.0], "selected": t[beta]}

    result = {
        "prereg_sha256": O.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "team_seasons": len(teams),
        "opp_index_2025": {"min": float(rels.min()), "p10": float(np.quantile(rels, 0.1)), "p90": float(np.quantile(rels, 0.9)), "max": float(rels.max())},
        "tune": {"season": TUNE, "units": len(tune_rows), "rps": tune, "beta": beta},
        "test": {"season": TEST, "units": len(test_rows), "rps": test, "terciles": terciles},
        "decision": decision,
    }
    d = decision
    L = ["## MLB context lane 1 (opponent K rate → pitcher K): held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_OPP_K_CONTEXT_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items()) + f"; team-seasons: {len(teams)}.")
    oi = result["opp_index_2025"]
    L.append(f"2025 opponent index spread: p10 {oi['p10']:.3f}, p90 {oi['p90']:.3f} (min {oi['min']:.3f}, max {oi['max']:.3f}).")
    L.append("")
    L.append(f"### Mean K RPS, k≥5 path (tune {TUNE}: {len(tune_rows)} starts · held-out {TEST}: {len(test_rows)} starts)")
    L.append("| beta | tune 2024 | held-out 2025 |")
    L.append("|---|---|---|")
    for b in O.BETAS:
        tag = " (production)" if b == 0 else (" ← selected" if b == beta else "")
        L.append(f"| {b:g}{tag} | {f4(tune[b])} | {f4(test[b])} |")
    L.append("")
    L.append("| check (2025) | value | result |")
    L.append("|---|---|---|")
    L.append(f"| rule 1: tuned beta > 0 | {beta:g} | {'PASS' if d['rule1_beta_positive'] else 'FAIL'} |")
    if d["bootstrap_vs_base"]:
        bb = d["bootstrap_vs_base"]
        L.append(f"| rule 2: RPS diff vs production [95% CI] | {f4(bb['diff'])} [{f4(bb['lo'])}, {f4(bb['hi'])}] | {'PASS' if d['rule2_beats_base'] else 'FAIL'} |")
    else:
        L.append("| rule 2: RPS diff vs production | n/a (beta = 0) | FAIL |")
    L.append(f"| rule 3: typical-line ECE ≤ base + 0.005 | {f4(d['typical_selected']['ece'])} vs {f4(d['typical_base']['ece'])} | {'PASS' if d['rule3_calibrated'] else 'FAIL'} |")
    L.append(f"| typical-line log loss (info) | {f4(d['typical_selected']['logloss'])} vs {f4(d['typical_base']['logloss'])} | |")
    L.append("")
    if terciles:
        L.append("By opponent-index tercile (2025, info only): " + "; ".join(
            f"{k} n={v['n']} mean K {v['mean_y']:.2f}: base {f4(v['base'])} → sel {f4(v['selected'])}" for k, v in terciles.items()))
        L.append("")
    L.append(f"**Decision (pre-registered rules): {'SHIPS — wire opponent-K adjustment into PITCHER_K (k≥5, lean-tier)' if d['ships'] else 'DOES NOT SHIP — pitcher K stays own-history only'}.**")
    return result, "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-oppk-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_oppk_research"))
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
