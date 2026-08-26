"""CFB joint full-game score model.

The model is fit only from market-blind football features and realized final scores.
Book lines/prices are applied after the joint path distribution exists. No key-number
mass is imposed. New models are candidates and inherit no promotion evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

import numpy as np

CFB_JOINT_MODEL_ID = "cfb_joint_ridge_residual_v1"
CFB_FEATURE_CONTRACT = "CFB_JOINT_GAME_FEATURES_V1"
CFB_SEED_POLICY = "EXPLICIT_NUMPY_PCG64_V1"

_BANNED = {
    "spread", "spread_line", "total", "total_line", "line", "price", "american_odds",
    "decimal_odds", "implied_probability", "implied_prob", "market_probability",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line", "closing_price",
    "home_moneyline", "away_moneyline", "odds",
}
_TEAM_KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
    "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
    "net_field_position", "explosive_rate",
)


class CFBModelError(ValueError):
    pass


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if name in _BANNED or "implied_prob" in name or "no_vig" in name or "novig" in name:
                raise CFBModelError(f"CFB_MARKET_DATA_PROHIBITED:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{i}]")


def _num(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBModelError(f"CFB_FEATURE_NUMERIC_REQUIRED:{name}") from exc
    if not isfinite(out):
        raise CFBModelError(f"CFB_FEATURE_NONFINITE:{name}")
    return out


def _metrics(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    value = row.get(f"{side}_metrics")
    if not isinstance(value, Mapping):
        raise CFBModelError(f"CFB_{side.upper()}_METRICS_REQUIRED")
    _assert_market_blind(value, path=f"{side}_metrics")
    return value


def _feature_vector(row: Mapping[str, Any]) -> np.ndarray:
    _assert_market_blind({k: v for k, v in row.items() if k not in {"home_score", "away_score", "season"}})
    home = _metrics(row, "home")
    away = _metrics(row, "away")
    h = [_num(home.get(key), f"home.{key}") for key in _TEAM_KEYS]
    a = [_num(away.get(key), f"away.{key}") for key in _TEAM_KEYS]
    neutral = row.get("neutral_site", False)
    if type(neutral) is not bool:
        raise CFBModelError("CFB_NEUTRAL_SITE_BOOL_REQUIRED")
    home_field = 0.0 if neutral else 1.0
    weather = row.get("weather") or {}
    if not isinstance(weather, Mapping):
        raise CFBModelError("CFB_WEATHER_MAPPING_REQUIRED")
    indoors_raw = weather.get("game_indoor", weather.get("gameIndoors"))
    if type(indoors_raw) is not bool:
        raise CFBModelError("CFB_WEATHER_INDOOR_FLAG_REQUIRED")
    indoors = 1.0 if indoors_raw else 0.0
    if indoors_raw:
        wind, temp = 0.0, 70.0
    else:
        wind = _num(weather.get("wind_speed", weather.get("windSpeed")), "weather.wind_speed")
        temp = _num(weather.get("temperature"), "weather.temperature")
    interactions = [
        h[0] - a[2], h[1] - a[3], a[0] - h[2], a[1] - h[3],
        h[4] - a[5], a[4] - h[5], h[8] - a[8], h[9] - a[9],
        h[10] - a[10], h[11] - a[11], h[12] - a[12],
    ]
    return np.asarray([*h, *a, *interactions, home_field, indoors, wind, temp], dtype=float)


def _feature_names() -> tuple[str, ...]:
    names = [f"home_{key}" for key in _TEAM_KEYS] + [f"away_{key}" for key in _TEAM_KEYS]
    names += [
        "home_rush_matchup", "home_pass_matchup", "away_rush_matchup", "away_pass_matchup",
        "home_success_matchup", "away_success_matchup", "eckel_diff", "points_per_eckel_diff",
        "points_per_drive_diff", "field_position_diff", "explosive_diff", "home_field", "indoors", "wind_speed", "temperature",
    ]
    return tuple(names)


def _ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(x.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    lhs, rhs = x.T @ x + penalty, x.T @ y
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


@dataclass(frozen=True)
class CFBJointScoreModel:
    model_id: str
    feature_contract: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    home_coefficients: tuple[float, ...]
    away_coefficients: tuple[float, ...]
    residual_pairs: tuple[tuple[float, float], ...]
    overtime_deltas: tuple[tuple[int, int], ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float

    def predict_means(self, row: Mapping[str, Any]) -> tuple[float, float]:
        raw = _feature_vector(row)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape:
            raise CFBModelError("CFB_MODEL_FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        home = float(design @ np.asarray(self.home_coefficients, dtype=float))
        away = float(design @ np.asarray(self.away_coefficients, dtype=float))
        if not isfinite(home) or not isfinite(away):
            raise CFBModelError("CFB_MODEL_PREDICTION_NONFINITE")
        return home, away

    def artifact_sha256(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return sha256(raw).hexdigest()


def fit_cfb_joint_score_model(rows: Iterable[Mapping[str, Any]], *, ridge_alpha: float = 10.0) -> CFBJointScoreModel:
    data = [dict(row) for row in rows]
    if len(data) < 20:
        raise CFBModelError("CFB_TRAINING_ROWS_INSUFFICIENT")
    alpha = _num(ridge_alpha, "ridge_alpha")
    if alpha < 0:
        raise CFBModelError("CFB_RIDGE_ALPHA_NEGATIVE")
    raw = np.asarray([_feature_vector(row) for row in data], dtype=float)
    means, scales = raw.mean(axis=0), raw.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw - means) / scales))
    home_y = np.asarray([_num(row.get("home_score"), "home_score") for row in data], dtype=float)
    away_y = np.asarray([_num(row.get("away_score"), "away_score") for row in data], dtype=float)
    if np.any(home_y < 0) or np.any(away_y < 0):
        raise CFBModelError("CFB_NEGATIVE_REALIZED_SCORE")
    home_coef, away_coef = _ridge(design, home_y, alpha), _ridge(design, away_y, alpha)
    home_resid, away_resid = home_y - design @ home_coef, away_y - design @ away_coef
    residual_pairs = tuple((float(h), float(a)) for h, a in zip(home_resid.tolist(), away_resid.tolist()))
    ot: list[tuple[int, int]] = []
    for row in data:
        if all(key in row for key in ("regulation_home_score", "regulation_away_score")):
            rh = int(_num(row.get("regulation_home_score"), "regulation_home_score"))
            ra = int(_num(row.get("regulation_away_score"), "regulation_away_score"))
            fh = int(_num(row.get("home_score"), "home_score"))
            fa = int(_num(row.get("away_score"), "away_score"))
            if rh == ra and fh != fa:
                dh, da = fh - rh, fa - ra
                if dh < 0 or da < 0 or dh == da:
                    raise CFBModelError("CFB_OVERTIME_DELTA_INVALID")
                ot.append((dh, da))
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    return CFBJointScoreModel(
        model_id=CFB_JOINT_MODEL_ID, feature_contract=CFB_FEATURE_CONTRACT,
        feature_names=_feature_names(), feature_means=tuple(map(float, means)), feature_scales=tuple(map(float, scales)),
        home_coefficients=tuple(map(float, home_coef)), away_coefficients=tuple(map(float, away_coef)),
        residual_pairs=residual_pairs, overtime_deltas=tuple(ot), train_seasons=seasons, ridge_alpha=float(alpha),
    )


def simulate_cfb_joint_distribution(
    model: CFBJointScoreModel, row: Mapping[str, Any], *, seed: int, n_paths: int = 20000,
) -> tuple[dict[str, int], ...]:
    if model.model_id != CFB_JOINT_MODEL_ID or model.feature_contract != CFB_FEATURE_CONTRACT:
        raise CFBModelError("CFB_MODEL_IDENTITY_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise CFBModelError("CFB_EXPLICIT_INTEGER_SEED_REQUIRED")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise CFBModelError("CFB_N_PATHS_INVALID")
    if not model.residual_pairs:
        raise CFBModelError("CFB_RESIDUAL_DISTRIBUTION_MISSING")
    home_mu, away_mu = model.predict_means(row)
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(model.residual_pairs), size=n_paths)
    rows: list[dict[str, int]] = []
    for i in idx.tolist():
        hr, ar = model.residual_pairs[i]
        home = max(0, int(round(home_mu + hr)))
        away = max(0, int(round(away_mu + ar)))
        if home == away:
            if not model.overtime_deltas:
                raise CFBModelError("CFB_OVERTIME_PROFILE_REQUIRED_FOR_TIED_PATH")
            dh, da = model.overtime_deltas[int(rng.integers(0, len(model.overtime_deltas)))]
            home += int(dh)
            away += int(da)
            if home == away:
                raise CFBModelError("CFB_OVERTIME_PROFILE_DID_NOT_RESOLVE_TIE")
        rows.append({"home_score": home, "away_score": away, "margin": home - away, "total": home + away})
    return tuple(rows)


def price_cfb_game_markets(
    distribution: Iterable[Mapping[str, Any]], *, spread_line: float, total_line: float,
) -> dict[str, Any]:
    data = [dict(row) for row in distribution]
    if not data:
        raise CFBModelError("CFB_DISTRIBUTION_EMPTY")
    s = _num(spread_line, "spread_line")
    t = _num(total_line, "total_line")
    n = float(len(data))
    margins = [_num(row.get("margin"), "margin") for row in data]
    totals = [_num(row.get("total"), "total") for row in data]
    home_w = sum(x > 0 for x in margins) / n
    away_w = sum(x < 0 for x in margins) / n
    tie = sum(x == 0 for x in margins) / n
    home_cover = sum(x + s > 0 for x in margins) / n
    away_cover = sum(x + s < 0 for x in margins) / n
    spread_push = sum(x + s == 0 for x in margins) / n
    over = sum(x > t for x in totals) / n
    under = sum(x < t for x in totals) / n
    total_push = sum(x == t for x in totals) / n
    return {
        "moneyline": {"home": home_w, "away": away_w, "tie_unresolved": tie},
        "spread": {"home": home_cover, "away": away_cover, "push": spread_push, "home_line": s},
        "total": {"over": over, "under": under, "push": total_push, "line": t},
    }
