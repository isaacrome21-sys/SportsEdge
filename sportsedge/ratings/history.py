"""Verified game-history records feeding the rating foundation.

A ``GameRecord`` is the minimal verified unit: two identified teams, two
verified integer scores, and a kickoff clock. Anything missing fails
closed at construction.

Fetching is intentionally NOT part of this module: history arrives from
free public endpoints (ESPN scoreboard for NFL/CFB/NBA, MLB StatsAPI for
MLB) via ``scripts/refresh_ratings.py``, which writes the provider store.
This keeps the ``sportsedge.ratings`` package dependency-free and free of
network code, so the RUN IT path can import it without side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from . import params
from .elo import _clock, _key


class HistoryError(ValueError):
    """Fail-closed history errors."""


@dataclass(frozen=True)
class GameRecord:
    """One verified completed game."""
    kickoff: datetime
    home: str
    away: str
    home_score: int
    away_score: int
    season: str | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        if self.kickoff.tzinfo is None:
            object.__setattr__(
                self, "kickoff", self.kickoff.replace(tzinfo=timezone.utc))
        if not _key(self.home) or not _key(self.away):
            raise HistoryError("GAME_TEAM_IDENTITY_MISSING")
        if _key(self.home) == _key(self.away):
            raise HistoryError("GAME_TEAMS_IDENTICAL")
        for label, score in (("home", self.home_score), ("away", self.away_score)):
            if not isinstance(score, int) or isinstance(score, bool):
                raise HistoryError("GAME_SCORE_UNVERIFIED:" + label)
            if score < 0:
                raise HistoryError("GAME_SCORE_NEGATIVE:" + label)


def season_label(sport: str, kickoff: datetime) -> str:
    """Campaign label for a kickoff (e.g. NFL Sep 2024 -> "2024").

    Boundaries are declared in ``params.SEASON_START_MONTH``: a game on or
    after the start month belongs to that calendar year's season.
    """
    sport = str(sport or "").upper().strip()
    if sport not in params.SPORTS:
        raise HistoryError("RATINGS_SPORT_UNSUPPORTED:" + sport)
    start_month = params.SEASON_START_MONTH[sport]
    when = kickoff.astimezone(timezone.utc)
    year = when.year
    return str(year if when.month >= start_month else year - 1)


def from_tuples(rows: Iterable[Mapping[str, Any]]) -> list[GameRecord]:
    """Build GameRecords from dict rows (the refresh script's format).

    Row keys: ``kickoff`` (ISO), ``home``, ``away``, ``home_score``,
    ``away_score``, optional ``season`` and ``event_id``.
    """
    records = []
    for row in rows:
        records.append(GameRecord(
            kickoff=_clock(row["kickoff"], "KICKOFF"),
            home=str(row["home"]), away=str(row["away"]),
            home_score=int(row["home_score"]),
            away_score=int(row["away_score"]),
            season=str(row["season"]) if row.get("season") else None,
            event_id=str(row["event_id"]) if row.get("event_id") else None,
        ))
    return records
