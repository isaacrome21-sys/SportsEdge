"""Fail-closed NFL research-card publishing contract.

This module sits downstream of SportsEdge model outputs. It does not rerun a
model, create Model_P, devig a market, or grant betting authority. Its job is
to prevent a research card from being published when the forecast, price, team
binding, economics, or source provenance is not current enough to support the
display.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.prop_edge_surface import (
    american_implied_probability,
    build_props_edge_board,
    settled_model_probability,
)


NFL_RESEARCH_CARD_SCHEMA = "NFL_RESEARCH_CARD_V1"
AUTHORITY_LABEL = "EXPERIMENTAL / NOT OFFICIAL"
SPLITS_SOURCE = "ScoresAndOdds"
_EPSILON = 1e-9


class NFLResearchCardError(ValueError):
    """Raised when an NFL research card would be misleading to publish."""


def _finite(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLResearchCardError(code) from exc
    if not isfinite(out):
        raise NFLResearchCardError(code)
    return out


def _parse_timestamp(value: Any, code: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise NFLResearchCardError(code)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            out = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise NFLResearchCardError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLResearchCardError(code)
    return out.astimezone(timezone.utc)


def validate_forecast_provenance(
    forecast_provenance: Mapping[str, Any],
    *,
    current_input_fingerprint: str,
    current_input_as_of: str | datetime | None = None,
) -> dict[str, Any]:
    """Prove that the displayed forecast was recomputed from current inputs.

    A card cannot paper over an injury/role change by relabeling an old score
    forecast. The forecast's input fingerprint must exactly match the current
    input fingerprint, and its generation time must not predate the current
    input snapshot when that timestamp is supplied.
    """
    if not isinstance(forecast_provenance, Mapping):
        raise NFLResearchCardError("NFL_CARD_FORECAST_PROVENANCE_REQUIRED")
    forecast_fingerprint = str(
        forecast_provenance.get("input_fingerprint") or ""
    ).strip()
    current_fingerprint = str(current_input_fingerprint or "").strip()
    if not forecast_fingerprint or not current_fingerprint:
        raise NFLResearchCardError("NFL_CARD_RECOMPUTE_OR_BLOCK:FINGERPRINT_REQUIRED")
    if forecast_fingerprint != current_fingerprint:
        raise NFLResearchCardError("NFL_CARD_RECOMPUTE_OR_BLOCK:FINGERPRINT_MISMATCH")

    generated_at = _parse_timestamp(
        forecast_provenance.get("generated_at"),
        "NFL_CARD_FORECAST_GENERATED_AT_REQUIRED",
    )
    if current_input_as_of is not None:
        inputs_at = _parse_timestamp(
            current_input_as_of,
            "NFL_CARD_CURRENT_INPUT_AS_OF_INVALID",
        )
        if generated_at < inputs_at:
            raise NFLResearchCardError("NFL_CARD_RECOMPUTE_OR_BLOCK:FORECAST_PREDATES_INPUTS")

    out = dict(forecast_provenance)
    out["input_fingerprint"] = forecast_fingerprint
    out["generated_at"] = generated_at.isoformat()
    out["validated_against_current_inputs"] = True
    out["publishable_as_current"] = True
    return out


def normalize_splits_context(context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Attach explicit ScoresAndOdds provenance to the display-only splits box."""
    if context is None:
        return None
    if not isinstance(context, Mapping):
        raise NFLResearchCardError("NFL_CARD_SPLITS_CONTEXT_INVALID")
    supplied_source = str(context.get("source") or "").strip()
    if supplied_source and supplied_source.casefold() != SPLITS_SOURCE.casefold():
        raise NFLResearchCardError("NFL_CARD_SPLITS_SOURCE_MISMATCH")
    out = dict(context)
    out["source"] = SPLITS_SOURCE
    out["promotion_authority"] = False
    out["used_in_model_probability"] = False
    out["used_in_score"] = False
    return out


def _quote_timestamp(row: Mapping[str, Any]) -> datetime:
    for key in ("quote_timestamp", "price_timestamp", "quote_as_of"):
        if row.get(key) is not None:
            return _parse_timestamp(row.get(key), "NFL_CARD_QUOTE_TIMESTAMP_INVALID")
    raise NFLResearchCardError("NFL_CARD_QUOTE_TIMESTAMP_REQUIRED")


def _model_probability(row: Mapping[str, Any]) -> float | None:
    value = row.get("model_probability")
    if value is not None:
        p = _finite(value, "NFL_CARD_MODEL_PROBABILITY_INVALID")
        if not 0.0 <= p <= 1.0:
            raise NFLResearchCardError("NFL_CARD_MODEL_PROBABILITY_INVALID")
        return p
    model_p = row.get("model_p")
    if model_p is None:
        return None
    push_p = row.get("push_p", 0.0)
    try:
        return settled_model_probability(float(model_p), float(push_p or 0.0))
    except (TypeError, ValueError) as exc:
        raise NFLResearchCardError("NFL_CARD_MODEL_PROBABILITY_INVALID") from exc


def _book_odds(row: Mapping[str, Any]) -> float | None:
    value = row.get("book_american")
    if value is None:
        value = row.get("american_odds")
    if value is None:
        return None
    return _finite(value, "NFL_CARD_AMERICAN_ODDS_INVALID")


def _qualification_score(row: Mapping[str, Any]) -> float | None:
    """Expose only an upstream qualification-only score.

    The downstream card never derives Score from EV or edge. If the approved
    qualification score is absent, the card leaves Score blank rather than
    substituting an economics-based ranking.
    """
    value = row.get("qualification_score")
    if value is None:
        return None
    score = _finite(value, "NFL_CARD_QUALIFICATION_SCORE_INVALID")
    if not 0.0 <= score <= 100.0:
        raise NFLResearchCardError("NFL_CARD_QUALIFICATION_SCORE_INVALID")
    return round(score, 1)


def _offer_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "game_id": row.get("game_id"),
        "market": row.get("provider_market") or row.get("market"),
        "player_id": row.get("player_id"),
        "player_name": row.get("player_name"),
        "side": row.get("side"),
        "line": row.get("line"),
        "bookmaker": row.get("bookmaker") or row.get("sportsbook"),
    }


def _bind_display_team(
    row: Mapping[str, Any],
    roster_team_by_player_id: Mapping[str, str] | None,
) -> tuple[str | None, bool]:
    player_id = str(row.get("player_id") or "").strip()
    player_name = str(row.get("player_name") or "").strip()
    raw_team = str(row.get("team") or row.get("team_abbr") or "").strip().upper()
    if not player_id and not player_name:
        return (raw_team or None, bool(raw_team))
    if not player_id or roster_team_by_player_id is None:
        return None, False

    bound = str(roster_team_by_player_id.get(player_id) or "").strip().upper()
    if not bound:
        return None, False
    if raw_team and raw_team != bound:
        raise NFLResearchCardError(
            f"NFL_CARD_PLAYER_TEAM_BINDING_MISMATCH:{player_id}:{raw_team}:{bound}"
        )
    return bound, True


def _strip_pick_framing(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in (
        "crown",
        "is_crowned",
        "pick",
        "top_pick",
        "best_bet",
        "featured_label",
    ):
        out.pop(key, None)
    # Never recycle the old economics-weighted research score on a publish card.
    out["score"] = _qualification_score(row)
    out["grade"] = None
    out["authority_label"] = AUTHORITY_LABEL
    out["official"] = False
    out["crown_allowed"] = False
    out["display_label"] = "RESEARCH EDGE"
    return out


def _screen_offer(
    row: Mapping[str, Any],
    *,
    as_of: datetime,
    max_quote_age_seconds: float,
    min_ev: float,
    min_probability_edge: float,
    roster_team_by_player_id: Mapping[str, str] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    identity = _offer_identity(row)
    reasons: list[str] = []

    p = _model_probability(row)
    odds = _book_odds(row)
    ev_raw = row.get("ev_per_dollar")
    ev = None if ev_raw is None else _finite(ev_raw, "NFL_CARD_EV_INVALID")

    if p is None:
        reasons.append("MODEL_PROBABILITY_MISSING")
    if odds is None:
        reasons.append("BOOK_PRICE_MISSING")
    if ev is None:
        reasons.append("EV_MISSING")

    implied = None if odds is None else american_implied_probability(odds)
    if ev is not None and ev <= max(0.0, min_ev) + _EPSILON:
        reasons.append("NON_POSITIVE_EV")
    if p is not None and implied is not None:
        if p <= implied + max(0.0, min_probability_edge) + _EPSILON:
            reasons.append("NO_BREAK_EVEN_EDGE")

    quote_at: datetime | None = None
    try:
        quote_at = _quote_timestamp(row)
    except NFLResearchCardError as exc:
        reasons.append(str(exc))
    if quote_at is not None:
        age = (as_of - quote_at).total_seconds()
        if age < -60.0:
            reasons.append("QUOTE_TIMESTAMP_IN_FUTURE")
        elif age > max_quote_age_seconds:
            reasons.append("STALE_QUOTE")
    if row.get("quote_fresh") is False:
        reasons.append("STALE_QUOTE")

    if reasons:
        return None, {
            **identity,
            "reasons": sorted(set(reasons)),
            "model_probability": p,
            "book_implied_probability": implied,
            "ev_per_dollar": ev,
            "quote_timestamp": None if quote_at is None else quote_at.isoformat(),
        }

    display_team, team_verified = _bind_display_team(row, roster_team_by_player_id)
    out = _strip_pick_framing(row)
    out.update(
        {
            "model_probability": p,
            "book_american": odds,
            "book_implied_probability": implied,
            "ev_per_dollar": ev,
            "quote_timestamp": quote_at.isoformat(),
            "display_team": display_team,
            "team_binding_verified": team_verified,
        }
    )
    return out, None


def _screen_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    max_quote_age_seconds: float,
    min_ev: float,
    min_probability_edge: float,
    roster_team_by_player_id: Mapping[str, str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise NFLResearchCardError("NFL_CARD_ROW_INVALID")
        good, blocked = _screen_offer(
            row,
            as_of=as_of,
            max_quote_age_seconds=max_quote_age_seconds,
            min_ev=min_ev,
            min_probability_edge=min_probability_edge,
            roster_team_by_player_id=roster_team_by_player_id,
        )
        if good is not None:
            kept.append(good)
        elif blocked is not None:
            excluded.append(blocked)
    kept.sort(
        key=lambda row: (
            float(row.get("ev_per_dollar") or float("-inf")),
            float(row.get("model_probability") or float("-inf")),
        ),
        reverse=True,
    )
    return kept, excluded


def build_nfl_research_card(
    *,
    game_market_rows: Sequence[Mapping[str, Any]] = (),
    prop_run_payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    forecast_provenance: Mapping[str, Any],
    current_input_fingerprint: str,
    current_input_as_of: str | datetime | None,
    as_of: str | datetime,
    max_quote_age_seconds: float = 900.0,
    min_ev: float = 0.0,
    min_probability_edge: float = 0.0,
    roster_team_by_player_id: Mapping[str, str] | None = None,
    splits_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only publishable NFL research-card payload from current inputs.

    The function deliberately has no crown/top-pick mode. It fails the whole
    card when forecast provenance is stale, then excludes any individual offer
    without a fresh quote, positive EV, and model probability above break-even.
    """
    card_as_of = _parse_timestamp(as_of, "NFL_CARD_AS_OF_INVALID")
    max_age = _finite(max_quote_age_seconds, "NFL_CARD_MAX_QUOTE_AGE_INVALID")
    if max_age <= 0.0:
        raise NFLResearchCardError("NFL_CARD_MAX_QUOTE_AGE_INVALID")

    forecast = validate_forecast_provenance(
        forecast_provenance,
        current_input_fingerprint=current_input_fingerprint,
        current_input_as_of=current_input_as_of,
    )

    game_rows, game_excluded = _screen_rows(
        list(game_market_rows),
        as_of=card_as_of,
        max_quote_age_seconds=max_age,
        min_ev=min_ev,
        min_probability_edge=min_probability_edge,
        roster_team_by_player_id=None,
    )

    prop_candidates: list[Mapping[str, Any]] = []
    if prop_run_payload is not None:
        prop_board = build_props_edge_board(
            prop_run_payload,
            view="all_priced",
            sort_by="ev",
        )
        prop_candidates = list(prop_board.get("rows") or [])
    prop_rows, prop_excluded = _screen_rows(
        prop_candidates,
        as_of=card_as_of,
        max_quote_age_seconds=max_age,
        min_ev=min_ev,
        min_probability_edge=min_probability_edge,
        roster_team_by_player_id=roster_team_by_player_id,
    )

    return {
        "schema_version": NFL_RESEARCH_CARD_SCHEMA,
        "sport": "NFL",
        "authority_label": AUTHORITY_LABEL,
        "official": False,
        "publish_state": "EXPERIMENTAL",
        "as_of": card_as_of.isoformat(),
        "forecast": forecast,
        "game_markets": {
            "research_edges": game_rows,
            "excluded": game_excluded,
        },
        "props": {
            "research_edges": prop_rows,
            "excluded": prop_excluded,
        },
        "splits": normalize_splits_context(splits_context),
        "governance": {
            "crown_allowed": False,
            "pick_language_allowed": False,
            "score_policy": "UPSTREAM_QUALIFICATION_ONLY",
            "score_uses_ev": False,
            "score_uses_edge": False,
            "stale_forecast_publish_allowed": False,
            "stale_quote_publish_allowed": False,
            "non_positive_ev_publish_allowed": False,
            "player_logo_requires_verified_team_binding": True,
            "splits_source": SPLITS_SOURCE,
        },
    }
