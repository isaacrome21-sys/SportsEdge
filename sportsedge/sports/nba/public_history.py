from __future__ import annotations

"""Materialize NBA training rows from timestamped public box-score history.

This adapter is source-agnostic but intended for public repositories such as
sportsdataverse/hoopR-nba-data. It only uses a prior game for a target game's
features when that prior game's public observation timestamp is strictly before
the target tipoff. Season files reconstructed later therefore cannot silently
backfill historical knowledge.

Research/training plumbing only. This module creates no Model_P, Truth Gate,
promotion, staking, or OFFICIAL authority.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import fmean
from typing import Iterable

from .training import NBATrainingRow


@dataclass(frozen=True)
class PublicNBABoxGame:
    game_id: str
    tipoff: datetime
    observed_at: datetime
    home_team_id: str
    away_team_id: str
    home_points: int
    away_points: int
    home_fga: float
    home_fta: float
    home_orb: float
    home_turnovers: float
    away_fga: float
    away_fta: float
    away_orb: float
    away_turnovers: float
    source_uri: str
    source_version: str

    def validate(self) -> None:
        if not all((self.game_id, self.home_team_id, self.away_team_id, self.source_uri, self.source_version)):
            raise ValueError("game identity and public-source provenance are required")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home and away teams must differ")
        for name, value in (("tipoff", self.tipoff), ("observed_at", self.observed_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.observed_at <= self.tipoff:
            raise ValueError("final box observation must occur after tipoff")
        if self.home_points < 0 or self.away_points < 0:
            raise ValueError("final scores must be non-negative")
        for name in ("home_fga", "home_fta", "home_orb", "home_turnovers",
                     "away_fga", "away_fta", "away_orb", "away_turnovers"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not str(self.source_uri).startswith("https://"):
            raise ValueError("source_uri must be https")


def _possessions(fga: float, fta: float, orb: float, turnovers: float) -> float:
    # Auditable box-score estimate. Averaging both teams dampens bookkeeping noise.
    out = float(fga) + 0.44 * float(fta) - float(orb) + float(turnovers)
    if not math.isfinite(out) or out <= 0:
        raise ValueError("estimated possessions must be positive")
    return out


def _game_possessions(game: PublicNBABoxGame) -> float:
    return fmean((
        _possessions(game.home_fga, game.home_fta, game.home_orb, game.home_turnovers),
        _possessions(game.away_fga, game.away_fta, game.away_orb, game.away_turnovers),
    ))


def _team_view(game: PublicNBABoxGame, team_id: str) -> tuple[float, float, float]:
    poss = _game_possessions(game)
    if team_id == game.home_team_id:
        return float(game.home_points), float(game.away_points), poss
    if team_id == game.away_team_id:
        return float(game.away_points), float(game.home_points), poss
    raise ValueError("team not present in historical game")


def _digest_games(games: Iterable[PublicNBABoxGame]) -> str:
    payload = []
    for g in sorted(games, key=lambda x: (x.tipoff, x.game_id)):
        payload.append({
            "game_id": g.game_id,
            "tipoff": g.tipoff.astimezone(timezone.utc).isoformat(),
            "observed_at": g.observed_at.astimezone(timezone.utc).isoformat(),
            "home": g.home_team_id,
            "away": g.away_team_id,
            "source_uri": g.source_uri,
            "source_version": g.source_version,
        })
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def materialize_public_training_rows(
    games: Iterable[PublicNBABoxGame], *, window: int = 10, min_history: int = 3,
) -> tuple[NBATrainingRow, ...]:
    """Build chronological NBA rows using only publicly observed prior games.

    A prior game is eligible for a target only when ``prior.observed_at < target.tipoff``.
    The target outcome can be observed later because it is a training label, never a
    feature. ``feature_as_of`` is the latest public observation actually used.
    """
    if window < 1 or min_history < 1 or min_history > window:
        raise ValueError("require 1 <= min_history <= window")
    ordered = tuple(sorted(games, key=lambda g: (g.tipoff, g.game_id)))
    if not ordered:
        raise ValueError("public NBA games are required")
    for game in ordered:
        game.validate()

    rows: list[NBATrainingRow] = []
    for target in ordered:
        prior = [g for g in ordered if g.game_id != target.game_id and g.observed_at < target.tipoff]
        home_hist = [g for g in prior if target.home_team_id in (g.home_team_id, g.away_team_id)][-window:]
        away_hist = [g for g in prior if target.away_team_id in (g.home_team_id, g.away_team_id)][-window:]
        if len(home_hist) < min_history or len(away_hist) < min_history:
            continue

        def summaries(team_id: str, hist: list[PublicNBABoxGame]) -> tuple[float, float, float]:
            views = [_team_view(g, team_id) for g in hist]
            pace = fmean(v[2] for v in views)
            offense = fmean(100.0 * v[0] / v[2] for v in views)
            defense = fmean(100.0 * v[1] / v[2] for v in views)
            return pace, offense, defense

        hp, hor, hdr = summaries(target.home_team_id, home_hist)
        ap, aor, adr = summaries(target.away_team_id, away_hist)
        used = tuple(home_hist + away_hist)
        feature_as_of = max(g.observed_at for g in used)
        if feature_as_of >= target.tipoff:
            raise AssertionError("PIT filter failed")
        row = NBATrainingRow(
            game_id=target.game_id,
            tipoff=target.tipoff,
            feature_as_of=feature_as_of,
            home_team_id=target.home_team_id,
            away_team_id=target.away_team_id,
            expected_possessions=fmean((hp, ap)),
            home_offensive_rating=hor,
            home_defensive_rating=hdr,
            away_offensive_rating=aor,
            away_defensive_rating=adr,
            home_points=target.home_points,
            away_points=target.away_points,
            source_version=f"PUBLIC_REPO_ROLLING_V1:{_digest_games(used)}",
        )
        row.validate()
        rows.append(row)
    return tuple(rows)


__all__ = ["PublicNBABoxGame", "materialize_public_training_rows"]
