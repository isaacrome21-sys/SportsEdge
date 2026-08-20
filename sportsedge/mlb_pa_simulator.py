"""Event-consistent MLB plate-appearance simulation kernel.

This module consumes already-estimated per-PA outcome probabilities. It does
not fit those probabilities and it does not contain market-specific
adjustments. All game and player read-outs derive from the same simulated
paths.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import random
from typing import Iterable, Mapping, Sequence

_OUTCOMES = ("K", "BB_HBP", "1B", "2B", "3B", "HR", "BIP_OUT")


@dataclass(frozen=True)
class PAProbabilities:
    k: float = 0.0
    bb_hbp: float = 0.0
    single: float = 0.0
    double: float = 0.0
    triple: float = 0.0
    hr: float = 0.0
    bip_out: float = 0.0

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any((not math.isfinite(x)) or x < 0.0 or x > 1.0 for x in values):
            raise ValueError("PA_PROBABILITY_OUT_OF_RANGE")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("PA_PROBABILITIES_MUST_SUM_TO_ONE")

    def as_tuple(self) -> tuple[float, ...]:
        return (self.k, self.bb_hbp, self.single, self.double, self.triple, self.hr, self.bip_out)

    def draw(self, rng: random.Random) -> str:
        u = rng.random()
        cumulative = 0.0
        for outcome, probability in zip(_OUTCOMES, self.as_tuple()):
            cumulative += probability
            if u < cumulative:
                return outcome
        return "BIP_OUT"


@dataclass(frozen=True)
class Batter:
    player_id: str
    probabilities: PAProbabilities

    def __post_init__(self) -> None:
        if not str(self.player_id):
            raise ValueError("BATTER_ID_REQUIRED")


@dataclass
class PlayerPathStats:
    pa: int = 0
    k: int = 0
    bb_hbp: int = 0
    singles: int = 0
    doubles: int = 0
    triples: int = 0
    hr: int = 0
    bip_outs: int = 0
    runs: int = 0
    rbi: int = 0

    @property
    def hits(self) -> int:
        return self.singles + self.doubles + self.triples + self.hr

    @property
    def total_bases(self) -> int:
        return self.singles + 2 * self.doubles + 3 * self.triples + 4 * self.hr


@dataclass(frozen=True)
class GameConfig:
    away: tuple[Batter, ...]
    home: tuple[Batter, ...]
    innings: int = 9
    max_plate_appearances_per_half_inning: int = 200

    def __post_init__(self) -> None:
        if not self.away or not self.home:
            raise ValueError("BOTH_LINEUPS_REQUIRED")
        if self.innings < 1:
            raise ValueError("INNINGS_MUST_BE_POSITIVE")
        if self.max_plate_appearances_per_half_inning < 3:
            raise ValueError("HALF_INNING_PA_CAP_TOO_SMALL")
        for lineup in (self.away, self.home):
            ids = [b.player_id for b in lineup]
            if len(ids) != len(set(ids)):
                raise ValueError("DUPLICATE_PLAYER_IN_LINEUP")


@dataclass(frozen=True)
class SBPathAttempt:
    runner_id: str
    base_occupied_before: bool
    success: bool


@dataclass(frozen=True)
class PitcherPathSegment:
    pitcher_id: str
    bf: int
    outs: int
    removed: bool
    bf_after_removal: int = 0


@dataclass
class GamePath:
    away_runs_by_inning: list[int]
    home_runs_by_inning: list[int]
    player_stats: dict[str, PlayerPathStats]
    away_bf: int
    home_bf: int
    away_outs: int
    home_outs: int
    pitcher_segments: list[PitcherPathSegment] = field(default_factory=list)
    sb_attempts: list[SBPathAttempt] = field(default_factory=list)

    @property
    def away_runs(self) -> int:
        return sum(self.away_runs_by_inning)

    @property
    def home_runs(self) -> int:
        return sum(self.home_runs_by_inning)

    @property
    def first_five_runs(self) -> tuple[int, int]:
        return (sum(self.away_runs_by_inning[:5]), sum(self.home_runs_by_inning[:5]))

    @property
    def nrfi(self) -> bool:
        away_first = self.away_runs_by_inning[0] if self.away_runs_by_inning else 0
        home_first = self.home_runs_by_inning[0] if self.home_runs_by_inning else 0
        return away_first == 0 and home_first == 0


@dataclass(frozen=True)
class GameMarketReadouts:
    home_moneyline_probability: float
    away_moneyline_probability: float
    tie_probability: float
    margin_pmf: Mapping[int, float]
    total_pmf: Mapping[int, float]
    away_team_total_pmf: Mapping[int, float]
    home_team_total_pmf: Mapping[int, float]
    f5_margin_pmf: Mapping[int, float]
    f5_total_pmf: Mapping[int, float]
    nrfi_probability: float
    yrfi_probability: float


def _stats(stats: dict[str, PlayerPathStats], player_id: str) -> PlayerPathStats:
    if player_id not in stats:
        stats[player_id] = PlayerPathStats()
    return stats[player_id]


def _score_runner(stats: dict[str, PlayerPathStats], runner_id: str | None) -> int:
    if runner_id is None:
        return 0
    _stats(stats, runner_id).runs += 1
    return 1


def _apply_outcome(
    outcome: str,
    batter_id: str,
    bases: list[str | None],
    stats: dict[str, PlayerPathStats],
) -> tuple[int, int]:
    """Apply one PA. Returns (outs_added, runs_scored)."""
    batter = _stats(stats, batter_id)
    batter.pa += 1
    if outcome == "K":
        batter.k += 1
        return 1, 0
    if outcome == "BIP_OUT":
        batter.bip_outs += 1
        return 1, 0

    runs = 0
    if outcome == "BB_HBP":
        batter.bb_hbp += 1
        if bases[0] is None:
            bases[0] = batter_id
            return 0, 0
        if bases[1] is None:
            bases[1], bases[0] = bases[0], batter_id
            return 0, 0
        if bases[2] is None:
            bases[2], bases[1], bases[0] = bases[1], bases[0], batter_id
            return 0, 0
        runs += _score_runner(stats, bases[2])
        bases[2], bases[1], bases[0] = bases[1], bases[0], batter_id
        batter.rbi += runs
        return 0, runs

    if outcome == "1B":
        batter.singles += 1
        runs += _score_runner(stats, bases[2])
        bases[2], bases[1], bases[0] = bases[1], bases[0], batter_id
    elif outcome == "2B":
        batter.doubles += 1
        runs += _score_runner(stats, bases[2])
        runs += _score_runner(stats, bases[1])
        bases[2], bases[1], bases[0] = bases[0], batter_id, None
    elif outcome == "3B":
        batter.triples += 1
        runs += sum(_score_runner(stats, runner) for runner in bases)
        bases[2], bases[1], bases[0] = batter_id, None, None
    elif outcome == "HR":
        batter.hr += 1
        runs += sum(_score_runner(stats, runner) for runner in bases)
        runs += _score_runner(stats, batter_id)
        bases[:] = [None, None, None]
    else:
        raise ValueError(f"UNKNOWN_PA_OUTCOME:{outcome}")
    batter.rbi += runs
    return 0, runs


def _half_inning(
    lineup: Sequence[Batter],
    lineup_index: int,
    rng: random.Random,
    stats: dict[str, PlayerPathStats],
    pa_cap: int,
) -> tuple[int, int, int]:
    outs = 0
    runs = 0
    batters_faced = 0
    bases: list[str | None] = [None, None, None]
    while outs < 3:
        if batters_faced >= pa_cap:
            raise RuntimeError("HALF_INNING_PA_CAP_EXCEEDED")
        batter = lineup[lineup_index % len(lineup)]
        lineup_index = (lineup_index + 1) % len(lineup)
        outcome = batter.probabilities.draw(rng)
        outs_added, runs_added = _apply_outcome(outcome, batter.player_id, bases, stats)
        outs += outs_added
        runs += runs_added
        batters_faced += 1
    return runs, lineup_index, batters_faced


def simulate_game(config: GameConfig, rng: random.Random | None = None) -> GamePath:
    rng = rng or random.Random()
    stats: dict[str, PlayerPathStats] = {}
    away_idx = home_idx = 0
    away_runs_by_inning: list[int] = []
    home_runs_by_inning: list[int] = []
    away_bf = home_bf = 0
    away_outs = home_outs = 0

    for inning in range(1, config.innings + 1):
        away_runs, away_idx, away_pa = _half_inning(
            config.away, away_idx, rng, stats, config.max_plate_appearances_per_half_inning
        )
        away_runs_by_inning.append(away_runs)
        away_bf += away_pa
        away_outs += 3

        if inning == config.innings and sum(home_runs_by_inning) > sum(away_runs_by_inning):
            home_runs_by_inning.append(0)
            continue

        home_runs, home_idx, home_pa = _half_inning(
            config.home, home_idx, rng, stats, config.max_plate_appearances_per_half_inning
        )
        home_runs_by_inning.append(home_runs)
        home_bf += home_pa
        home_outs += 3

    path = GamePath(
        away_runs_by_inning=away_runs_by_inning,
        home_runs_by_inning=home_runs_by_inning,
        player_stats=stats,
        away_bf=away_bf,
        home_bf=home_bf,
        away_outs=away_outs,
        home_outs=home_outs,
    )
    validate_path_conservation(path)
    return path


def simulate_many(config: GameConfig, *, n: int, seed: int | None = None) -> tuple[GamePath, ...]:
    if n <= 0:
        raise ValueError("SIMULATION_COUNT_MUST_BE_POSITIVE")
    rng = random.Random(seed)
    return tuple(simulate_game(config, rng) for _ in range(n))


def _pmf(values: Iterable[int]) -> dict[int, float]:
    values = tuple(values)
    if not values:
        raise ValueError("EMPTY_SIMULATION_SET")
    counts = Counter(values)
    n = len(values)
    return {key: counts[key] / n for key in sorted(counts)}


def read_game_markets(paths: Sequence[GamePath]) -> GameMarketReadouts:
    if not paths:
        raise ValueError("EMPTY_SIMULATION_SET")
    n = len(paths)
    home_wins = sum(p.home_runs > p.away_runs for p in paths)
    away_wins = sum(p.away_runs > p.home_runs for p in paths)
    ties = n - home_wins - away_wins
    nrfi = sum(p.nrfi for p in paths) / n
    return GameMarketReadouts(
        home_moneyline_probability=home_wins / n,
        away_moneyline_probability=away_wins / n,
        tie_probability=ties / n,
        margin_pmf=_pmf(p.home_runs - p.away_runs for p in paths),
        total_pmf=_pmf(p.home_runs + p.away_runs for p in paths),
        away_team_total_pmf=_pmf(p.away_runs for p in paths),
        home_team_total_pmf=_pmf(p.home_runs for p in paths),
        f5_margin_pmf=_pmf(p.first_five_runs[1] - p.first_five_runs[0] for p in paths),
        f5_total_pmf=_pmf(sum(p.first_five_runs) for p in paths),
        nrfi_probability=nrfi,
        yrfi_probability=1.0 - nrfi,
    )


def validate_path_conservation(path: GamePath) -> None:
    for player_id, stats in path.player_stats.items():
        expected_tb = stats.singles + 2 * stats.doubles + 3 * stats.triples + 4 * stats.hr
        if stats.total_bases != expected_tb:
            raise ValueError(f"PATH_TB_IDENTITY_FAILED:{player_id}")
        if stats.hr > stats.hits:
            raise ValueError(f"PATH_HR_EXCEEDS_HITS:{player_id}")
        if stats.pa != stats.k + stats.bb_hbp + stats.singles + stats.doubles + stats.triples + stats.hr + stats.bip_outs:
            raise ValueError(f"PATH_PA_ACCOUNTING_FAILED:{player_id}")
    if path.away_outs > path.away_bf or path.home_outs > path.home_bf:
        raise ValueError("PATH_OUTS_EXCEED_BF")
    for segment in path.pitcher_segments:
        if segment.outs > segment.bf:
            raise ValueError(f"PATH_PITCHER_OUTS_EXCEED_BF:{segment.pitcher_id}")
        if segment.removed and segment.bf_after_removal:
            raise ValueError(f"PATH_BF_AFTER_PITCHER_REMOVAL:{segment.pitcher_id}")
    for attempt in path.sb_attempts:
        if not attempt.base_occupied_before:
            raise ValueError(f"PATH_SB_WITHOUT_OCCUPIED_BASE:{attempt.runner_id}")
