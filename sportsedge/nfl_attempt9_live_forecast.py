"""Frozen Attempt-9 raw margin/total forecasts for the phone card.

Does not invent a fallback mean. Short history is NO_MODEL.
Integer market thresholds stay blocked in the probability wrapper.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import groupby
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence
import json

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "artifacts/football/nfl_attempt9_runtime_v1.json"
MODEL_P_PATH = Path(__file__).resolve().parents[1] / "artifacts/football/nfl_attempt9_model_p_v1.json"
DECAY = 0.85
MIN_PRIOR_GAMES = 5
MAX_PRIOR_GAMES = 10
FEATURE_NAMES = (
    "home_points_for",
    "home_points_against",
    "away_points_for",
    "away_points_against",
    "home_net",
    "away_net",
)

NO_MODEL_MONEYLINE = "NO_MODEL:UNSUPPORTED_V1_NO_TIE_MASS_MODEL"
NO_MODEL_INTEGER = "NO_MODEL:NFL_ATTEMPT9_MODEL_P_PUSH_MODEL_REQUIRED_FOR_INTEGER_LINE"
NO_MODEL_HISTORY = "NO_MODEL:INSUFFICIENT_PRIOR_GAMES"
NO_MODEL_MARKET = "NO_MODEL:MARKET_NOT_ON_ATTEMPT9_CARD"


class NflAttempt9LiveError(ValueError):
    pass


def load_runtime(path: Path = RUNTIME_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise NflAttempt9LiveError("NFL_ATTEMPT9_RUNTIME_NOT_OBJECT")
    return dict(payload)


def load_model_p(path: Path = MODEL_P_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise NflAttempt9LiveError("NFL_ATTEMPT9_MODEL_P_NOT_OBJECT")
    return dict(payload)


def _weighted(pairs: Sequence[tuple[float, float]]) -> tuple[float, float]:
    window = list(pairs)[-MAX_PRIOR_GAMES:]
    weights = [DECAY ** (len(window) - 1 - i) for i in range(len(window))]
    wsum = sum(weights)
    pf = sum(w * row[0] for w, row in zip(weights, window)) / wsum
    pa = sum(w * row[1] for w, row in zip(weights, window)) / wsum
    return float(pf), float(pa)


def recency_features(
    games: Sequence[Mapping[str, Any]],
    *,
    home: str,
    away: str,
    asof: date,
) -> dict[str, Any]:
    """Strictly-prior Attempt-9 features. Same-date games are not in history."""
    ordered = sorted(
        (g for g in games if str(g.get("date") or "")[:10] < asof.isoformat()),
        key=lambda g: (str(g["date"])[:10], str(g.get("id") or "")),
    )
    hist: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for _, batch in groupby(ordered, key=lambda g: str(g["date"])[:10]):
        rows = list(batch)
        for g in rows:
            hist[str(g["home"])].append((float(g["hs"]), float(g["as"])))
            hist[str(g["away"])].append((float(g["as"]), float(g["hs"])))
    if len(hist[home]) < MIN_PRIOR_GAMES or len(hist[away]) < MIN_PRIOR_GAMES:
        return {
            "ok": False,
            "reason": NO_MODEL_HISTORY,
            "home_prior_games": len(hist[home]),
            "away_prior_games": len(hist[away]),
        }
    hp, ap = _weighted(hist[home]), _weighted(hist[away])
    values = [hp[0], hp[1], ap[0], ap[1], hp[0] - hp[1], ap[0] - ap[1]]
    return {
        "ok": True,
        "reason": "ATTEMPT9_FEATURES",
        "home_prior_games": len(hist[home]),
        "away_prior_games": len(hist[away]),
        "features": dict(zip(FEATURE_NAMES, values)),
        "vector": values,
    }


def raw_forecasts(runtime: Mapping[str, Any], vector: Sequence[float]) -> dict[str, float]:
    targets = runtime["runtime"]["targets"]
    out: dict[str, float] = {}
    for name in ("margin", "total"):
        spec = targets[name]
        mean = spec["feature_mean"]
        std = spec["feature_std"]
        beta = spec["coefficients"]
        z = [(float(vector[i]) - float(mean[i])) / float(std[i]) for i in range(6)]
        pred = float(spec["intercept"]) + sum(float(b) * zi for b, zi in zip(beta, z))
        if not isfinite(pred):
            raise NflAttempt9LiveError(f"NFL_ATTEMPT9_FORECAST_NONFINITE:{name}")
        out[name] = pred
    return out


def is_integer_line(line: float) -> bool:
    return abs(float(line) - round(float(line))) <= 1e-12


def market_eligibility(market: str, line: float | None) -> str | None:
    key = str(market).strip().lower()
    if key in {"moneyline", "ml"}:
        return NO_MODEL_MONEYLINE
    if key in {"team_total", "1h_moneyline", "1h_spread", "1h_total", "2h_moneyline",
               "2h_spread", "2h_total", "quarter_moneyline", "quarter_spread",
               "quarter_total", "alt_spread", "alt_total", "player_prop"}:
        return NO_MODEL_MARKET
    if key not in {"spread", "total"}:
        return NO_MODEL_MARKET
    if line is None or is_integer_line(float(line)):
        return NO_MODEL_INTEGER
    return None
