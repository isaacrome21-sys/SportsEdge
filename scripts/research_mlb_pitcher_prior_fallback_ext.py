#!/usr/bin/env python3
"""Run the pre-registered BB/H/ER extension of the few-starts pitcher fallback (#1482).

Protocol: docs/MLB_PITCHER_PRIOR_FALLBACK_EXT_PREREG.md. Fetches StatsAPI pitching
game logs for 2022-2025 starters, scores the frozen league_short m=4 fallback on 2025
(decision) and 2024 (sign consistency), and writes a markdown report.
Research only: changes no picks.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge import mlb_pitcher_prior_ext_research as X  # noqa: E402
from sportsedge import mlb_pitcher_prior_research as R  # noqa: E402

SEASONS = (2022, 2023, 2024, 2025)
CONSISTENCY, TEST = 2024, 2025


def _base_runner():
    spec = importlib.util.spec_from_file_location("_prior_fallback_runner", ROOT / "scripts" / "research_mlb_pitcher_prior_fallback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_starts(cache: Path, workers: int, seasons=SEASONS) -> list[X.XStart]:
    base = _base_runner()
    cache.mkdir(parents=True, exist_ok=True)
    jobs = [(pid, season) for season in seasons for pid in base.season_starters(season)]

    def one(job):
        pid, season = job
        f = cache / f"{pid}_{season}.json"
        if f.exists():
            payload = json.loads(f.read_text())
        else:
            q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
            payload = base._get(f"{base.API}/people/{pid}/stats?{q}")
            f.write_text(json.dumps(payload))
        return X.starts_from_gamelog(payload, pitcher_id=pid, season=season)

    starts: list[X.XStart] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rows in ex.map(one, jobs):
            starts.extend(rows)
    return starts


def f4(x: float) -> str:
    return f"{x:.4f}"


def run(starts: list[X.XStart]) -> tuple[dict, str]:
    window = R.prior_window_counts(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in SEASONS}
    pools = {y: X.league_short_pool(by_season[y - 1], window) for y in (CONSISTENCY, TEST)}
    test_rows = X.evaluate(by_season[TEST], window, pools[TEST], ks=range(1, 5))
    cons_rows = X.evaluate(by_season[CONSISTENCY], window, pools[CONSISTENCY], ks=range(1, 5))
    k0_rows = X.evaluate(by_season[TEST], window, pools[TEST], ks=[0])
    ref_rows = X.reference_rows(by_season[TEST], window)
    decision = X.ship_decision(test_rows, cons_rows, ref_rows)

    by_k = {}
    for k in range(1, 5):
        sub = [r for r in test_rows if r["k"] == k]
        if sub:
            by_k[k] = {"n": len(sub), **{st: {"own": X.mean_rps(sub, "own", st), "fallback": X.mean_rps(sub, "fallback", st)} for st in X.STATS}}

    result = {
        "prereg_sha256": X.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "units": {"test_2025": len(test_rows), "consistency_2024": len(cons_rows), "k0_2025": len(k0_rows), "reference_k_ge_5_2025": len(ref_rows)},
        "rps_2025": {st: {"own": X.mean_rps(test_rows, "own", st), "fallback": X.mean_rps(test_rows, "fallback", st),
                          "reference_k_ge_5_own": X.mean_rps(ref_rows, "own", st), "k0_fallback_info": X.mean_rps(k0_rows, "fallback", st)} for st in X.STATS},
        "by_k_2025": by_k,
        "decision": decision,
    }

    L = ["## MLB few-starts fallback → BB / Hits allowed / ER: held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_PITCHER_PRIOR_FALLBACK_EXT_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. "
             "Frozen candidate `league_short m=4` (the #1495 selection, no tuning). Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items())
             + f". Units: 2025 k=1..4 {len(test_rows)}, 2024 k=1..4 {len(cons_rows)}.")
    L.append("")
    L.append("| check | " + " | ".join(X.MARKET[s] for s in X.STATS) + " |")
    L.append("|---|" + "---|" * len(X.STATS))
    rows_md = [
        ("2025 RPS own-only → fallback", lambda st, m: f"{f4(result['rps_2025'][st]['own'])} → {f4(result['rps_2025'][st]['fallback'])}"),
        ("2025 diff [95% CI]", lambda st, m: f"{f4(m['test_vs_own']['diff'])} [{f4(m['test_vs_own']['lo'])}, {f4(m['test_vs_own']['hi'])}]"),
        ("2024 diff (sign check)", lambda st, m: f4(m["consistency_vs_own"]["diff"])),
        ("2025 typical-line log loss own → fallback", lambda st, m: f"{f4(m['own_typical']['logloss'])} → {f4(m['fallback_typical']['logloss'])}"),
        ("2025 typical-line ECE (cap)", lambda st, m: f"{f4(m['fallback_typical']['ece'])} ({f4(m['ece_cap'])})"),
        ("reference k≥5 RPS / ECE", lambda st, m: f"{f4(result['rps_2025'][st]['reference_k_ge_5_own'])} / {f4(m['reference_typical']['ece'])}"),
        ("rule 1 (CI < 0)", lambda st, m: "PASS" if m["rule1_beats_own_2025"] else "FAIL"),
        ("rule 2 (calibrated)", lambda st, m: "PASS" if m["rule2_calibrated_2025"] else "FAIL"),
        ("rule 3 (2024 sign)", lambda st, m: "PASS" if m["rule3_sign_2024"] else "FAIL"),
        ("**decision**", lambda st, m: "**SHIPS**" if m["ships"] else "**STAYS BLOCKED**"),
    ]
    for label, fn in rows_md:
        L.append(f"| {label} | " + " | ".join(fn(st, decision["markets"][X.MARKET[st]]) for st in X.STATS) + " |")
    L.append("")
    L.append("By k (2025 RPS own → fallback, BB/H/ER): " + "; ".join(
        f"k={k} n={v['n']}: " + "/".join(f"{v[st]['own']:.2f}→{v[st]['fallback']:.2f}" for st in X.STATS) for k, v in by_k.items()))
    L.append(f"k=0 (info only, stays BLOCKED): {len(k0_rows)} starts, fallback RPS " + "/".join(f"{result['rps_2025'][st]['k0_fallback_info']:.3f}" for st in X.STATS) + ".")
    L.append("")
    shipped = [m for m, v in decision["markets"].items() if v["ships"]]
    L.append(f"**Decision (pre-registered rules): {', '.join(shipped) + ' may replace BLOCKED for k=1..4 (half lines, LEAN max)' if shipped else 'nothing ships; k<5 BB/H/ER stay BLOCKED'}.**")
    return result, "\n".join(L) + "\n"


EXT_FIELDS = {"outs": "outs", "strikeouts": "k", "walks": "bb", "hits": "h", "earned_runs": "er"}


def build_ext_pool_artifact(starts: list[X.XStart], season: int) -> dict:
    """Frozen league_short pool for ``season`` with outs/K/BB/H/ER counts (used for season+1 games).

    Same definition as the base ``build_pool_artifact`` (#1497): starts in ``season`` made
    when the pitcher had <5 strictly-earlier starts in seasons season-1..season.
    """
    window = R.prior_window_counts(starts)
    short = [s for s in starts if s.season == season and len(window.get(s, ())) < R.MIN_PRODUCTION_STARTS]
    if len(short) < 100:
        raise RuntimeError(f"league_short pool for {season} too small: {len(short)}")
    counts: dict[str, dict[str, int]] = {}
    for name, attr in EXT_FIELDS.items():
        table: dict[str, int] = {}
        for s in short:
            v = str(getattr(s, attr))
            table[v] = table.get(v, 0) + 1
        counts[name] = {k: table[k] for k in sorted(table, key=int)}
    return {
        "schema": "MLB_PITCHER_PRIOR_POOL_EXT_V1", "pool": "league_short", "season": int(season),
        "definition": "regular-season starts in `season` made when the pitcher had <5 prior starts in seasons season-1..season (production window)",
        "starts": len(short), "counts": counts,
        "source": "MLB StatsAPI people/{id}/stats gameLog group=pitching gameType=R",
        "built_by": "scripts/research_mlb_pitcher_prior_fallback_ext.py --emit-pool",
        "validation": "#1943 (pre-registration sha256 " + X.prereg_sha256() + ")",
    }


def base_cross_check(artifact: dict, config_dir: Path = ROOT / "config") -> str:
    """Compare outs/K counts with the committed base artifact (must be the same pool)."""
    base_path = config_dir / f"mlb_pitcher_prior_league_short_{artifact['season']}.json"
    if not base_path.exists():
        return f"NO BASE ARTIFACT ({base_path.name} missing) — do not commit"
    base = json.loads(base_path.read_text())
    same = all(base["counts"][k] == artifact["counts"][k] for k in ("outs", "strikeouts")) and base.get("starts") == artifact["starts"]
    return (f"MATCHES {base_path.name} ({artifact['starts']} starts, identical outs/K counts)" if same
            else f"MISMATCH vs {base_path.name} (base {base.get('starts')} starts, ext {artifact['starts']}) — do not commit")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-prior-ext-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_prior_ext_research"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--emit-pool", type=int, help="build the frozen league_short BB/H/ER prior artifact for this season")
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.emit_pool:
        season = args.emit_pool
        artifact = build_ext_pool_artifact(fetch_starts(args.cache, args.workers, seasons=(season - 1, season)), season)
        text = json.dumps(artifact, indent=2) + "\n"
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / f"mlb_pitcher_prior_league_short_ext_{season}.json").write_text(text)
        md = (f"## MLB few-starts prior pool artifact, BB/H/ER extension ({season})\n\n"
              f"Base cross-check: **{base_cross_check(artifact)}**.\n\n"
              f"Commit as `config/mlb_pitcher_prior_league_short_ext_{season}.json` (used for {season + 1} games). "
              "Research output only; nothing is priced until committed.\n\n```json\n" + text + "```\n")
        (args.out_dir / "report.md").write_text(md)
        print(md)
        return 0
    result, md = run(fetch_starts(args.cache, args.workers))
    md += f"\n_runtime {time.time() - t0:.0f}s_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
