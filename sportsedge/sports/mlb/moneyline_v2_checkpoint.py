"""Deterministic fixed-checkpoint evaluation for MLB MONEYLINE Promotion Evidence V2.

The evaluator is intentionally downstream of immutable completed forward evidence.
It never changes Model_P, a decision, a quote, deployment eligibility, stake size,
or OFFICIAL state. It only produces hash-bound checkpoint receipts at the frozen
50/100/150 graded-bet prefixes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from math import isfinite, log, sqrt
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from sportsedge.mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)

CHECKPOINT_VERSION = "mlb_moneyline_promotion_evidence_v2_checkpoint_v1"
POLICY_PATH = Path("config/promotion_evidence_policy_v2.json")
CHECKPOINTS = (50, 100, 150)


class MLBMoneylineV2CheckpointError(ValueError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineV2CheckpointError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineV2CheckpointError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2CheckpointError(f"{field}: numeric value required") from exc
    if not isfinite(out):
        raise MLBMoneylineV2CheckpointError(f"{field}: finite value required")
    return out


def _load_policy(path: str | Path = POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineV2CheckpointError("promotion policy unreadable") from exc
    if not isinstance(value, dict) or value.get("policy_id") != "PROMOTION_EVIDENCE_POLICY_V2":
        raise MLBMoneylineV2CheckpointError("promotion policy mismatch")
    forward = value.get("forward_capture") or {}
    inference = forward.get("clv_inference") or {}
    checkpoints = value.get("checkpoints") or {}
    if checkpoints.get("evaluate_only_at_graded_counts") != [50, 100, 150]:
        raise MLBMoneylineV2CheckpointError("fixed checkpoint policy drift")
    if (
        float(inference.get("confidence_level", -1)) != 0.95
        or inference.get("standard_error") != "CR1_CLUSTER_BY_SLATE_DATE"
        or inference.get("cluster_key") != "slate_date"
        or inference.get("reference_distribution") != "STUDENT_T_G_MINUS_1"
        or int(inference.get("minimum_clusters_for_interval", -1)) != 5
        or inference.get("continuous_peeking_for_promotion") is not False
    ):
        raise MLBMoneylineV2CheckpointError("CLV inference policy drift")
    return value


def _t975(df: int) -> float:
    # Exact 0.975 Student-t critical values for the small-df region that matters
    # to the frozen minimum-cluster policy. Above 30, a third-order asymptotic
    # expansion is deterministic and more than sufficient for checkpoint signs.
    table = {
        1: 12.7062047364, 2: 4.3026527297, 3: 3.1824463053, 4: 2.7764451052,
        5: 2.5705818356, 6: 2.4469118511, 7: 2.3646242510, 8: 2.3060041352,
        9: 2.2621571629, 10: 2.2281388520, 11: 2.2009851601, 12: 2.1788128297,
        13: 2.1603686565, 14: 2.1447866879, 15: 2.1314495456, 16: 2.1199052992,
        17: 2.1098155778, 18: 2.1009220402, 19: 2.0930240544, 20: 2.0859634473,
        21: 2.0796138447, 22: 2.0738730679, 23: 2.0686576104, 24: 2.0638985616,
        25: 2.0595385528, 26: 2.0555294386, 27: 2.0518305165, 28: 2.0484071418,
        29: 2.0452296421, 30: 2.0422724563,
    }
    if df < 1:
        raise MLBMoneylineV2CheckpointError("Student-t degrees of freedom invalid")
    if df in table:
        return table[df]
    z = 1.959963984540054
    d = float(df)
    return (
        z
        + (z**3 + z) / (4.0 * d)
        + (5.0 * z**5 + 16.0 * z**3 + 3.0 * z) / (96.0 * d**2)
        + (3.0 * z**7 + 19.0 * z**5 + 17.0 * z**3 - 15.0 * z) / (384.0 * d**3)
    )


def _cr1_cluster_mean_ci(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "cluster_count": 0,
            "mean": None,
            "standard_error": None,
            "ci_lower": None,
            "ci_upper": None,
            "status": "NO_VALID_CLOSES",
        }
    xs = [_finite(row.get("clv_probability_points"), "clv_probability_points") for row in rows]
    clusters: dict[str, list[float]] = defaultdict(list)
    for row, x in zip(rows, xs):
        key = str(row.get("slate_date") or "")
        if not key:
            raise MLBMoneylineV2CheckpointError("slate_date required for CLV clustering")
        clusters[key].append(x)
    mean = fmean(xs)
    g = len(clusters)
    if g < 5:
        return {
            "n": len(xs),
            "cluster_count": g,
            "mean": mean,
            "standard_error": None,
            "ci_lower": None,
            "ci_upper": None,
            "status": "INSUFFICIENT_CLUSTERS_FOR_INTERVAL",
        }
    scores = [sum(x - mean for x in values) for values in clusters.values()]
    variance = (g / (g - 1.0)) * sum(score * score for score in scores) / (len(xs) ** 2)
    se = sqrt(max(0.0, variance))
    critical = _t975(g - 1)
    return {
        "n": len(xs),
        "cluster_count": g,
        "mean": mean,
        "standard_error": se,
        "student_t_df": g - 1,
        "student_t_critical_975": critical,
        "ci_lower": mean - critical * se,
        "ci_upper": mean + critical * se,
        "status": "AVAILABLE",
    }


def _ece(ps: list[float], ys: list[int], bins: int = 10) -> float:
    total = 0.0
    n = len(ps)
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        members = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if members:
            total += len(members) / n * abs(fmean(p for p, _ in members) - fmean(y for _, y in members))
    return total


def _selection_conditioned_diagnostics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    # These are diagnostics on edge-selected bets, not the unbiased calibration
    # holdout required before authority. They are deliberately not used to pass
    # the calibration gate.
    ps = [_finite(row.get("model_p"), "model_p") for row in rows]
    ys = [int(row.get("outcome")) for row in rows]
    if any(not 0.0 < p < 1.0 for p in ps) or any(y not in (0, 1) for y in ys):
        raise MLBMoneylineV2CheckpointError("model_p/outcome invalid")
    eps = 1e-15
    return {
        "n": len(rows),
        "brier": fmean((p - y) ** 2 for p, y in zip(ps, ys)),
        "log_loss": -fmean(y * log(max(p, eps)) + (1 - y) * log(max(1 - p, eps)) for p, y in zip(ps, ys)),
        "ece_10_bin": _ece(ps, ys, 10),
        "status": "SELECTION_CONDITIONED_DIAGNOSTIC_NOT_CALIBRATION_AUTHORITY",
    }


def _validate_rows(
    rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen_games: set[int] = set()
    artifact: str | None = None
    for raw in rows:
        row = dict(raw)
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise MLBMoneylineV2CheckpointError(str(exc)) from exc
        if row.get("status") != "FORWARD_EVIDENCE_COMPLETE_V2":
            raise MLBMoneylineV2CheckpointError("only completed V2 evidence is admissible")
        if row.get("graded_bet") is not True or row.get("evidence_counts") is not True:
            raise MLBMoneylineV2CheckpointError("completed V2 row must be a counted graded bet")
        if row.get("promotion_authority") is not False:
            raise MLBMoneylineV2CheckpointError("evidence row authority flag invalid")
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2CheckpointError("game_pk invalid") from exc
        if game_pk in seen_games:
            raise MLBMoneylineV2CheckpointError(f"DUPLICATE_OR_MUTATED_EVIDENCE_ROW:{game_pk}")
        seen_games.add(game_pk)
        current_artifact = str(row.get("model_artifact_sha256") or "")
        if len(current_artifact) != 64:
            raise MLBMoneylineV2CheckpointError("model artifact binding missing")
        if artifact is None:
            artifact = current_artifact
        elif current_artifact != artifact:
            raise MLBMoneylineV2CheckpointError("evidence clock mixes model artifacts")
        start = _ts(row.get("event_start_ts"), "event_start_ts")
        frozen = _ts(row.get("decision_frozen_at_utc"), "decision_frozen_at_utc")
        if not frozen < start:
            raise MLBMoneylineV2CheckpointError("decision not frozen before event start")
        slate = str(row.get("slate_date") or "")
        try:
            slate_date = date.fromisoformat(slate)
        except ValueError as exc:
            raise MLBMoneylineV2CheckpointError("slate_date invalid") from exc
        if slate_date != start.date():
            raise MLBMoneylineV2CheckpointError("slate_date must equal UTC event-start date")
        outcome = int(row.get("outcome", -1))
        if outcome not in (0, 1):
            raise MLBMoneylineV2CheckpointError("outcome invalid")
        _finite(row.get("paper_roi_fraction_per_1u"), "paper_roi_fraction_per_1u")
        close_status = str(row.get("close_status") or "")
        if close_status == "AVAILABLE":
            _finite(row.get("clv_probability_points"), "clv_probability_points")
            close_ts = _ts(row.get("close_observed_at_utc"), "close_observed_at_utc")
            if not close_ts < start:
                raise MLBMoneylineV2CheckpointError("close captured after event start")
            _finite(row.get("close_home_odds"), "close_home_odds")
            _finite(row.get("close_away_odds"), "close_away_odds")
        elif close_status == "MISSING":
            if row.get("clv_probability_points") is not None:
                raise MLBMoneylineV2CheckpointError("missing close cannot carry CLV")
        else:
            raise MLBMoneylineV2CheckpointError("close_status invalid")
        row["_record_sha256"] = _sha256(row)
        ordered.append(row)
    ordered.sort(key=lambda row: (_ts(row["decision_frozen_at_utc"], "decision_frozen_at_utc"), int(row["game_pk"])))
    return ordered


def _prefix_sha(rows: list[Mapping[str, Any]]) -> str:
    payload = [str(row["_record_sha256"]) for row in rows]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def _metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    closes = [row for row in rows if row.get("close_status") == "AVAILABLE"]
    roi = [_finite(row.get("paper_roi_fraction_per_1u"), "paper_roi_fraction_per_1u") for row in rows]
    return {
        "graded_bets": len(rows),
        "distinct_games": len({int(row["game_pk"]) for row in rows}),
        "slate_clusters": len({str(row["slate_date"]) for row in rows}),
        "close_rows": len(closes),
        "close_coverage": len(closes) / len(rows) if rows else 0.0,
        "mean_clv_probability_points": fmean(float(row["clv_probability_points"]) for row in closes) if closes else None,
        "clv_cr1_student_t_95": _cr1_cluster_mean_ci(closes),
        "mean_paper_roi_fraction_per_1u": fmean(roi) if roi else None,
        "selection_conditioned_model_diagnostics": _selection_conditioned_diagnostics(rows) if rows else None,
    }


def evaluate_v2_checkpoints(
    rows: Iterable[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    lane = dict(binding or load_forward_lane_binding())
    active_policy = dict(policy or _load_policy())
    data = _validate_rows(rows, lane)
    policy_checkpoints = active_policy["checkpoints"]
    kill = active_policy["kill_and_demotion_rules"]
    receipts: list[dict[str, Any]] = []
    prior_chain_ok = True

    for count in CHECKPOINTS:
        if len(data) < count:
            break
        prefix = data[:count]
        metrics = _metrics(prefix)
        ci = metrics["clv_cr1_student_t_95"]
        close_coverage = float(metrics["close_coverage"])
        roi = float(metrics["mean_paper_roi_fraction_per_1u"])
        mean_clv = metrics["mean_clv_probability_points"]
        demotion_reasons: list[str] = []
        if close_coverage < 0.90:
            demotion_reasons.append("CLOSE_COVERAGE_BELOW_0_90")
        if roi < -0.075:
            demotion_reasons.append("ROI_BELOW_MINUS_0_075")
        if ci.get("status") == "AVAILABLE" and float(ci["ci_upper"]) < 0.0:
            demotion_reasons.append("CLV_95_CI_UPPER_BELOW_ZERO")

        cfg = policy_checkpoints[f"checkpoint_{count}"]
        criteria: dict[str, bool] = {
            "min_graded_bets": int(metrics["graded_bets"]) >= int(cfg["min_graded_bets"]),
            "min_distinct_games": int(metrics["distinct_games"]) >= int(cfg["min_distinct_games"]),
            "min_slate_clusters": int(metrics["slate_clusters"]) >= int(cfg["min_slate_clusters"]),
            "min_close_coverage": close_coverage >= float(cfg["min_close_coverage"]),
            "max_roi_loss_fraction": roi >= -float(cfg["max_roi_loss_fraction"]),
        }
        if count == 50:
            criteria["min_mean_clv_pp"] = mean_clv is not None and float(mean_clv) >= float(cfg["min_mean_clv_pp"])
            criteria["frozen_lane_definition"] = bool(lane.get("lane_definition_sha256"))
            criteria["genuine_model_p_from_frozen_artifact"] = len({str(row["model_artifact_sha256"]) for row in prefix}) == 1
            criteria["working_two_sided_pregame_capture"] = all(
                row.get("entry_home_odds") is not None and row.get("entry_away_odds") is not None for row in prefix
            )
            criteria["working_two_sided_close_capture"] = close_coverage >= float(cfg["min_close_coverage"])
        elif count == 150:
            criteria["clv_interval_available"] = ci.get("status") == "AVAILABLE"
            criteria["clv_ci_lower_pp_must_be_above"] = (
                ci.get("status") == "AVAILABLE" and float(ci["ci_lower"]) > float(cfg["clv_ci_lower_pp_must_be_above"])
            )

        checkpoint_pass = all(criteria.values()) and not demotion_reasons and prior_chain_ok
        if count == 50:
            disposition = "PROBATION_CANDIDATE" if checkpoint_pass else "PAPER_CONTINUE"
        elif count == 100:
            disposition = "PROBATION_CONTINUE_CANDIDATE" if checkpoint_pass else "PAPER_CONTINUE"
        else:
            disposition = "OFFICIAL_CANDIDATE_EVIDENCE_PASS" if checkpoint_pass else "PAPER_CONTINUE"
        if not checkpoint_pass:
            prior_chain_ok = False

        receipt = {
            "schema_version": CHECKPOINT_VERSION,
            "checkpoint_graded_count": count,
            "target_state": cfg["target_state"],
            "disposition": disposition,
            "checkpoint_pass": checkpoint_pass,
            "sequential_ladder_pass": prior_chain_ok,
            "criteria": criteria,
            "demotion_reasons": demotion_reasons,
            "metrics": metrics,
            "lane_id": lane["lane_id"],
            "lane_definition_sha256": lane["lane_definition_sha256"],
            "market_definition_sha256": lane["market_definition_sha256"],
            "policy_id": lane["policy_id"],
            "policy_sha256": lane["policy_sha256"],
            "model_artifact_sha256": str(prefix[0]["model_artifact_sha256"]),
            "evidence_prefix_sha256": _prefix_sha(prefix),
            "first_decision_frozen_at_utc": str(prefix[0]["decision_frozen_at_utc"]),
            "last_decision_frozen_at_utc": str(prefix[-1]["decision_frozen_at_utc"]),
            "calibration_authority_status": "SEPARATE_UNBIASED_FORWARD_CALIBRATION_REQUIRED",
            "warnings_clearance_status": "SEPARATE_WARNING_CLEARANCE_REQUIRED" if count == 150 else "NOT_APPLICABLE_YET",
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        receipt["receipt_sha256"] = _sha256(receipt)
        receipts.append(receipt)

    next_checkpoint = next((value for value in CHECKPOINTS if len(data) < value), None)
    return {
        "schema_version": CHECKPOINT_VERSION,
        "graded_bets_available": len(data),
        "reached_checkpoints": [r["checkpoint_graded_count"] for r in receipts],
        "next_checkpoint": next_checkpoint,
        "checkpoint_receipts": receipts,
        "status": "CHECKPOINTS_EVALUATED" if receipts else "FORWARD_EVIDENCE_ACCUMULATING",
        "calibration_authority_status": "SEPARATE_UNBIASED_FORWARD_CALIBRATION_REQUIRED",
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
