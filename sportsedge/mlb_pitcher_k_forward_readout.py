"""One-look adjudication for the frozen prospective MLB pitcher-K validation lane."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from math import floor
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from .mlb_pitcher_k_forward_validation import (
    PREDICTION_SCHEMA,
    SETTLEMENT_SCHEMA,
)

READOUT_SCHEMA = "SPORTSEDGE_MLB_PITCHER_K_FORWARD_READOUT_V1"
PROTOCOL_PATH = Path("config/research/mlb_pitcher_k_forward_validation_v1.json")
FIT_SHA256 = "70a31ff9b995a2d54df87feb2d51e2518fa9cd8593bf6c047970e08557b6ecea"
MIN_GRADED_UNITS = 150
BOOT_REPS = 2000
BOOT_SEED = 20261007
CI_LEVEL = 0.95


class PitcherKForwardReadoutError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PitcherKForwardReadoutError(f"{field} invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PitcherKForwardReadoutError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise PitcherKForwardReadoutError("empty bootstrap distribution")
    xs = sorted(float(v) for v in values)
    pos = (len(xs) - 1) * float(q)
    lo = int(floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def _prediction_identity(row: Mapping[str, Any]) -> tuple[int, int]:
    if row.get("schema") != PREDICTION_SCHEMA:
        raise PitcherKForwardReadoutError("unexpected prediction schema")
    if str(row.get("fit_sha256") or "") != FIT_SHA256:
        raise PitcherKForwardReadoutError("prediction fit identity mismatch")
    if row.get("status") != "CAPTURED_PROSPECTIVE":
        raise PitcherKForwardReadoutError("prediction is not prospective")
    if (row.get("authority") or {}).get("production_activation") is not False:
        raise PitcherKForwardReadoutError("prediction authority mismatch")
    observed = _parse_utc(row.get("observed_at_utc"), "prediction observed_at")
    first_pitch = _parse_utc(row.get("first_pitch_at_utc"), "prediction first_pitch")
    if observed >= first_pitch:
        raise PitcherKForwardReadoutError("prediction not strictly pre-first-pitch")
    receipt_sha = str(row.get("receipt_sha256") or "")
    check = dict(row)
    check.pop("receipt_sha256", None)
    if len(receipt_sha) != 64 or canonical_sha256(check) != receipt_sha:
        raise PitcherKForwardReadoutError("prediction receipt hash mismatch")
    return int(row["game_pk"]), int(row["pitcher_id"])


def _settlement_by_prediction(
    settlements: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in settlements:
        if row.get("schema") != SETTLEMENT_SCHEMA:
            raise PitcherKForwardReadoutError("unexpected settlement schema")
        pred_sha = str(row.get("prediction_sha256") or "")
        if len(pred_sha) != 64:
            raise PitcherKForwardReadoutError("settlement prediction hash missing")
        if pred_sha in out and dict(out[pred_sha]) != dict(row):
            raise PitcherKForwardReadoutError("conflicting settlement for prediction")
        receipt_sha = str(row.get("receipt_sha256") or "")
        check = dict(row)
        check.pop("receipt_sha256", None)
        if len(receipt_sha) != 64 or canonical_sha256(check) != receipt_sha:
            raise PitcherKForwardReadoutError("settlement receipt hash mismatch")
        out[pred_sha] = row
    return out


def select_judged_units(
    predictions: Sequence[Mapping[str, Any]],
    settlements: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Choose the last captured pregame prediction per (game, pitcher), then require a graded settlement."""
    settlement_index = _settlement_by_prediction(settlements)
    latest: dict[tuple[int, int], Mapping[str, Any]] = {}
    for prediction in predictions:
        identity = _prediction_identity(prediction)
        current = latest.get(identity)
        if current is None:
            latest[identity] = prediction
            continue
        candidate_key = (
            _parse_utc(prediction["observed_at_utc"], "prediction observed_at"),
            str(prediction["receipt_sha256"]),
        )
        current_key = (
            _parse_utc(current["observed_at_utc"], "prediction observed_at"),
            str(current["receipt_sha256"]),
        )
        if candidate_key > current_key:
            latest[identity] = prediction

    judged: list[dict[str, Any]] = []
    for identity, prediction in sorted(latest.items()):
        pred_sha = str(prediction["receipt_sha256"])
        settlement = settlement_index.get(pred_sha)
        if not isinstance(settlement, Mapping):
            continue
        if settlement.get("status") == "VOID_NOT_STARTER":
            continue
        if settlement.get("status") != "GRADED":
            raise PitcherKForwardReadoutError("unknown settlement status")
        if int(settlement["game_pk"]) != identity[0] or int(settlement["pitcher_id"]) != identity[1]:
            raise PitcherKForwardReadoutError("prediction/settlement identity mismatch")
        judged.append({
            "game_pk": identity[0],
            "pitcher_id": identity[1],
            "prediction_sha256": pred_sha,
            "observed_at_utc": str(prediction["observed_at_utc"]),
            "line": float(prediction["line"]),
            "candidate_p_over": float(prediction["candidate_p_over"]),
            "market_fair_p_over": float(prediction["market_fair_p_over"]),
            "candidate_log_loss": float(settlement["candidate_log_loss"]),
            "market_log_loss": float(settlement["market_log_loss"]),
            "candidate_minus_market_log_loss": float(settlement["candidate_minus_market_log_loss"]),
            "candidate_brier": float(settlement["candidate_brier"]),
            "market_brier": float(settlement["market_brier"]),
            "outcome_over": bool(settlement["outcome_over"]),
        })
    return judged


def _cluster_mean_ci(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    clusters: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        clusters[int(row["pitcher_id"])].append(float(row["candidate_minus_market_log_loss"]))
    if not clusters:
        raise PitcherKForwardReadoutError("no graded clusters")
    keys = sorted(clusters)
    point_values = [v for key in keys for v in clusters[key]]
    rng = random.Random(BOOT_SEED)
    boots: list[float] = []
    for _ in range(BOOT_REPS):
        sampled = [keys[rng.randrange(len(keys))] for _ in keys]
        values = [v for key in sampled for v in clusters[key]]
        boots.append(sum(values) / len(values))
    alpha = (1.0 - CI_LEVEL) / 2.0
    return {
        "value": sum(point_values) / len(point_values),
        "lo": _quantile(boots, alpha),
        "hi": _quantile(boots, 1.0 - alpha),
        "clusters": len(keys),
        "n": len(point_values),
        "reps": BOOT_REPS,
        "seed": BOOT_SEED,
        "ci": CI_LEVEL,
    }


def build_readout(
    predictions: Sequence[Mapping[str, Any]],
    settlements: Sequence[Mapping[str, Any]],
    *,
    protocol_path: str | Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    judged = select_judged_units(predictions, settlements)
    if len(judged) < MIN_GRADED_UNITS:
        raise PitcherKForwardReadoutError(
            f"INSUFFICIENT_GRADED_UNITS:{len(judged)}<{MIN_GRADED_UNITS}"
        )
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    if protocol.get("schema") != "SPORTSEDGE_MLB_PITCHER_K_FORWARD_VALIDATION_V1":
        raise PitcherKForwardReadoutError("forward protocol identity mismatch")
    if protocol.get("status") != "FROZEN_BEFORE_FIRST_PROSPECTIVE_PREDICTION":
        raise PitcherKForwardReadoutError("forward protocol status mismatch")
    evaluation = protocol.get("evaluation") or {}
    if int(evaluation.get("minimum_graded_units") or -1) != MIN_GRADED_UNITS:
        raise PitcherKForwardReadoutError("minimum graded units mismatch")
    bootstrap = evaluation.get("bootstrap") or {}
    if (
        bootstrap.get("cluster") != "pitcher_id"
        or int(bootstrap.get("reps") or -1) != BOOT_REPS
        or int(bootstrap.get("seed") or -1) != BOOT_SEED
        or float(bootstrap.get("ci") or -1) != CI_LEVEL
    ):
        raise PitcherKForwardReadoutError("bootstrap contract mismatch")

    ci = _cluster_mean_ci(judged)
    candidate_ll = sum(r["candidate_log_loss"] for r in judged) / len(judged)
    market_ll = sum(r["market_log_loss"] for r in judged) / len(judged)
    candidate_brier = sum(r["candidate_brier"] for r in judged) / len(judged)
    market_brier = sum(r["market_brier"] for r in judged) / len(judged)
    passes = (
        len(judged) >= MIN_GRADED_UNITS
        and float(ci["hi"]) < 0.0
        and candidate_brier <= market_brier
    )
    readout = {
        "schema": READOUT_SCHEMA,
        "status": "FINAL_ONE_LOOK_COMPLETE",
        "fit_sha256": FIT_SHA256,
        "protocol_sha256": file_sha256(protocol_path),
        "selection_rule": "LAST_PROSPECTIVELY_CAPTURED_PAIRED_PRE_FIRST_PITCH_PREDICTION_PER_GAME_PITCHER",
        "graded_units": len(judged),
        "unique_pitchers": len({int(r["pitcher_id"]) for r in judged}),
        "candidate_mean_log_loss": candidate_ll,
        "market_mean_log_loss": market_ll,
        "candidate_minus_market_log_loss_ci": ci,
        "candidate_mean_brier": candidate_brier,
        "market_mean_brier": market_brier,
        "passes_forward_validation_gate": passes,
        "blockers": [] if passes else [
            reason for condition, reason in (
                (float(ci["hi"]) < 0.0, "LOG_LOSS_CI_NOT_ENTIRELY_BELOW_ZERO"),
                (candidate_brier <= market_brier, "CANDIDATE_BRIER_WORSE_THAN_MARKET"),
            ) if not condition
        ],
        "judged_prediction_sha256": [str(r["prediction_sha256"]) for r in judged],
        "authority": {
            "forward_validation_complete": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
        "next_step": (
            "SEPARATE_ACTIVATION_REVIEW_ALLOWED"
            if passes
            else "KEEP_CURRENT_PRODUCTION_PITCHER_K_PATH"
        ),
    }
    readout["readout_sha256"] = canonical_sha256(readout)
    return readout
