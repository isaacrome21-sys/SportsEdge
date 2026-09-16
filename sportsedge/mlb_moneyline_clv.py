"""Paired closing-line evidence for MLB MONEYLINE.

This module is downstream of Model_P. It never creates or modifies Model_P.
It evaluates model-directed probability CLV against a paired two-sided close
using multiplicative no-vig normalization and fails closed on missing identity.
"""
from __future__ import annotations

from math import isfinite
from statistics import fmean
from typing import Any, Iterable, Mapping

CLV_VERSION = "mlb_moneyline_clv_v1"


class MLBMoneylineCLVError(ValueError):
    pass


def _american_prob(odds: Any) -> float:
    try:
        x = float(odds)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineCLVError("american odds must be numeric") from exc
    if not isfinite(x) or x == 0:
        raise MLBMoneylineCLVError("invalid american odds")
    return 100.0 / (x + 100.0) if x > 0 else (-x) / ((-x) + 100.0)


def paired_no_vig(home_odds: Any, away_odds: Any) -> tuple[float, float]:
    h, a = _american_prob(home_odds), _american_prob(away_odds)
    total = h + a
    if total <= 0:
        raise MLBMoneylineCLVError("invalid paired market")
    return h / total, a / total


def evaluate_paired_closes(rows: Iterable[Mapping[str, Any]], *, min_mean_clv: float = 0.005) -> dict[str, Any]:
    values: list[float] = []
    for i, row in enumerate(rows):
        game_pk = row.get("game_pk")
        if game_pk in (None, ""):
            raise MLBMoneylineCLVError(f"row {i}: game_pk required")
        side = str(row.get("model_side") or "").upper()
        if side not in {"HOME", "AWAY"}:
            raise MLBMoneylineCLVError(f"row {i}: model_side must be HOME or AWAY")
        try:
            model_p = float(row.get("model_p"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineCLVError(f"row {i}: model_p invalid") from exc
        if not isfinite(model_p) or not 0 < model_p < 1:
            raise MLBMoneylineCLVError(f"row {i}: model_p invalid")
        h, a = paired_no_vig(row.get("close_home_odds"), row.get("close_away_odds"))
        close_p = h if side == "HOME" else a
        values.append(model_p - close_p)

    if not values:
        return {
            "clv_version": CLV_VERSION,
            "n": 0,
            "status": "BLOCKED_NO_ADMISSIBLE_PAIRED_CLOSES",
            "promotion_authority": False,
        }
    mean_clv = fmean(values)
    return {
        "clv_version": CLV_VERSION,
        "n": len(values),
        "mean_model_directed_probability_clv": mean_clv,
        "threshold": min_mean_clv,
        "clv_gate_pass": mean_clv >= min_mean_clv,
        "status": "CLV_PASS_OTHER_GATES_REQUIRED" if mean_clv >= min_mean_clv else "BLOCKED_CLV",
        "promotion_authority": False,
        "devig_method": "MULTIPLICATIVE_V1",
    }
