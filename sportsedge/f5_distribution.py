"""Shared first-five score distribution and deterministic market read-outs.

This candidate is intentionally built from actual strictly-prior first-five inning
scores. It never scales a full-game mean by 5/9. Each team's scoring marginal is
an equal blend of its own F5 runs-for empirical PMF and the opponent's F5
runs-allowed empirical PMF. The two resulting marginals form one joint F5 score
state reused by all F5 market read-outs.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .source_lineage import canonical_json_sha256

F5_DISTRIBUTION_VERSION = "mlb_f5_empirical_state_v1_candidate"
F5_READOUT_VERSION = "mlb_f5_readout_v1"
F5_MARKETS = frozenset({"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"})
MIN_HISTORY_GAMES = 10


class F5DistributionError(ValueError):
    pass


@dataclass(frozen=True)
class F5Distribution:
    away_history_games: int
    home_history_games: int
    joint_score_pmf: dict[str, float]
    distribution_sha256: str
    distribution_version: str = F5_DISTRIBUTION_VERSION


@dataclass(frozen=True)
class F5Readout:
    market: str
    line: float | None
    side: str
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str = F5_READOUT_VERSION


def _count_pool(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise F5DistributionError(f"{field} must be a sequence")
    if len(value) < MIN_HISTORY_GAMES:
        raise F5DistributionError(
            f"{field} requires at least {MIN_HISTORY_GAMES} strictly-prior games"
        )
    out: list[int] = []
    for index, raw in enumerate(value):
        if isinstance(raw, bool):
            raise F5DistributionError(f"{field}[{index}] must be integer >= 0")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise F5DistributionError(f"{field}[{index}] must be integer >= 0") from exc
        if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
            raise F5DistributionError(f"{field}[{index}] must be integer >= 0")
        out.append(int(numeric))
    return tuple(out)


def _empirical_pmf(values: tuple[int, ...]) -> dict[int, float]:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    n = len(values)
    return {key: count / n for key, count in counts.items()}


def _blend(left: dict[int, float], right: dict[int, float]) -> dict[int, float]:
    keys = set(left) | set(right)
    out = {key: 0.5 * left.get(key, 0.0) + 0.5 * right.get(key, 0.0) for key in keys}
    if abs(sum(out.values()) - 1.0) > 1e-12:
        raise F5DistributionError("blended F5 marginal does not conserve probability")
    return out


def build_f5_distribution(features: Mapping[str, Any]) -> F5Distribution:
    if not isinstance(features, Mapping):
        raise F5DistributionError("F5 features must be an object")
    away_for = _count_pool(features.get("away_f5_runs_for"), "away_f5_runs_for")
    away_against = _count_pool(features.get("away_f5_runs_against"), "away_f5_runs_against")
    home_for = _count_pool(features.get("home_f5_runs_for"), "home_f5_runs_for")
    home_against = _count_pool(features.get("home_f5_runs_against"), "home_f5_runs_against")
    if len(away_for) != len(away_against):
        raise F5DistributionError("away F5 history arrays must align")
    if len(home_for) != len(home_against):
        raise F5DistributionError("home F5 history arrays must align")

    away_scoring = _blend(_empirical_pmf(away_for), _empirical_pmf(home_against))
    home_scoring = _blend(_empirical_pmf(home_for), _empirical_pmf(away_against))
    joint: dict[str, float] = {}
    for away_runs, away_p in sorted(away_scoring.items()):
        for home_runs, home_p in sorted(home_scoring.items()):
            joint[f"{away_runs},{home_runs}"] = away_p * home_p
    if abs(sum(joint.values()) - 1.0) > 1e-12:
        raise F5DistributionError("F5 joint score PMF does not conserve probability")

    digest = canonical_json_sha256({
        "version": F5_DISTRIBUTION_VERSION,
        "blend_policy": "equal_offense_opponent_allowed_empirical_marginals",
        "joint_score_pmf": joint,
    })
    return F5Distribution(
        away_history_games=len(away_for),
        home_history_games=len(home_for),
        joint_score_pmf=joint,
        distribution_sha256=digest,
    )


def _states(distribution: F5Distribution):
    total = 0.0
    rows: list[tuple[int, int, float]] = []
    for key, raw_p in distribution.joint_score_pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away_runs = int(away_text)
            home_runs = int(home_text)
            probability = float(raw_p)
        except (TypeError, ValueError) as exc:
            raise F5DistributionError("invalid F5 joint score state") from exc
        if away_runs < 0 or home_runs < 0 or not isfinite(probability) or probability < 0:
            raise F5DistributionError("invalid F5 joint score state")
        total += probability
        rows.append((away_runs, home_runs, probability))
    if abs(total - 1.0) > 1e-12:
        raise F5DistributionError("F5 joint score PMF does not conserve probability")
    return tuple(rows)


def _line(value: Any, *, required: bool) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool):
        raise F5DistributionError("line must be finite numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise F5DistributionError("line must be finite numeric") from exc
    if not isfinite(out):
        raise F5DistributionError("line must be finite numeric")
    return out


def read_f5_probability(
    distribution: F5Distribution,
    *,
    market: str,
    line: Any = None,
    side: str,
    team_side: str | None = None,
) -> F5Readout:
    if not isinstance(distribution, F5Distribution):
        raise F5DistributionError("distribution must be F5Distribution")
    market = str(market or "").upper()
    side = str(side or "").upper()
    if market not in F5_MARKETS:
        raise F5DistributionError(f"unsupported F5 market: {market}")
    rows = _states(distribution)

    if market == "F5_MONEYLINE":
        resolved_line = _line(line, required=False)
        if side in {"HOME", "HOME_ML"}:
            probability = sum(p for away, home, p in rows if home > away)
        elif side in {"AWAY", "AWAY_ML"}:
            probability = sum(p for away, home, p in rows if away > home)
        else:
            raise F5DistributionError("F5 moneyline side must be HOME or AWAY")
        push_probability = sum(p for away, home, p in rows if away == home)
    elif market == "F5_RUN_LINE":
        resolved_line = _line(line, required=True)
        assert resolved_line is not None
        if side in {"HOME", "HOME_RL"}:
            margins = tuple((home - away) + resolved_line for away, home, _ in rows)
        elif side in {"AWAY", "AWAY_RL"}:
            margins = tuple((away - home) + resolved_line for away, home, _ in rows)
        else:
            raise F5DistributionError("F5 run-line side must be HOME or AWAY")
        probability = sum(p for (_, _, p), value in zip(rows, margins) if value > 0)
        push_probability = sum(p for (_, _, p), value in zip(rows, margins) if abs(value) < 1e-12)
    elif market == "F5_TOTALS":
        resolved_line = _line(line, required=True)
        assert resolved_line is not None
        if resolved_line < 0:
            raise F5DistributionError("F5 totals line must be >= 0")
        if side == "OVER":
            probability = sum(p for away, home, p in rows if away + home > resolved_line)
        elif side == "UNDER":
            probability = sum(p for away, home, p in rows if away + home < resolved_line)
        else:
            raise F5DistributionError("F5 totals side must be OVER or UNDER")
        push_probability = sum(p for away, home, p in rows if abs(away + home - resolved_line) < 1e-12)
    else:
        resolved_line = _line(line, required=True)
        assert resolved_line is not None
        if resolved_line < 0:
            raise F5DistributionError("F5 team-total line must be >= 0")
        selected = str(team_side or "").upper()
        if selected not in {"AWAY", "HOME"}:
            raise F5DistributionError("F5 team-total team_side must be AWAY or HOME")
        values = tuple(away if selected == "AWAY" else home for away, home, _ in rows)
        if side == "OVER":
            probability = sum(p for (_, _, p), value in zip(rows, values) if value > resolved_line)
        elif side == "UNDER":
            probability = sum(p for (_, _, p), value in zip(rows, values) if value < resolved_line)
        else:
            raise F5DistributionError("F5 team-total side must be OVER or UNDER")
        push_probability = sum(p for (_, _, p), value in zip(rows, values) if abs(value - resolved_line) < 1e-12)

    if probability < -1e-12 or push_probability < -1e-12 or probability + push_probability > 1.0 + 1e-9:
        raise F5DistributionError("F5 readout probability mass invalid")
    readout_sha = canonical_json_sha256({
        "version": F5_READOUT_VERSION,
        "distribution_sha256": distribution.distribution_sha256,
        "market": market,
        "line": resolved_line,
        "side": side,
        "team_side": str(team_side or "").upper() or None,
        "probability": float(probability),
        "push_probability": float(push_probability),
    })
    return F5Readout(
        market=market,
        line=resolved_line,
        side=side,
        probability=float(probability),
        push_probability=float(push_probability),
        distribution_sha256=distribution.distribution_sha256,
        readout_sha256=readout_sha,
    )
