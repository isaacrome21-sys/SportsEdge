"""Research-only manual intake for CFB starting-QB source rows.

Callers (or a future scheduled job) supply already-parsed dated rows.
This module does not fetch the web, does not authenticate sources, and does not
emit PLAY. It only normalizes and returns scored evidence for downstream binding.
Zero promotion_authority and play_authority are guaranteed on every returned record.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sportsedge.cfb_starting_qb_intake import from_source_rows
from sportsedge.cfb_starting_qb_evidence import StartingQBEvidence


def normalize_manual_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    default_observed_at: datetime | None = None,
    require_source_url_for_high: bool = True,
) -> list[StartingQBEvidence]:
    """Normalize caller-supplied rows into scored evidence.

    If require_source_url_for_high is True (default), any row that would score
    >= 0.70 without a source_url is downgraded to MODERATE before return.
    All records carry promotion_authority=False and play_authority=False.
    """
    scored = from_source_rows(rows, default_observed_at=default_observed_at)
    out: list[StartingQBEvidence] = []
    for row in scored:
        current = row
        if require_source_url_for_high and current.confidence >= 0.70 and not (current.source_url or "").strip():
            current = replace(
                current,
                confidence=0.55,
                confidence_label="MODERATE",
                notes=(current.notes + " [URL_REQUIRED_FOR_HIGH]").strip(),
            )
        # Force zero authority regardless of caller input
        if current.promotion_authority or current.play_authority:
            current = replace(current, promotion_authority=False, play_authority=False)
        out.append(current)
    return out


def example_rows_for_week(week: int, season: int = 2026) -> list[dict[str, Any]]:
    """Return a minimal example payload shape (not live data)."""
    return [
        {
            "team": "Alabama",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Example Starter",
            "source_url": "https://example.edu/athletics/depth-chart",
            "season": season,
            "week": week,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "notes": "example only",
        }
    ]


__all__ = ["normalize_manual_rows", "example_rows_for_week"]
