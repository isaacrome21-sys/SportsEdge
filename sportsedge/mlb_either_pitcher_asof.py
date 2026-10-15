"""As-of per-pitcher count distributions feeding the Either-Pitcher ladders.

Source: free MLB Stats API pitcher game logs
(``people/{id}/stats?stats=gameLog&group=pitching&season=YYYY``).
Point-in-time: a start is used only if its gamePk has a known first pitch in the
schedule cache and the game was FINAL and available by ``as_of``
(``is_trainable``: start + 6h). Unknown gamePk or start time means the start is
excluded (fail closed). Relief appearances are excluded. Model probabilities
only; settlement stays UNVERIFIED_DK_RULES and the market baseline is MISSING.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .mlb_f5_team_total_ladder import F5LadderError, either_pitcher_ladder, is_trainable

FIELDS = {"EITHER_PITCHER_HITS_ALLOWED": "hits", "EITHER_PITCHER_BB": "baseOnBalls",
          "EITHER_PITCHER_ER": "earnedRuns"}
LAST_N = 15
MIN_STARTS = 5
PRIOR_STRENGTH = 10.0
SUPPORT = 16


def parse_pitcher_gamelog(payload: Mapping[str, Any]) -> list[dict]:
    out = []
    for block in payload.get("stats") or []:
        for sp in block.get("splits") or []:
            st = sp.get("stat") or {}
            try:
                out.append({"game_pk": int(sp["game"]["gamePk"]), "date": sp.get("date"),
                            "game_type": sp.get("gameType"), "started": int(st.get("gamesStarted") or 0) == 1,
                            **{f: int(st[f]) for f in FIELDS.values()}})
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _usable(logs, as_of, start_by_pk):
    seen, rows = set(), []
    for g in logs:
        if not g.get("started") or g.get("game_type") != "R" or g["game_pk"] in seen:
            continue
        start = start_by_pk.get(g["game_pk"])
        if start is None or not is_trainable({"start": start, "status": "FINAL"}, as_of):
            continue
        seen.add(g["game_pk"])
        rows.append((start, g))
    rows.sort(key=lambda t: (t[0], t[1]["game_pk"]))
    return [g for _, g in rows[-LAST_N:]]


def pitcher_count_pmf(logs: Sequence[Mapping[str, Any]], *, market: str, as_of: datetime,
                      start_by_pk: Mapping[int, datetime], prior_pmf: Sequence[float] | None = None) -> dict:
    field = FIELDS.get(market)
    if field is None:
        raise F5LadderError("unsupported Either-Pitcher market")
    used = _usable(logs, as_of, start_by_pk)
    if len(used) < MIN_STARTS:
        raise F5LadderError(f"requires >= {MIN_STARTS} as-of starts")
    counts = [0.0] * SUPPORT
    for g in used:
        counts[min(g[field], SUPPORT - 1)] += 1
    if prior_pmf is not None:
        prior = list(prior_pmf)[:SUPPORT] + [0.0] * max(0, SUPPORT - len(prior_pmf))
        if abs(sum(prior) - 1) > 1e-9:
            raise F5LadderError("prior_pmf must sum to 1")
        pmf = [(c + PRIOR_STRENGTH * p) / (len(used) + PRIOR_STRENGTH) for c, p in zip(counts, prior)]
    else:
        pmf = [c / len(used) for c in counts]
    return {"pmf": pmf, "starts_used": len(used), "game_pks": [g["game_pk"] for g in used]}


def league_prior_pmf(all_logs: Sequence[Sequence[Mapping[str, Any]]], *, market: str, as_of: datetime,
                     start_by_pk: Mapping[int, datetime]) -> list[float]:
    field = FIELDS[market]
    counts = [0.0] * SUPPORT
    for logs in all_logs:
        for g in _usable(logs, as_of, start_by_pk):
            counts[min(g[field], SUPPORT - 1)] += 1
    n = sum(counts)
    if n < 50:
        raise F5LadderError("league prior requires >= 50 as-of starts")
    return [c / n for c in counts]


def price_either_pitcher(away_logs, home_logs, *, market: str, lines: Sequence[float], as_of: datetime,
                         start_by_pk: Mapping[int, datetime], prior_pmf: Sequence[float] | None = None) -> dict:
    a = pitcher_count_pmf(away_logs, market=market, as_of=as_of, start_by_pk=start_by_pk, prior_pmf=prior_pmf)
    h = pitcher_count_pmf(home_logs, market=market, as_of=as_of, start_by_pk=start_by_pk, prior_pmf=prior_pmf)
    out = either_pitcher_ladder(a["pmf"], h["pmf"], lines)
    out.update(market=market, as_of=as_of.isoformat(), away_starts=a["starts_used"], home_starts=h["starts_used"],
               provenance={"away_game_pks": a["game_pks"], "home_game_pks": h["game_pks"]})
    return out
