#!/usr/bin/env python3
"""Deterministic MLB PIT replay scorer bound to MLB_REPLAY_POLICY_V1.

This scorer preserves the frozen-policy/blob/commit binding restored on main while
supporting the complete 38-market replay surface. CLV and ROI uncertainty use the
frozen one-way slate-date CR1 estimator with no IID fallback. Missing close,
settlement, or binary outcome evidence is excluded rather than synthesized.

This script never imports third-party predictions/results and grants no Model_P,
Truth Gate, promotion, floor-freeze, eligibility, staking, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

POLICY_ID = "MLB_REPLAY_POLICY_V1"
FROZEN_POLICY_REPO_PATH = "config/mlb_replay_policy_v1.json"
FROZEN_POLICY_GIT_BLOB_SHA = "5f00bd1b2f7cbe5c86070eb7bfa9a847e553d953"
CR1_ESTIMATOR = "ONE_WAY_CLUSTER_ROBUST_CR1"
CLUSTER_KEY = "slate_date_ct"

_REQUIRED_BASE = {
    "decision_id", "slate_date_ct", "market", "model_p", "decision_no_vig_p",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def verify_policy_commit(commit: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("policy commit must be a full 40-hex Git commit SHA")
    try:
        resolved_commit = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip().lower()
        blob = subprocess.run(
            ["git", "rev-parse", f"{resolved_commit}:{FROZEN_POLICY_REPO_PATH}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("policy commit is not resolvable in this Git checkout") from exc
    if blob != FROZEN_POLICY_GIT_BLOB_SHA:
        raise ValueError(f"policy commit does not bind frozen policy blob:{blob}")
    return resolved_commit


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def required_float(row: dict[str, str], key: str) -> float:
    value = str(row.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing numeric value: {key}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"non-finite numeric value: {key}")
    return out


def optional_float(row: dict[str, str], key: str) -> float | None:
    value = str(row.get(key, "")).strip()
    if not value:
        return None
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"non-finite numeric value: {key}")
    return out


def mean(xs: Iterable[float]) -> float | None:
    values = list(xs)
    return sum(values) / len(values) if values else None


def flatten_catalog(catalog: dict[str, Any]) -> list[str]:
    markets: list[str] = []
    for key, raw in catalog.items():
        if key == "schema_version":
            continue
        if not isinstance(raw, list):
            raise ValueError(f"catalog field must be list: {key}")
        markets.extend(str(value).strip().upper() for value in raw)
    if len(markets) != len(set(markets)):
        raise ValueError("duplicate canonical market in catalog")
    if len(markets) != 38:
        raise ValueError(f"expected 38 canonical MLB markets, found {len(markets)}")
    return markets


def unauthorized_markets(policy: dict[str, Any]) -> set[str]:
    tiers = policy.get("benchmark", {}).get("market_tiers", {})
    raw = tiers.get("N_WAY_UNAUTHORIZED_V1", {}).get("markets", [])
    return {str(value).strip().upper() for value in raw}


def cr1_mean(values: list[float], clusters: list[str]) -> dict[str, Any]:
    if len(values) != len(clusters):
        raise ValueError("CR1 value/cluster length mismatch")
    n = len(values)
    if n == 0:
        return {
            "n": 0, "clusters": 0, "estimate": None, "se_cr1": None,
            "t_cr1": None, "status": "NO_EVIDENCE",
        }
    estimate = sum(values) / n
    by_cluster: dict[str, float] = defaultdict(float)
    for value, cluster in zip(values, clusters):
        if not cluster:
            raise ValueError("empty slate_date_ct forbidden")
        by_cluster[cluster] += value - estimate
    g = len(by_cluster)
    if g < 2:
        return {
            "n": n, "clusters": g, "estimate": estimate, "se_cr1": None,
            "t_cr1": None, "status": "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK",
        }
    variance = (g / (g - 1.0)) * sum(v * v for v in by_cluster.values()) / (n * n)
    se = math.sqrt(max(0.0, variance))
    return {
        "n": n, "clusters": g, "estimate": estimate, "se_cr1": se,
        "t_cr1": None if se == 0.0 else estimate / se, "status": "CR1_SCORED",
    }


def cr1_ratio(
    numerators: list[float], denominators: list[float], clusters: list[str]
) -> dict[str, Any]:
    if not (len(numerators) == len(denominators) == len(clusters)):
        raise ValueError("CR1 ratio input length mismatch")
    n = len(numerators)
    if n == 0:
        return {
            "n": 0, "clusters": 0, "estimate": None, "se_cr1": None,
            "t_cr1": None, "total_risk": 0.0, "status": "NO_EVIDENCE",
        }
    if any(risk <= 0.0 for risk in denominators):
        raise ValueError("risked_stake must be > 0 for ROI evidence")
    total_risk = sum(denominators)
    estimate = sum(numerators) / total_risk
    by_cluster: dict[str, float] = defaultdict(float)
    for net, risk, cluster in zip(numerators, denominators, clusters):
        if not cluster:
            raise ValueError("empty slate_date_ct forbidden")
        by_cluster[cluster] += net - estimate * risk
    g = len(by_cluster)
    if g < 2:
        return {
            "n": n, "clusters": g, "estimate": estimate, "se_cr1": None,
            "t_cr1": None, "total_risk": total_risk,
            "status": "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK",
        }
    variance = (
        (g / (g - 1.0))
        * sum(v * v for v in by_cluster.values())
        / (total_risk * total_risk)
    )
    se = math.sqrt(max(0.0, variance))
    return {
        "n": n, "clusters": g, "estimate": estimate, "se_cr1": se,
        "t_cr1": None if se == 0.0 else estimate / se,
        "total_risk": total_risk, "status": "CR1_SCORED",
    }


# Backward-compatible names retained for the restored #800 scorer contract.
def cluster_cr1(values: list[float], clusters: list[str]) -> dict[str, float | int | None]:
    result = cr1_mean(values, clusters)
    return {
        "se": result["se_cr1"],
        "t_stat": result["t_cr1"],
        "clusters": result["clusters"],
    }


def cluster_cr1_ratio(
    numerators: list[float], denominators: list[float], clusters: list[str]
) -> dict[str, float | int | None]:
    result = cr1_ratio(numerators, denominators, clusters)
    return {
        "se": result["se_cr1"],
        "t_stat": result["t_cr1"],
        "clusters": result["clusters"],
    }


def validate_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    missing = _REQUIRED_BASE - set(rows[0])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    decision_ids: set[str] = set()
    observations: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if _REQUIRED_BASE - set(row):
            raise ValueError("row missing required columns")
        if any(not str(row.get(k, "")).strip() for k in _REQUIRED_BASE):
            raise ValueError("blank decision identity/model field forbidden")

        decision_id = str(row["decision_id"]).strip()
        if decision_id in decision_ids:
            raise ValueError("duplicate decision_id forbidden")
        decision_ids.add(decision_id)

        composite_values = tuple(str(row.get(k, "")).strip() for k in ("game_id", "market", "side", "book"))
        if all(composite_values):
            if composite_values in observations:
                raise ValueError("duplicate game/market/side/book observation forbidden")
            observations.add(composite_values)

        model_p = required_float(row, "model_p")
        decision_p = required_float(row, "decision_no_vig_p")
        if not 0.0 <= model_p <= 1.0 or not 0.0 <= decision_p <= 1.0:
            raise ValueError("invalid probability/outcome")

        outcome = optional_float(row, "outcome")
        if outcome is not None and outcome not in (0.0, 1.0):
            raise ValueError("invalid probability/outcome")

        close_p = optional_float(row, "close_no_vig_p")
        if close_p is not None and not 0.0 <= close_p <= 1.0:
            raise ValueError("invalid no-vig probability")

        net_return = optional_float(row, "net_return")
        risk = optional_float(row, "risked_stake")
        if (net_return is None) != (risk is None):
            raise ValueError("net_return and risked_stake must be jointly present or absent")
        if risk is not None:
            if risk < 0.0:
                raise ValueError("negative risked_stake forbidden")
            if risk == 0.0 and net_return != 0.0:
                raise ValueError("nonzero net_return with zero risked_stake forbidden")


def score(
    rows: list[dict[str, str]], *, validated: bool = False, unauthorized: bool = False
) -> dict[str, Any]:
    if unauthorized:
        empty_clv = cr1_mean([], [])
        empty_roi = cr1_ratio([], [], [])
        return {
            "status": "N_WAY_UNAUTHORIZED_V1", "n": len(rows),
            "binary_score_n": 0, "brier": None, "log_loss": None,
            "clv": empty_clv, "roi": empty_roi,
            "mean_clv": None, "clv_cr1_se": None, "clv_t_stat": None,
            "roi_cr1_se": None, "roi_t_stat": None,
            "standard_error_estimator": CR1_ESTIMATOR, "cluster_key": CLUSTER_KEY,
        }
    if not rows:
        return {"status": "NO_EVIDENCE"}
    if not validated:
        validate_rows(rows)

    model_ps = [required_float(row, "model_p") for row in rows]
    binary_ps: list[float] = []
    binary_ys: list[float] = []
    clv_values: list[float] = []
    clv_clusters: list[str] = []
    roi_net: list[float] = []
    roi_risk: list[float] = []
    roi_clusters: list[str] = []

    for row, p in zip(rows, model_ps):
        cluster = str(row.get(CLUSTER_KEY, "")).strip()
        if not cluster:
            raise ValueError("slate_date_ct required")

        outcome = optional_float(row, "outcome")
        if outcome is not None:
            if outcome not in (0.0, 1.0):
                raise ValueError("invalid probability/outcome")
            binary_ps.append(p)
            binary_ys.append(outcome)

        decision_p = required_float(row, "decision_no_vig_p")
        close_p = optional_float(row, "close_no_vig_p")
        if close_p is not None:
            if not 0.0 <= close_p <= 1.0:
                raise ValueError("close_no_vig_p outside [0,1]")
            clv_values.append(close_p - decision_p)
            clv_clusters.append(cluster)

        net = optional_float(row, "net_return")
        risk = optional_float(row, "risked_stake")
        if (net is None) != (risk is None):
            raise ValueError("net_return and risked_stake must be jointly present or absent")
        if net is not None and risk is not None:
            if risk < 0.0:
                raise ValueError("negative risked_stake forbidden")
            if risk == 0.0:
                if net != 0.0:
                    raise ValueError("nonzero net_return with zero risked_stake forbidden")
            else:
                roi_net.append(net)
                roi_risk.append(risk)
                roi_clusters.append(cluster)

    eps = 1e-15
    brier = mean((p - y) ** 2 for p, y in zip(binary_ps, binary_ys))
    logloss = mean(
        -(y * math.log(max(eps, p)) + (1.0 - y) * math.log(max(eps, 1.0 - p)))
        for p, y in zip(binary_ps, binary_ys)
    )
    clv = cr1_mean(clv_values, clv_clusters)
    roi = cr1_ratio(roi_net, roi_risk, roi_clusters)

    return {
        "status": "SCORED_NOT_PROMOTED",
        "n": len(rows),
        "slate_clusters": len({str(row[CLUSTER_KEY]).strip() for row in rows}),
        "slate_clusters_all_decisions": len({str(row[CLUSTER_KEY]).strip() for row in rows}),
        "binary_score_n": len(binary_ys),
        "brier": brier,
        "log_loss": logloss,
        "clv": clv,
        "roi_detail": roi,
        # "roi" remains the legacy scalar while "roi_detail" carries full CR1 detail.
        # The 38-market orchestrator normalizes either representation below.
        "mean_clv": clv["estimate"],
        "roi": roi["estimate"],
        "clv_cr1_se": clv["se_cr1"],
        "clv_t_stat": clv["t_cr1"],
        "roi_cr1_se": roi["se_cr1"],
        "roi_t_stat": roi["t_cr1"],
        "standard_error_estimator": CR1_ESTIMATOR,
        "cluster_key": CLUSTER_KEY,
        "excluded_from_binary_scoring_missing_outcome": len(rows) - len(binary_ys),
        "excluded_from_clv_missing_close": len(rows) - len(clv_values),
        "excluded_from_roi_missing_settlement": len(rows) - len(roi_net),
    }


def replay_score(
    rows: list[dict[str, str]], *, unauthorized: bool = False
) -> dict[str, Any]:
    """38-market representation with nested CLV/ROI CR1 records."""
    if unauthorized:
        return score(rows, unauthorized=True)
    if not rows:
        return {
            "status": "NO_EVIDENCE", "n": 0, "binary_score_n": 0,
            "brier": None, "log_loss": None,
            "clv": cr1_mean([], []), "roi": cr1_ratio([], [], []),
            "excluded_from_binary_scoring_missing_outcome": 0,
            "excluded_from_clv_missing_close": 0,
            "excluded_from_roi_missing_settlement": 0,
        }
    base = score(rows)
    return {
        "status": base["status"],
        "n": base["n"],
        "slate_clusters": base["slate_clusters"],
        "slate_clusters_all_decisions": base["slate_clusters_all_decisions"],
        "binary_score_n": base["binary_score_n"],
        "brier": base["brier"],
        "log_loss": base["log_loss"],
        "clv": base["clv"],
        "roi": base["roi_detail"],
        "mean_clv": base["mean_clv"],
        "roi_estimate": base["roi"],
        "clv_cr1_se": base["clv_cr1_se"],
        "clv_t_stat": base["clv_t_stat"],
        "roi_cr1_se": base["roi_cr1_se"],
        "roi_t_stat": base["roi_t_stat"],
        "standard_error_estimator": base["standard_error_estimator"],
        "cluster_key": base["cluster_key"],
        "excluded_from_binary_scoring_missing_outcome": base["excluded_from_binary_scoring_missing_outcome"],
        "excluded_from_clv_missing_close": base["excluded_from_clv_missing_close"],
        "excluded_from_roi_missing_settlement": base["excluded_from_roi_missing_settlement"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--policy", type=Path, default=Path(FROZEN_POLICY_REPO_PATH))
    ap.add_argument("--policy-commit", required=True, help="full Git commit SHA containing the frozen policy blob")
    ap.add_argument("--catalog", type=Path, default=Path("config/mlb_market_catalog.json"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("policy_id") != POLICY_ID or policy.get("status") != "FROZEN_PRE_REPLAY":
        raise SystemExit("frozen MLB replay policy identity/status mismatch")
    stats = policy.get("statistics", {}).get("primary_standard_error", {})
    if (
        stats.get("estimator") != CR1_ESTIMATOR
        or stats.get("cluster_key") != CLUSTER_KEY
        or stats.get("iid_fallback_allowed") is not False
    ):
        raise SystemExit("frozen MLB replay CR1 contract mismatch")

    actual_blob = git_blob_sha(args.policy)
    if actual_blob != FROZEN_POLICY_GIT_BLOB_SHA:
        raise SystemExit(f"frozen MLB replay policy blob mismatch:{actual_blob}")
    try:
        policy_commit = verify_policy_commit(args.policy_commit)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    canonical_markets = flatten_catalog(catalog)
    canonical_set = set(canonical_markets)
    blocked_nway = unauthorized_markets(policy)
    if not blocked_nway <= canonical_set:
        raise SystemExit("policy contains unauthorized market outside canonical catalog")

    rows = load_rows(args.input)
    validate_rows(rows)
    by_market: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        market = str(row.get("market", "")).strip().upper()
        if market not in canonical_set:
            raise ValueError(f"non-canonical market in replay input: {market}")
        by_market[market].append(row)

    market_reports = {
        market: replay_score(by_market.get(market, []), unauthorized=market in blocked_nway)
        for market in canonical_markets
    }
    report = {
        "schema_version": 2,
        "policy_id": POLICY_ID,
        "policy_sha256": sha256_file(args.policy),
        "policy_git_blob_sha": actual_blob,
        "policy_git_commit": policy_commit,
        "catalog_sha256": sha256_file(args.catalog),
        "input_sha256": sha256_file(args.input),
        "canonical_market_count": len(canonical_markets),
        "markets_with_decisions": sum(bool(by_market.get(market)) for market in canonical_markets),
        "cr1_contract": {
            "estimator": CR1_ESTIMATOR,
            "cluster_key": CLUSTER_KEY,
            "iid_fallback_allowed": False,
        },
        "markets": market_reports,
        "governance": {
            "third_party_predictions_imported": False,
            "historical_backfill_promoted": False,
            "model_p_created": False,
            "floor_derived": False,
            "eligibility_changed": False,
            "truth_gate_pass_granted": False,
            "staking_authority_granted": False,
            "official_status_granted": False,
            "forward_evidence_created": False,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "markets": len(report["markets"]), "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
