#!/usr/bin/env python3
"""Run the pre-registered 2026 stability check of the live MLB context lanes (#1482).

Scores the frozen production OPP-K, OPP-OUTS and UMP-BB configs against their
baselines on the 2026 regular season (never used for selection or testing), plus an
information-only re-tune on 2025. One shared fetch feeds all three lanes.
Research only: changes no picks. See docs/MLB_CONTEXT_LANE_STABILITY_2026_PREREG.md.
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
from sportsedge import mlb_context_lane_stability_research as S  # noqa: E402
from sportsedge import mlb_opp_k_context_research as RK  # noqa: E402
from sportsedge import mlb_opp_outs_context_research as RO  # noqa: E402
from sportsedge import mlb_umpire_context_research as RU  # noqa: E402

MONTHS = ((3, 1, 3, 31), (4, 1, 4, 30), (5, 1, 5, 31), (6, 1, 6, 30), (7, 1, 7, 31), (8, 1, 8, 31), (9, 1, 9, 30), (10, 1, 10, 31))
MIN_USABLE_SHARE = 0.9


def fetch(cache: Path, workers: int) -> dict:
    """Raw payloads keyed by job; every lane parses the same bytes."""
    cache.mkdir(parents=True, exist_ok=True)

    def cached(name: str, url: str) -> dict:
        f = cache / name
        if f.exists():
            return json.loads(f.read_text())
        payload = _get(url)
        f.write_text(json.dumps(payload))
        return payload

    pjobs = [(pid, season) for season in S.PITCHER_SEASONS for pid in season_starters(season)]
    tjobs = [(tid, season) for season in S.TEAM_SEASONS for tid in team_ids(season)]
    sjobs = [(season, m) for season in S.TEAM_SEASONS for m in MONTHS]

    def pone(job):
        pid, season = job
        q = urlencode({"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
        return job, cached(f"p{pid}_{season}.json", f"{API}/people/{pid}/stats?{q}")

    def tone(job):
        tid, season = job
        q = urlencode({"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"})
        return job, cached(f"t{tid}_{season}.json", f"{API}/teams/{tid}/stats?{q}")

    def sone(job):
        season, (m1, d1, m2, d2) = job
        q = urlencode({"sportId": 1, "gameType": "R", "hydrate": "officials",
                       "startDate": f"{season}-{m1:02d}-{d1:02d}", "endDate": f"{season}-{m2:02d}-{d2:02d}"})
        return job, cached(f"s{season}_{m1:02d}.json", f"{API}/schedule?{q}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return {"pitchers": dict(ex.map(pone, pjobs)), "teams": dict(ex.map(tone, tjobs)), "schedules": dict(ex.map(sone, sjobs))}


def f4(x: float) -> str:
    return f"{x:.4f}"


def _by_season(starts):
    return {s: [x for x in starts if x.season == s] for s in S.PITCHER_SEASONS}


def lane_opp_k(raw: dict) -> dict:
    teams = {}
    for job, payload in raw["teams"].items():
        rows = RK.team_games_from_gamelog(payload)
        if len(rows) < 100:
            raise RuntimeError(f"team gameLog {job} looks incomplete: {len(rows)} games")
        teams[job] = rows
    starts = [s for (pid, season), p in raw["pitchers"].items() for s in RK.kstarts_from_gamelog(p, pitcher_id=pid, season=season)]
    index, window, by = RK.OppIndex(teams), RK.production_window(starts), _by_season(starts)
    retune_rows = RK.evaluate(by[S.RETUNE], window, index)
    held_rows = RK.evaluate(by[S.HELDOUT], window, index)
    frozen, base = S.FROZEN["OPP-K"], S.BASELINES["OPP-K"]
    retuned = RK.select_beta(RK.rps_table(retune_rows))
    return _summarise("OPP-K", held_rows, retune_rows, frozen, base, retuned,
                      boot=lambda rows, a, b: RK.cluster_bootstrap(rows, a, b),
                      typical=lambda rows, c: RK.typical_metrics(rows, c),
                      table=RK.rps_table, label=lambda c: f"beta {c:g}", y="y_k", starts=by)


def lane_opp_outs(raw: dict) -> dict:
    teams = {}
    for job, payload in raw["teams"].items():
        rows = RO.team_rows_from_gamelog(payload)
        if min(len(v) for v in rows.values()) < 100:
            raise RuntimeError(f"team gameLog {job} looks incomplete")
        teams[job] = rows
    starts = [s for (pid, season), p in raw["pitchers"].items() for s in RO.ostarts_from_gamelog(p, pitcher_id=pid, season=season)]
    indices, window, by = RO.build_indices(teams), RK.production_window(starts), _by_season(starts)
    retune_rows = RO.evaluate(by[S.RETUNE], window, indices)
    held_rows = RO.evaluate(by[S.HELDOUT], window, indices)
    frozen, base = S.FROZEN["OPP-OUTS"], S.BASELINES["OPP-OUTS"]
    retuned = RO.select(RO.rps_table(retune_rows))
    return _summarise("OPP-OUTS", held_rows, retune_rows, frozen, base, retuned,
                      boot=lambda rows, a, b: RO.cluster_bootstrap(rows, a, b),
                      typical=lambda rows, c: RO.typical_metrics(rows, c),
                      table=RO.rps_table, label=RO.label, y="y_outs", starts=by)


def lane_ump_bb(raw: dict) -> dict:
    umps: dict[int, int] = {}
    for payload in raw["schedules"].values():
        umps.update(RU.home_plate_by_game(payload))
    teams = {}
    for job, payload in raw["teams"].items():
        rows = RU.team_game_rows(payload)
        if len(rows) < 100:
            raise RuntimeError(f"team gameLog {job} looks incomplete (rows with gamePk: {len(rows)})")
        teams[job] = rows
    games = RU.game_totals([row for rows in teams.values() for row in rows])
    uidx = RU.UmpIndex(games, umps)
    share = uidx.usable_games / max(1, len(games))
    if share < MIN_USABLE_SHARE:
        raise RuntimeError(f"only {share:.1%} of games have a home-plate umpire; schedule officials look incomplete")
    starts = [s for (pid, season), p in raw["pitchers"].items() for s in RU.ustarts_from_gamelog(p, pitcher_id=pid, season=season)]
    window, by = RK.production_window(starts), _by_season(starts)
    retune_rows, retune_drop = RU.evaluate("bb", by[S.RETUNE], window, umps, uidx, None)
    held_rows, held_drop = RU.evaluate("bb", by[S.HELDOUT], window, umps, uidx, None)
    frozen, base = S.FROZEN["UMP-BB"], S.BASELINES["UMP-BB"]
    retuned = RU.select(RU.rps_table(retune_rows, "bb"))
    out = _summarise("UMP-BB", held_rows, retune_rows, frozen, base, retuned,
                     boot=lambda rows, a, b: RU.cluster_bootstrap(rows, a, b, "bb"),
                     typical=lambda rows, c: RU.typical_metrics(rows, c, "bb"),
                     table=lambda rows: RU.rps_table(rows, "bb"), label=RU.label, y="y", starts=by)
    out["umpire_coverage"] = {"games": len(games), "with_hp_umpire": uidx.usable_games, "share": share,
                              "dropped_no_ump": {"retune": retune_drop, "heldout": held_drop}}
    return out


def _summarise(lane, held_rows, retune_rows, frozen, base, retuned, *, boot, typical, table, label, y, starts) -> dict:
    if not held_rows or not retune_rows:
        raise RuntimeError(f"{lane}: no units")
    held = table(held_rows)
    decision = S.stability_decision(boot(held_rows, frozen, base), typical(held_rows, base), typical(held_rows, frozen))
    return {
        "lane": lane, "market": S.MARKETS[lane], "frozen": label(frozen), "baseline": label(base),
        "units": {"retune_2025": len(retune_rows), "heldout_2026": len(held_rows)},
        "starters_loaded": {s: len(v) for s, v in starts.items()},
        "mean_y": {"2025": float(np.mean([r[y] for r in retune_rows])), "2026": float(np.mean([r[y] for r in held_rows]))},
        "heldout_rps": {"baseline": held[base], "frozen": held[frozen]},
        "info_retune": {"selected_on_2025": label(retuned), "same_as_frozen": retuned == frozen,
                        "heldout_rps_of_retuned": held[retuned]},
        "decision": decision,
    }


def report(lanes: list[dict]) -> str:
    L = ["## MLB context lanes: 2026 stability check (frozen production configs, held-out 2026)", ""]
    L.append(f"Pre-registration `docs/MLB_CONTEXT_LANE_STABILITY_2026_PREREG.md` sha256 `{S.prereg_sha256()[:16]}…`. "
             "Research only: **no picks changed by this run.**")
    L.append("")
    L.append("| lane | frozen config | units 2026 | RPS base → frozen | diff [95% CI] | typical ECE base → frozen | verdict |")
    L.append("|---|---|---|---|---|---|---|")
    for x in lanes:
        d = x["decision"]
        b = d["bootstrap_frozen_minus_base"]
        L.append(f"| {x['lane']} ({x['market']}) | {x['frozen']} | {x['units']['heldout_2026']} | "
                 f"{f4(x['heldout_rps']['baseline'])} → {f4(x['heldout_rps']['frozen'])} | "
                 f"{f4(b['diff'])} [{f4(b['lo'])}, {f4(b['hi'])}] | "
                 f"{f4(d['typical_base']['ece'])} → {f4(d['typical_frozen']['ece'])} | **{d['verdict']}** |")
    L.append("")
    L.append("Information only (cannot change a config): the original selection re-run with tune 2025.")
    L.append("")
    L.append("| lane | selected on 2025 | same as frozen | its 2026 RPS | mean outcome 2025 → 2026 |")
    L.append("|---|---|---|---|---|")
    for x in lanes:
        i = x["info_retune"]
        L.append(f"| {x['lane']} | {i['selected_on_2025']} | {'yes' if i['same_as_frozen'] else 'no'} | "
                 f"{f4(i['heldout_rps_of_retuned'])} | {x['mean_y']['2025']:.3f} → {x['mean_y']['2026']:.3f} |")
    for x in lanes:
        if "umpire_coverage" in x:
            u = x["umpire_coverage"]
            L.append("")
            L.append(f"UMP-BB umpire coverage: {u['with_hp_umpire']}/{u['games']} games ({u['share']:.1%}); "
                     f"units dropped for no umpire: 2025 {u['dropped_no_ump']['retune']}, 2026 {u['dropped_no_ump']['heldout']}.")
    L.append("")
    for x in lanes:
        L.append(f"- **{x['lane']}: {S.verdict_text(x['decision']['verdict'])}.**")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path(".cache/mlb-lane-stability-2026"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_lane_stability_2026"))
    ap.add_argument("--workers", type=int, default=24)
    args = ap.parse_args(argv)
    t0 = time.time()
    raw = fetch(args.cache, args.workers)
    lanes = [lane_opp_k(raw), lane_opp_outs(raw), lane_ump_bb(raw)]
    md = report(lanes) + f"\n_runtime {time.time() - t0:.0f}s_\n"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = {"prereg_sha256": S.prereg_sha256(), "lanes": lanes}
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (args.out_dir / "report.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
