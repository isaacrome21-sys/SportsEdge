"""Research-only richer CFB joint-score challenger.

This candidate extends the canonical CFB joint score model with PIT-safe roster,
QB, talent, portal, coaching, tempo, havoc, special-teams, rest and travel state.
It remains market-blind: sportsbook lines, prices and implied probabilities are
prohibited inputs. Historical materialization must prove each feature existed by
``feature_asof_ts`` before kickoff.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

import numpy as np

from sportsedge.sports.cfb.joint_model import price_cfb_game_markets

CFB_RICH_MODEL_ID = "cfb_joint_rich_ridge_residual_v2_candidate"
CFB_RICH_FEATURE_CONTRACT = "CFB_JOINT_GAME_FEATURES_V2_RICH_PIT"
CFB_RICH_DEFAULT_PATHS = 100000

_BANNED = {
    "spread", "spread_line", "total", "total_line", "line", "price", "american_odds",
    "decimal_odds", "implied_probability", "implied_prob", "market_probability",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line", "closing_price",
    "home_moneyline", "away_moneyline", "odds", "ticket_pct", "money_pct", "handle_pct",
}
_BASE_TEAM_KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
    "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
    "net_field_position", "explosive_rate",
)
_RICH_TEAM_KEYS = (
    "returning_production", "talent_composite", "recruiting_3yr_points", "portal_net_value",
    "qb_value", "qb_continuity", "availability_value", "coach_continuity",
    "tempo_plays_per_game", "havoc_created", "havoc_allowed", "special_teams_value",
)


class CFBRichCandidateError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise CFBRichCandidateError(f"{field}:INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None:
        raise CFBRichCandidateError(f"{field}:NAIVE_TIMESTAMP")
    return dt


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CFBRichCandidateError(f"{field}:NUMERIC_REQUIRED")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBRichCandidateError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(x):
        raise CFBRichCandidateError(f"{field}:NONFINITE")
    return x


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if name in _BANNED or "implied_prob" in name or "no_vig" in name or "novig" in name:
                raise CFBRichCandidateError(f"MARKET_DATA_PROHIBITED:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{i}]")


def _validate_temporal(row: Mapping[str, Any]) -> None:
    asof = _dt(row.get("feature_asof_ts"), "feature_asof_ts")
    start = _dt(row.get("game_start_ts"), "game_start_ts")
    if not asof < start:
        raise CFBRichCandidateError("CFB_RICH_FEATURE_NOT_STRICTLY_PREGAME")
    source_times = row.get("source_asof_ts") or {}
    if not isinstance(source_times, Mapping):
        raise CFBRichCandidateError("source_asof_ts:MAPPING_REQUIRED")
    for name, value in source_times.items():
        if _dt(value, f"source_asof_ts.{name}") > asof:
            raise CFBRichCandidateError(f"SOURCE_AFTER_FEATURE_ASOF:{name}")


def _mapping(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = row.get(key)
    if not isinstance(value, Mapping):
        raise CFBRichCandidateError(f"{key}:MAPPING_REQUIRED")
    _assert_market_blind(value, key)
    return value


def _feature_vector(row: Mapping[str, Any]) -> np.ndarray:
    _validate_temporal(row)
    _assert_market_blind({
        key: value for key, value in row.items()
        if key not in {"home_score", "away_score", "season", "game_start_ts", "feature_asof_ts", "source_asof_ts"}
    })
    hm = _mapping(row, "home_metrics")
    am = _mapping(row, "away_metrics")
    hc = _mapping(row, "home_context")
    ac = _mapping(row, "away_context")
    hbase = [_num(hm.get(key), f"home_metrics.{key}") for key in _BASE_TEAM_KEYS]
    abase = [_num(am.get(key), f"away_metrics.{key}") for key in _BASE_TEAM_KEYS]
    hrich = [_num(hc.get(key), f"home_context.{key}") for key in _RICH_TEAM_KEYS]
    arich = [_num(ac.get(key), f"away_context.{key}") for key in _RICH_TEAM_KEYS]

    neutral = row.get("neutral_site", False)
    if type(neutral) is not bool:
        raise CFBRichCandidateError("neutral_site:BOOLEAN_REQUIRED")
    home_field = 0.0 if neutral else 1.0
    weather = row.get("weather") or {}
    if not isinstance(weather, Mapping):
        raise CFBRichCandidateError("weather:MAPPING_REQUIRED")
    indoor = weather.get("game_indoor", weather.get("gameIndoors"))
    if type(indoor) is not bool:
        raise CFBRichCandidateError("weather.game_indoor:BOOLEAN_REQUIRED")
    if indoor:
        wind, temp, precip = 0.0, 70.0, 0.0
    else:
        wind = _num(weather.get("wind_speed", weather.get("windSpeed")), "weather.wind_speed")
        temp = _num(weather.get("temperature"), "weather.temperature")
        precip = _num(weather.get("precip_probability", weather.get("precipProbability", 0.0)), "weather.precip_probability")

    situational = [
        _num(row.get("home_rest_days"), "home_rest_days") - _num(row.get("away_rest_days"), "away_rest_days"),
        _num(row.get("away_travel_miles", 0.0), "away_travel_miles") - _num(row.get("home_travel_miles", 0.0), "home_travel_miles"),
        _num(row.get("away_timezone_shift", 0.0), "away_timezone_shift") - _num(row.get("home_timezone_shift", 0.0), "home_timezone_shift"),
    ]
    matchup = [
        hbase[0] - abase[2], hbase[1] - abase[3], abase[0] - hbase[2], abase[1] - hbase[3],
        hbase[4] - abase[5], abase[4] - hbase[5], hbase[8] - abase[8], hbase[9] - abase[9],
        hbase[10] - abase[10], hbase[11] - abase[11], hbase[12] - abase[12],
    ]
    rich_diffs = [h - a for h, a in zip(hrich, arich)]
    return np.asarray([
        *hbase, *abase, *hrich, *arich, *matchup, *rich_diffs, *situational,
        home_field, 1.0 if indoor else 0.0, wind, temp, precip,
    ], dtype=float)


def _feature_names() -> tuple[str, ...]:
    names = [f"home_{key}" for key in _BASE_TEAM_KEYS] + [f"away_{key}" for key in _BASE_TEAM_KEYS]
    names += [f"home_{key}" for key in _RICH_TEAM_KEYS] + [f"away_{key}" for key in _RICH_TEAM_KEYS]
    names += [
        "home_rush_matchup", "home_pass_matchup", "away_rush_matchup", "away_pass_matchup",
        "home_success_matchup", "away_success_matchup", "eckel_diff", "points_per_eckel_diff",
        "points_per_drive_diff", "field_position_diff", "explosive_diff",
    ]
    names += [f"{key}_diff" for key in _RICH_TEAM_KEYS]
    names += [
        "rest_days_diff", "travel_burden_diff", "timezone_burden_diff", "home_field", "indoors",
        "wind_speed", "temperature", "precip_probability",
    ]
    return tuple(names)


def _ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(x.shape[1], dtype=float) * alpha
    penalty[0, 0] = 0.0
    lhs = x.T @ x + penalty
    rhs = x.T @ y
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


@dataclass(frozen=True)
class CFBRichJointModel:
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
            raise CFBRichCandidateError("FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        home = float(design @ np.asarray(self.home_coefficients, dtype=float))
        away = float(design @ np.asarray(self.away_coefficients, dtype=float))
        if not isfinite(home) or not isfinite(away):
            raise CFBRichCandidateError("PREDICTION_NONFINITE")
        return home, away

    def artifact_sha256(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return sha256(raw).hexdigest()


def fit_cfb_rich_joint_score_model(
    rows: Iterable[Mapping[str, Any]], *,
    ridge_alpha: float = 10.0,
    min_rows: int = 100,
) -> CFBRichJointModel:
    data = [dict(row) for row in rows]
    if len(data) < int(min_rows):
        raise CFBRichCandidateError(f"TRAINING_ROWS_INSUFFICIENT:{len(data)}<{int(min_rows)}")
    alpha = _num(ridge_alpha, "ridge_alpha")
    if alpha < 0:
        raise CFBRichCandidateError("RIDGE_ALPHA_NEGATIVE")
    raw = np.asarray([_feature_vector(row) for row in data], dtype=float)
    means = raw.mean(axis=0)
    scales = raw.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data)), (raw - means) / scales))
    home_y = np.asarray([_num(row.get("home_score"), "home_score") for row in data], dtype=float)
    away_y = np.asarray([_num(row.get("away_score"), "away_score") for row in data], dtype=float)
    if np.any(home_y < 0) or np.any(away_y < 0):
        raise CFBRichCandidateError("NEGATIVE_REALIZED_SCORE")
    home_coef = _ridge(design, home_y, alpha)
    away_coef = _ridge(design, away_y, alpha)
    home_resid = home_y - design @ home_coef
    away_resid = away_y - design @ away_coef
    residual_pairs = tuple((float(h), float(a)) for h, a in zip(home_resid, away_resid))
    overtime: list[tuple[int, int]] = []
    for row in data:
        if "regulation_home_score" in row and "regulation_away_score" in row:
            rh = int(_num(row["regulation_home_score"], "regulation_home_score"))
            ra = int(_num(row["regulation_away_score"], "regulation_away_score"))
            fh = int(_num(row["home_score"], "home_score"))
            fa = int(_num(row["away_score"], "away_score"))
            if rh == ra and fh != fa:
                dh, da = fh - rh, fa - ra
                if dh < 0 or da < 0 or dh == da:
                    raise CFBRichCandidateError("OVERTIME_DELTA_INVALID")
                overtime.append((dh, da))
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    return CFBRichJointModel(
        model_id=CFB_RICH_MODEL_ID,
        feature_contract=CFB_RICH_FEATURE_CONTRACT,
        feature_names=_feature_names(),
        feature_means=tuple(map(float, means)),
        feature_scales=tuple(map(float, scales)),
        home_coefficients=tuple(map(float, home_coef)),
        away_coefficients=tuple(map(float, away_coef)),
        residual_pairs=residual_pairs,
        overtime_deltas=tuple(overtime),
        train_seasons=seasons,
        ridge_alpha=alpha,
    )


def simulate_cfb_rich_distribution(
    model: CFBRichJointModel,
    row: Mapping[str, Any], *,
    seed: int,
    n_paths: int = CFB_RICH_DEFAULT_PATHS,
) -> tuple[dict[str, int], ...]:
    if model.model_id != CFB_RICH_MODEL_ID or model.feature_contract != CFB_RICH_FEATURE_CONTRACT:
        raise CFBRichCandidateError("MODEL_IDENTITY_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise CFBRichCandidateError("EXPLICIT_INTEGER_SEED_REQUIRED")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise CFBRichCandidateError("N_PATHS_INVALID")
    if not model.residual_pairs:
        raise CFBRichCandidateError("RESIDUAL_DISTRIBUTION_MISSING")
    home_mu, away_mu = model.predict_means(row)
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(model.residual_pairs), size=n_paths)
    out: list[dict[str, int]] = []
    for i in idx.tolist():
        hr, ar = model.residual_pairs[i]
        home = max(0, int(round(home_mu + hr)))
        away = max(0, int(round(away_mu + ar)))
        if home == away:
            if not model.overtime_deltas:
                raise CFBRichCandidateError("OVERTIME_PROFILE_REQUIRED_FOR_TIED_PATH")
            dh, da = model.overtime_deltas[int(rng.integers(0, len(model.overtime_deltas)))]
            home += int(dh)
            away += int(da)
            if home == away:
                raise CFBRichCandidateError("OVERTIME_DID_NOT_RESOLVE_TIE")
        out.append({"home_score": home, "away_score": away, "margin": home - away, "total": home + away})
    return tuple(out)


def price_candidate_game_markets(distribution, *, spread_line: float, total_line: float):
    return price_cfb_game_markets(distribution, spread_line=spread_line, total_line=total_line)
