"""Minimal verified NBA game-market pricing (ML / spread / total).

Data path (all free, public, verified):
  ESPN NBA scoreboard -> parse_completed_games() -> ratings_model.replay()
  -> predicted home/away points -> normal-CDF probabilities for
  MONEYLINE, SPREAD and TOTAL.

The residual sigmas come from the training games' own margin/total errors
(no market data, no league priors). This is the minimal end-to-end verified
path; it carries no betting authority and no market is "verified" until the
backtest harness validates it (see docs/NBA_FEASIBILITY_2026-10-11.md).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .espn_verified_source import NBADataError
from .ratings_model import NBARatings, NBARatingsParams, replay


@dataclass(frozen=True)
class NBAGameMarketPrices:
    home_team_id: str
    away_team_id: str
    predicted_home_points: float
    predicted_away_points: float
    predicted_margin: float   # home - away
    predicted_total: float    # home + away
    sigma_margin: float
    sigma_total: float
    ml_home_probability: float
    model_version: str

    def validate(self) -> None:
        for name in ("predicted_home_points", "predicted_away_points",
                     "predicted_margin", "predicted_total",
                     "sigma_margin", "sigma_total", "ml_home_probability"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise NBADataError("NBA_GAME_PRICE_NONFINITE:" + name)
        if self.sigma_margin <= 0 or self.sigma_total <= 0:
            raise NBADataError("NBA_GAME_PRICE_SIGMA_NONPOSITIVE")
        if not 0.0 < self.ml_home_probability < 1.0:
            raise NBADataError("NBA_GAME_PRICE_ML_DEGENERATE")
        if not self.home_team_id or not self.away_team_id or self.home_team_id == self.away_team_id:
            raise NBADataError("NBA_GAME_PRICE_TEAM_IDENTITY_UNVERIFIED")


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def fit_verified_games(games: list, params: NBARatingsParams | None = None,
                       min_games: int = 30) -> tuple[NBARatings, float, float]:
    """Fit ratings on verified completed games; return (ratings, sigma_margin, sigma_total).

    ``games`` are parse_completed_games() rows with tipoff/home_team_id/
    away_team_id/home_score/away_score. Sigmas are the train residual
    standard deviations (fail closed when degenerate).
    """
    rows = [g for g in games if isinstance(g, dict)]
    if len(rows) < min_games:
        raise NBADataError(f"NBA_INSUFFICIENT_VERIFIED_GAMES:{len(rows)}<{min_games}")
    chronological = sorted(rows, key=lambda g: (str(g.get("tipoff")), str(g.get("event_id"))))

    def as_replay_row(g):
        return {
            "date": str(g["tipoff"]),
            "season": str(g["tipoff"])[:4],
            "home": str(g["home_team_id"]),
            "away": str(g["away_team_id"]),
            "home_pts": float(g["home_score"]),
            "away_pts": float(g["away_score"]),
        }

    margin_errors: list[float] = []
    total_errors: list[float] = []

    def on_pre(game, ratings: NBARatings) -> None:
        hp, ap = ratings.predict(game["home"], game["away"])
        margin_errors.append((game["home_pts"] - game["away_pts"]) - (hp - ap))
        total_errors.append((game["home_pts"] + game["away_pts"]) - (hp + ap))

    ratings = replay([as_replay_row(g) for g in chronological],
                     params or NBARatingsParams(), on_pre=on_pre)

    def sigma(errors: list[float], name: str) -> float:
        n = len(errors)
        if n < min_games:
            raise NBADataError("NBA_RESIDUAL_SAMPLE_TOO_SMALL:" + name)
        mean = sum(errors) / n
        var = sum((e - mean) ** 2 for e in errors) / n
        out = math.sqrt(var)
        if not math.isfinite(out) or out <= 0:
            raise NBADataError("NBA_RESIDUAL_SIGMA_DEGENERATE:" + name)
        return out

    return ratings, sigma(margin_errors, "margin"), sigma(total_errors, "total")


def price_game_markets(*, home_team_id: str, away_team_id: str,
                       ratings: NBARatings, sigma_margin: float,
                       sigma_total: float,
                       model_version: str = "NBA_VERIFIED_GAME_V1") -> NBAGameMarketPrices:
    """Price MONEYLINE for a fixture from fitted ratings.

    Spread/total probabilities are read from the same normal margin/total
    distributions via ``spread_probability`` / ``total_probability``.
    """
    if not home_team_id or not away_team_id or home_team_id == away_team_id:
        raise NBADataError("NBA_GAME_PRICE_TEAM_IDENTITY_UNVERIFIED")
    if not math.isfinite(sigma_margin) or sigma_margin <= 0:
        raise NBADataError("NBA_GAME_PRICE_SIGMA_NONPOSITIVE:margin")
    if not math.isfinite(sigma_total) or sigma_total <= 0:
        raise NBADataError("NBA_GAME_PRICE_SIGMA_NONPOSITIVE:total")
    hp, ap = ratings.predict(str(home_team_id), str(away_team_id))
    if not math.isfinite(hp) or not math.isfinite(ap):
        raise NBADataError("NBA_RATINGS_PREDICTION_NONFINITE")
    margin, total = hp - ap, hp + ap
    ml_home = _phi(margin / sigma_margin)
    if not 0.0 < ml_home < 1.0:
        raise NBADataError("NBA_GAME_PRICE_ML_DEGENERATE")
    prices = NBAGameMarketPrices(
        home_team_id=str(home_team_id), away_team_id=str(away_team_id),
        predicted_home_points=hp, predicted_away_points=ap,
        predicted_margin=margin, predicted_total=total,
        sigma_margin=sigma_margin, sigma_total=sigma_total,
        ml_home_probability=ml_home, model_version=model_version)
    prices.validate()
    return prices


def spread_probability(prices: NBAGameMarketPrices, line: float, *, selection: str) -> float:
    """P(home covers) style probability for SPREAD from the margin distribution.

    ``line`` is the home spread line (e.g. -4.5); selection in {HOME, AWAY}.
    Push mass (margin == line exactly) is excluded from the win probability;
    callers grading against outcomes handle pushes at settlement.
    """
    prices.validate()
    sel = str(selection or "").strip().upper()
    if sel not in {"HOME", "AWAY"}:
        raise NBADataError("NBA_SPREAD_SELECTION_INVALID:" + str(selection))
    try:
        ln = float(line)
    except (ValueError, TypeError) as exc:
        raise NBADataError("NBA_SPREAD_LINE_UNVERIFIED") from exc
    if not math.isfinite(ln):
        raise NBADataError("NBA_SPREAD_LINE_UNVERIFIED")
    # P(home margin + line > 0); away is the mirror.
    p_home_covers = _phi((prices.predicted_margin + ln) / prices.sigma_margin)
    return p_home_covers if sel == "HOME" else 1.0 - p_home_covers


def total_probability(prices: NBAGameMarketPrices, line: float, *, selection: str) -> float:
    """P(total over/under line) from the total distribution."""
    prices.validate()
    sel = str(selection or "").strip().upper()
    if sel not in {"OVER", "UNDER"}:
        raise NBADataError("NBA_TOTAL_SELECTION_INVALID:" + str(selection))
    try:
        ln = float(line)
    except (ValueError, TypeError) as exc:
        raise NBADataError("NBA_TOTAL_LINE_UNVERIFIED") from exc
    if not math.isfinite(ln):
        raise NBADataError("NBA_TOTAL_LINE_UNVERIFIED")
    p_over = _phi((prices.predicted_total - ln) / prices.sigma_total)
    return p_over if sel == "OVER" else 1.0 - p_over
