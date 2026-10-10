#!/usr/bin/env python3
"""Run the pre-registered postseason PITCHER_BB / H / ER / H+W+ER bias check (#1482).

Fetches StatsAPI postseason schedules + boxscores (2022-2025) and regular-season pitching
game logs for each starter (Y-1, Y), scores the production prices at the typical lines
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research_mlb_pitcher_prior_fallback import API, _get  # noqa: E402
from sportsedge import mlb_postseason_prop_bias_ext_research as R  # noqa: E402
from sportsedge.mlb_pitcher_prior_ext_research import starts_from_gamelog  # noqa: E402
from sportsedge.mlb_postseason_prop_bias_research import final_postseason_games  # noqa: E402

MIN_GAMES_PER_SEASON = 25


def fetch(cache: Path, workers: int):
    cache.mkdir(parents=True, exist_ok=True)

    def cached(name: str, url: str) -> dict:
        f = cache / name
        if f.exists():
            return json.loads(f.read_text())
        payload = _get(url)
        f.write_text(json.dumps(payload))
        return payload

    games = []
    for season in R.SEASONS:
        q = urlencode({"sportId": 1, "season": season, "gameTypes": ",".join(R.POSTSEASON_TYPES),
                       "startDate": f"{season}-09-25", "endDate": f"{season}-11-15"})
        rows = final_postseason_games(cached(f"sched{season}.json", f"{API}/schedule?{q}"))
        if len(rows) < MIN_GAMES_PER_SEASON:
            raise RuntimeError(f"postseason schedule {season} looks incomplete: {len(rows)} final games")
        games.extend((season, *r) for r in rows)

    def bone(job):
        season, pk, day, gt = job
        return R.starters_from_boxscore(cached(f"b{pk}.json", f"{API}/game/{pk}/boxscore"),
                                        game_pk=pk, date=day, season=season, game_type=gt)

    def pone(job):
        pid, season = job
        q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
        payload = cached(f"p{pid}_{season}.json", f"{API}/people/{pid}/stats?{q}")
        return starts_from_gamelog(payload, pitcher_id=pid, season=season)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        starts = [s for rows in ex.map(bone, games) for s in rows]
        pjobs = sorted({(s.pitcher_id, y) for s in starts for y in (s.season - 1, s.season)})
        regular = [r for rows in ex.map(pone, pjobs) for r in rows]
    if len(starts) < 1.8 * len(games):
        raise RuntimeError(f"boxscores look incomplete: {len(starts)} starters for {len(games)} games")
    return games, starts, regular


def f4(x: float) -> str:
    return f"{x:+.4f}" if x == x else "n/a"


def run(games, starts, regular) -> tuple[dict, str]:
    rows, drops = R.build_rows(starts, regular)
    result = {"prereg_sha256": R.prereg_sha256(), "games": len(games), "starters": len(starts),
              "units": len(rows), "drops": drops,
              "units_by_season": {s: sum(r["season"] == s for r in rows) for s in R.SEASONS},
              "units_with_prior_pool": sum(bool(r["has_prior_pool"]) for r in rows),
              "markets": {m: {"decision": R.decision(rows, m), "info": R.info_metrics(rows, m),
                              "info_by_season": {s: R.info_metrics([r for r in rows if r["season"] == s], m) for s in R.SEASONS}}
                          for m in R.MARKETS}}
    L = ["## MLB postseason pitcher BB / H / ER / H+W+ER: bias check of the production price", ""]
    L.append(f"Pre-registration `docs/MLB_POSTSEASON_PITCHER_PROP_BIAS_EXT_PREREG.md` sha256 `{result['prereg_sha256'][:16]}…`. "
             "Research only: **no picks changed by this run.**")
    L.append("")
    L.append(f"Final postseason games: {len(games)}; starters parsed: {len(starts)}; scored units (k≥5): {len(rows)} "
             f"({', '.join(f'{s}: {n}' for s, n in result['units_by_season'].items())}); dropped: {drops}; "
             f"units with a long-window prior pool (H/ER/H+W+ER): {result['units_with_prior_pool']}.")
    L.append("Prices are `pitcher_joint_engine.price_pitcher_market` on the production k≥5 features. "
             "PITCHER_BB is scored with the UMP-BB lane off (not reproduced; see prereg).")
    L.append("")
    L.append("Over-bias = mean(p_over − hit) over the typical lines; positive = the card's overs are too likely.")
    L.append("")
    L.append("| market | pooled bias [95% game-cluster CI] | 2022 | 2023 | 2024 | 2025 | rule 1 CI≠0 | rule 2 \\|bias\\|≥0.03 | rule 3 2022 same sign | decision |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for m in R.MARKETS:
        d = result["markets"][m]["decision"]
        p = d["pooled"]
        ps = d["per_season"]
        L.append(f"| {m} | {f4(p['bias'])} [{f4(p['lo'])}, {f4(p['hi'])}] | " + " | ".join(f4(ps[s]) for s in R.SEASONS) +
                 f" | {'PASS' if d['rule1_ci_excludes_0'] else 'FAIL'} | {'PASS' if d['rule2_material'] else 'FAIL'} | "
                 f"{'PASS' if d['rule3_2022_same_sign'] else 'FAIL'} | **{'GUARD' if d['guard'] else 'NO GUARD'}** |")
    L.append("")
    L.append("Info (pooled, typical lines):")
    for m in R.MARKETS:
        i = result["markets"][m]["info"]
        if i:
            L.append(f"- {m}: Brier {i['brier']:.4f}, log loss {i['logloss']:.4f}, ECE {i['ece']:.4f}, "
                     f"share p_over≥0.5 {i['p_over_ge_half']:.2f}; own last-10 mean {i['mean_own_last10']:.2f} vs realised {i['mean_real']:.2f}.")
    L.append("")
    guarded = [m for m in R.MARKETS if result["markets"][m]["decision"]["guard"]]
    if guarded:
        L.append(f"**Decision (pre-registered rules): GUARD {', '.join(guarded)}** — a separate PR adds these to the "
                 "postseason block list on phone cards. model_p and regular-season pricing are unchanged.")
    else:
        L.append("**Decision (pre-registered rules): NO GUARD** — these markets stay as they are on postseason cards (LEAN max).")
    return result, "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-postseason-bias-ext-research"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_postseason_bias_ext_research"))
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args(argv)
    t0 = time.time()
    data = fetch(args.cache, args.workers)
    result, md = run(*data)
    md += f"\n_runtime {time.time() - t0:.0f}s_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
