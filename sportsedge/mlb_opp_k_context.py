"""Context lane 1 in production: opponent strikeout index -> PITCHER_K (#1482 D1b).

Validated in #1509 under the pre-registration docs/MLB_OPP_K_CONTEXT_PREREG.md
(sha256 1f9b0621...). The held-out 2025 test chose ``beta = 1`` and passed all three
ship rules. Scope stays exactly what was validated:

* PITCHER_K only, normal path (k >= 5 own starts, last 10), half-integer lines;
* each own start's K is rescaled by (tonight's opponent index / that start's
  opponent index) ** beta; the engine keeps n = k (no Kish shrinkage of split rows);
* the opponent index is built from the same StatsAPI team hitting game logs with the
  same strictly-prior, W = 1000 PA shrinkage as the research code (it reuses
  ``OppIndex`` from that module, so the index is identical by construction);
* if anything needed is missing (team logs, opponent ids, pitcher's team), the row
  is priced exactly as before and the card says it is unadjusted. Never BLOCKED by
  this lane, never promoted by it (pitcher props stay LEAN max).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from .mlb_opp_k_context_research import OppIndex, team_games_from_gamelog

BETA = 1.0
MARKET = "PITCHER_K"
MIN_OWN_STARTS = 5
PREREG_SHA256_PREFIX = "1f9b0621"
VALIDATED_IN = "#1509"
TEAMS_PER_SEASON = 30
MIN_PRIOR_SEASON_GAMES = 100


class OppKContextError(ValueError):
    pass


def build_index(fetch_team_season: Callable[[int, int], Mapping[str, Any]], team_ids: Sequence[int],
                target_date: date, *, workers: int = 8) -> OppIndex:
    """Index over seasons Y-2..Y (Y-2 is needed for z_prev of last season's starts)."""
    ids = sorted({int(t) for t in team_ids})
    if len(ids) != TEAMS_PER_SEASON:
        raise OppKContextError(f"expected {TEAMS_PER_SEASON} MLB teams, got {len(ids)}")
    y = target_date.year
    jobs = [(t, s) for s in (y - 2, y - 1, y) for t in ids]

    def one(job: tuple[int, int]) -> tuple[tuple[int, int], list[tuple[str, int, int]]]:
        return job, team_games_from_gamelog(fetch_team_season(*job))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, jobs))
    games: dict[tuple[int, int], list[tuple[str, int, int]]] = {}
    for (team, season), rows in results:
        if season < y and len(rows) < MIN_PRIOR_SEASON_GAMES:
            raise OppKContextError(f"team {team} season {season} hitting log incomplete ({len(rows)} games)")
        if rows:
            games[(team, season)] = rows
    return OppIndex(games)


def opponent_of(team_id: int | None, away_team_id: int, home_team_id: int) -> int | None:
    if team_id is None:
        return None
    if int(team_id) == int(away_team_id):
        return int(home_team_id)
    if int(team_id) == int(home_team_id):
        return int(away_team_id)
    return None


def adjustment_features(index: OppIndex, *, target_opp_id: int, target_date: date,
                        history: Sequence[tuple[date, int]]) -> dict[str, Any]:
    """Engine payload: the frozen beta plus rel() for tonight's opponent and each own start."""
    if len(history) < MIN_OWN_STARTS:
        raise OppKContextError(f"opp-K lane needs >= {MIN_OWN_STARTS} own starts")
    target_rel = index.rel(int(target_opp_id), target_date.year, target_date.isoformat())
    hist_rel = [index.rel(int(opp), d.year, d.isoformat()) for d, opp in history]
    if not target_rel > 0 or any(not r > 0 for r in hist_rel):
        raise OppKContextError("non-positive opponent index")
    return {"market": MARKET, "beta": BETA, "target_rel": float(target_rel),
            "history_rel": [float(r) for r in hist_rel], "opponent_team_id": int(target_opp_id),
            "prereg_sha256_prefix": PREREG_SHA256_PREFIX, "validated_in": VALIDATED_IN}


def applies(features: Mapping[str, Any], market: str, line: float) -> bool:
    """Same scope test the engine uses: K, half line, adjustment payload present."""
    return (str(market).upper() == MARKET and isinstance(features.get("opp_k_adjustment"), Mapping)
            and not float(line).is_integer())


def summary(pool: Sequence[Mapping[str, Any]], adj: Mapping[str, Any]) -> dict[str, Any]:
    """Presentation numbers for the card (the engine computes the price itself)."""
    raw = [int(r["strikeouts"]) for r in pool]
    rels = [float(r) for r in adj["history_rel"]]
    beta, target = float(adj["beta"]), float(adj["target_rel"])
    xs = [min(max(v * (target / h) ** beta, 0.0), 20.0) for v, h in zip(raw, rels)]
    return {"beta": beta, "target_rel": target, "history_rel_mean": sum(rels) / len(rels),
            "factor": (sum(xs) / sum(raw)) if sum(raw) > 0 else 1.0, "own_starts": len(raw),
            "opponent_team_id": adj.get("opponent_team_id")}


def opp_k_notes(payload: Mapping[str, Any], names: Mapping[str, str] | None = None) -> list[str]:
    """One card note per pitcher: the K adjustment applied, or why K stayed unadjusted."""
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
        if isinstance(ev.get("opp_k_adjustment"), Mapping):
            applied.setdefault(entity, ev["opp_k_adjustment"])
        elif ev.get("opp_k_unadjusted"):
            unadjusted.setdefault(entity, str(ev["opp_k_unadjusted"]))
    notes = []
    for entity, adj in sorted(applied.items()):
        who = (names or {}).get(entity) or entity
        notes.append(f"OPP-K ADJ x{float(adj.get('factor', 1.0)):.2f} {who} Pitcher K: opponent K index "
                     f"{float(adj.get('target_rel', 1.0)):.2f} vs {float(adj.get('history_rel_mean', 1.0)):.2f} avg over his last "
                     f"{adj.get('own_starts')} starts (beta {float(adj.get('beta', BETA)):g}, validated {VALIDATED_IN}). LEAN max.")
    for entity, reason in sorted(unadjusted.items()):
        if entity in applied:
            continue
        who = (names or {}).get(entity) or entity
        notes.append(f"OPP-K UNADJUSTED {who} Pitcher K: {reason}; priced from own starts only (as before).")
    return notes
