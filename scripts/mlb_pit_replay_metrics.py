#!/usr/bin/env python3
"""Deterministic MLB PIT replay scorer bound to MLB_REPLAY_POLICY_V1.

The scorer implements the frozen slate-date one-way cluster-robust CR1 estimator
for CLV and ROI and emits every canonical MLB market, including zero-evidence and
policy-unauthorized dispositions. Missing close observations are excluded from CLV;
non-binary/push/void/unsettled outcomes are excluded from Brier/log-loss; missing
settlements are excluded from ROI. Nothing is synthesized and there is no IID fallback.

This script never imports third-party predictions/results and grants no Model_P,
promotion, floor-freeze, eligibility, Truth Gate, staking, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

POLICY_ID = "MLB_REPLAY_POLICY_V1"
CR1_ESTIMATOR = "ONE_WAY_CLUSTER_ROBUST_CR1"
CLUSTER_KEY = "slate_date_ct"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
    """Intercept-only one-way CR1 estimate for a mean.

    For K=1, the standard CR1 finite-sample correction reduces to G/(G-1):
    Var(mean) = G/(G-1) * sum_g(sum_{i in g}(x_i-xbar))^2 / N^2.
    """
    if len(values) != len(clusters):
        raise ValueError("CR1 value/cluster length mismatch")
    n = len(values)
    if n == 0:
        return {"n": 0, "clusters": 0, "estimate": None, "se_cr1": None, "t_cr1": None, "status": "NO_EVIDENCE"}
    estimate = sum(values) / n
    by_cluster: dict[str, float] = defaultdict(float)
    for value, cluster in zip(values, clusters):
        if not cluster:
            raise ValueError("empty slate_date_ct forbidden")
        by_cluster[cluster] += value - estimate
    g = len(by_cluster)
    if g < 2:
        return {"n": n, "clusters": g, "estimate": estimate, "se_cr1": None, "t_cr1": None, "status": "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK"}
    variance = (g / (g - 1.0)) * sum(score * score for score in by_cluster.values()) / (n * n)
    variance = max(0.0, variance)
    se = math.sqrt(variance)
    t_stat = None if se == 0.0 else estimate / se
    return {"n": n, "clusters": g, "estimate": estimate, "se_cr1": se, "t_cr1": t_stat, "status": "CR1_SCORED"}


def cr1_ratio(numerators: list[float], denominators: list[float], clusters: list[str]) -> dict[str, Any]:
    """One-way CR1 for theta=sum(net_return)/sum(risked_stake).

    The cluster score is sum_g(net_i - theta*risk_i); the derivative of the
    estimating equation is total risk. This keeps the point estimate exactly equal
    to the frozen ROI definition while clustering uncertainty by slate date.
    """
    if not (len(numerators) == len(denominators) == len(clusters)):
        raise ValueError("CR1 ratio input length mismatch")
    n = len(numerators)
    if n == 0:
        return {"n": 0, "clusters": 0, "estimate": None, "se_cr1": None, "t_cr1": None, "total_risk": 0.0, "status": "NO_EVIDENCE"}
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
        return {"n": n, "clusters": g, "estimate": estimate, "se_cr1": None, "t_cr1": None, "total_risk": total_risk, "status": "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK"}
    variance = (g / (g - 1.0)) * sum(score * score for score in by_cluster.values()) / (total_risk * total_risk)
    variance = max(0.0, variance)
    se = math.sqrt(variance)
    t_stat = None if se == 0.0 else estimate / se
    return {"n": n, "clusters": g, "estimate": estimate, "se_cr1": se, "t_cr1": t_stat, "total_risk": total_risk, "status": "CR1_SCORED"}


def score(rows: list[dict[str, str]], *, unauthorized: bool = False) -> dict[str, Any]:
    required_columns = {
        "decision_id", "slate_date_ct", "market", "model_p", "outcome",
        "decision_no_vig_p", "close_no_vig_p", "net_return", "risked_stake",
    }
    if unauthorized:
        return {
            "status": "N_WAY_UNAUTHORIZED_V1",
            "n": len(rows),
            "binary_score_n": 0,
            "brier": None,
            "log_loss": None,
            "clv": cr1_mean([], []),
            "roi": cr1_ratio([], [], []),
        }
    if not rows:
        return {
            "status": "NO_EVIDENCE",
            "n": 0,
            "binary_score_n": 0,
            "brier": None,
            "log_loss": None,
            "clv": cr1_mean([], []),
            "roi": cr1_ratio([], [], []),
        }
    missing = required_columns - set(rows[0])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    ids = [str(row["decision_id"]).strip() for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("duplicate/empty decision_id forbidden")

    model_ps = [required_float(row, "model_p") for row in rows]
    if any(not 0.0 <= p <= 1.0 for p in model_ps):
        raise ValueError("invalid probability/outcome")
    binary_ps: list[float] = []
    binary_ys: list[float] = []
    for row, p in zip(rows, model_ps):
        y = optional_float(row, "outcome")
        if y is None:
            continue
        if y not in (0.0, 1.0):
            raise ValueError("invalid probability/outcome")
        binary_ps.append(p)
        binary_ys.append(y)
    eps = 1e-15
    brier = mean((p - y) ** 2 for p, y in zip(binary_ps, binary_ys))
    logloss = mean(-(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p))) for p, y in zip(binary_ps, binary_ys))

    clv_values: list[float] = []
    clv_clusters: list[str] = []
    roi_net: list[float] = []
    roi_risk: list[float] = []
    roi_clusters: list[str] = []
    for row in rows:
        cluster = str(row.get(CLUSTER_KEY, "")).strip()
        if not cluster:
            raise ValueError("slate_date_ct required")
        decision_p = required_float(row, "decision_no_vig_p")
        if not 0.0 <= decision_p <= 1.0:
            raise ValueError("decision_no_vig_p outside [0,1]")
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
            if risk <= 0.0:
                raise ValueError("risked_stake must be > 0")
            roi_net.append(net)
            roi_risk.append(risk)
            roi_clusters.append(cluster)

    return {
        "status": "SCORED_NOT_PROMOTED",
        "n": len(rows),
        "slate_clusters_all_decisions": len({row[CLUSTER_KEY] for row in rows}),
        "binary_score_n": len(binary_ys),
        "brier": brier,
        "log_loss": logloss,
        "clv": cr1_mean(clv_values, clv_clusters),
        "roi": cr1_ratio(roi_net, roi_risk, roi_clusters),
        "excluded_from_binary_scoring_missing_outcome": len(rows) - len(binary_ys),
        "excluded_from_clv_missing_close": len(rows) - len(clv_values),
        "excluded_from_roi_missing_settlement": len(rows) - len(roi_net),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--policy", type=Path, default=Path("config/mlb_replay_policy_v1.json"))
    ap.add_argument("--catalog", type=Path, default=Path("config/mlb_market_catalog.json"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("policy_id") != POLICY_ID or policy.get("status") != "FROZEN_PRE_REPLAY":
        raise SystemExit("frozen MLB replay policy identity/status mismatch")
    stats = policy.get("statistics", {}).get("primary_standard_error", {})
    if stats.get("estimator") != CR1_ESTIMATOR or stats.get("cluster_key") != CLUSTER_KEY or stats.get("iid_fallback_allowed") is not False:
        raise SystemExit("frozen MLB replay CR1 contract mismatch")

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    canonical_markets = flatten_catalog(catalog)
    canonical_set = set(canonical_markets)
    blocked_nway = unauthorized_markets(policy)
    if not blocked_nway <= canonical_set:
        raise SystemExit("policy contains unauthorized market outside canonical catalog")

    rows = load_rows(args.input)
    seen_ids: set[str] = set()
    by_market: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        market = str(row.get("market", "")).strip().upper()
        if market not in canonical_set:
            raise ValueError(f"non-canonical market in replay input: {market}")
        decision_id = str(row.get("decision_id", "")).strip()
        if not decision_id or decision_id in seen_ids:
            raise ValueError("duplicate/empty decision_id forbidden across replay input")
        seen_ids.add(decision_id)
        by_market[market].append(row)

    market_reports = {
        market: score(by_market.get(market, []), unauthorized=market in blocked_nway)
        for market in canonical_markets
    }
    report = {
        "schema_version": 2,
        "policy_id": POLICY_ID,
        "policy_sha256": sha256_file(args.policy),
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
            "official_status_granted": False,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "markets": len(report["markets"]), "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
