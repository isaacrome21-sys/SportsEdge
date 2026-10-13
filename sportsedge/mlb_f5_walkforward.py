"""Walk-forward validation of the F5 run share and F5 team-total ladder.

Free MLB Stats API schedule+linescore data only. For each slate (officialDate)
the cutoff is the slate's earliest first pitch. The F5 run share, team
full-game run means and the naive baseline are fitted only on games that were
FINAL with their linescore available at the cutoff (Stats API schedule has no
end time, so start + 6h conservative buffer via ``is_trainable``). Games without
a parseable start time are never trained on or scored. The market baseline
is MISSING (no paired timestamped odds); the naive baseline is the strictly-prior
league frequency of team F5 runs > line.
"""
from __future__ import annotations

from collections import defaultdict, deque
from math import log
from typing import Any, Iterable, Mapping

from datetime import datetime

from .mlb_f5_team_total_ladder import MIN_SHARE_GAMES, is_trainable, price_f5_team_totals

LINES = (0.5, 1.5, 2.5)
TEAM_WINDOW = 30
MIN_TEAM_GAMES = 10
EPS = 1e-6


def parse_schedule(payloads: Iterable[Mapping[str, Any]]) -> list[dict]:
    games = {}
    for payload in payloads:
        for d in payload.get("dates") or []:
            for g in d.get("games") or []:
                if (g.get("status") or {}).get("codedGameState") != "F" or g.get("gameType") != "R":
                    continue
                inn = (g.get("linescore") or {}).get("innings") or []
                if len(inn) < 5:
                    continue
                try:
                    a = [int((i.get("away") or {}).get("runs") or 0) for i in inn]
                    h = [int((i.get("home") or {}).get("runs") or 0) for i in inn]
                    h_f5 = [int(i["home"]["runs"]) for i in inn[:5]]
                    teams = g["teams"]
                except (KeyError, TypeError, ValueError):
                    continue
                games[int(g["gamePk"])] = {
                    "game_id": int(g["gamePk"]), "date": g.get("officialDate") or d.get("date"),
                    "start": _ts(g.get("gameDate")), "status": "FINAL",
                    "away": int(teams["away"]["team"]["id"]), "home": int(teams["home"]["team"]["id"]),
                    "innings": len(inn), "away_f5": sum(a[:5]), "home_f5": sum(h_f5),
                    "away_reg": sum(a[:9]), "home_reg": sum(h[:9]),
                    "away_runs": int(teams["away"].get("score", sum(a))),
                    "home_runs": int(teams["home"].get("score", sum(h))),
                }
    return sorted((g for g in games.values() if g["start"] is not None),
                  key=lambda g: (g["date"], g["start"], g["game_id"]))


def _ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else None


def _ll(p: float, y: int) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return -(y * log(p) + (1 - y) * log(1 - p))


def run_walkforward(games: list[dict], *, start_date: str | None = None) -> dict:
    by_date = defaultdict(list)
    for g in games:
        by_date[g["date"]].append(g)
    hist = defaultdict(lambda: deque(maxlen=TEAM_WINDOW))
    f5_sum = reg_sum = share_games = team_obs = 0
    over_cnt = {x: 0 for x in LINES}
    stats = {x: {"n": 0, "brier_model": 0.0, "brier_naive": 0.0, "ll_model": 0.0, "ll_naive": 0.0,
                 "mean_p": 0.0, "hit_rate": 0.0} for x in LINES}
    pending: list[dict] = []
    for date in sorted(by_date):
        slate = by_date[date]
        cutoff = min(g["start"] for g in slate)
        ready = [g for g in pending if is_trainable(g, cutoff)]
        pending = [g for g in pending if not is_trainable(g, cutoff)]
        for g in sorted(ready, key=lambda g: (g["start"], g["game_id"])):
            hist[g["away"]].append(g["away_runs"])
            hist[g["home"]].append(g["home_runs"])
            if g["innings"] >= 9:
                f5_sum += g["away_f5"] + g["home_f5"]
                reg_sum += g["away_reg"] + g["home_reg"]
                share_games += 1
            for x in LINES:
                over_cnt[x] += int(g["away_f5"] > x) + int(g["home_f5"] > x)
            team_obs += 2
        if (start_date is None or date >= start_date) and share_games >= MIN_SHARE_GAMES and team_obs:
            share = f5_sum / reg_sum
            for g in slate:
                if len(hist[g["away"]]) < MIN_TEAM_GAMES or len(hist[g["home"]]) < MIN_TEAM_GAMES:
                    continue
                out = price_f5_team_totals({
                    "away_mean_runs": max(sum(hist[g["away"]]) / len(hist[g["away"]]), 0.1),
                    "home_mean_runs": max(sum(hist[g["home"]]) / len(hist[g["home"]]), 0.1),
                    "f5_share": share, "lines": LINES})
                for side, runs in (("AWAY", g["away_f5"]), ("HOME", g["home_f5"])):
                    for row in out["teams"][side]["ladder"]:
                        x = row["line"]
                        y = int(runs > x)
                        p, q = row["over"], over_cnt[x] / team_obs
                        s = stats[x]
                        s["n"] += 1
                        s["brier_model"] += (p - y) ** 2
                        s["brier_naive"] += (q - y) ** 2
                        s["ll_model"] += _ll(p, y)
                        s["ll_naive"] += _ll(q, y)
                        s["mean_p"] += p
                        s["hit_rate"] += y
        pending.extend(slate)
    for s in stats.values():
        n = max(s["n"], 1)
        for k in ("brier_model", "brier_naive", "ll_model", "ll_naive", "mean_p", "hit_rate"):
            s[k] = round(s[k] / n, 5)
    return {"lines": {str(k): v for k, v in stats.items()},
            "final_f5_share": round(f5_sum / reg_sum, 5) if reg_sum else None,
            "market_baseline": "MISSING", "team_window": TEAM_WINDOW}
