#!/usr/bin/env python3
"""Does preseason 247 talent beat the CFB closing spread? 2016-2025, no CFBD calls.

Data comes from pinned public GitHub mirrors (see sportsedge/sports/cfb/public_mirror.py).
Leave-one-season-out OLS on target = home margin + closing home spread with
features [1, talent diff, talent diff / week, neutral]. Pre-registered pass
rule (#1476): |pred| >= 0.5, pooled ATS >= 53.0% and >= 7 of 10 held-out
seasons >= 52.4%. Otherwise talent is not a validated CFB bet signal.

Phone hook: a "[CFB LINES]" issue with board {"backtest": "talent_mirror"}.
Add "save_cache": true to also store lines_<season> / talent_<season> items in
the #1475 issue cache so later CFBD runs only need the tables still missing.
Evaluation only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEASONS = list(range(2016, 2026))


def report(games, talent, out=print) -> bool:
    from sportsedge.sports.cfb import public_mirror as pm
    specs = [
        ("PRIMARY talent + talent/week + neutral, vs CLOSE", dict(), pm.PRIMARY_COLS),
        ("talent only, vs CLOSE", dict(), [0, 1, 3]),
        ("weeks 1-4 only, vs CLOSE (exploratory)", dict(max_week=4), pm.PRIMARY_COLS),
        ("vs OPEN (exploratory)", dict(line="spread_open"), pm.PRIMARY_COLS),
    ]
    for name, kw, cols in specs:
        X, y, seasons = pm.design(games, talent, **kw)
        out(f"CFB_SDV_TALENT_MIRROR == {name} n={len(y)}")
        for t in (0.5, 1.0, 1.5, 2.0):
            pooled, per = pm.loso_ats(X, y, seasons, cols, t)
            good = sum(1 for wl in per.values() if pm.pct(*wl) >= pm.PASS_SEASON)
            out(f"CFB_SDV_TALENT_MIRROR   |pred|>={t}: {pooled[0]}-{pooled[1]} {pm.pct(*pooled):.1f}% "
                f"seasons>=52.4%: {good}/{len(per)} | " +
                " ".join(f"{s % 100}:{pm.pct(*wl):.0f}({sum(wl)})" for s, wl in sorted(per.items())))
    X, y, seasons = pm.design(games, talent)
    pooled, per = pm.loso_ats(X, y, seasons, pm.PRIMARY_COLS, pm.PRIMARY_THRESHOLD)
    ok = pm.verdict(pooled, per)
    out(f"CFB_SDV_TALENT_MIRROR VERDICT {'PASS' if ok else 'FAIL'} pooled {pm.pct(*pooled):.1f}% "
        f"({pooled[0]}-{pooled[1]}) at |pred|>={pm.PRIMARY_THRESHOLD}")
    return ok


def main(argv=None, board=None) -> int:
    from sportsedge.sports.cfb import public_mirror as pm
    games, talent = pm.load_all(SEASONS)
    for s in SEASONS:
        n = sum(1 for g in games if g["season"] == s)
        print(f"CFB_SDV_TALENT_MIRROR season {s}: {n} games with spreads, {len(talent.get(s, {}))} talent teams")
    report(games, talent)
    if isinstance(board, dict) and board.get("save_cache"):
        from sportsedge.sports.cfb import cfbd_issue_cache as cc
        have = cc.load_cache()
        for s in SEASONS:
            if f"lines_{s}" not in have:
                cc.save_item(f"lines_{s}", pm.to_cache_lines(games, s))
        for s in SEASONS:
            # Key talent by the schedule's CFBD team names so it joins with lines_<season>.
            names = {n for g in games if g["season"] == s for n in (g["home"], g["away"])}
            tbl = {n: talent.get(s, {})[pm.canon(n)] for n in names if pm.canon(n) in talent.get(s, {})}
            if f"talent_{s}" not in have and tbl:
                cc.save_item(f"talent_{s}", tbl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
