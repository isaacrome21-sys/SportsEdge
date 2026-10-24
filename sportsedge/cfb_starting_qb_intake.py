"""Research-only intake for CFB starting-QB evidence.

Accepts pre-parsed dated rows from callers (manual, scrape, or future API).
Does not fetch the web, authenticate promotion, or emit PLAY.
Non-mapping rows are skipped. Every returned record has promotion_authority=False
and play_authority=False.
"""
from __future__ import annotations

from dataclasses import replace
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

    Non-mapping items are skipped. Expected keys (all optional except team + source):
      team, source, starter_name, starter_jersey, backup_name,
      opponent, game_id, season, week, source_url, observed_at, notes,
      illinois_college_team
    """
    out: list[StartingQBEvidence] = []
    for raw in rows or []:
        if not isinstance(raw, Mapping):
            continue
        observed = raw.get("observed_at") or default_observed_at
        record = score_starting_qb(
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
        )
        if record.promotion_authority or record.play_authority:
            record = replace(record, promotion_authority=False, play_authority=False)
        out.append(record)
    return out


def best_for_team(
    rows: Iterable[Mapping[str, Any]],
    team: str,
    *,
    default_observed_at: datetime | None = None,
) -> StartingQBEvidence | None:
    """Return the highest-confidence usable starter for one team."""
    scored = from_source_rows(rows, default_observed_at=default_observed_at)
    candidates = [r for r in scored if r.team.casefold() == str(team).casefold()]
    return merge_evidence(candidates)


__all__ = ["from_source_rows", "best_for_team"]
