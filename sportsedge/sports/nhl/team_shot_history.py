from __future__ import annotations

"""Fit matchup team-SOG expectations from official completed NHL boxscores.

This is a transparent development baseline for the existing coherent team-shot
path generator.  Only completed-game receipts actually retrieved before the
target cutoff are eligible.  Retrospective downloads therefore cannot become
point-in-time inputs for an earlier target game.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Iterable

from .official_boxscore_source import NHLOfficialCompletedGame
from .team_shots import NHLTeamShotParameters


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


@dataclass
class _ShotHistory:
    games: int = 0
    sog_for: int = 0
    sog_against: int = 0

    def add(self, *, sog_for: int, sog_against: int) -> None:
        self.games += 1
        self.sog_for += sog_for
        self.sog_against += sog_against


@dataclass(frozen=True)
class NHLTeamShotFit:
    parameters: NHLTeamShotParameters
    cutoff: str
    home_team_id: str
    away_team_id: str
    home_games: int
    away_games: int
    league_team_games: int
    history_sha256: str
    authority: str = "DEVELOPMENT_BASELINE / NOT Model_P / NOT TRUTH_GATE / NOT OFFICIAL"


def _eligible(
    games: Iterable[NHLOfficialCompletedGame], *, cutoff: str,
) -> tuple[NHLOfficialCompletedGame, ...]:
    cut = _utc(cutoff)
    rows = [
        game for game in games
        if _utc(game.start_time_utc) < cut and _utc(game.captured_at) < cut
    ]
    rows.sort(key=lambda g: (_utc(g.start_time_utc), g.game_id))
    if len({g.game_id for g in rows}) != len(rows):
        raise ValueError("duplicate completed game id")
    return tuple(rows)


def _history_digest(games: tuple[NHLOfficialCompletedGame, ...]) -> str:
    payload = [
        {
            "game_id": g.game_id,
            "start_time_utc": g.start_time_utc,
            "captured_at": g.captured_at,
            "home_team_id": g.home_team_id,
            "away_team_id": g.away_team_id,
            "home_sog": g.home_sog,
            "away_sog": g.away_sog,
            "source_raw_sha256": g.source_raw_sha256,
        }
        for g in games
    ]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _shrunk_mean(total: int, games: int, league_mean: float, shrinkage_games: float) -> float:
    if games <= 0:
        raise ValueError("positive history games required")
    weight = games / (games + shrinkage_games)
    return weight * (total / games) + (1.0 - weight) * league_mean


def fit_matchup_team_shot_parameters(
    games: Iterable[NHLOfficialCompletedGame],
    *,
    home_team_id: str,
    away_team_id: str,
    cutoff: str,
    version: str,
    min_games: int = 10,
    shrinkage_games: float = 10.0,
) -> NHLTeamShotFit:
    """Fit full-game SOG means for a future matchup without market inputs.

    Each team's offensive SOG mean and the opponent's SOG-allowed mean are
    independently shrunk toward the eligible league team-game mean.  Matchup
    expectation is their arithmetic mean.  The simple formula is frozen and
    auditable; validation must determine whether it is useful.
    """
    if not home_team_id or not away_team_id or home_team_id == away_team_id:
        raise ValueError("distinct home/away team ids required")
    if not version or min_games < 1 or not math.isfinite(shrinkage_games) or shrinkage_games < 0:
        raise ValueError("version, positive min_games and nonnegative shrinkage required")
    eligible = _eligible(games, cutoff=cutoff)
    if not eligible:
        raise ValueError("no eligible completed-game receipts before cutoff")

    histories: dict[str, _ShotHistory] = {}
    total_sog = 0
    team_games = 0
    for game in eligible:
        home = histories.setdefault(game.home_team_id, _ShotHistory())
        away = histories.setdefault(game.away_team_id, _ShotHistory())
        home.add(sog_for=game.home_sog, sog_against=game.away_sog)
        away.add(sog_for=game.away_sog, sog_against=game.home_sog)
        total_sog += game.home_sog + game.away_sog
        team_games += 2

    home = histories.get(home_team_id)
    away = histories.get(away_team_id)
    if home is None or away is None or home.games < min_games or away.games < min_games:
        raise ValueError("insufficient eligible team SOG history")
    league_mean = total_sog / team_games
    home_offense = _shrunk_mean(home.sog_for, home.games, league_mean, shrinkage_games)
    home_defense = _shrunk_mean(home.sog_against, home.games, league_mean, shrinkage_games)
    away_offense = _shrunk_mean(away.sog_for, away.games, league_mean, shrinkage_games)
    away_defense = _shrunk_mean(away.sog_against, away.games, league_mean, shrinkage_games)
    expected_home = (home_offense + away_defense) / 2.0
    expected_away = (away_offense + home_defense) / 2.0
    digest = _history_digest(eligible)
    params = NHLTeamShotParameters(
        version=f"{version}:{digest}",
        home_expected_sog=expected_home,
        away_expected_sog=expected_away,
    )
    params.validate()
    return NHLTeamShotFit(
        parameters=params,
        cutoff=_utc(cutoff).isoformat(),
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_games=home.games,
        away_games=away.games,
        league_team_games=team_games,
        history_sha256=digest,
    )


__all__ = ["NHLTeamShotFit", "fit_matchup_team_shot_parameters"]
