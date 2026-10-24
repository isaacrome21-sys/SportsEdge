#!/usr/bin/env python3
"""Chronological backtest of the CFB matchup model and its market-blend weight.

Model (same as artifacts/free_models.py CFB_MATCHUP_OFF_DEF_V1 +
CFB_OPPONENT_ADJUSTED_V1): each team's last 5 completed games this season,
points for/against opponent-adjusted by the opponent's own prior averages,
shrunk 3 games toward 28; projected points = offense + opponent defense - 28,
home field 2.5. Only games completed BEFORE the target game are used.

Market: CFBD /lines closing spread and total (consensus first). For blend
weights w in 0.0..1.0 the blended margin/total is line + w*(model - line).
Each weight is scored by log-loss of the cover / over probability
(normal, SD 15.5 margin / 15.0 total; pushes excluded) and by hit rate when
the blended number disagrees with the line. Weight is chosen on the earlier
season(s) and reported out-of-sample on the last season. Evaluation only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE, HFA, SHRINK_GAMES, WINDOW = 28.0, 2.5, 3, 5
SD_MARGIN, SD_TOTAL = 15.5, 15.0
WEIGHTS = [round(i / 10, 1) for i in range(11)]
PROVIDERS = ("consensus", "DraftKings", "Bovada", "ESPN Bet", "William Hill (New Jersey)")


def fetch(seasons, key):
    from sportsedge.sports.cfb.source import _auth, _cfbd_url, _json_get
    import time
    games = []
    for idx, s in enumerate(seasons):
        data = None
        for attempt in range(3):  # CFBD 429/502: wait and retry the whole season
            if idx or attempt:
                time.sleep(60 if attempt == 0 else 120)
            try:
                data = _json_get(_cfbd_url("/lines", {"year": int(s), "seasonType": "regular"}),
                                 headers=_auth(key), max_attempts=2) or []
                break
            except Exception as exc:
                print(f"FETCH_RETRY season={s} attempt={attempt + 1}: {exc}"[:300])
        if data is None:
            print(f"FETCH_FAILED season={s}")
            continue
        print(f"fetched season={s} games={len(data)}")
        for g in data:
            if g.get("homeScore") is None or g.get("awayScore") is None:
                continue
            by = {str(l.get("provider")): l for l in g.get("lines") or []}
            pick = next((by[p] for p in PROVIDERS if p in by and by[p].get("spread") is not None), None)
            spread = total = None
            if pick:
                try:
                    spread = float(pick["spread"])
                    total = float(pick["overUnder"]) if pick.get("overUnder") is not None else None
                except (TypeError, ValueError):
                    pass
            games.append({"season": int(s), "week": int(g.get("week") or 0),
                          "start": str(g.get("startDate") or ""), "id": str(g.get("id")),
                          "home": g.get("homeTeam"), "away": g.get("awayTeam"),
                          "hs": float(g["homeScore"]), "as": float(g["awayScore"]),
                          "spread": spread, "total": total})
    games.sort(key=lambda g: (g["season"], g["start"], g["id"]))
    got = {g["season"] for g in games}
    missing = [s for s in seasons if int(s) not in got]
    if missing:  # never choose a weight from a partial dataset
        raise SystemExit(f"INCOMPLETE_DATA missing seasons={missing}; no weight chosen")
    return games


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def project(games):
    """Walk games chronologically; emit model margin/total from prior games only."""
    hist = defaultdict(list)  # (season, team) -> [(pf, pa, opp)]
    out = []

    def avg(season, team, upto=None):
        h = hist[(season, team)][-WINDOW:] if upto is None else hist[(season, team)][:upto][-WINDOW:]
        if not h:
            return None
        return sum(x[0] for x in h) / len(h), sum(x[1] for x in h) / len(h)

    def unit(season, team):
        h = hist[(season, team)]
        recent = h[-WINDOW:]
        if len(recent) < 3:
            return None
        offs, defs = [], []
        start = len(h) - len(recent)
        for i, (pf, pa, opp, opp_n) in enumerate(recent):
            o = avg(season, opp, opp_n)
            if o:
                offs.append(pf - (o[1] - BASE))
                defs.append(pa - (o[0] - BASE))
            else:
                offs.append(pf)
                defs.append(pa)
        n = len(recent)
        off = (sum(offs) + BASE * SHRINK_GAMES) / (n + SHRINK_GAMES)
        de = (sum(defs) + BASE * SHRINK_GAMES) / (n + SHRINK_GAMES)
        return off, de

    # Games sharing a kickoff are simultaneous: evaluate all of them before
    # admitting any result into the prior-game history.
    pending = []
    current_kickoff = None

    def flush_pending():
        for game in pending:
            season = game["season"]
            nh = len(hist[(season, game["away"])])
            na = len(hist[(season, game["home"])])
            hist[(season, game["home"])].append((game["hs"], game["as"], game["away"], nh))
            hist[(season, game["away"])].append((game["as"], game["hs"], game["home"], na))
        pending.clear()

    # JSON fixture inputs may be unordered; never admit future scores first.
    for g in sorted(games, key=lambda x: (x["season"], x["start"], x["id"])):
        kickoff = (g["season"], g["start"])
        if current_kickoff is not None and kickoff != current_kickoff:
            flush_pending()
        current_kickoff = kickoff
        s = g["season"]
        hu, au = unit(s, g["home"]), unit(s, g["away"])
        if hu and au and g["spread"] is not None:
            hp = hu[0] + au[1] - BASE + HFA / 2
            ap = au[0] + hu[1] - BASE - HFA / 2
            out.append({**g, "model_margin": hp - ap, "model_total": hp + ap})
        pending.append(g)
    flush_pending()
    return out


def score(rows, w):
    ll_s = ll_t = n_s = n_t = 0.0
    hit = {k: [0, 0] for k in (0, 3, 5, 7)}
    thit = {k: [0, 0] for k in (0, 3, 5, 7)}
    for r in rows:
        mkt_m = -r["spread"]  # CFBD spread is home line; home margin expectation = -spread
        actual = r["hs"] - r["as"]
        if actual != mkt_m:
            blend = mkt_m + w * (r["model_margin"] - mkt_m)
            p = min(max(phi((blend - mkt_m) / SD_MARGIN), 1e-6), 1 - 1e-6)
            y = 1 if actual > mkt_m else 0
            ll_s += -(y * math.log(p) + (1 - y) * math.log(1 - p))
            n_s += 1
            gap = abs(r["model_margin"] - mkt_m)
            for k in hit:
                if gap >= k and r["model_margin"] != mkt_m:
                    hit[k][1] += 1
                    hit[k][0] += int((r["model_margin"] > mkt_m) == bool(y))
        if r["total"] is not None:
            act_t = r["hs"] + r["as"]
            if act_t != r["total"]:
                blend_t = r["total"] + w * (r["model_total"] - r["total"])
                p = min(max(phi((blend_t - r["total"]) / SD_TOTAL), 1e-6), 1 - 1e-6)
                y = 1 if act_t > r["total"] else 0
                ll_t += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                n_t += 1
                gap = abs(r["model_total"] - r["total"])
                for k in thit:
                    if gap >= k and r["model_total"] != r["total"]:
                        thit[k][1] += 1
                        thit[k][0] += int((r["model_total"] > r["total"]) == bool(y))
    return {"w": w, "spread_logloss": ll_s / max(n_s, 1), "total_logloss": ll_t / max(n_t, 1),
            "n_spread": int(n_s), "n_total": int(n_t),
            "ats_by_gap": {k: (v[0], v[1], round(v[0] / v[1], 4) if v[1] else None) for k, v in hit.items()},
            "ou_by_gap": {k: (v[0], v[1], round(v[0] / v[1], 4) if v[1] else None) for k, v in thit.items()}}


def main(argv=None):
    try:
        return _main(argv)
    except BaseException as exc:  # stdout is what the workflow posts
        print(f"BACKTEST_FAILED: {type(exc).__name__}: {exc}"[:600])
        return 1


def _main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2024,2025,2026")
    ap.add_argument("--games-json")
    ap.add_argument("--output", default="artifacts/run_it/cfb_matchup_blend_backtest.json")
    args = ap.parse_args(argv)
    seasons = [int(x) for x in args.seasons.split(",")]
    if args.games_json:
        games = json.loads(Path(args.games_json).read_text())
    else:
        key = (os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY")
               or os.environ.get("CFBD_KEY") or "").strip()
        if not key:
            raise SystemExit("CFBD_API_KEY_REQUIRED")
        games = fetch(seasons, key)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).with_name("cfb_lines_games.json").write_text(json.dumps(games))
    rows = project(games)
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season"]].append(r)
    report = {"seasons": seasons, "rows": len(rows), "per_season": {}}
    for s, rs in sorted(by_season.items()):
        report["per_season"][s] = [score(rs, w) for w in WEIGHTS]
    train = [r for r in rows if r["season"] < max(seasons)]
    test = [r for r in rows if r["season"] == max(seasons)]
    if train and test:
        best_s = min(WEIGHTS, key=lambda w: score(train, w)["spread_logloss"])
        best_t = min(WEIGHTS, key=lambda w: score(train, w)["total_logloss"])
        report["chosen_on_train"] = {"spread_w": best_s, "total_w": best_t}
        report["out_of_sample"] = {"spread": score(test, best_s), "total": score(test, best_t),
                                   "market_only": score(test, 0.0)}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=1, default=str))
    print("CFB_MATCHUP_BLEND_BACKTEST rows=%d" % len(rows))
    for s, res in report["per_season"].items():
        bs = min(res, key=lambda x: x["spread_logloss"])
        bt = min(res, key=lambda x: x["total_logloss"])
        print(f"{s}: n={res[0]['n_spread']} best spread w={bs['w']} total w={bt['w']} "
              f"ATS gap>=5 {res[0]['ats_by_gap'][5]} O/U gap>=5 {res[0]['ou_by_gap'][5]}")
    if "out_of_sample" in report:
        o = report["out_of_sample"]
        print("OOS chosen", report["chosen_on_train"],
              "spread LL", round(o["spread"]["spread_logloss"], 4),
              "vs market", round(o["market_only"]["spread_logloss"], 4),
              "| total LL", round(o["total"]["total_logloss"], 4),
              "vs market", round(o["market_only"]["total_logloss"], 4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
