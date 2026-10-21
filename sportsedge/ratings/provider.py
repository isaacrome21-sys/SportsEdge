"""Canonical team-strength interface: ``get_team_strength(team, as_of)``.

This is the single entry point the pricing modules use. It returns the
neutral-site team strength (in points above league average) derived from
the opponent-adjusted Elo rating, which feeds the score means built by
``sportsedge.ratings.layers.build_means``.

Fail-closed rules:
* Unknown team (no verified game history) -> ``RatingError`` UNRATED_TEAM.
  Pricing must BLOCK, never silently price at a 1500-average rating.
* Provider not configured (no history loaded) -> ``RatingError``
  PROVIDER_UNCONFIGURED.
* ``as_of`` at or before a team's first recorded game -> strength 0.0 with
  ``games_n = 0`` and ``rated=False`` (explicit, auditable).

History loading: a provider is built from verified completed games
(free sources only: ESPN scoreboard, MLB StatsAPI) via ``build_provider``,
or from a persisted JSON store via ``RatingProvider.load``. The store is
refreshed by an offline job (``scripts/refresh_ratings.py``); the RUN IT
path only reads the store, never fetches history itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from . import params
from .elo import EloTracker, EloError, _clock, _key
from .history import GameRecord, season_label


class RatingError(ValueError):
    """Fail-closed team-strength errors; pricing must block on these."""


@dataclass(frozen=True)
class TeamStrength:
    """Neutral-site team strength at a point in time (no-lookahead)."""
    sport: str
    team: str                       # canonical team key
    as_of: str                      # ISO clock the strength is valid at
    rating: float                   # Elo rating (1500 = average)
    rating_games: int               # games reflected in the rating
    strength_points: float          # (rating - 1500) / elo_per_point
    rated: bool                     # False when no history exists at as_of
    elo_per_point: float
    rating_source: str = "sportsedge.ratings EloTracker"

    def audit_row(self) -> dict[str, Any]:
        return {
            "sport": self.sport, "team": self.team, "as_of": self.as_of,
            "rating": round(self.rating, 2), "rating_games": self.rating_games,
            "strength_points": round(self.strength_points, 3),
            "rated": self.rated, "elo_per_point": self.elo_per_point,
            "source": self.rating_source,
        }


class RatingProvider:
    """Per-sport Elo ratings with the canonical strength interface."""

    def __init__(self, sport: str, tracker: Optional[EloTracker] = None):
        self.sport = str(sport or "").upper().strip()
        if self.sport not in params.SPORTS:
            raise RatingError("RATINGS_SPORT_UNSUPPORTED:" + self.sport)
        self._tracker = tracker or EloTracker(self.sport)

    # -- canonical interface -----------------------------------------

    def get_team_strength(self, team: str, as_of: Any) -> TeamStrength:
        """Return the neutral-site strength of ``team`` valid at ``as_of``.

        The rating reflects only games with kickoff strictly before
        ``as_of`` (no-lookahead). Raises ``RatingError`` for unknown teams
        so callers block instead of silently pricing an average team.
        """
        key = _key(team)
        if not key:
            raise RatingError("UNRATED_TEAM:identity missing")
        when = _clock(as_of, "AS_OF")
        rating, games = self._tracker.rating_at(key, when)
        if games == 0:
            raise RatingError(f"UNRATED_TEAM:{self.sport}:{team}")
        elo_per_point = params.get(self.sport, "elo_per_point")
        return TeamStrength(
            sport=self.sport, team=key,
            as_of=when.astimezone(timezone.utc).isoformat(),
            rating=rating, rating_games=games,
            strength_points=(rating - params.get(self.sport, "init")) / elo_per_point,
            rated=True, elo_per_point=elo_per_point,
        )

    def strength_or_zero(self, team: str, as_of: Any) -> TeamStrength:
        """Non-strict variant: unrated teams yield 0.0 strength, flagged.

        For research comparisons only. Production pricing must use the
        strict ``get_team_strength`` and block on ``RatingError``.
        """
        try:
            return self.get_team_strength(team, as_of)
        except RatingError:
            when = _clock(as_of, "AS_OF").astimezone(timezone.utc).isoformat()
            return TeamStrength(
                sport=self.sport, team=_key(team), as_of=when,
                rating=params.get(self.sport, "init"), rating_games=0,
                strength_points=0.0, rated=False,
                elo_per_point=params.get(self.sport, "elo_per_point"),
                rating_source="sportsedge.ratings EloTracker (UNRATED: strength=0)",
            )

    # -- history ingestion --------------------------------------------

    def record_games(self, games: Iterable[GameRecord]) -> int:
        """Record verified completed games in chronological order.

        ``games`` must be sorted by kickoff ascending; out-of-order input
        raises (no silent lookahead). Returns games recorded.
        """
        ordered = sorted(games, key=lambda g: g.kickoff)
        n = 0
        for game in ordered:
            season = game.season or season_label(self.sport, game.kickoff)
            self._tracker.record_game(
                date=game.kickoff, home=game.home, away=game.away,
                home_score=game.home_score, away_score=game.away_score,
                season=season)
            n += 1
        return n

    @property
    def tracker(self) -> EloTracker:
        return self._tracker

    # -- persistence ----------------------------------------------------

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "built_at": datetime.now(timezone.utc).isoformat(),
                   "tracker": self._tracker.to_dict()}
        path.write_text(json.dumps(payload, indent=1))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "RatingProvider":
        path = Path(path)
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise RatingError("RATINGS_STORE_UNREADABLE:" + str(path)) from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise RatingError("RATINGS_STORE_VERSION_INVALID:" + str(path))
        try:
            tracker = EloTracker.from_dict(payload.get("tracker") or {})
        except EloError as exc:
            raise RatingError("RATINGS_STORE_INVALID:" + str(path) + ":" + str(exc)) from exc
        return cls(tracker.sport, tracker)


def build_provider(sport: str, games: Iterable[GameRecord]) -> RatingProvider:
    """Build a provider from verified completed games (chronological)."""
    provider = RatingProvider(sport)
    provider.record_games(games)
    return provider


#: Module-level configured providers (populated by ``configure``).
_PROVIDERS: dict[str, RatingProvider] = {}


def configure(sport: str, provider: RatingProvider) -> None:
    """Bind a provider for a sport (called once at runner startup)."""
    sport = str(sport or "").upper().strip()
    if sport not in params.SPORTS:
        raise RatingError("RATINGS_SPORT_UNSUPPORTED:" + sport)
    if not isinstance(provider, RatingProvider) or provider.sport != sport:
        raise RatingError("RATINGS_PROVIDER_MISMATCH")
    _PROVIDERS[sport] = provider


def configured(sport: str) -> bool:
    return str(sport or "").upper().strip() in _PROVIDERS


def get_team_strength(team: str, as_of: Any, sport: str) -> TeamStrength:
    """Module-level canonical interface.

    Raises ``RatingError`` when no provider is configured for the sport
    (fail closed: pricing must not invent strengths).
    """
    sport = str(sport or "").upper().strip()
    provider = _PROVIDERS.get(sport)
    if provider is None:
        raise RatingError("PROVIDER_UNCONFIGURED:" + sport)
    return provider.get_team_strength(team, as_of)


def clear_configuration() -> None:
    """Test/utility hook: unbind all providers."""
    _PROVIDERS.clear()
