"""Either-Pitcher ladder walk-forward per docs/MLB_EITHER_PITCHER_WALKFORWARD_SPEC_20261013.md.

The candidate is per-pitcher as-of PMFs (last 15 usable starts, smoothed toward
the as-of league start PMF with strength 10). The naive baseline is both pitchers
at the league PMF. A start is usable only once FINAL and available by the slate
cutoff (``is_trainable``). The league prior resets each season. Events need both
listed probables to have started that gamePk. Research only; market baseline MISSING.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import log
from typing import Any, Iterable, Mapping

from .mlb_either_pitcher_asof import FIELDS, LAST_N, MIN_STARTS, PRIOR_STRENGTH, SUPPORT, parse_pitcher_gamelog
from .mlb_f5_team_total_ladder import either_pitcher_ladder, is_trainable

LINES = {"EITHER_PITCHER_HITS_ALLOWED": (5.5, 6.5, 7.5), "EITHER_PITCHER_BB": (2.5, 3.5),
         "EITHER_PITCHER_ER": (2.5, 3.5)}
MIN_LEAGUE = 50
EPS = 1e-6


def _ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else None


def build_events(schedules: Iterable[Mapping[str, Any]], logs_by_pitcher: Mapping[int, list]) -> list[dict]:
    starts = {}  # (pitcher, gamePk) -> stat row
    for pid, logs in logs_by_pitcher.items():
        for g in logs:
            if g["started"] and g["game_type"] == "R":
                starts[(pid, g["game_pk"])] = g
    events = {}
    for payload in schedules:
        for d in payload.get("dates") or []:
            for g in d.get("games") or []:
                if (g.get("status") or {}).get("codedGameState") != "F" or g.get("gameType") != "R":
                    continue
                st = _ts(g.get("gameDate"))
                pa = (g["teams"]["away"].get("probablePitcher") or {}).get("id")
                ph = (g["teams"]["home"].get("probablePitcher") or {}).get("id")
                if st is None or not pa or not ph:
                    continue
                pk = int(g["gamePk"])
                events[pk] = {"game_pk": pk, "date": g.get("officialDate") or d.get("date"), "start": st,
                              "away_p": int(pa), "home_p": int(ph),
                              "away": starts.get((int(pa), pk)), "home": starts.get((int(ph), pk))}
    return sorted(events.values(), key=lambda e: (e["date"], e["start"], e["game_pk"]))


def _ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * log(p) + (1 - y) * log(1 - p))


def run_season(events: list[dict]) -> dict:
    by_date = defaultdict(list)
    for e in events:
        by_date[e["date"]].append(e)
    hist = defaultdict(list)  # pitcher -> [(start, row)]
    league = {m: [0.0] * SUPPORT for m in FIELDS}
    n_league = 0
    pending: list[tuple[int, datetime, int, dict]] = []
    res = {m: {str(x): {"n": 0, "brier_cand": 0.0, "brier_naive": 0.0, "ll_cand": 0.0, "ll_naive": 0.0,
                        "mean_p": 0.0, "hit_rate": 0.0} for x in LINES[m]} for m in LINES}
    excluded_no_start = 0
    for date in sorted(by_date):
        slate = by_date[date]
        cutoff = min(e["start"] for e in slate)
        keep = []
        for pid, st, pk, row in pending:
            if is_trainable({"start": st, "status": "FINAL"}, cutoff):
                hist[pid].append((st, pk, row))
                for m, f in FIELDS.items():
                    league[m][min(row[f], SUPPORT - 1)] += 1
                n_league += 1
            else:
                keep.append((pid, st, pk, row))
        pending = keep
        for e in slate:
            if e["away"] is None or e["home"] is None:
                excluded_no_start += 1
                continue
            if n_league < MIN_LEAGUE:
                continue
            ha = sorted(hist[e["away_p"]])[-LAST_N:]
            hh = sorted(hist[e["home_p"]])[-LAST_N:]
            if len(ha) < MIN_STARTS or len(hh) < MIN_STARTS:
                continue
            for m, f in FIELDS.items():
                lp = [c / n_league for c in league[m]]

                def pmf(h):
                    cnt = [0.0] * SUPPORT
                    for _, _, r in h:
                        cnt[min(r[f], SUPPORT - 1)] += 1
                    return [(c + PRIOR_STRENGTH * p) / (len(h) + PRIOR_STRENGTH) for c, p in zip(cnt, lp)]
                cand = either_pitcher_ladder(pmf(ha), pmf(hh), LINES[m])["ladder"]
                naive = either_pitcher_ladder(lp, lp, LINES[m])["ladder"]
                mx = max(e["away"][f], e["home"][f])
                for c, nv in zip(cand, naive):
                    y = int(mx > c["line"])
                    s = res[m][str(c["line"])]
                    s["n"] += 1
                    s["brier_cand"] += (c["over"] - y) ** 2
                    s["brier_naive"] += (nv["over"] - y) ** 2
                    s["ll_cand"] += _ll(c["over"], y)
                    s["ll_naive"] += _ll(nv["over"], y)
                    s["mean_p"] += c["over"]
                    s["hit_rate"] += y
        for e in slate:
            for side in ("away", "home"):
                if e[side] is not None:
                    pending.append((e[side + "_p"], e["start"], e["game_pk"], e[side]))
    for m in res:
        for s in res[m].values():
            n = max(s["n"], 1)
            for k in list(s):
                if k != "n":
                    s[k] = round(s[k] / n, 5)
    return {"markets": res, "excluded_probable_did_not_start": excluded_no_start, "market_baseline": "MISSING"}


def decide(season_2025: dict) -> dict:
    return {m: "PASS_RESEARCH" if all(v["brier_cand"] < v["brier_naive"] and v["ll_cand"] < v["ll_naive"]
                                      for v in season_2025["markets"][m].values()) else "FAIL"
            for m in season_2025["markets"]}


def load_logs(paths: Iterable[str]) -> dict[int, list]:
    import json
    out: dict[int, list] = defaultdict(list)
    for p in paths:
        pid = int(p.rsplit("-", 1)[1].split(".")[0])
        out[pid] += parse_pitcher_gamelog(json.load(open(p)))
    return out
