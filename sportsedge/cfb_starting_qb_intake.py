"""Research-only intake for CFB starting-QB evidence.

Accepts pre-parsed dated rows from callers (manual, scrape, or future API).
Does not fetch the web, authenticate promotion, or emit PLAY.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from sportsedge.cfb_starting_qb_evidence import (
    StartingQBEvidence,
    merge_evidence,
    score_starting_qb,
)


def from_source_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    default_observed_at: datetime | None = None,
) -> list[StartingQBEvidence]:
    """Convert a sequence of source dicts into scored evidence records.

    Expected keys (all optional except team + source):
      team, source, starter_name, starter_jersey, backup_name,
      opponent, game_id, season, week, source_url, observed_at, notes,
      illinois_college_team, content_verified
    """
    out: list[StartingQBEvidence] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        observed = raw.get("observed_at") or default_observed_at
        out.append(
            score_starting_qb(
                team=str(raw.get("team") or ""),
                source=str(raw.get("source") or "UNKNOWN"),
                starter_name=raw.get("starter_name"),
                starter_jersey=raw.get("starter_jersey"),
                backup_name=raw.get("backup_name"),
                opponent=raw.get("opponent"),
                game_id=raw.get("game_id"),
                season=raw.get("season"),
                week=raw.get("week"),
                source_url=raw.get("source_url"),
                observed_at=observed,
                notes=str(raw.get("notes") or ""),
                illinois_college_team=bool(raw.get("illinois_college_team")),
                content_verified=raw.get("content_verified") is True,
            )
        )
    return out


def best_for_team(
    rows: Iterable[Mapping[str, Any]],
    team: str,
    *,
    game_id: str | None = None,
    default_observed_at: datetime | None = None,
) -> StartingQBEvidence | None:
    """Best usable starter for one team, scoped to one game when given.

    Without game_id the rows must all refer to a single game, otherwise the
    merge fails closed rather than mixing fixtures.
    """
    scored = from_source_rows(rows, default_observed_at=default_observed_at)
    return merge_evidence(scored, team=team, game_id=game_id)


__all__ = ["from_source_rows", "best_for_team"]
