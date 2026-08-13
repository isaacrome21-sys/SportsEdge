from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import math
from typing import Any, Iterable, Mapping, Sequence

EXPECTED_MODEL_SHA = "0bdf71e272e406611e241e2427904f3c8e3a9405700f440bedacf0b74ed1580e"
FORWARD_START = date(2026, 8, 13)
MIN_FULL_DAYS = 14
MIN_GAMES = 200
MAX_ABS_CAL_Z = 2.50
MAX_BRIER_DELTA_V5 = 0.0010
MAX_LOGLOSS_DELTA_V5 = 0.0020
MIN_COVERAGE = 0.90
BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0000000001))


class NRFIForwardEvaluationError(RuntimeError):
    pass


def _parse_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NRFIForwardEvaluationError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _z(pred_mean: float, obs_mean: float, n: int) -> float:
    if n <= 0:
        raise NRFIForwardEvaluationError("EMPTY_SAMPLE")
    var = max(pred_mean * (1.0 - pred_mean), 1e-12)
    return abs(obs_mean - pred_mean) / math.sqrt(var / n)


def _brier(ps: Sequence[float], ys: Sequence[int]) -> float:
    return sum((p-y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def _logloss(ps: Sequence[float], ys: Sequence[int]) -> float:
    eps = 1e-12
    return sum(-(y*math.log(min(max(p, eps), 1-eps)) + (1-y)*math.log(min(max(1-p, eps), 1-eps))) for p,y in zip(ps,ys)) / len(ps)


def select_latest_complete_pairs(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for raw in rows:
        r = dict(raw)
        market = str(r.get("market") or "").upper()
        if market not in {"NRFI", "YRFI"}:
            continue
        if str(r.get("model_artifact_sha256") or "") != EXPECTED_MODEL_SHA:
            continue
        if r.get("outcome") is not None or r.get("outcome_attached_at_utc") is not None:
            raise NRFIForwardEvaluationError("PREDICTION_ROW_MUTATED_WITH_OUTCOME")
        g = str(r.get("game_id") or "")
        if not g:
            raise NRFIForwardEvaluationError("GAME_ID_MISSING")
        generated = _parse_utc(str(r.get("generated_at_utc") or ""))
        cutoff = _parse_utc(str(r.get("cutoff_at_utc") or ""))
        if generated >= cutoff:
            raise NRFIForwardEvaluationError("LATE_PREDICTION")
        grouped.setdefault(g, {}).setdefault(market, []).append(r)

    out: list[dict[str, Any]] = []
    for game_id, by_market in grouped.items():
        if "NRFI" not in by_market or "YRFI" not in by_market:
            continue
        nrfi_by_ts = {str(x["generated_at_utc"]): x for x in by_market["NRFI"]}
        yrfi_by_ts = {str(x["generated_at_utc"]): x for x in by_market["YRFI"]}
        common = sorted(set(nrfi_by_ts) & set(yrfi_by_ts), key=_parse_utc)
        if not common:
            continue
        ts = common[-1]
        nrow, yrow = nrfi_by_ts[ts], yrfi_by_ts[ts]
        np, yp = float(nrow["model_p"]), float(yrow["model_p"])
        if abs((np + yp) - 1.0) > 1e-9:
            raise NRFIForwardEvaluationError(f"NRFI_YRFI_NOT_COMPLEMENTS:{game_id}")
        nprov, yprov = dict(nrow.get("provenance") or {}), dict(yrow.get("provenance") or {})
        if nprov != yprov:
            raise NRFIForwardEvaluationError(f"PAIR_PROVENANCE_MISMATCH:{game_id}")
        base_v5 = yprov.get("base_v5_yrfi_p")
        if base_v5 is None:
            raise NRFIForwardEvaluationError(f"V5_COMPARATOR_MISSING:{game_id}")
        out.append({
            "game_id": game_id,
            "generated_at_utc": ts,
            "cutoff_at_utc": yrow["cutoff_at_utc"],
            "v6_yrfi_p": yp,
            "v5_yrfi_p": float(base_v5),
            "feature_contract_sha256": yrow.get("feature_contract_sha256"),
            "source_cutoff": yrow.get("source_cutoff"),
        })
    out.sort(key=lambda r: (r["cutoff_at_utc"], r["game_id"]))
    return out


def evaluate(*, prediction_rows: Iterable[Mapping[str, Any]], outcomes: Mapping[str, int], as_of_date: date, source_available_games: int | None = None) -> dict[str, Any]:
    pairs = select_latest_complete_pairs(prediction_rows)
    observed = [p for p in pairs if p["game_id"] in outcomes]
    for p in observed:
        y = outcomes[p["game_id"]]
        if y not in (0, 1):
            raise NRFIForwardEvaluationError(f"INVALID_OUTCOME:{p['game_id']}")

    ps = [float(p["v6_yrfi_p"]) for p in observed]
    v5 = [float(p["v5_yrfi_p"]) for p in observed]
    ys = [int(outcomes[p["game_id"]]) for p in observed]
    n = len(observed)
    full_days = max(0, (as_of_date - FORWARD_START).days)
    coverage_den = int(source_available_games if source_available_games is not None else len({p["game_id"] for p in pairs}))
    coverage = (n / coverage_den) if coverage_den > 0 else 0.0

    result: dict[str, Any] = {
        "schema_version": "nrfi_v6_forward_evaluation_v1",
        "as_of_date": as_of_date.isoformat(),
        "unique_prediction_games": len(pairs),
        "observed_games": n,
        "full_calendar_days": full_days,
        "coverage": coverage,
        "minimum_days_met": full_days >= MIN_FULL_DAYS,
        "minimum_games_met": n >= MIN_GAMES,
        "coverage_gate_pass": coverage >= MIN_COVERAGE,
        "model_artifact_sha256": EXPECTED_MODEL_SHA,
        "eligible": False,
        "reasons": [],
    }
    if n == 0:
        result["reasons"].append("FORWARD_SHADOW_NO_OBSERVED_OUTCOMES")
        return result

    pred_mean, obs_mean = sum(ps)/n, sum(ys)/n
    overall_z = _z(pred_mean, obs_mean, n)
    brier_v6, brier_v5 = _brier(ps, ys), _brier(v5, ys)
    log_v6, log_v5 = _logloss(ps, ys), _logloss(v5, ys)
    result.update({
        "predicted_yrfi_rate": pred_mean,
        "observed_yrfi_rate": obs_mean,
        "overall_abs_calibration_z": overall_z,
        "overall_calibration_gate_pass": overall_z <= MAX_ABS_CAL_Z,
        "brier_v6": brier_v6,
        "brier_v5": brier_v5,
        "brier_gate_pass": brier_v6 <= brier_v5 + MAX_BRIER_DELTA_V5,
        "logloss_v6": log_v6,
        "logloss_v5": log_v5,
        "logloss_gate_pass": log_v6 <= log_v5 + MAX_LOGLOSS_DELTA_V5,
    })

    bucket_results = []
    bucket_gate = True
    for lo, hi in BUCKETS:
        idx = [i for i,p in enumerate(ps) if lo <= p < hi]
        if not idx:
            bucket_results.append({"lo":lo,"hi":min(hi,1.0),"n":0,"evaluated":False})
            continue
        bps=[ps[i] for i in idx]; bys=[ys[i] for i in idx]; bn=len(idx)
        bz=_z(sum(bps)/bn, sum(bys)/bn, bn)
        evaluated = bn >= 75
        passed = (bz <= MAX_ABS_CAL_Z) if evaluated else None
        if evaluated and not passed:
            bucket_gate = False
        bucket_results.append({"lo":lo,"hi":min(hi,1.0),"n":bn,"evaluated":evaluated,"abs_calibration_z":bz,"pass":passed})
    result["buckets"] = bucket_results
    result["bucket_calibration_gate_pass"] = bucket_gate

    checks = {
        "minimum_days_met": result["minimum_days_met"],
        "minimum_games_met": result["minimum_games_met"],
        "coverage_gate_pass": result["coverage_gate_pass"],
        "overall_calibration_gate_pass": result["overall_calibration_gate_pass"],
        "bucket_calibration_gate_pass": result["bucket_calibration_gate_pass"],
        "brier_gate_pass": result["brier_gate_pass"],
        "logloss_gate_pass": result["logloss_gate_pass"],
    }
    result["reasons"] = [k for k,v in checks.items() if not v]
    result["eligible"] = all(checks.values())
    return result
