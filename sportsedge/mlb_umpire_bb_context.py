"""Context lane 2b-BB in production: home-plate umpire walk index -> PITCHER_BB (#1482 D2b).

Validated in #1528 under docs/MLB_UMPIRE_CONTEXT_PREREG.md (sha256 a4669856...).
The held-out 2025 test selected ``W = 6000, beta = 2`` for the BB sub-lane and passed
all three ship rules. (The K sub-lane did NOT ship; PITCHER_K is untouched here.)
Scope stays exactly what was validated:

* PITCHER_BB only, normal path (k >= 5 own starts, last 10), half-integer lines;
* each own start's walks are rescaled by (tonight's plate-umpire BB index / that
  start's plate-umpire BB index) ** beta, split floor/ceil, clipped to [0, 10];
  the engine keeps n = k;
* the umpire index is the research ``UmpIndex`` itself (trailing 365 days, strictly
  before the date, shrunk with W PA toward the league rate), built from the same
  StatsAPI team hitting game logs lanes 1/2a already fetch plus regular-season
  schedule ``officials``; a history start whose umpire is unknown takes rel = 1,
  exactly as in the research;
* if tonight's umpire is not assigned yet, or any input is missing, the row keeps
  its current price and the card says why. Never BLOCKED by this lane, never
  promoted by it (pitcher props stay LEAN max).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Sequence

from .mlb_umpire_context_research import UmpIndex, game_totals, home_plate_by_game, team_game_rows

BETA = 2.0
W = 6000.0
STAT = "bb"
MARKET = "PITCHER_BB"
CAP = 10
MIN_OWN_STARTS = 5
PREREG_SHA256_PREFIX = "a4669856"
VALIDATED_IN = "#1528"
TEAMS_PER_SEASON = 30
MIN_PRIOR_SEASON_GAMES = 100
MIN_USABLE_SHARE = 0.9


class UmpireBBContextError(ValueError):
    pass


def schedule_windows(target_date: date) -> list[tuple[date, date]]:
    """Monthly [start, end] chunks from Mar 1 of Y-2 through the day before the target.

    Y-2 is needed because a start early in season Y-1 looks back 365 days.
    """
    out: list[tuple[date, date]] = []
    last = target_date - timedelta(days=1)
    for season in (target_date.year - 2, target_date.year - 1, target_date.year):
        for month in range(3, 11):  # regular season, March through October (as in the research runner)
            start = date(season, month, 1)
            end = date(season, month + 1, 1) - timedelta(days=1)
            if start > last:
                return out
            out.append((start, min(end, last)))
    return out


class UmpireBBIndex:
    """Slate-level umpire BB index plus the gamePk -> plate umpire map it was built from."""

    def __init__(self, index: UmpIndex, umpires: Mapping[int, int], *, games: int, usable_share: float):
        self.index = index
        self.umpires = dict(umpires)
        self.games = int(games)
        self.usable_share = float(usable_share)

    def rel(self, umpire_id: int | None, d: date) -> float:
        return float(self.index.rel(umpire_id, d.isoformat(), STAT, W))


def build_index(fetch_team_season: Callable[[int, int], Mapping[str, Any]], team_ids: Sequence[int],
                fetch_schedule: Callable[[date, date], Mapping[str, Any]], target_date: date, *,
                workers: int = 8) -> UmpireBBIndex:
    """Same construction as the research runner, restricted to games before the target date."""
    ids = sorted({int(t) for t in team_ids})
    if len(ids) != TEAMS_PER_SEASON:
        raise UmpireBBContextError(f"expected {TEAMS_PER_SEASON} MLB teams, got {len(ids)}")
    y = target_date.year
    team_jobs = [(t, s) for s in (y - 2, y - 1, y) for t in ids]
    windows = schedule_windows(target_date)

    def team_one(job: tuple[int, int]):
        return job, team_game_rows(fetch_team_season(*job))

    def sched_one(window: tuple[date, date]):
        return home_plate_by_game(fetch_schedule(*window))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        team_results = list(ex.map(team_one, team_jobs))
        sched_results = list(ex.map(sched_one, windows))
    flat = []
    for (team, season), rows in team_results:
        if season < y and len(rows) < MIN_PRIOR_SEASON_GAMES:
            raise UmpireBBContextError(f"team {team} season {season} hitting log incomplete ({len(rows)} games)")
        flat.extend(rows)
    cutoff = target_date.isoformat()
    games = {pk: v for pk, v in game_totals(flat).items() if v[0] < cutoff}
    umpires: dict[int, int] = {}
    for got in sched_results:
        umpires.update(got)
    if not games:
        raise UmpireBBContextError("no prior games")
    index = UmpIndex(games, umpires)
    share = index.usable_games / len(games)
    if share < MIN_USABLE_SHARE:
        raise UmpireBBContextError(f"only {share:.0%} of prior games have a plate umpire; schedule officials incomplete")
    return UmpireBBIndex(index, umpires, games=len(games), usable_share=share)


def adjustment_features(index: UmpireBBIndex, *, target_umpire: Mapping[str, Any], target_date: date,
                        history: Sequence[tuple[date, int | None]]) -> dict[str, Any]:
    """Engine payload: frozen (W, beta) plus rel() for tonight's umpire and each own start's umpire."""
    if len(history) < MIN_OWN_STARTS:
        raise UmpireBBContextError(f"umpire-BB lane needs >= {MIN_OWN_STARTS} own starts")
    ump_id = int(target_umpire["umpire_id"])
    target_rel = index.rel(ump_id, target_date)
    hist_ump = [index.umpires.get(int(pk)) if pk is not None else None for _, pk in history]
    hist_rel = [index.rel(u, d) for (d, _), u in zip(history, hist_ump)]
    if not target_rel > 0 or any(not r > 0 for r in hist_rel):
        raise UmpireBBContextError("non-positive umpire index")
    return {"market": MARKET, "stat": STAT, "W": W, "beta": BETA, "target_rel": float(target_rel),
            "history_rel": [float(r) for r in hist_rel], "umpire_id": ump_id,
            "umpire_name": target_umpire.get("umpire_name"),
            "history_umpires_known": sum(u is not None for u in hist_ump),
            "prereg_sha256_prefix": PREREG_SHA256_PREFIX, "validated_in": VALIDATED_IN}


def applies(features: Mapping[str, Any], market: str, line: float) -> bool:
    """Same scope test the engine uses: BB, half line, adjustment payload present."""
    return (str(market).upper() == MARKET and isinstance(features.get("ump_bb_adjustment"), Mapping)
            and not float(line).is_integer())


def summary(pool: Sequence[Mapping[str, Any]], adj: Mapping[str, Any]) -> dict[str, Any]:
    """Presentation numbers for the card (the engine computes the price itself)."""
    raw = [int(r["walks_allowed"]) for r in pool]
    rels = [float(r) for r in adj["history_rel"]]
    beta, target = float(adj["beta"]), float(adj["target_rel"])
    xs = [min(max(v * (target / h) ** beta, 0.0), float(CAP)) for v, h in zip(raw, rels)]
    return {"beta": beta, "W": float(adj.get("W", W)), "target_rel": target,
            "history_rel_mean": sum(rels) / len(rels),
            "factor": (sum(xs) / sum(raw)) if sum(raw) > 0 else 1.0, "own_starts": len(raw),
            "umpire_id": adj.get("umpire_id"), "umpire_name": adj.get("umpire_name"),
            "history_umpires_known": adj.get("history_umpires_known")}


def ump_bb_notes(payload: Mapping[str, Any], names: Mapping[str, str] | None = None) -> list[str]:
    """One card note per pitcher: the BB adjustment applied, or why BB stayed unadjusted."""
    results: list[Any] = list(payload.get("results") or [])
    for game in payload.get("games") or []:
        if isinstance(game, Mapping):
            results.extend(game.get("results") or [])
    applied: dict[str, Mapping[str, Any]] = {}
    unadjusted: dict[str, str] = {}
    for row in results:
        if not isinstance(row, Mapping) or str(row.get("market")) != MARKET:
            continue
        ev = row.get("empirical_evidence")
        if not isinstance(ev, Mapping):
            continue
        entity = str(row.get("entity_id"))
        if isinstance(ev.get("ump_bb_adjustment"), Mapping):
            applied.setdefault(entity, ev["ump_bb_adjustment"])
        elif ev.get("ump_bb_unadjusted"):
            unadjusted.setdefault(entity, str(ev["ump_bb_unadjusted"]))
    notes = []
    for entity, adj in sorted(applied.items()):
        who = (names or {}).get(entity) or entity
        ump = adj.get("umpire_name") or f"umpire {adj.get('umpire_id')}"
        notes.append(
            f"UMP-BB ADJ x{float(adj.get('factor', 1.0)):.2f} {who} Pitcher BB: plate umpire {ump} walk index "
            f"{float(adj.get('target_rel', 1.0)):.2f} vs {float(adj.get('history_rel_mean', 1.0)):.2f} avg over his last "
            f"{adj.get('own_starts')} starts (W {float(adj.get('W', W)):g}, beta {float(adj.get('beta', BETA)):g}, "
            f"validated {VALIDATED_IN}). LEAN max."
        )
    for entity, reason in sorted(unadjusted.items()):
        if entity in applied:
            continue
        who = (names or {}).get(entity) or entity
        notes.append(f"UMP-BB UNADJUSTED {who} Pitcher BB: {reason}; priced from own starts only (as before).")
    return notes


__all__ = ["BETA", "W", "MARKET", "adjustment_features", "applies", "build_index", "schedule_windows", "summary", "ump_bb_notes"]
