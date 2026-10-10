#!/usr/bin/env python3
"""Run the pre-registered H+W+ER extension of the few-starts pitcher fallback (#1482).

Protocol: docs/MLB_PITCHER_PRIOR_FALLBACK_HWE_PREREG.md. Reuses the #1943 StatsAPI
fetch (2022-2025 starters), scores the frozen league_short m=4 fallback on the per-start
sum hits + walks + earned runs for 2025 (decision) and 2024 (sign consistency), and
writes a markdown report. ``--emit-pool`` builds the frozen H+W+ER prior artifact.
Research only: changes no picks.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge import mlb_pitcher_prior_ext_research as X  # noqa: E402
from sportsedge import mlb_pitcher_prior_hwe_research as H  # noqa: E402
from sportsedge import mlb_pitcher_prior_research as R  # noqa: E402

SEASONS = (2022, 2023, 2024, 2025)
CONSISTENCY, TEST = 2024, 2025


def _ext_runner():
    spec = importlib.util.spec_from_file_location("_prior_ext_runner", ROOT / "scripts" / "research_mlb_pitcher_prior_fallback_ext.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def f4(x: float) -> str:
    return f"{x:.4f}"


def run(starts: list[X.XStart]) -> tuple[dict, str]:
    window = R.prior_window_counts(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in SEASONS}
    pools = {y: H.league_short_pool(by_season[y - 1], window) for y in (CONSISTENCY, TEST)}
    test_rows = H.evaluate(by_season[TEST], window, pools[TEST], ks=range(1, 5))
    cons_rows = H.evaluate(by_season[CONSISTENCY], window, pools[CONSISTENCY], ks=range(1, 5))
    k0_rows = H.evaluate(by_season[TEST], window, pools[TEST], ks=[0])
    ref_rows = H.reference_rows(by_season[TEST], window)
    d = H.ship_decision(test_rows, cons_rows, ref_rows)
    by_k = {}
    for k in range(1, 5):
        sub = [r for r in test_rows if r["k"] == k]
        if sub:
            by_k[k] = {"n": len(sub), "own": H.mean_rps(sub, "own"), "fallback": H.mean_rps(sub, "fallback")}
    result = {
        "prereg_sha256": H.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "units": {"test_2025": len(test_rows), "consistency_2024": len(cons_rows), "k0_2025": len(k0_rows), "reference_k_ge_5_2025": len(ref_rows)},
        "rps_2025": {"own": H.mean_rps(test_rows, "own"), "fallback": H.mean_rps(test_rows, "fallback"),
                     "reference_k_ge_5_own": H.mean_rps(ref_rows, "own"), "k0_fallback_info": H.mean_rps(k0_rows, "fallback")},
        "by_k_2025": by_k,
        "decision": d,
    }
    r = result["rps_2025"]
    L = ["## MLB few-starts fallback → Hits + Walks + ER: held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_PITCHER_PRIOR_FALLBACK_HWE_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. "
             "Frozen candidate `league_short m=4` (the #1495 selection, no tuning). Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items())
             + f". Units: 2025 k=1..4 {len(test_rows)}, 2024 k=1..4 {len(cons_rows)}.")
    L.append("")
    L.append("| check | PITCHER_HITS_WALKS_ER |")
    L.append("|---|---|")
    L.append(f"| 2025 RPS own-only → fallback | {f4(r['own'])} → {f4(r['fallback'])} |")
    L.append(f"| 2025 diff [95% CI] | {f4(d['test_vs_own']['diff'])} [{f4(d['test_vs_own']['lo'])}, {f4(d['test_vs_own']['hi'])}] |")
    L.append(f"| 2024 diff (sign check) | {f4(d['consistency_vs_own']['diff'])} |")
    L.append(f"| 2025 typical-line log loss own → fallback | {f4(d['own_typical']['logloss'])} → {f4(d['fallback_typical']['logloss'])} |")
    L.append(f"| 2025 typical-line ECE (cap) | {f4(d['fallback_typical']['ece'])} ({f4(d['ece_cap'])}) |")
    L.append(f"| reference k≥5 RPS / ECE | {f4(r['reference_k_ge_5_own'])} / {f4(d['reference_typical']['ece'])} |")
    L.append(f"| rule 1 (CI < 0) | {'PASS' if d['rule1_beats_own_2025'] else 'FAIL'} |")
    L.append(f"| rule 2 (calibrated) | {'PASS' if d['rule2_calibrated_2025'] else 'FAIL'} |")
    L.append(f"| rule 3 (2024 sign) | {'PASS' if d['rule3_sign_2024'] else 'FAIL'} |")
    L.append(f"| **decision** | {'**SHIPS**' if d['ships'] else '**STAYS BLOCKED**'} |")
    L.append("")
    L.append("By k (2025 RPS own → fallback): " + "; ".join(f"k={k} n={v['n']}: {v['own']:.2f}→{v['fallback']:.2f}" for k, v in by_k.items()))
    L.append(f"k=0 (info only, stays BLOCKED): {len(k0_rows)} starts, fallback RPS {r['k0_fallback_info']:.3f}.")
    L.append("")
    L.append("**Decision (pre-registered rules): " + ("PITCHER_HITS_WALKS_ER may replace BLOCKED for k=1..4 (half lines ≤ 24.5, LEAN max)"
             if d["ships"] else "H+W+ER k<5 stays BLOCKED") + ".**")
    return result, "\n".join(L) + "\n"


def build_hwe_pool_artifact(starts: list[X.XStart], season: int) -> dict:
    """Frozen league_short pool for ``season`` with outs/K and per-start H+W+ER counts (used for season+1 games)."""
    window = R.prior_window_counts(starts)
    short = [s for s in starts if s.season == season and len(window.get(s, ())) < R.MIN_PRODUCTION_STARTS]
    if len(short) < 100:
        raise RuntimeError(f"league_short pool for {season} too small: {len(short)}")
    counts: dict[str, dict[str, int]] = {}
    for name, fn in (("outs", lambda s: s.outs), ("strikeouts", lambda s: s.k), ("hits_walks_er", H.hwe)):
        table: dict[str, int] = {}
        for s in short:
            v = str(fn(s))
            table[v] = table.get(v, 0) + 1
        counts[name] = {k: table[k] for k in sorted(table, key=int)}
    return {
        "schema": "MLB_PITCHER_PRIOR_POOL_HWE_V1", "pool": "league_short", "season": int(season),
        "definition": "regular-season starts in `season` made when the pitcher had <5 prior starts in seasons season-1..season (production window); hits_walks_er is the per-start sum",
        "starts": len(short), "counts": counts,
        "source": "MLB StatsAPI people/{id}/stats gameLog group=pitching gameType=R",
        "built_by": "scripts/research_mlb_pitcher_prior_fallback_hwe.py --emit-pool",
        "validation": "pending RESEARCH pitcher_prior_fallback_hwe (pre-registration sha256 " + H.prereg_sha256() + ")",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-prior-ext-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_prior_hwe_research"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--emit-pool", type=int, help="build the frozen league_short H+W+ER prior artifact for this season")
    args = ap.parse_args(argv)
    t0 = time.time()
    ext = _ext_runner()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.emit_pool:
        season = args.emit_pool
        artifact = build_hwe_pool_artifact(ext.fetch_starts(args.cache, args.workers, seasons=(season - 1, season)), season)
        text = json.dumps(artifact, indent=2) + "\n"
        (args.out_dir / f"mlb_pitcher_prior_league_short_hwe_{season}.json").write_text(text)
        md = (f"## MLB few-starts prior pool artifact, H+W+ER extension ({season})\n\n"
              f"Base cross-check: **{ext.base_cross_check(artifact)}**.\n\n"
              f"Commit as `config/mlb_pitcher_prior_league_short_hwe_{season}.json` (used for {season + 1} games) only if "
              "`RESEARCH pitcher_prior_fallback_hwe` ships. Research output only; nothing is priced until committed.\n\n```json\n" + text + "```\n")
        (args.out_dir / "report.md").write_text(md)
        print(md)
        return 0
    result, md = run(ext.fetch_starts(args.cache, args.workers, seasons=SEASONS))
    md += f"\n_runtime {time.time() - t0:.0f}s_\n"
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
