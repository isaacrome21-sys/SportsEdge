"""Football simulation primitives.

The legacy score-level interface remains for compatibility, but event-rich paths
are the canonical substrate for halves, quarters and player-stat read-outs.
Those read-outs are derived from the same play stream; no period or player
market is independently sampled.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import erf, sqrt
from typing import Iterable, Mapping, Sequence

import numpy as np


def _normal_cdf(x: float, mean: float, sigma: float) -> float:
    z = (x - mean) / (sigma * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))


@dataclass(frozen=True)
class KeyNumberMarginModel:
    """Discrete margin PMF with empirical point masses at key numbers."""

    mean: float
    sigma: float
    empirical_key_mass: dict[int, float]

    def __post_init__(self) -> None:
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if any(value < 0 for value in self.empirical_key_mass.values()):
            raise ValueError("key-number masses must be nonnegative")
        if sum(self.empirical_key_mass.values()) >= 1.0:
            raise ValueError("key-number masses must sum to less than 1")

    def margin_pmf(self, support: Iterable[int]) -> dict[int, float]:
        values = sorted({int(x) for x in support})
        if not values:
            raise ValueError("support must be nonempty")
        missing_keys = set(self.empirical_key_mass) - set(values)
        if missing_keys:
            raise ValueError(f"support missing key margins: {sorted(missing_keys)}")

        base: dict[int, float] = {}
        for margin in values:
            if margin in self.empirical_key_mass:
                continue
            lo = margin - 0.5
            hi = margin + 0.5
            base[margin] = max(0.0, _normal_cdf(hi, self.mean, self.sigma) - _normal_cdf(lo, self.mean, self.sigma))

        remaining = 1.0 - sum(self.empirical_key_mass.values())
        base_total = sum(base.values())
        if base_total <= 0:
            raise ValueError("normal component has no probability mass on support")

        pmf = {margin: probability * remaining / base_total for margin, probability in base.items()}
        pmf.update({int(k): float(v) for k, v in self.empirical_key_mass.items()})
        residual = 1.0 - sum(pmf.values())
        if abs(residual) > 1e-15:
            first_nonkey = next(m for m in values if m not in self.empirical_key_mass)
            pmf[first_nonkey] += residual
        return dict(sorted(pmf.items()))


@dataclass(frozen=True)
class PlayEvent:
    period: int
    offense: str
    play_type: str = "OTHER"
    points: int = 0
    passer_id: str | None = None
    receiver_id: str | None = None
    rusher_id: str | None = None
    passing_yards: int = 0
    rushing_yards: int = 0
    target: int = 0
    reception: int = 0
    down: int | None = None
    distance: int | None = None
    yardline_100: int | None = None
    seconds_remaining_game: int | None = None
    score_diff_before: int | None = None
    personnel: str | None = None

    def __post_init__(self) -> None:
        if self.period not in (1, 2, 3, 4):
            raise ValueError("FOOTBALL_PERIOD_OUT_OF_RANGE")
        if not str(self.offense):
            raise ValueError("FOOTBALL_OFFENSE_REQUIRED")
        if self.points < 0:
            raise ValueError("FOOTBALL_NEGATIVE_POINTS")
        if self.target not in (0, 1) or self.reception not in (0, 1):
            raise ValueError("FOOTBALL_TARGET_RECEPTION_MUST_BE_BINARY")
        if self.reception > self.target:
            raise ValueError("FOOTBALL_RECEPTION_EXCEEDS_TARGET")
        if self.reception and not self.receiver_id:
            raise ValueError("FOOTBALL_RECEPTION_REQUIRES_RECEIVER")
        if self.target and not self.receiver_id:
            raise ValueError("FOOTBALL_TARGET_REQUIRES_RECEIVER")
        if self.passing_yards and self.play_type != "PASS":
            raise ValueError("FOOTBALL_PASS_YARDS_ON_NON_PASS")
        if self.rushing_yards and self.play_type != "RUSH":
            raise ValueError("FOOTBALL_RUSH_YARDS_ON_NON_RUSH")
        if self.play_type == "PASS" and (self.target or self.reception or self.passing_yards) and not self.passer_id:
            raise ValueError("FOOTBALL_PASS_REQUIRES_PASSER")
        if self.play_type == "RUSH" and self.rushing_yards and not self.rusher_id:
            raise ValueError("FOOTBALL_RUSH_REQUIRES_RUSHER")


@dataclass(frozen=True)
class FootballGamePath:
    home_team: str
    away_team: str
    plays: tuple[PlayEvent, ...]
    home_quarter_points: tuple[int, int, int, int]
    away_quarter_points: tuple[int, int, int, int]
    team_passing_yards: Mapping[str, int]
    team_rushing_yards: Mapping[str, int]
    player_receiving_yards: Mapping[str, int]
    player_rushing_yards: Mapping[str, int]
    player_targets: Mapping[str, int]
    player_receptions: Mapping[str, int]

    @classmethod
    def from_plays(cls, *, home_team: str, away_team: str, plays: Sequence[PlayEvent]) -> "FootballGamePath":
        if not home_team or not away_team or home_team == away_team:
            raise ValueError("FOOTBALL_DISTINCT_TEAMS_REQUIRED")
        home_q = [0, 0, 0, 0]
        away_q = [0, 0, 0, 0]
        team_pass = defaultdict(int)
        team_rush = defaultdict(int)
        rec_yards = defaultdict(int)
        rush_yards = defaultdict(int)
        targets = defaultdict(int)
        receptions = defaultdict(int)

        for play in plays:
            if play.offense not in {home_team, away_team}:
                raise ValueError(f"FOOTBALL_UNKNOWN_OFFENSE:{play.offense}")
            points = home_q if play.offense == home_team else away_q
            points[play.period - 1] += play.points
            if play.play_type == "PASS":
                team_pass[play.offense] += play.passing_yards
                if play.receiver_id is not None:
                    rec_yards[play.receiver_id] += play.passing_yards
                    targets[play.receiver_id] += play.target
                    receptions[play.receiver_id] += play.reception
            elif play.play_type == "RUSH":
                team_rush[play.offense] += play.rushing_yards
                if play.rusher_id is not None:
                    rush_yards[play.rusher_id] += play.rushing_yards

        path = cls(
            home_team=home_team,
            away_team=away_team,
            plays=tuple(plays),
            home_quarter_points=tuple(home_q),
            away_quarter_points=tuple(away_q),
            team_passing_yards=dict(team_pass),
            team_rushing_yards=dict(team_rush),
            player_receiving_yards=dict(rec_yards),
            player_rushing_yards=dict(rush_yards),
            player_targets=dict(targets),
            player_receptions=dict(receptions),
        )
        validate_event_path_conservation(path)
        return path

    @property
    def home_score(self) -> int:
        return sum(self.home_quarter_points)

    @property
    def away_score(self) -> int:
        return sum(self.away_quarter_points)

    @property
    def final_score(self) -> tuple[int, int]:
        return self.home_score, self.away_score

    @property
    def first_half_score(self) -> tuple[int, int]:
        return sum(self.home_quarter_points[:2]), sum(self.away_quarter_points[:2])


@dataclass(frozen=True)
class FootballEventMarketReadouts:
    final_margin_pmf: Mapping[int, float]
    final_total_pmf: Mapping[int, float]
    first_half_margin_pmf: Mapping[int, float]
    first_half_total_pmf: Mapping[int, float]
    quarter_margin_pmfs: tuple[Mapping[int, float], Mapping[int, float], Mapping[int, float], Mapping[int, float]]
    quarter_total_pmfs: tuple[Mapping[int, float], Mapping[int, float], Mapping[int, float], Mapping[int, float]]


def _pmf(values: Iterable[int]) -> dict[int, float]:
    vals = tuple(values)
    if not vals:
        raise ValueError("FOOTBALL_EMPTY_PATH_SET")
    counts = Counter(vals)
    n = len(vals)
    return {key: counts[key] / n for key in sorted(counts)}


def read_event_game_markets(paths: Sequence[FootballGamePath]) -> FootballEventMarketReadouts:
    if not paths:
        raise ValueError("FOOTBALL_EMPTY_PATH_SET")
    return FootballEventMarketReadouts(
        final_margin_pmf=_pmf(p.home_score - p.away_score for p in paths),
        final_total_pmf=_pmf(p.home_score + p.away_score for p in paths),
        first_half_margin_pmf=_pmf(p.first_half_score[0] - p.first_half_score[1] for p in paths),
        first_half_total_pmf=_pmf(sum(p.first_half_score) for p in paths),
        quarter_margin_pmfs=tuple(
            _pmf(p.home_quarter_points[q] - p.away_quarter_points[q] for p in paths) for q in range(4)
        ),
        quarter_total_pmfs=tuple(
            _pmf(p.home_quarter_points[q] + p.away_quarter_points[q] for p in paths) for q in range(4)
        ),
    )


def validate_event_path_conservation(path: FootballGamePath) -> None:
    home_from_plays = [0, 0, 0, 0]
    away_from_plays = [0, 0, 0, 0]
    team_pass = defaultdict(int)
    team_rush = defaultdict(int)
    rec_yards = defaultdict(int)
    rush_yards = defaultdict(int)
    targets = defaultdict(int)
    receptions = defaultdict(int)

    for play in path.plays:
        if play.offense == path.home_team:
            home_from_plays[play.period - 1] += play.points
        elif play.offense == path.away_team:
            away_from_plays[play.period - 1] += play.points
        else:
            raise ValueError(f"FOOTBALL_UNKNOWN_OFFENSE:{play.offense}")
        if play.play_type == "PASS":
            team_pass[play.offense] += play.passing_yards
            if play.receiver_id is not None:
                rec_yards[play.receiver_id] += play.passing_yards
                targets[play.receiver_id] += play.target
                receptions[play.receiver_id] += play.reception
        elif play.play_type == "RUSH":
            team_rush[play.offense] += play.rushing_yards
            if play.rusher_id is not None:
                rush_yards[play.rusher_id] += play.rushing_yards

    if tuple(home_from_plays) != tuple(path.home_quarter_points) or tuple(away_from_plays) != tuple(path.away_quarter_points):
        raise ValueError("FOOTBALL_PERIOD_SCORE_RECONCILIATION_FAILED")
    if dict(team_pass) != dict(path.team_passing_yards):
        raise ValueError("FOOTBALL_TEAM_PASSING_YARDS_RECONCILIATION_FAILED")
    if dict(team_rush) != dict(path.team_rushing_yards):
        raise ValueError("FOOTBALL_TEAM_RUSHING_YARDS_RECONCILIATION_FAILED")
    if dict(rec_yards) != dict(path.player_receiving_yards):
        raise ValueError("FOOTBALL_RECEIVING_YARDS_RECONCILIATION_FAILED")
    if dict(rush_yards) != dict(path.player_rushing_yards):
        raise ValueError("FOOTBALL_PLAYER_RUSHING_YARDS_RECONCILIATION_FAILED")
    if dict(targets) != dict(path.player_targets) or dict(receptions) != dict(path.player_receptions):
        raise ValueError("FOOTBALL_TARGET_RECEPTION_RECONCILIATION_FAILED")
    for player_id, receptions_value in path.player_receptions.items():
        if receptions_value > path.player_targets.get(player_id, 0):
            raise ValueError(f"FOOTBALL_RECEPTIONS_EXCEED_TARGETS:{player_id}")

    if path.first_half_score != (
        path.home_quarter_points[0] + path.home_quarter_points[1],
        path.away_quarter_points[0] + path.away_quarter_points[1],
    ):
        raise ValueError("FOOTBALL_FIRST_HALF_RECONCILIATION_FAILED")
    if path.final_score != (sum(path.home_quarter_points), sum(path.away_quarter_points)):
        raise ValueError("FOOTBALL_FINAL_SCORE_RECONCILIATION_FAILED")


class JointScoreSimulator:
    """Legacy compatibility interface for score-only callers.

    This class is retained so existing consumers do not break while the event
    simulator is wired into production. New halves/quarters/player markets must
    not use this score-only output.
    """

    def __init__(
        self,
        margin_model: KeyNumberMarginModel,
        total_mean: float,
        total_sigma: float,
        seed: int | None = None,
    ) -> None:
        if total_sigma <= 0:
            raise ValueError("total_sigma must be positive")
        self.margin_model = margin_model
        self.total_mean = float(total_mean)
        self.total_sigma = float(total_sigma)
        self.rng = np.random.default_rng(seed)

    def simulate(self, n: int) -> list[dict[str, int]]:
        if n <= 0:
            return []
        support = np.arange(-80, 81, dtype=int)
        pmf = self.margin_model.margin_pmf(support.tolist())
        margins = self.rng.choice(np.array(list(pmf), dtype=int), size=n, p=np.array(list(pmf.values()), dtype=float))
        raw_totals = np.rint(self.rng.normal(self.total_mean, self.total_sigma, size=n)).astype(int)

        rows: list[dict[str, int]] = []
        for margin, raw_total in zip(margins.tolist(), raw_totals.tolist()):
            total = max(abs(int(margin)), max(0, int(raw_total)))
            if (total - int(margin)) % 2 != 0:
                total += 1
            home = (total + int(margin)) // 2
            away = (total - int(margin)) // 2
            rows.append(
                {
                    "home_score": int(home),
                    "away_score": int(away),
                    "margin": int(home - away),
                    "total": int(home + away),
                }
            )
        return rows
