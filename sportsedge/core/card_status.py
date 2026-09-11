"""Card row status and TRIAL evidence policy (all sports).

TRIAL never creates Model_P. It can only label a row already priced by the
canonical pipeline and carrying a paired no-vig edge. OFFICIAL/PASS semantics
remain promotion-owned and unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

OFFICIAL = "OFFICIAL"
PASS = "PASS"
TRIAL = "TRIAL"
BLOCKED = "BLOCKED"
NO_ENGINE = "NO_ENGINE"
STATUSES = (OFFICIAL, PASS, TRIAL, BLOCKED, NO_ENGINE)
PAPER = "PAPER"
MICRO = "MICRO"


def load_trial_policy(path) -> dict:
    raw = Path(path).read_bytes()
    policy = json.loads(raw)
    if policy.get("policy_id") != "TRIAL_POLICY_V1":
        raise ValueError("TRIAL_POLICY_ID_MISMATCH")
    policy["_sha256"] = hashlib.sha256(raw).hexdigest()
    return policy


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _row(status: str, reasons: list[str], *, stake_units=None, trial_stage=None,
         policy_sha=None, quote: Mapping[str, Any] | None = None,
         stage_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "status": status,
        "reasons": list(dict.fromkeys(reasons)),
        "confidence_allowed": status == OFFICIAL,
        "stake_units": stake_units,
        "trial_stage": trial_stage,
        "trial_policy_sha256": policy_sha,
        "trial_stage_evidence": dict(stage_evidence) if stage_evidence is not None else None,
    }
    if status == TRIAL and quote is not None:
        for field in ("book", "price_american", "retrieved_at", "model_artifact_sha"):
            out[field] = quote.get(field)
    return out


def resolve_row_status(*, engine_exists: bool, model_p, blockers, promoted: bool,
                       edge=None, edge_floor=None, trial_policy=None,
                       quote=None, settled_trial_rows=None) -> dict:
    """Resolve one already-priced decision row.

    ``edge`` must already be on the paired two-sided no-vig, non-push basis used
    by TRIAL_POLICY_V1. This function never derives Model_P or devigs a market.

    MICRO is never caller-selected. When a TRIAL qualifies, its stage is
    recomputed from ``settled_trial_rows`` under the current model/policy clock;
    absent or insufficient evidence therefore resolves to PAPER.
    """
    reasons = list(dict.fromkeys(blockers or []))
    if not engine_exists:
        return _row(NO_ENGINE, ["NO_ENGINE"])
    if model_p is None:
        if not reasons:
            raise ValueError("MISSING_MODEL_P_WITHOUT_REASON")
        if not promoted:
            reasons.append("NOT_PROMOTED")
        return _row(BLOCKED, reasons)
    try:
        p = float(model_p)
    except (TypeError, ValueError) as exc:
        raise ValueError("MODEL_P_OUT_OF_RANGE") from exc
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise ValueError("MODEL_P_OUT_OF_RANGE")

    if not promoted:
        reasons.append("NOT_PROMOTED")
    elif edge_floor is None:
        reasons.append("NO_FROZEN_EDGE_FLOOR")

    if not reasons:
        if edge is None:
            raise ValueError("EDGE_MISSING_FOR_PRICED_ROW")
        if float(edge) < float(edge_floor):
            return _row(PASS, ["BELOW_EDGE_FLOOR"])
        return _row(OFFICIAL, [])

    if trial_policy is None:
        return _row(BLOCKED, reasons)
    allowed_blockers = set(trial_policy["promotion_blockers"])
    if any(reason not in allowed_blockers for reason in reasons):
        return _row(BLOCKED, reasons)

    quote_row = dict(quote or {})
    missing = [field for field in trial_policy["required_row_fields"] if quote_row.get(field) in (None, "")]
    if missing:
        return _row(BLOCKED, reasons + ["TRIAL_ROW_INCOMPLETE"])
    if not _is_sha256(quote_row.get("model_artifact_sha")):
        return _row(BLOCKED, reasons + ["TRIAL_MODEL_ARTIFACT_SHA_INVALID"])
    quote_row["model_artifact_sha"] = str(quote_row["model_artifact_sha"]).lower()
    if edge is None:
        raise ValueError("EDGE_MISSING_FOR_PRICED_ROW")
    trial_edge = float(edge)
    if not math.isfinite(trial_edge):
        raise ValueError("EDGE_INVALID_FOR_PRICED_ROW")
    if trial_edge < float(trial_policy["min_trial_edge"]):
        return _row(BLOCKED, reasons + ["BELOW_TRIAL_THRESHOLD"])

    stage_evidence = trial_stage_for_market(
        list(settled_trial_rows or []),
        trial_policy,
        model_artifact_sha=quote_row["model_artifact_sha"],
    )
    stage = stage_evidence["stage"]
    stake = float(trial_policy["stages"][stage]["stake_units"])
    return _row(
        TRIAL,
        reasons,
        stake_units=stake,
        trial_stage=stage,
        policy_sha=trial_policy.get("_sha256"),
        quote=quote_row,
        stage_evidence=stage_evidence,
    )


def _slate_key(row: Mapping[str, Any]) -> str:
    """Stable cap partition. Callers may use any one canonical slate field."""
    for key in ("slate_id", "slate_date", "slate_date_ct", "slate"):
        value = row.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return "__CALLER_SLATE__"


def _has_explicit_slate(row: Mapping[str, Any]) -> bool:
    return any(row.get(key) not in (None, "") for key in ("slate_id", "slate_date", "slate_date_ct", "slate"))


def apply_trial_cap(rows: list, trial_policy: dict) -> list:
    """Keep top-N TRIAL rows per (sport, slate), highest edge first."""
    cap = int(trial_policy["max_trial_plays_per_sport_per_slate"])
    if cap < 0:
        raise ValueError("TRIAL_CAP_INVALID")
    out = [dict(row) for row in rows]
    groups: dict[tuple[Any, str], list[int]] = {}
    for i, row in enumerate(out):
        if row.get("status") == TRIAL:
            groups.setdefault((row.get("sport"), _slate_key(row)), []).append(i)
    for idxs in groups.values():
        idxs.sort(key=lambda i: (-float(out[i]["edge"]), str(out[i].get("market_id", ""))))
        for i in idxs[cap:]:
            reasons = list(out[i].get("reasons", []))
            if "TRIAL_CAP_EXCEEDED" not in reasons:
                reasons.append("TRIAL_CAP_EXCEEDED")
            out[i].update(
                status=BLOCKED,
                stake_units=None,
                trial_stage=None,
                trial_policy_sha256=None,
                trial_stage_evidence=None,
                reasons=reasons,
            )
    return out


def trial_stage_for_market(settled: list, trial_policy: dict, *, model_artifact_sha: str) -> dict:
    """Compute PAPER/MICRO using only the current frozen evidence clock.

    Rows from older model artifacts or older TRIAL policy hashes are ignored.
    Remaining rows are clustered by ``slate_date`` using the intercept-only CR1
    cluster-robust standard error specified by TRIAL_POLICY_V1.
    """
    current_model_sha = str(model_artifact_sha or "").strip().lower()
    current_policy_sha = str(trial_policy.get("_sha256") or "").strip().lower()
    if not _is_sha256(current_model_sha):
        raise ValueError("TRIAL_MODEL_ARTIFACT_SHA_REQUIRED")
    if not _is_sha256(current_policy_sha):
        raise ValueError("TRIAL_POLICY_SHA_REQUIRED")

    eligible = []
    for raw in settled:
        row = dict(raw)
        if str(row.get("model_artifact_sha") or "").strip().lower() != current_model_sha:
            continue
        if str(row.get("trial_policy_sha256") or "").strip().lower() != current_policy_sha:
            continue
        if row.get("slate_date") in (None, "") or row.get("clv_pp") is None:
            continue
        try:
            clv = float(row["clv_pp"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(clv):
            continue
        row["clv_pp"] = clv
        eligible.append(row)

    rule = trial_policy["stages"][MICRO]
    n = len(eligible)
    clusters: dict[Any, list[float]] = {}
    for row in eligible:
        clusters.setdefault(row["slate_date"], []).append(float(row["clv_pp"]))
    g = len(clusters)
    result = {
        "stage": PAPER,
        "settled": n,
        "slate_clusters": g,
        "mean_clv_pp": None,
        "clv_t_stat": None,
        "model_artifact_sha": current_model_sha,
        "trial_policy_sha256": current_policy_sha,
    }
    if n == 0:
        return result
    mean = sum(float(row["clv_pp"]) for row in eligible) / n
    result["mean_clv_pp"] = mean
    if n < int(rule["min_settled"]) or g < max(2, int(rule["min_slate_clusters"])):
        return result

    cluster_score_ss = sum(sum(x - mean for x in xs) ** 2 for xs in clusters.values())
    variance = (g / (g - 1)) * cluster_score_ss / (n * n)
    if variance <= 0:
        return result
    t_stat = mean / math.sqrt(variance)
    result["clv_t_stat"] = t_stat
    if mean >= float(rule["min_mean_clv_pp"]) and t_stat >= float(rule["min_clv_t_stat"]):
        result["stage"] = MICRO
    return result


def _nonzero(value: Any) -> bool:
    if value in (None, "", "—"):
        return False
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return True


def _valid_probability(value: Any) -> bool:
    try:
        p = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(p) and 0.0 < p < 1.0


def assert_card_integrity(rows: list, trial_policy: dict | None = None) -> None:
    """Raise on any rendered row that violates the frozen status contract."""
    trial_groups: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows):
        status = row.get("status")
        if status not in STATUSES:
            raise ValueError(f"ROW_{i}_UNKNOWN_STATUS")
        if status != OFFICIAL and row.get("confidence") not in (None, "", "—"):
            raise ValueError(f"ROW_{i}_CONFIDENCE_ON_NON_OFFICIAL")
        if status != OFFICIAL and row.get("confidence_allowed") not in (None, False):
            raise ValueError(f"ROW_{i}_CONFIDENCE_FLAG_ON_NON_OFFICIAL")
        if status in (OFFICIAL, PASS, TRIAL) and not _valid_probability(row.get("model_p")):
            raise ValueError(f"ROW_{i}_{status}_WITHOUT_VALID_MODEL_P")
        if status == NO_ENGINE and row.get("model_p") not in (None, "", "—"):
            raise ValueError(f"ROW_{i}_NO_ENGINE_WITH_MODEL_P")
        if status == BLOCKED and not row.get("reasons"):
            raise ValueError(f"ROW_{i}_BLOCKED_WITHOUT_REASON")

        if status in (PASS, BLOCKED, NO_ENGINE):
            for field in ("stake_units", "stake", "units"):
                if _nonzero(row.get(field)):
                    raise ValueError(f"ROW_{i}_STAKE_ON_{status}")

        if status == TRIAL:
            if trial_policy is None:
                raise ValueError(f"ROW_{i}_TRIAL_WITHOUT_POLICY")
            reasons = list(row.get("reasons") or [])
            if set(reasons) != set(trial_policy["promotion_blockers"]):
                raise ValueError(f"ROW_{i}_TRIAL_BLOCKER_INVALID")
            try:
                trial_edge = float(row.get("edge"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"ROW_{i}_TRIAL_EDGE_INVALID") from exc
            if not math.isfinite(trial_edge) or trial_edge < float(trial_policy["min_trial_edge"]):
                raise ValueError(f"ROW_{i}_TRIAL_EDGE_INVALID")
            stage = row.get("trial_stage")
            if stage not in trial_policy["stages"]:
                raise ValueError(f"ROW_{i}_TRIAL_STAGE_INVALID")
            expected_stake = float(trial_policy["stages"][stage]["stake_units"])
            if row.get("stake_units") is None or float(row["stake_units"]) != expected_stake:
                raise ValueError(f"ROW_{i}_TRIAL_STAKE_INVALID")
            for alias in ("stake", "units"):
                if row.get(alias) not in (None, "", "—") and float(row[alias]) != expected_stake:
                    raise ValueError(f"ROW_{i}_TRIAL_STAKE_ALIAS_INVALID")
            for forbidden in ("kelly", "kelly_fraction", "bankroll_fraction"):
                if row.get(forbidden) not in (None, "", "—"):
                    raise ValueError(f"ROW_{i}_TRIAL_{forbidden.upper()}_PROHIBITED")
            if row.get("trial_policy_sha256") != trial_policy.get("_sha256"):
                raise ValueError(f"ROW_{i}_TRIAL_POLICY_HASH_MISMATCH")
            for field in trial_policy["required_row_fields"]:
                if row.get(field) in (None, ""):
                    raise ValueError(f"ROW_{i}_TRIAL_MISSING_{field.upper()}")
            if not _is_sha256(row.get("model_artifact_sha")):
                raise ValueError(f"ROW_{i}_TRIAL_MODEL_ARTIFACT_SHA_INVALID")

            sport = str(row.get("sport") or "").strip().upper()
            if not sport:
                raise ValueError(f"ROW_{i}_TRIAL_SPORT_MISSING")
            if not _has_explicit_slate(row):
                raise ValueError(f"ROW_{i}_TRIAL_SLATE_MISSING")
            group_key = (sport, _slate_key(row))
            trial_groups[group_key] = trial_groups.get(group_key, 0) + 1

            evidence = row.get("trial_stage_evidence")
            if not isinstance(evidence, Mapping):
                raise ValueError(f"ROW_{i}_TRIAL_STAGE_EVIDENCE_MISSING")
            if evidence.get("stage") != stage:
                raise ValueError(f"ROW_{i}_TRIAL_STAGE_EVIDENCE_MISMATCH")
            if str(evidence.get("model_artifact_sha") or "").lower() != str(row.get("model_artifact_sha") or "").lower():
                raise ValueError(f"ROW_{i}_TRIAL_MODEL_CLOCK_MISMATCH")
            if str(evidence.get("trial_policy_sha256") or "").lower() != str(trial_policy.get("_sha256") or "").lower():
                raise ValueError(f"ROW_{i}_TRIAL_POLICY_CLOCK_MISMATCH")
            if stage == MICRO:
                rule = trial_policy["stages"][MICRO]
                if int(evidence.get("settled", -1)) < int(rule["min_settled"]):
                    raise ValueError(f"ROW_{i}_MICRO_SETTLED_INSUFFICIENT")
                if int(evidence.get("slate_clusters", -1)) < int(rule["min_slate_clusters"]):
                    raise ValueError(f"ROW_{i}_MICRO_SLATES_INSUFFICIENT")
                if evidence.get("mean_clv_pp") is None or float(evidence["mean_clv_pp"]) < float(rule["min_mean_clv_pp"]):
                    raise ValueError(f"ROW_{i}_MICRO_CLV_INSUFFICIENT")
                if evidence.get("clv_t_stat") is None or float(evidence["clv_t_stat"]) < float(rule["min_clv_t_stat"]):
                    raise ValueError(f"ROW_{i}_MICRO_TSTAT_INSUFFICIENT")

    if trial_policy is not None:
        cap = int(trial_policy["max_trial_plays_per_sport_per_slate"])
        for (sport, slate), count in trial_groups.items():
            if count > cap:
                raise ValueError(f"TRIAL_CAP_EXCEEDED:{sport}:{slate}:{count}>{cap}")
