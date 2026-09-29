from __future__ import annotations

"""Coherent NHL goalie-save paths bound to opponent team SOG paths.

The engine deliberately separates *engine mechanics* from fitted performance.
Callers must supply a versioned save-probability / starter-shot-share artifact
learned from market-free history.  Every simulated goalie save is a subset of
that path's opponent shots on goal; no sportsbook line or price is an input.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import random
from typing import Sequence

from .official_boxscore_source import NHLOfficialCompletedGame, NHLGoalieBoxscore


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class NHLGoalieSaveParameters:
    version: str
    goalie_id: str
    save_probability: float
    starter_shot_share: float
    source: str
    history_sha256: str
    starts: int
    starter_status: str = "PROJECTED"

    def validate(self) -> None:
        if not all((self.version, self.goalie_id, self.source, self.history_sha256)):
            raise ValueError("goalie save parameter identity/provenance required")
        if self.starts <= 0:
            raise ValueError("positive historical start count required")
        if self.starter_status not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("starter_status must be CONFIRMED or PROJECTED")
        for name, value in (
            ("save_probability", self.save_probability),
            ("starter_shot_share", self.starter_shot_share),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0,1]")


@dataclass(frozen=True)
class NHLGoalieSavePaths:
    goalie_id: str
    saves: tuple[int, ...]
    shots_faced: tuple[int, ...]
    opponent_sog: tuple[int, ...]
    seed: int
    parameter_version: str
    starter_status: str

    @property
    def simulations(self) -> int:
        return len(self.saves)


def _binomial(rng: random.Random, trials: int, probability: float) -> int:
    if trials < 0:
        raise ValueError("trials must be nonnegative")
    return sum(1 for _ in range(trials) if rng.random() < probability)


def simulate_goalie_save_paths(
    opponent_sog: Sequence[int],
    params: NHLGoalieSaveParameters,
    *,
    game_seed: int,
    seed: int | None = None,
) -> NHLGoalieSavePaths:
    """Simulate goalie saves as a coherent subset of opponent SOG.

    ``starter_shot_share`` captures pull/relief risk from prior starts.  It does
    not assert that the goalie is confirmed; confirmation state is carried
    explicitly in the returned path object.
    """
    params.validate()
    shots = tuple(opponent_sog)
    if not shots:
        raise ValueError("opponent SOG paths required")
    if any((not isinstance(x, int)) or x < 0 for x in shots):
        raise ValueError("opponent SOG must be nonnegative integers")
    if seed is None:
        payload = (
            f"{int(game_seed)}|{params.version}|{params.goalie_id}|"
            f"{params.save_probability:.12g}|{params.starter_shot_share:.12g}|goalie-saves-v1"
        )
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    faced: list[int] = []
    saves: list[int] = []
    for team_sog in shots:
        goalie_shots = _binomial(rng, team_sog, params.starter_shot_share)
        goalie_saves = _binomial(rng, goalie_shots, params.save_probability)
        faced.append(goalie_shots)
        saves.append(goalie_saves)
    return NHLGoalieSavePaths(
        goalie_id=params.goalie_id,
        saves=tuple(saves),
        shots_faced=tuple(faced),
        opponent_sog=shots,
        seed=int(seed),
        parameter_version=params.version,
        starter_status=params.starter_status,
    )


def goalie_saves_over(paths: NHLGoalieSavePaths, line: float) -> tuple[float, float, float]:
    if not paths.saves:
        raise ValueError("goalie save paths are empty")
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    diffs = [value - line for value in paths.saves]
    n = len(diffs)
    wins = sum(x > 0 for x in diffs)
    pushes = sum(x == 0 for x in diffs)
    return wins / n, pushes / n, (n - wins - pushes) / n


def _goalies_for_side(game: NHLOfficialCompletedGame, side: str) -> tuple[NHLGoalieBoxscore, ...]:
    return game.home_goalies if side == "HOME" else game.away_goalies


def _opponent_sog(game: NHLOfficialCompletedGame, side: str) -> int:
    return game.away_sog if side == "HOME" else game.home_sog


def _starter(goalies: tuple[NHLGoalieBoxscore, ...]) -> NHLGoalieBoxscore | None:
    eligible = [g for g in goalies if g.toi_seconds is not None and g.toi_seconds > 0]
    if not eligible:
        return None
    return max(eligible, key=lambda g: (g.toi_seconds or 0, g.player_id))


def fit_empirical_goalie_save_parameters(
    games: Sequence[NHLOfficialCompletedGame],
    *,
    goalie_id: str,
    cutoff: str,
    version: str,
    min_starts: int = 5,
    starter_status: str = "PROJECTED",
) -> NHLGoalieSaveParameters:
    """Fit a transparent empirical saves baseline from prior official boxscores.

    Historical starter identity is inferred only as the goalie with the most TOI
    in that team's completed-game boxscore.  Rows at/after ``cutoff`` are
    excluded.  This is a development baseline, not a calibrated performance or
    betting-authority claim.
    """
    if not goalie_id or not version or min_starts < 1:
        raise ValueError("goalie_id/version and positive min_starts required")
    cut = _utc(cutoff)
    rows: list[dict[str, object]] = []
    total_saves = 0
    total_shots = 0
    shot_share_sum = 0.0
    starts = 0

    ordered = sorted(games, key=lambda g: (_utc(g.start_time_utc), g.game_id))
    for game in ordered:
        if _utc(game.start_time_utc) >= cut:
            continue
        for side in ("HOME", "AWAY"):
            goalies = _goalies_for_side(game, side)
            start = _starter(goalies)
            if start is None or start.player_id != goalie_id:
                continue
            if start.saves is None or start.shots_against is None:
                continue
            opp_sog = _opponent_sog(game, side)
            if opp_sog <= 0 or start.shots_against > opp_sog:
                continue
            starts += 1
            total_saves += start.saves
            total_shots += start.shots_against
            shot_share_sum += start.shots_against / opp_sog
            rows.append({
                "game_id": game.game_id,
                "start_time_utc": game.start_time_utc,
                "side": side,
                "saves": start.saves,
                "shots_against": start.shots_against,
                "opponent_sog": opp_sog,
                "source_raw_sha256": game.source_raw_sha256,
            })

    if starts < min_starts or total_shots <= 0:
        raise ValueError("insufficient historical goalie starts")
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    params = NHLGoalieSaveParameters(
        version=version,
        goalie_id=goalie_id,
        save_probability=total_saves / total_shots,
        starter_shot_share=shot_share_sum / starts,
        source="official-nhl-gamecenter-boxscores",
        history_sha256=digest,
        starts=starts,
        starter_status=starter_status,
    )
    params.validate()
    return params


__all__ = [
    "NHLGoalieSaveParameters",
    "NHLGoalieSavePaths",
    "simulate_goalie_save_paths",
    "goalie_saves_over",
    "fit_empirical_goalie_save_parameters",
]
