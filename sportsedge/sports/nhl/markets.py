"""NHL market probabilities derived only from coherent shared simulation paths.

These helpers do not fit team strength or infer anything from sportsbook prices. They
turn already-simulated NHL score paths into honest win/push/loss probability mass so
RUN IT can later bind the same distribution to moneyline, puck line, totals and team
totals without creating mutually inconsistent probabilities.
"""

from dataclasses import dataclass
import math

from .simulation import NHLGamePaths


@dataclass(frozen=True)
class OutcomeProbability:
    win: float
    push: float
    loss: float

    def __post_init__(self) -> None:
        values = (self.win, self.push, self.loss)
        if any(not math.isfinite(v) or v < 0.0 or v > 1.0 for v in values):
            raise ValueError("probability mass must be finite and in [0, 1]")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-12):
            raise ValueError("win/push/loss probability mass must sum to 1")


def _validate_paths(paths: NHLGamePaths) -> int:
    n = paths.simulations
    if n <= 0:
        raise ValueError("at least one simulation path is required")
    if not (len(paths.home_regulation) == len(paths.away_regulation) == len(paths.home_final) == len(paths.away_final) == n):
        raise ValueError("NHL score path arrays must have equal length")
    return n


def _mass(values: list[int], n: int) -> OutcomeProbability:
    wins = sum(v > 0 for v in values)
    pushes = sum(v == 0 for v in values)
    return OutcomeProbability(wins / n, pushes / n, (n - wins - pushes) / n)


def home_moneyline(paths: NHLGamePaths) -> OutcomeProbability:
    """Final home moneyline from final-score paths; NHL final scores cannot tie."""
    n = _validate_paths(paths)
    return _mass([h - a for h, a in zip(paths.home_final, paths.away_final)], n)


def home_regulation_three_way(paths: NHLGamePaths) -> tuple[float, float, float]:
    """Return (home, draw, away) regulation probability mass."""
    n = _validate_paths(paths)
    home = draw = 0
    for h, a in zip(paths.home_regulation, paths.away_regulation):
        home += h > a
        draw += h == a
    away = n - home - draw
    return home / n, draw / n, away / n


def home_puck_line(paths: NHLGamePaths, line: float) -> OutcomeProbability:
    """Home puck-line W/P/L, preserving push mass for integer lines."""
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    n = _validate_paths(paths)
    margins = [h - a + line for h, a in zip(paths.home_final, paths.away_final)]
    return _mass(margins, n)


def game_total_over(paths: NHLGamePaths, line: float) -> OutcomeProbability:
    """Full-game over W/P/L from the same final paths used by ML and puck line."""
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    n = _validate_paths(paths)
    return _mass([h + a - line for h, a in zip(paths.home_final, paths.away_final)], n)


def team_total_over(paths: NHLGamePaths, *, home: bool, line: float) -> OutcomeProbability:
    """Home/away team-total over W/P/L from shared final paths."""
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    n = _validate_paths(paths)
    scores = paths.home_final if home else paths.away_final
    return _mass([score - line for score in scores], n)
