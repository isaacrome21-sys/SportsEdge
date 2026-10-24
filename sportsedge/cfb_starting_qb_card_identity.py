"""Research-only helper that attaches starting-QB evidence to a CFB spread card payload.

Does not emit PLAY, authenticate promotion, or override any existing gate.
Callers pass the raw card dict and dated source rows; this returns a new dict
with an added `starting_qb_identity` key.
"""
from __future__ import annotations

from typing import Any, Mapping

from sportsedge.cfb_starting_qb_spread_binding import bind_starting_qbs_to_spread


def attach_starting_qb_identity(
    card: Mapping[str, Any],
    source_rows: list[Mapping[str, Any]],
    *,
    assess_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a shallow copy of card with starting_qb_identity attached.

    Research-only. The assessment result is included for inspection but never
    promotes the card to PLAY.
    """
    home = str(card.get("home_team") or card.get("home") or "")
    away = str(card.get("away_team") or card.get("away") or "")
    game_id = card.get("game_id") or card.get("id")
    season = card.get("season")
    week = card.get("week")

    bound = bind_starting_qbs_to_spread(
        source_rows=source_rows,
        home_team=home,
        away_team=away,
        game_id=str(game_id) if game_id is not None else None,
        season=int(season) if season is not None else None,
        week=int(week) if week is not None else None,
        assess_kwargs=assess_kwargs,
    )

    identity = {
        "schema_version": "SPORTSEDGE_CFB_STARTING_QB_CARD_IDENTITY_V1",
        "home_qb": None if bound.home_qb is None else {
            "name": bound.home_qb.starter_name,
            "confidence": bound.home_qb.confidence,
            "label": bound.home_qb.confidence_label,
            "source": bound.home_qb.source,
            "source_url": bound.home_qb.source_url,
            "notes": bound.home_qb.notes,
        },
        "away_qb": None if bound.away_qb is None else {
            "name": bound.away_qb.starter_name,
            "confidence": bound.away_qb.confidence,
            "label": bound.away_qb.confidence_label,
            "source": bound.away_qb.source,
            "source_url": bound.away_qb.source_url,
            "notes": bound.away_qb.notes,
        },
        "matchup_identity_confidence": bound.matchup_identity_confidence,
        "matchup_identity_label": bound.matchup_identity_label,
        "binding_notes": bound.binding_notes,
        "play_authority": False,
        "promotion_authority": False,
        "assessment_status": bound.assessment.status,
        "assessment_reason": bound.assessment.reason,
    }

    out = dict(card)
    out["starting_qb_identity"] = identity
    return out


__all__ = ["attach_starting_qb_identity"]
