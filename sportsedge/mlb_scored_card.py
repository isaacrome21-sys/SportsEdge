"""MySpariEdge-style MLB RUN IT card presentation.

Pure presentation: ranks already-produced SportsEdge results. It never creates Model_P,
changes confidence, or grants governance authority. ACTIONABLE rows must carry the
versioned provenance emitted by ``score_mlb_edge``; unverified scores fail closed.
"""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_edge_score import MLB_EDGE_SCORE_PROVENANCE
from .mlb_empirical_support import is_empirical

_STATUS_ORDER={"ACTIONABLE":0,"LEAN":1,"PASS":2,"BLOCKED":3,"NO_MODEL":4}
_UNVERIFIED_REASON="UNVERIFIED_CONFIDENCE_PROVENANCE"
MIN_CARD_EV=0.02
EV_FLOOR_REASON="BELOW_MIN_CARD_EV_2PCT"
EMPIRICAL_SIDE_CONFLICT_REASON="EMPIRICAL_SIDE_CONFLICT"
_TEAM_OUTCOME_MARKETS=frozenset({"MONEYLINE","RUN_LINE","F5_MONEYLINE","F5_RUN_LINE"})
_EMPIRICAL_OWN_TEAM_OVER=frozenset({
    "PITCHER_K","PITCHER_OUTS",
    "HITS","HOME_RUNS","TOTAL_BASES","RBI","RUNS","STOLEN_BASES","BATTER_BB",
    "EXTRA_BASE_HITS","SINGLES","DOUBLES","TRIPLES","HITS_RUNS_RBIS",
    "HITS_RUNS_STOLEN_BASES","RUNS_RBIS","HITS_STOLEN_BASES","HITS_WALKS_STOLEN_BASES",
})
_EMPIRICAL_OPP_TEAM_OVER=frozenset({
    "PITCHER_ER","PITCHER_HITS_ALLOWED","PITCHER_BB","PITCHER_HITS_WALKS_ER","BATTER_K",
})


def _dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError("CARD_ROW_MUST_BE_MAPPING_OR_DATACLASS")


def _verified_model_score(row: Mapping[str, Any]) -> bool:
    if str(row.get("confidence_provenance") or "").strip().upper() != MLB_EDGE_SCORE_PROVENANCE:
        return False
    try:
        model_p=float(row["model_p"])
        market_p=float(row["market_p"])
        edge=float(row["edge"])
        ev=float(row["ev_per_dollar"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(isfinite(value) for value in (model_p, market_p, edge, ev)):
        return False
    if not (0 < model_p < 1 and 0 < market_p < 1):
        return False
    if abs((model_p-market_p)-edge) > 1e-9:
        return False
    reasons={str(reason).strip().upper() for reason in (row.get("reason_codes") or ())}
    return "POWER_V1_NO_VIG" in reasons


def _star_rating(*, score: int, status: str, verified: bool) -> int:
    """Map the locked qualification score to the public phone-card tier contract.

    Score B remains qualification-only; this function is presentation only.
    88+ = 5 stars, 82-87 = 4 stars, and any verified score <=81 = 3 stars.
    Blocked, no-model, or unverified rows always receive 0 stars.
    """
    if status in {"LEAN", "BLOCKED", "NO_MODEL"} or not verified:
        return 0
    if score >= 88:
        return 5
    if score >= 82:
        return 4
    return 3


def _other_team(side: str | None) -> str | None:
    return {"AWAY":"HOME","HOME":"AWAY"}.get(str(side or "").upper())


def _team_outcome_side(row: Mapping[str, Any]) -> str | None:
    if str(row.get("market") or "").upper() not in _TEAM_OUTCOME_MARKETS:
        return None
    side=str(row.get("side") or "").upper()
    return side if side in {"AWAY","HOME"} else None


def _empirical_implied_team(row: Mapping[str, Any]) -> str | None:
    """Team direction implied by an empirical prop, or None when not safely bindable.

    This is only a presentation conflict check. It does not change a probability.
    """
    if not is_empirical(row):
        return None
    team=str(row.get("team_side") or "").upper()
    side=str(row.get("side") or "").upper()
    market=str(row.get("market") or "").upper()
    if team not in {"AWAY","HOME"} or side not in {"OVER","UNDER"}:
        return None
    if market in _EMPIRICAL_OWN_TEAM_OVER:
        own_when_over=True
    elif market in _EMPIRICAL_OPP_TEAM_OVER:
        own_when_over=False
    else:
        return None
    supports_own = own_when_over if side == "OVER" else not own_when_over
    return team if supports_own else _other_team(team)


def _side_rank(row: Mapping[str, Any]) -> tuple[int,float]:
    try:
        score=int(row.get("confidence_score") or 0)
    except (TypeError,ValueError):
        score=0
    try:
        ev=float(row.get("ev_per_dollar"))
    except (TypeError,ValueError):
        ev=float("-inf")
    return score,ev


def _apply_empirical_side_conflicts(rows: list[dict[str, Any]]) -> None:
    """Fail empirical props to PASS when they oppose the core ACTIONABLE side.

    The core side always wins this presentation conflict. Unbound props fail neutral.
    """
    by_game: dict[str,list[dict[str,Any]]] = {}
    for row in rows:
        game_id=row.get("game_id")
        if game_id not in {None,""}:
            by_game.setdefault(str(game_id),[]).append(row)
    for game_rows in by_game.values():
        core=[r for r in game_rows if r.get("scored_status")=="ACTIONABLE" and not is_empirical(r) and _team_outcome_side(r)]
        if not core:
            continue
        keeper=max(core,key=_side_rank)
        keep_team=_team_outcome_side(keeper)
        for row in game_rows:
            if row.get("scored_status") not in {"ACTIONABLE","LEAN"} or not is_empirical(row):
                continue
            implied=_empirical_implied_team(row)
            if implied is None or implied == keep_team:
                continue
            row["scored_status"]="PASS"
            row["status"]="PASS"
            row["star_rating"]=0
            reasons=list(row.get("presentation_reason_codes") or ())
            if EMPIRICAL_SIDE_CONFLICT_REASON not in reasons:
                reasons.append(EMPIRICAL_SIDE_CONFLICT_REASON)
            row["presentation_reason_codes"]=tuple(reasons)


def build_mlb_scored_card(rows: Sequence[Any], *, actionable_only: bool=False) -> list[dict[str, Any]]:
    out=[]
    for raw in rows:
        row=_dict(raw)
        status=str(row.get("scored_status") or row.get("status") or "NO_MODEL").upper()
        score=int(row.get("confidence_score") or 0)
        edge=row.get("edge")
        ev=row.get("ev_per_dollar")
        verified=_verified_model_score(row)
        if status=="ACTIONABLE" and not verified:
            status="PASS"
            reasons=list(row.get("presentation_reason_codes") or ())
            if _UNVERIFIED_REASON not in reasons:
                reasons.append(_UNVERIFIED_REASON)
            row["presentation_reason_codes"]=tuple(reasons)
        if status=="ACTIONABLE" and ev is not None and float(ev) < MIN_CARD_EV:
            status="PASS"
            reasons=list(row.get("presentation_reason_codes") or ())
            if EV_FLOOR_REASON not in reasons:
                reasons.append(EV_FLOOR_REASON)
            row["presentation_reason_codes"]=tuple(reasons)
        row["confidence_score"]=max(0,min(100,score))
        row["confidence_provenance"]=str(row.get("confidence_provenance") or "UNVERIFIED").strip().upper()
        row["confidence_verified"]=verified
        row["scored_status"]=status
        row["edge_pct"]=None if edge is None else round(100*float(edge),2)
        row["ev_pct"]=None if ev is None else round(100*float(ev),2)
        row["star_rating"]=_star_rating(score=row["confidence_score"], status=status, verified=verified)
        out.append(row)
    _apply_empirical_side_conflicts(out)
    if actionable_only:
        out=[row for row in out if row["scored_status"]=="ACTIONABLE"]
    return sorted(out,key=lambda r:(_STATUS_ORDER.get(r["scored_status"],9),-r["confidence_score"],-(r["ev_per_dollar"] if r.get("ev_per_dollar") is not None else -999)))


def top_mlb_edges(rows: Sequence[Any], *, limit: int=10) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("LIMIT_MUST_BE_POSITIVE")
    return build_mlb_scored_card(rows,actionable_only=True)[:limit]
