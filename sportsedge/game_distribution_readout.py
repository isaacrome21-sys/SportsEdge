"""Deterministic market probability read-outs from one MLB V7 score distribution.

The stochastic game distribution is produced separately. This module consumes the
same joint score PMF to derive MONEYLINE, RUN_LINE, and TOTALS probabilities without
re-running or perturbing the simulator.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .source_lineage import canonical_json_sha256
from .v7_distribution import GameDistribution

READOUT_VERSION = "mlb_v7_game_readout_v1"
SUPPORTED_READOUTS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS"})


class GameReadoutError(ValueError):
    pass


@dataclass(frozen=True)
class GameReadout:
    market: str
    line: float | None
    side: str
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str = READOUT_VERSION


def _finite_line(value: Any, *, required: bool) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool):
        raise GameReadoutError("line must be finite numeric")
    try:
        line = float(value)
    except (TypeError, ValueError) as exc:
        raise GameReadoutError("line must be finite numeric") from exc
    if not isfinite(line):
        raise GameReadoutError("line must be finite numeric")
    return line


def _states(distribution: GameDistribution | Mapping[str, Any]):
    if isinstance(distribution, GameDistribution):
        pmf = distribution.joint_score_pmf
        distribution_sha = distribution.result_sha256
    elif isinstance(distribution, Mapping):
        pmf = distribution.get("joint_score_pmf")
        distribution_sha = distribution.get("result_sha256")
    else:
        raise GameReadoutError("distribution must be GameDistribution or mapping")
    if not isinstance(pmf, Mapping) or not pmf:
        raise GameReadoutError("joint_score_pmf missing")
    if not isinstance(distribution_sha, str) or len(distribution_sha) != 64:
        raise GameReadoutError("distribution result_sha256 missing or malformed")

    rows = []
    total = 0.0
    for key, raw_probability in pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away_runs = int(away_text)
            home_runs = int(home_text)
            probability = float(raw_probability)
        except (TypeError, ValueError) as exc:
            raise GameReadoutError("invalid joint score state") from exc
        if away_runs < 0 or home_runs < 0 or not isfinite(probability) or probability < 0:
            raise GameReadoutError("invalid joint score state")
        total += probability
        rows.append((away_runs, home_runs, probability))
    if abs(total - 1.0) > 1e-9:
        raise GameReadoutError("joint score PMF does not conserve probability")
    return tuple(rows), distribution_sha


def read_game_probability(
    distribution: GameDistribution | Mapping[str, Any],
    *,
    market: str,
    line: Any = None,
    side: str,
) -> GameReadout:
    market = str(market or "").upper()
    side = str(side or "").upper()
    if market not in SUPPORTED_READOUTS:
        raise GameReadoutError(f"unsupported readout market: {market}")
    rows, distribution_sha = _states(distribution)

    if market == "MONEYLINE":
        resolved_line = _finite_line(line, required=False)
        if side in {"HOME", "HOME_ML"}:
            probability = sum(p for away, home, p in rows if home > away)
        elif side in {"AWAY", "AWAY_ML"}:
            probability = sum(p for away, home, p in rows if away > home)
        else:
            raise GameReadoutError("moneyline side must be HOME or AWAY")
        push_probability = 0.0
    elif market == "RUN_LINE":
        resolved_line = _finite_line(line, required=True)
        if side in {"HOME", "HOME_RL"}:
            margins = tuple((home - away) + resolved_line for away, home, _ in rows)
        elif side in {"AWAY", "AWAY_RL"}:
            margins = tuple((away - home) + resolved_line for away, home, _ in rows)
        else:
            raise GameReadoutError("run-line side must be HOME or AWAY")
        probability = sum(p for (_, _, p), value in zip(rows, margins) if value > 0)
        push_probability = sum(p for (_, _, p), value in zip(rows, margins) if abs(value) < 1e-12)
    else:
        resolved_line = _finite_line(line, required=True)
        if resolved_line is None or resolved_line < 0:
            raise GameReadoutError("totals line must be >= 0")
        if side == "OVER":
            probability = sum(p for away, home, p in rows if away + home > resolved_line)
        elif side == "UNDER":
            probability = sum(p for away, home, p in rows if away + home < resolved_line)
        else:
            raise GameReadoutError("totals side must be OVER or UNDER")
        push_probability = sum(
            p for away, home, p in rows if abs((away + home) - resolved_line) < 1e-12
        )

    if probability < -1e-12 or push_probability < -1e-12 or probability + push_probability > 1.0 + 1e-9:
        raise GameReadoutError("readout probability mass invalid")
    readout_sha = canonical_json_sha256({
        "version": READOUT_VERSION,
        "distribution_sha256": distribution_sha,
        "market": market,
        "line": resolved_line,
        "side": side,
        "probability": float(probability),
        "push_probability": float(push_probability),
    })
    return GameReadout(
        market=market,
        line=resolved_line,
        side=side,
        probability=float(probability),
        push_probability=float(push_probability),
        distribution_sha256=distribution_sha,
        readout_sha256=readout_sha,
    )
