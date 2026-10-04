"""Context lane 2a in production: opponent on-base index -> PITCHER_OUTS (#1482 D2a).

Validated in #1523 under docs/MLB_OPP_OUTS_CONTEXT_PREREG.md (sha256 9aad1cdd...).
The held-out 2025 test selected ``obidx`` with ``beta = -0.25`` and passed all
three ship rules. Scope stays exactly what was validated:

* PITCHER_OUTS only, normal path (k >= 5 own starts, last 10), half-integer lines;
* each own start's outs are rescaled by (tonight's opponent on-base index / that
  start's opponent on-base index) ** beta; the engine keeps n = k;
* the index is the same shrunk construction as lane 1, event = H+BB+HBP per PA,
  built from the same StatsAPI team hitting game logs (no second fetch);
* a missing input keeps the unadjusted outs price and the card says why.
  Never BLOCKED by this lane, never promoted (pitcher props stay LEAN max).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping, Sequence

from .mlb_opp_k_context import opponent_of
from .mlb_opp_k_context_research import OppIndex
from .mlb_opp_outs_context_research import team_rows_from_gamelog

BETA = -0.25
INDEX = "obidx"
MARKET = "PITCHER_OUTS"
MIN_OWN_STARTS = 5
PREREG_SHA256_PREFIX = "9aad1cdd"
VALIDATED_IN = "#1523"
TEAMS_PER_SEASON = 30
MIN_PRIOR_SEASON_GAMES = 100


class OppOutsContextError(ValueError):
    pass


def build_index(fetch_team_season: Callable[[int, int], Mapping[str, Any]], team_ids: Sequence[int],
                target_date: date) -> OppIndex:
    """On-base index over seasons Y-2..Y from the same team logs lane 1 fetches."""
    ids = sorted({int(t) for t in team_ids})
    if len(ids) != TEAMS_PER_SEASON:
        raise OppOutsContextError(f"expected {TEAMS_PER_SEASON} MLB teams, got {len(ids)}")
    y = target_date.year
    games: dict[tuple[int, int], list[tuple[str, int, int]]] = {}
    for season in (y - 2, y - 1, y):
        for team in ids:
            rows = team_rows_from_gamelog(fetch_team_season(team, season)).get(INDEX) or []
            if season < y and len(rows) < MIN_PRIOR_SEASON_GAMES:
                raise OppOutsContextError(f"team {team} season {season} on-base log incomplete ({len(rows)} games)")
            games[(team, season)] = list(rows)
    return OppIndex(games)


def adjustment_features(index: OppIndex, *, target_opp_id: int, target_date: date,
                        history: Sequence[tuple[date, int]]) -> dict[str, Any]:
    if len(history) < MIN_OWN_STARTS:
        raise OppOutsContextError(f"opp-outs lane needs >= {MIN_OWN_STARTS} own starts")
    target_rel = index.rel(int(target_opp_id), target_date.year, target_date.isoformat())
    hist_rel = [index.rel(int(opp), d.year, d.isoformat()) for d, opp in history]
    if not target_rel > 0 or any(not r > 0 for r in hist_rel):
        raise OppOutsContextError("non-positive opponent index")
    return {"market": MARKET, "index": INDEX, "beta": BETA, "target_rel": float(target_rel),
            "history_rel": [float(r) for r in hist_rel], "opponent_team_id": int(target_opp_id),
            "prereg_sha256_prefix": PREREG_SHA256_PREFIX, "validated_in": VALIDATED_IN}


def applies(features: Mapping[str, Any], market: str, line: float) -> bool:
    return (str(market).upper() == MARKET and isinstance(features.get("opp_outs_adjustment"), Mapping)
            and not float(line).is_integer())


def summary(pool: Sequence[Mapping[str, Any]], adj: Mapping[str, Any]) -> dict[str, Any]:
    raw = [int(r["outs"]) for r in pool]
    rels = [float(r) for r in adj["history_rel"]]
    beta, target = float(adj["beta"]), float(adj["target_rel"])
    xs = [min(max(v * (target / h) ** beta, 0.0), 27.0) for v, h in zip(raw, rels)]
    return {"beta": beta, "index": adj.get("index") or INDEX, "target_rel": target,
            "history_rel_mean": sum(rels) / len(rels),
            "factor": (sum(xs) / sum(raw)) if sum(raw) > 0 else 1.0, "own_starts": len(raw),
            "opponent_team_id": adj.get("opponent_team_id")}


def opp_outs_notes(payload: Mapping[str, Any], names: Mapping[str, str] | None = None) -> list[str]:
    """One card note per pitcher: the outs adjustment applied, or why outs stayed unadjusted."""
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
        if isinstance(ev.get("opp_outs_adjustment"), Mapping):
            applied.setdefault(entity, ev["opp_outs_adjustment"])
        elif ev.get("opp_outs_unadjusted"):
            unadjusted.setdefault(entity, str(ev["opp_outs_unadjusted"]))
    notes = []
    for entity, adj in sorted(applied.items()):
        who = (names or {}).get(entity) or entity
        notes.append(
            f"OPP-OUTS ADJ x{float(adj.get('factor', 1.0)):.2f} {who} Pitcher outs: opponent on-base index "
            f"{float(adj.get('target_rel', 1.0)):.2f} vs {float(adj.get('history_rel_mean', 1.0)):.2f} avg over his last "
            f"{adj.get('own_starts')} starts (beta {float(adj.get('beta', BETA)):g}, validated {VALIDATED_IN}). LEAN max."
        )
    for entity, reason in sorted(unadjusted.items()):
        if entity in applied:
            continue
        who = (names or {}).get(entity) or entity
        notes.append(f"OPP-OUTS UNADJUSTED {who} Pitcher outs: {reason}; priced from own starts only (as before).")
    return notes


__all__ = ["BETA", "INDEX", "MARKET", "adjustment_features", "applies", "build_index", "opponent_of", "opp_outs_notes", "summary"]
