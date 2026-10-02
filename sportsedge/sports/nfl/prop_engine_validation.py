"""PIT walk-forward diagnostics for NFL player-prop candidate engines.

This validates model-side probability distributions without pretending that
historical sportsbook decision/close prices exist. Frozen, predeclared stat
thresholds are distribution probes only. Every held-out evaluation also requires
actual pre-kickoff availability/role evidence, and passing markets require an
actual pre-kickoff starting-QB confirmation. Missing or post-kickoff confirmations
fail closed for that held-out row.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite, log
from typing import Any, Iterable, Mapping

from .prop_engines import (
    ENGINE_CONTRACT,
    MARKETS,
    MODEL_P_STATUS,
    PropEngineError,
    fit_nfl_prop_engine,
    predict_nfl_prop,
)

VALIDATION_CONTRACT = "NFL_PLAYER_PROP_ENGINE_WALKFORWARD_V1"
_EPS = 1e-12
_PASSING_MARKETS = frozenset({
    "PASSING_YARDS", "PASS_ATTEMPTS", "COMPLETIONS", "PASSING_TDS", "INTERCEPTIONS"
})

# Frozen diagnostic thresholds. These are model-distribution probes, not claimed
# historical sportsbook lines and never used in fitting.
DIAGNOSTIC_THRESHOLDS: dict[str, tuple[float | None, ...]] = {
    "ANYTIME_TD": (None,),
    "RECEPTIONS": (2.5, 4.5, 6.5),
    "RECEIVING_YARDS": (39.5, 59.5, 79.5),
    "TARGETS": (4.5, 6.5, 8.5),
    "RUSHING_YARDS": (39.5, 59.5, 79.5),
    "RUSH_ATTEMPTS": (9.5, 14.5, 19.5),
    "PASSING_YARDS": (199.5, 249.5, 299.5),
    "PASS_ATTEMPTS": (29.5, 34.5, 39.5),
    "COMPLETIONS": (19.5, 24.5, 29.5),
    "PASSING_TDS": (0.5, 1.5, 2.5),
    "INTERCEPTIONS": (0.5, 1.5),
}


def _finite(value: Any, reason: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if not isfinite(out):
        raise ValueError(reason)
    return out


def _utc(value: Any, reason: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError(reason)
    return out.astimezone(timezone.utc)


def _pre_kickoff_timestamp(row: Mapping[str, Any], field: str, kickoff: datetime) -> datetime:
    observed = _utc(row.get(field), f"PROP_PIT_{field.upper()}_REQUIRED")
    if observed >= kickoff:
        raise ValueError(f"PROP_PIT_{field.upper()}_NOT_PREKICKOFF")
    return observed


def _pit_prediction_inputs(row: Mapping[str, Any], market: str) -> tuple[str, bool, bool | None]:
    kickoff = _utc(row.get("kickoff_ts"), "PROP_PIT_KICKOFF_INVALID")
    availability = str(row.get("availability_status") or "").strip().upper()
    if availability not in {"ACTIVE", "EXPECTED_ACTIVE"}:
        raise ValueError(f"PROP_PIT_AVAILABILITY_BLOCKED:{availability or 'MISSING'}")
    _pre_kickoff_timestamp(row, "availability_asof_ts", kickoff)

    if row.get("role_confirmed") is not True:
        raise ValueError("PROP_PIT_ROLE_UNCONFIRMED")
    _pre_kickoff_timestamp(row, "role_confirmed_at", kickoff)

    starter: bool | None = None
    if market in _PASSING_MARKETS:
        if row.get("starting_qb_confirmed") is not True:
            raise ValueError("PROP_PIT_STARTING_QB_UNCONFIRMED")
        _pre_kickoff_timestamp(row, "starting_qb_confirmed_at", kickoff)
        starter = True
    return availability, True, starter


def _clip(p: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(p)))


def _brier(y: int, p: float) -> float:
    return (_clip(p) - int(y)) ** 2


def _log_loss(y: int, p: float) -> float:
    q = _clip(p)
    return -(int(y) * log(q) + (1 - int(y)) * log(1.0 - q))


def _realized_value(row: Mapping[str, Any], market: str) -> float:
    if market == "ANYTIME_TD":
        rush = _finite(row.get("rushing_tds", 0), "PROP_VALIDATION_RUSH_TD_INVALID")
        recv = _finite(row.get("receiving_tds", 0), "PROP_VALIDATION_RECV_TD_INVALID")
        return 1.0 if rush + recv > 0.0 else 0.0
    field = MARKETS[market][0]
    if row.get(field) in (None, ""):
        raise ValueError(f"PROP_VALIDATION_STAT_MISSING:{field}")
    return _finite(row.get(field), f"PROP_VALIDATION_STAT_INVALID:{field}")


def _calibration(rows: list[dict[str, Any]], bins: int = 10) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "ece": None, "max_bin_deviation": None, "bins": []}
    bucketed: list[list[dict[str, Any]]] = [[] for _ in range(bins)]
    for row in rows:
        p = min(1.0, max(0.0, float(row["probability"])))
        index = min(bins - 1, int(p * bins))
        bucketed[index].append(row)
    result = []
    weighted = 0.0
    max_dev = 0.0
    for index, bucket in enumerate(bucketed):
        if not bucket:
            continue
        mean_p = sum(float(r["probability"]) for r in bucket) / len(bucket)
        rate = sum(int(r["outcome"]) for r in bucket) / len(bucket)
        dev = abs(mean_p - rate)
        weighted += len(bucket) * dev
        max_dev = max(max_dev, dev)
        result.append({
            "bin": index,
            "n": len(bucket),
            "mean_probability": mean_p,
            "observed_rate": rate,
            "absolute_deviation": dev,
        })
    return {
        "n": len(rows),
        "ece": weighted / len(rows),
        "max_bin_deviation": max_dev,
        "bins": result,
    }


def build_nfl_prop_walkforward_evidence(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_manifest_sha256: str,
    min_games: int = 6,
    recency_decay: float = 0.90,
    calibration_bins: int = 10,
) -> dict[str, Any]:
    data = [dict(row) for row in rows]
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data:
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            continue
        kickoff = str(row.get("kickoff_ts") or "").strip()
        game_id = str(row.get("game_id") or "").strip()
        if not kickoff or not game_id:
            raise ValueError("PROP_VALIDATION_IDENTITY_MISSING")
        by_player[player_id].append(row)
    for games in by_player.values():
        games.sort(key=lambda r: (str(r["kickoff_ts"]), str(r["game_id"])))

    evaluations: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    for market in MARKETS:
        thresholds = DIAGNOSTIC_THRESHOLDS[market]
        for player_id, games in sorted(by_player.items()):
            for index, heldout in enumerate(games):
                if index < min_games:
                    continue
                history = games[:index]
                as_of = heldout["kickoff_ts"]
                try:
                    model = fit_nfl_prop_engine(
                        history,
                        player_id=player_id,
                        market_id=market,
                        as_of=as_of,
                        source_manifest_sha256=source_manifest_sha256,
                        min_games=min_games,
                        recency_decay=recency_decay,
                    )
                    actual = _realized_value(heldout, market)
                    availability, role_confirmed, starting_qb_confirmed = _pit_prediction_inputs(
                        heldout, market
                    )
                except (PropEngineError, ValueError) as exc:
                    skipped[f"{market}:{str(exc).split(':')[0]}"] += 1
                    continue

                for threshold in thresholds:
                    if market == "ANYTIME_TD":
                        side = "YES"
                        outcome = int(actual > 0.0)
                    else:
                        side = "OVER"
                        outcome = int(actual > float(threshold))
                    try:
                        prediction = predict_nfl_prop(
                            model,
                            side=side,
                            line=threshold,
                            availability_status=availability,
                            role_confirmed=role_confirmed,
                            starting_qb_confirmed=starting_qb_confirmed,
                        )
                    except PropEngineError as exc:
                        skipped[f"{market}:{str(exc).split(':')[0]}"] += 1
                        continue
                    evaluations.append({
                        "market_id": market,
                        "player_id": player_id,
                        "game_id": str(heldout["game_id"]),
                        "kickoff_ts": str(heldout["kickoff_ts"]),
                        "threshold": threshold,
                        "side": side,
                        "probability": prediction.model_probability,
                        "outcome": outcome,
                        "brier": _brier(outcome, prediction.model_probability),
                        "log_loss": _log_loss(outcome, prediction.model_probability),
                        "sample_n_at_fit": model.sample_n,
                        "pit_role_confirmed": True,
                        "pit_starting_qb_confirmed": starting_qb_confirmed,
                    })

    markets: dict[str, dict[str, Any]] = {}
    for market in MARKETS:
        subset = [row for row in evaluations if row["market_id"] == market]
        markets[market] = {
            "n": len(subset),
            "brier": None if not subset else sum(r["brier"] for r in subset) / len(subset),
            "log_loss": None if not subset else sum(r["log_loss"] for r in subset) / len(subset),
            "calibration": _calibration(subset, bins=calibration_bins),
            "thresholds": list(DIAGNOSTIC_THRESHOLDS[market]),
            "historical_market_price_evidence": "UNAVAILABLE_NOT_PROVIDED",
            "clv": "UNAVAILABLE_NOT_PROVIDED",
            "after_vig_roi": "UNAVAILABLE_NOT_PROVIDED",
            "edge_floor": "UNAVAILABLE_NOT_FROZEN",
            "promotion_eligible": False,
            "truth_gate_eligible": False,
        }

    return {
        "contract": VALIDATION_CONTRACT,
        "engine_contract": ENGINE_CONTRACT,
        "model_p_status": MODEL_P_STATUS,
        "status": "MODEL_DISTRIBUTION_DIAGNOSTIC_ONLY",
        "source_manifest_sha256": source_manifest_sha256,
        "evaluation_count": len(evaluations),
        "player_count": len(by_player),
        "pit_confirmation_contract": "PREKICKOFF_AVAILABILITY_ROLE_AND_STARTING_QB_WHEN_APPLICABLE",
        "parameters": {
            "min_games": int(min_games),
            "recency_decay": float(recency_decay),
            "calibration_bins": int(calibration_bins),
        },
        "markets": markets,
        "skipped": dict(sorted(skipped.items())),
        "promotion_eligible": False,
        "truth_gate_eligible": False,
        "missing_promotion_evidence": [
            "AUTHENTIC_HISTORICAL_DECISION_PRICES",
            "AUTHENTIC_HISTORICAL_CLOSE_PRICES",
            "CLV",
            "AFTER_VIG_ROI",
            "FROZEN_EDGE_FLOORS",
        ],
    }
