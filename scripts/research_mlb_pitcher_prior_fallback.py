#!/usr/bin/env python3
"""Run the pre-registered few-starts pitcher fallback validation (#1482 item B).

Fetches StatsAPI pitching game logs for 2022-2025 starters, tunes on 2024, evaluates
once on 2025, and writes a markdown report. Research only: changes no picks.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge import mlb_pitcher_prior_research as R  # noqa: E402

API = "https://statsapi.mlb.com/api/v1"
SEASONS = (2022, 2023, 2024, 2025)
TUNE, TEST = 2024, 2025


def _get(url: str, *, tries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"})
            with urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network flake: retry with backoff
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def season_starters(season: int) -> list[int]:
    q = urlencode({"stats": "season", "group": "pitching", "season": season, "sportId": 1,
                   "gameType": "R", "playerPool": "ALL", "limit": 5000})
    payload = _get(f"{API}/stats?{q}")
    ids = set()
    for block in payload.get("stats") or []:
        for split in block.get("splits") or []:
            try:
                if float((split.get("stat") or {}).get("gamesStarted", 0) or 0) > 0:
                    ids.add(int(split["player"]["id"]))
            except (KeyError, TypeError, ValueError):
                continue
    if len(ids) < 250:
        raise RuntimeError(f"starter list for {season} looks incomplete: {len(ids)}")
    return sorted(ids)


def fetch_starts(cache: Path, workers: int) -> list[R.Start]:
    cache.mkdir(parents=True, exist_ok=True)
    jobs = []
    for season in SEASONS:
        for pid in season_starters(season):
            jobs.append((pid, season))

    def one(job):
        pid, season = job
        f = cache / f"{pid}_{season}.json"
        if f.exists():
            payload = json.loads(f.read_text())
        else:
            q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
            payload = _get(f"{API}/people/{pid}/stats?{q}")
            f.write_text(json.dumps(payload))
        return R.starts_from_gamelog(payload, pitcher_id=pid, season=season)

    starts: list[R.Start] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rows in ex.map(one, jobs):
            starts.extend(rows)
    return starts


def disp(name: str) -> str:
    return name.replace("|", " m=")


def fmt(x: float, d: int = 4) -> str:
    return f"{x:.{d}f}"


def run(starts: list[R.Start]) -> tuple[dict, str]:
    window = R.prior_window_counts(starts)
    by_season = {s: [x for x in starts if x.season == s] for s in SEASONS}
    pools = {y: R.build_pools(by_season[y - 1], window) for y in (TUNE, TEST)}

    tune_rows = R.evaluate(by_season[TUNE], window, pools[TUNE], ks=range(1, 5))["rows"]
    tune_table = R.score_table(tune_rows)
    selected = R.select(tune_table)

    test_rows = R.evaluate(by_season[TEST], window, pools[TEST], ks=range(1, 5))["rows"]
    test_table = R.score_table(test_rows)
    k0_rows = R.evaluate(by_season[TEST], window, pools[TEST], ks=[0])["rows"]
    k0_table = R.score_table(k0_rows)
    ref_rows = R.reference_rows(by_season[TEST], window)
    ref_table = R.score_table(ref_rows)
    decision = R.ship_decision(test_rows, selected, ref_rows)
    prior_only = selected.split("|")[0] + "|inf"
    vs_prior = {stat: R.cluster_bootstrap_diff(test_rows, selected, prior_only, stat) for stat in ("outs", "k")} if prior_only != selected else None

    by_k = {}
    for k in range(1, 5):
        sub = [r for r in test_rows if r["k"] == k]
        if sub:
            t = R.score_table(sub)
            by_k[k] = {"n": len(sub), "own": t["own"], "selected": t[selected]}

    result = {
        "prereg_sha256": R.prereg_sha256(),
        "starts_loaded": {s: len(v) for s, v in by_season.items()},
        "tune": {"season": TUNE, "units": len(tune_rows), "table": tune_table, "selected": selected},
        "test": {"season": TEST, "units": len(test_rows), "table": {k: test_table[k] for k in ("own", selected, prior_only) if k in test_table},
                 "by_k": by_k, "vs_prior_only": vs_prior},
        "k0_info": {"units": len(k0_rows), "selected": k0_table.get(selected), "prior_only": k0_table.get(prior_only)},
        "reference_k_ge_5": {"units": len(ref_rows), "own": ref_table.get("own")},
        "decision": decision,
    }

    L = ["## MLB few-starts pitcher fallback: held-out validation", ""]
    L.append(f"Pre-registration `docs/MLB_PITCHER_PRIOR_FALLBACK_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. Research only: **no picks changed by this run.**")
    L.append("")
    L.append("Starts loaded: " + ", ".join(f"{s}: {n}" for s, n in result["starts_loaded"].items()))
    L.append("")
    L.append(f"### Tuning ({TUNE}, k=1..4, {len(tune_rows)} starts). RPS, lower is better")
    L.append("| candidate | outs | K |")
    L.append("|---|---|---|")
    ranked = sorted(tune_table.items(), key=lambda kv: 0.5 * (kv[1]["rps_outs"] / tune_table["own"]["rps_outs"] + kv[1]["rps_k"] / tune_table["own"]["rps_k"]))
    for name, t in ranked[:8] + ([("own", tune_table["own"])] if all(n != "own" for n, _ in ranked[:8]) else []):
        L.append(f"| {disp(name)}{' ← selected' if name == selected else ''} | {fmt(t['rps_outs'])} | {fmt(t['rps_k'])} |")
    L.append("")
    L.append(f"### Held-out ({TEST}, k=1..4, {len(test_rows)} starts), frozen selection `{disp(selected)}`")
    L.append("| model | outs RPS | K RPS |")
    L.append("|---|---|---|")
    for name, t in result["test"]["table"].items():
        L.append(f"| {disp(name)} | {fmt(t['rps_outs'])} | {fmt(t['rps_k'])} |")
    L.append("")
    L.append("| check | outs | K |")
    L.append("|---|---|---|")
    c = decision["checks"]
    L.append("| RPS diff vs own-only [95% CI] | " + " | ".join(f"{fmt(c[s]['bootstrap_vs_own']['diff'])} [{fmt(c[s]['bootstrap_vs_own']['lo'])}, {fmt(c[s]['bootstrap_vs_own']['hi'])}]" for s in ("outs", "k")) + " |")
    if vs_prior:
        L.append("| RPS diff vs prior-only [95% CI] | " + " | ".join(f"{fmt(vs_prior[s]['diff'])} [{fmt(vs_prior[s]['lo'])}, {fmt(vs_prior[s]['hi'])}]" for s in ("outs", "k")) + " |")
    L.append("| typical-line log loss | " + " | ".join(fmt(c[s]["fallback_typical"]["logloss"]) for s in ("outs", "k")) + " |")
    L.append("| typical-line ECE (cap) | " + " | ".join(f"{fmt(c[s]['fallback_typical']['ece'])} ({fmt(c[s]['ece_cap'])})" for s in ("outs", "k")) + " |")
    L.append("| reference k≥5 own-only ECE | " + " | ".join(fmt(c[s]["reference_typical"]["ece"]) for s in ("outs", "k")) + " |")
    L.append("| rule 1 (beats own-only) | " + " | ".join("PASS" if c[s]["rule1_beats_own"] else "FAIL" for s in ("outs", "k")) + " |")
    L.append("| rule 2 (calibrated) | " + " | ".join("PASS" if c[s]["rule2_calibrated"] else "FAIL" for s in ("outs", "k")) + " |")
    L.append("")
    L.append("By k (held-out RPS outs / K): " + "; ".join(f"k={k} n={v['n']}: own {fmt(v['own']['rps_outs'],2)}/{fmt(v['own']['rps_k'],2)} → sel {fmt(v['selected']['rps_outs'],2)}/{fmt(v['selected']['rps_k'],2)}" for k, v in by_k.items()))
    if result["reference_k_ge_5"]["own"]:
        ref = result["reference_k_ge_5"]["own"]
        L.append("")
        L.append(f"Reference, production own-only on k≥5 ({result['reference_k_ge_5']['units']} starts): outs {fmt(ref['rps_outs'])}, K {fmt(ref['rps_k'])}.")
    k0 = result["k0_info"]
    if k0["selected"]:
        L.append(f"k=0 (info only, stays BLOCKED): {k0['units']} starts, selected outs {fmt(k0['selected']['rps_outs'])} / K {fmt(k0['selected']['rps_k'])}.")
    L.append("")
    L.append(f"**Decision (pre-registered rules): {'SHIPS — fallback may replace BLOCKED for k=1..4 (lean-tier only)' if decision['ships'] else 'DOES NOT SHIP — k<5 starters stay BLOCKED'}.**")
    return result, "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-prior-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_prior_research"))
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args(argv)
    t0 = time.time()
    starts = fetch_starts(args.cache, args.workers)
    result, md = run(starts)
    md += f"\n_runtime {time.time() - t0:.0f}s_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
