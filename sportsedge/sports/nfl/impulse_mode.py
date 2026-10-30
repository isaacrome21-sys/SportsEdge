"""User-directed NFL impulse lane over SportsEdge model probabilities.

This module intentionally ignores OFFICIAL / Truth-Gate eligibility when deciding
which rows to *show* as impulse plays.  It does not mutate governance state,
relabel rows as OFFICIAL, or manufacture a model probability.  The user's
specified decision source is the existing SportsEdge model probability plus the
actual offered price.

Same-game parlays are never priced by multiplying leg probabilities.  A joint
probability must come from a same-path / correlation-aware model output before
promo EV is computed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.sports.nfl.prop_edge_surface import (
    NFLPropsEdgeError,
    american_implied_probability,
    build_props_edge_board,
)


NFL_IMPULSE_SCHEMA = "NFL_IMPULSE_V1"
_EPSILON = 1e-12


@dataclass(frozen=True)
class ProfitBoostTerms:
    """Terms needed to evaluate a sportsbook profit boost."""

    boost_rate: float = 0.50
    max_wager: float = 25.0
    min_legs: int = 3
    min_total_american_odds: int = -200
    sgp_only: bool = True
    eligible_game: str | None = None


def _finite(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLPropsEdgeError(error) from exc
    if not isfinite(out):
        raise NFLPropsEdgeError(error)
    return out


def _probability(value: Any, error: str) -> float:
    out = _finite(value, error)
    if not 0.0 <= out <= 1.0:
        raise NFLPropsEdgeError(error)
    return out


def american_profit_per_dollar(american_odds: float | int) -> float:
    """Return sportsbook profit, excluding returned stake, per $1 risked."""
    odds = _finite(american_odds, "NFL_IMPULSE_AMERICAN_ODDS_INVALID")
    if abs(odds) < 100.0:
        raise NFLPropsEdgeError("NFL_IMPULSE_AMERICAN_ODDS_INVALID")
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)


def profit_multiple_to_american(profit_multiple: float) -> int:
    """Convert profit-per-dollar to an equivalent American price."""
    profit = _finite(profit_multiple, "NFL_IMPULSE_PROFIT_MULTIPLE_INVALID")
    if profit <= 0.0:
        raise NFLPropsEdgeError("NFL_IMPULSE_PROFIT_MULTIPLE_INVALID")
    if profit >= 1.0:
        return int(round(100.0 * profit))
    return int(round(-100.0 / profit))


def offered_ev_per_dollar(model_probability: float, american_odds: float | int) -> float:
    """Compute offered-price EV directly from model probability and book price."""
    p = _probability(model_probability, "NFL_IMPULSE_MODEL_PROBABILITY_INVALID")
    profit = american_profit_per_dollar(american_odds)
    return p * profit - (1.0 - p)


def impulse_grade(model_probability: float, ev_per_dollar: float) -> str:
    """Simple user-facing impulse label; no governance authority is implied."""
    p = _probability(model_probability, "NFL_IMPULSE_MODEL_PROBABILITY_INVALID")
    ev = _finite(ev_per_dollar, "NFL_IMPULSE_EV_INVALID")
    if ev >= 0.20 and p >= 0.60:
        return "SMASH"
    if ev >= 0.10 and p >= 0.56:
        return "STRONG"
    if ev > 0.0:
        return "PLAY"
    return "PASS"


def _row_team_match(row: Mapping[str, Any], teams: set[str]) -> bool:
    if not teams:
        return True
    row_teams = {
        str(row.get(key) or "").strip().upper()
        for key in ("team", "team_abbr", "home_team", "away_team")
        if str(row.get(key) or "").strip()
    }
    return bool(row_teams & teams)


def build_impulse_board(
    run_payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    teams: Iterable[str] | None = None,
    market: str | None = None,
    min_model_probability: float = 0.0,
    min_ev: float = 0.0,
    include_negative_ev: bool = False,
    include_stale: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build an impulse card using model probability + actual offered price.

    OFFICIAL eligibility, Truth-Gate state, promotion evidence and staking
    authority are deliberately not selection filters in this view.  Their
    original fields remain untouched for auditability.
    """
    min_p = _probability(
        min_model_probability, "NFL_IMPULSE_MIN_MODEL_PROBABILITY_INVALID"
    )
    threshold_ev = _finite(min_ev, "NFL_IMPULSE_MIN_EV_INVALID")
    team_filter = {
        str(team).strip().upper() for team in (teams or ()) if str(team).strip()
    }

    base = build_props_edge_board(
        run_payload,
        view="all_projections",
        market=market,
        teams=team_filter,
        sort_by="model_probability",
    )

    rows: list[dict[str, Any]] = []
    for raw in base["rows"]:
        if not _row_team_match(raw, team_filter):
            continue
        p = raw.get("model_probability")
        odds = raw.get("book_american")
        if p is None or odds is None:
            continue
        if not bool(raw.get("quote_fresh", True)) and not include_stale:
            continue

        probability = _probability(p, "NFL_IMPULSE_MODEL_PROBABILITY_INVALID")
        if probability < min_p:
            continue
        ev = offered_ev_per_dollar(probability, odds)
        if not include_negative_ev and ev < threshold_ev:
            continue

        row = dict(raw)
        row.update(
            {
                "impulse_mode": True,
                "impulse_source": "MODEL_PROBABILITY_PLUS_OFFERED_PRICE",
                "impulse_break_even_probability": american_implied_probability(odds),
                "impulse_offered_ev_per_dollar": ev,
                "impulse_offered_ev_pct": round(ev * 100.0, 1),
                "impulse_grade": impulse_grade(probability, ev),
                "impulse_play": ev >= threshold_ev,
                "official_eligibility_ignored_for_impulse_selection": True,
                "truth_gate_ignored_for_impulse_selection": True,
                "official_status_unchanged": True,
            }
        )
        rows.append(row)

    rows.sort(
        key=lambda row: (
            float(row["impulse_offered_ev_per_dollar"]),
            float(row["model_probability"]),
        ),
        reverse=True,
    )
    if limit is not None:
        if isinstance(limit, bool) or int(limit) < 0:
            raise NFLPropsEdgeError("NFL_IMPULSE_LIMIT_INVALID")
        rows = rows[: int(limit)]

    return {
        "schema_version": NFL_IMPULSE_SCHEMA,
        "sport": "NFL",
        "mode": "IMPULSE",
        "rows": rows,
        "summary": {
            "play_rows": len(rows),
            "best_ev": max(
                (float(row["impulse_offered_ev_per_dollar"]) for row in rows),
                default=None,
            ),
            "top_model_probability": max(
                (float(row["model_probability"]) for row in rows), default=None
            ),
        },
        "authority": {
            "selection_source": "MODEL_PROBABILITY_PLUS_OFFERED_PRICE",
            "requires_official_p": False,
            "requires_truth_gate": False,
            "mutates_official_eligibility": False,
            "mutates_truth_gate": False,
            "staking_authority": False,
        },
    }


def evaluate_profit_boost_sgp(
    *,
    joint_model_probability: float | None,
    sgp_american_odds: float | int,
    leg_count: int,
    wager: float,
    terms: ProfitBoostTerms | None = None,
    same_game: bool = True,
    game_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate a profit-boost SGP from a correlation-aware joint probability."""
    promo = terms or ProfitBoostTerms()
    odds = _finite(sgp_american_odds, "NFL_IMPULSE_SGP_ODDS_INVALID")
    if abs(odds) < 100.0:
        raise NFLPropsEdgeError("NFL_IMPULSE_SGP_ODDS_INVALID")
    if isinstance(leg_count, bool) or int(leg_count) < 1:
        raise NFLPropsEdgeError("NFL_IMPULSE_SGP_LEG_COUNT_INVALID")
    risk = _finite(wager, "NFL_IMPULSE_WAGER_INVALID")
    if risk < 0.0:
        raise NFLPropsEdgeError("NFL_IMPULSE_WAGER_INVALID")

    eligibility_reasons: list[str] = []
    if int(leg_count) < int(promo.min_legs):
        eligibility_reasons.append("MIN_LEGS_NOT_MET")
    # "-200 or longer" means -200, -190, ..., +100, +200, etc.
    if odds < float(promo.min_total_american_odds):
        eligibility_reasons.append("MIN_TOTAL_ODDS_NOT_MET")
    if promo.sgp_only and not same_game:
        eligibility_reasons.append("SGP_REQUIRED")
    if promo.eligible_game is not None and game_id is not None:
        if str(game_id).strip().upper() != str(promo.eligible_game).strip().upper():
            eligibility_reasons.append("WRONG_GAME")

    applied_wager = min(risk, float(promo.max_wager))
    base_profit = american_profit_per_dollar(odds)
    boosted_profit = base_profit * (1.0 + float(promo.boost_rate))
    boosted_break_even = 1.0 / (1.0 + boosted_profit)
    boosted_american = profit_multiple_to_american(boosted_profit)

    if joint_model_probability is None:
        joint_p = None
        boosted_ev = None
        status = "JOINT_MODEL_P_REQUIRED"
    else:
        joint_p = _probability(
            joint_model_probability, "NFL_IMPULSE_JOINT_MODEL_PROBABILITY_INVALID"
        )
        boosted_ev = joint_p * boosted_profit - (1.0 - joint_p)
        status = "PLAY" if boosted_ev > 0.0 and not eligibility_reasons else "PASS"

    return {
        "schema_version": NFL_IMPULSE_SCHEMA,
        "mode": "IMPULSE_PROMO_SGP",
        "eligible": not eligibility_reasons,
        "eligibility_reasons": eligibility_reasons,
        "leg_count": int(leg_count),
        "same_game": bool(same_game),
        "game_id": game_id,
        "book_american_odds": odds,
        "joint_model_probability": joint_p,
        "base_profit_per_dollar": base_profit,
        "boost_rate": float(promo.boost_rate),
        "boosted_profit_per_dollar": boosted_profit,
        "boosted_effective_american": boosted_american,
        "boosted_break_even_probability": boosted_break_even,
        "boosted_ev_per_dollar": boosted_ev,
        "boosted_ev_pct": None if boosted_ev is None else round(boosted_ev * 100.0, 1),
        "requested_wager": risk,
        "applied_wager": applied_wager,
        "max_wager": float(promo.max_wager),
        "expected_profit_dollars": None
        if boosted_ev is None
        else boosted_ev * applied_wager,
        "status": status,
        "terms": asdict(promo),
        "correlation_rule": "JOINT_MODEL_P_REQUIRED_DO_NOT_MULTIPLY_LEG_PROBABILITIES",
        "official_status_unchanged": True,
        "truth_gate_used": False,
    }


def rank_profit_boost_sgps(
    candidates: Sequence[Mapping[str, Any]],
    *,
    wager: float = 25.0,
    terms: ProfitBoostTerms | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank candidate SGPs by boosted EV without assuming leg independence."""
    promo = terms or ProfitBoostTerms()
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        result = evaluate_profit_boost_sgp(
            joint_model_probability=candidate.get("joint_model_probability"),
            sgp_american_odds=candidate.get("american_odds"),
            leg_count=int(candidate.get("leg_count") or len(candidate.get("legs") or ())),
            wager=wager,
            terms=promo,
            same_game=bool(candidate.get("same_game", True)),
            game_id=candidate.get("game_id"),
        )
        result["candidate_id"] = candidate.get("candidate_id")
        result["legs"] = list(candidate.get("legs") or ())
        ranked.append(result)

    ranked.sort(
        key=lambda row: (
            row.get("boosted_ev_per_dollar") is not None,
            float(row.get("boosted_ev_per_dollar") or float("-inf")),
        ),
        reverse=True,
    )
    if isinstance(limit, bool) or int(limit) < 0:
        raise NFLPropsEdgeError("NFL_IMPULSE_LIMIT_INVALID")
    return ranked[: int(limit)]
