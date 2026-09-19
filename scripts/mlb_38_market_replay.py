#!/usr/bin/env python3
"""Run the frozen MLB replay plumbing across the complete 38-market catalog.

Inputs are immutable provider snapshots plus durable PIT model observations. The run
materializes direct provider markets, executes the frozen promotion replay bridge,
converts eligible rows into deterministic scoring input, applies the frozen CR1
scorer, and emits a per-market disposition matrix.

The bundle is evidence preparation only. It cannot manufacture missing historical
quotes, create forward evidence, lower/freeze floors, change eligibility, grant a
Truth Gate PASS, stake a wager, or label anything OFFICIAL.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.mlb_pit_replay_metrics import (flatten_catalog, git_blob_sha, replay_score, sha256_file, unauthorized_markets, validate_rows, verify_policy_commit, FROZEN_POLICY_GIT_BLOB_SHA)
except ModuleNotFoundError:
    from mlb_pit_replay_metrics import (flatten_catalog, git_blob_sha, replay_score, sha256_file, unauthorized_markets, validate_rows, verify_policy_commit, FROZEN_POLICY_GIT_BLOB_SHA)
from sportsedge.mlb_promotion_replay import build_mlb_promotion_replay
from sportsedge.sports.mlb.provider_market_catalog import (
    NO_DIRECT_PROVIDER_KEY,
    PROVIDER_KEY_BY_MARKET,
    validate_provider_coverage,
)
from sportsedge.sports.mlb.the_odds_api_materializer import materialize_persisted_snapshot

ARCHIVE_SCHEMA = "MLB_THE_ODDS_API_HISTORICAL_ARCHIVE_V1"
ARCHIVE_SOURCE = "THE_ODDS_API_HISTORICAL"
SCORER_FIELDS = (
    "decision_id",
    "game_id",
    "slate_date_ct",
    "market",
    "side",
    "book",
    "model_p",
    "outcome",
    "decision_no_vig_p",
    "close_no_vig_p",
    "net_return",
    "risked_stake",
)


class MLB38MarketReplayError(ValueError):
    pass


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MLB38MarketReplayError(f"JSON_UNREADABLE:{path}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hex64(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise MLB38MarketReplayError(f"SHA256_INVALID:{field}")
    return text


def _load_observations(path: Path) -> list[dict[str, Any]]:
    payload = _json(path)
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, Mapping) and isinstance(payload.get("observations"), list):
        raw = payload["observations"]
    else:
        raise MLB38MarketReplayError("PIT_OBSERVATIONS_LIST_REQUIRED")
    observations = [dict(row) for row in raw if isinstance(row, Mapping)]
    if len(observations) != len(raw):
        raise MLB38MarketReplayError("PIT_OBSERVATION_MAPPING_REQUIRED")
    return observations


def _snapshot_dirs(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        raise MLB38MarketReplayError("ARCHIVE_ROOT_REQUIRED")
    dirs = sorted({path.parent for path in root.rglob("snapshot.meta.json")})
    if not dirs:
        raise MLB38MarketReplayError("ARCHIVE_EMPTY_NO_SNAPSHOTS")
    return dirs


def _materialize_archive(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    hard_failures: list[dict[str, Any]] = []
    for directory in _snapshot_dirs(root):
        meta_path = directory / "snapshot.meta.json"
        raw_path = directory / "snapshot.json"
        meta = _json(meta_path)
        if not isinstance(meta, Mapping):
            raise MLB38MarketReplayError(f"ARCHIVE_META_MAPPING_REQUIRED:{directory}")
        if meta.get("schema") != ARCHIVE_SCHEMA or meta.get("source") != ARCHIVE_SOURCE:
            raise MLB38MarketReplayError(f"ARCHIVE_IDENTITY_INVALID:{directory}")
        if meta.get("interpolated") is not False or meta.get("reconstructed") is not False:
            raise MLB38MarketReplayError(f"ARCHIVE_RECONSTRUCTED_OR_INTERPOLATED_FORBIDDEN:{directory}")
        try:
            raw = raw_path.read_bytes()
        except OSError as exc:
            raise MLB38MarketReplayError(f"ARCHIVE_RAW_UNREADABLE:{directory}") from exc
        expected = _hex64(meta.get("payload_sha256"), f"{directory}:payload_sha256")
        actual = sha256(raw).hexdigest()
        if actual != expected:
            raise MLB38MarketReplayError(f"ARCHIVE_SHA256_MISMATCH:{directory}")
        result = materialize_persisted_snapshot(raw, source_sha256=expected)
        observed_at = str(result.get("observed_at") or "")
        provider_timestamp = str(meta.get("provider_timestamp") or "")
        if provider_timestamp and observed_at.replace("+00:00", "Z") != provider_timestamp.replace("+00:00", "Z"):
            raise MLB38MarketReplayError(f"ARCHIVE_PROVIDER_TIMESTAMP_MISMATCH:{directory}")
        snapshots.append({
            "path": str(directory),
            "payload_sha256": actual,
            "status": result["status"],
            "quote_count": result["quote_count"],
            "quote_count_by_market": result["quote_count_by_market"],
            "failure_count": result["failure_count"],
        })
        if result["status"] == "BLOCKED_PROVIDER_SNAPSHOT":
            hard_failures.append({"path": str(directory), "failures": result["failures"]})
        quotes.extend(result["quotes"])
    manifest = {
        "schema_version": 1,
        "provider": "THE_ODDS_API",
        "archive_schema": ARCHIVE_SCHEMA,
        "snapshot_count": len(snapshots),
        "canonical_quote_count": len(quotes),
        "hard_failure_count": len(hard_failures),
        "status": "BLOCKED_PROVIDER_SNAPSHOT" if hard_failures else "MATERIALIZED",
        "snapshots": snapshots,
        "hard_failures": hard_failures,
        "promotion_authority": False,
    }
    if hard_failures:
        raise MLB38MarketReplayError("ARCHIVE_CONTAINS_BLOCKED_PROVIDER_SNAPSHOT")
    return quotes, manifest


def _to_scorer_row(row: Mapping[str, Any]) -> dict[str, str]:
    outcome_name = str(row.get("settled_outcome") or "").upper()
    outcome = "1" if outcome_name == "WIN" else "0" if outcome_name == "LOSS" else ""
    roi = row.get("roi_per_dollar")
    return {
        "decision_id": str(row.get("observation_key") or ""),
        "game_id": str(row.get("game_id") or ""),
        "slate_date_ct": str(row.get("slate_date_ct") or ""),
        "market": str(row.get("market") or "").upper(),
        "side": str(row.get("side") or "").upper(),
        "book": str(row.get("book_key") or "").lower(),
        "model_p": str(row.get("model_p") if row.get("model_p") is not None else ""),
        "outcome": outcome,
        "decision_no_vig_p": str(row.get("decision_no_vig_p") if row.get("decision_no_vig_p") is not None else ""),
        "close_no_vig_p": "" if row.get("close_no_vig_p") is None else str(row.get("close_no_vig_p")),
        "net_return": "" if roi is None else str(roi),
        "risked_stake": "" if roi is None else "1.0",
    }


def _write_scorer_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _score_all(
    *, scorer_rows: list[dict[str, str]], markets: list[str], policy: Mapping[str, Any],
    policy_path: Path, catalog_path: Path, scorer_csv: Path, policy_commit: str,
) -> dict[str, Any]:
    actual_blob = git_blob_sha(policy_path)
    if actual_blob != FROZEN_POLICY_GIT_BLOB_SHA:
        raise MLB38MarketReplayError(f"FROZEN_POLICY_GIT_BLOB_MISMATCH:{actual_blob}")
    try:
        bound_commit = verify_policy_commit(policy_commit)
    except ValueError as exc:
        raise MLB38MarketReplayError(f"FROZEN_POLICY_COMMIT_BINDING_FAILED:{exc}") from exc
    validate_rows(scorer_rows)
    blocked_nway = unauthorized_markets(dict(policy))
    by_market: dict[str, list[dict[str, str]]] = {market: [] for market in markets}
    seen: set[str] = set()
    for row in scorer_rows:
        decision_id = row["decision_id"]
        if not decision_id or decision_id in seen:
            raise MLB38MarketReplayError("SCORER_DECISION_ID_EMPTY_OR_DUPLICATE")
        seen.add(decision_id)
        market = row["market"]
        if market not in by_market:
            raise MLB38MarketReplayError(f"SCORER_NON_CANONICAL_MARKET:{market}")
        by_market[market].append(row)
    return {
        "schema_version": 2,
        "policy_id": policy.get("policy_id"),
        "policy_sha256": sha256_file(policy_path),
        "policy_git_blob_sha": actual_blob,
        "policy_git_commit": bound_commit,
        "catalog_sha256": sha256_file(catalog_path),
        "input_sha256": sha256_file(scorer_csv),
        "canonical_market_count": len(markets),
        "markets_with_decisions": sum(bool(by_market[market]) for market in markets),
        "cr1_contract": {
            "estimator": "ONE_WAY_CLUSTER_ROBUST_CR1",
            "cluster_key": "slate_date_ct",
            "iid_fallback_allowed": False,
        },
        "markets": {
            market: replay_score(by_market[market], unauthorized=market in blocked_nway)
            for market in markets
        },
        "governance": {
            "third_party_predictions_imported": False,
            "historical_backfill_promoted": False,
            "model_p_created": False,
            "floor_derived": False,
            "eligibility_changed": False,
            "truth_gate_pass_granted": False,
            "official_status_granted": False,
            "forward_evidence_created": False,
        },
    }


def _matrix(
    markets: list[str], metrics: Mapping[str, Any], replay: Mapping[str, Any], observations: list[dict[str, Any]],
) -> dict[str, Any]:
    exclusions_by_market: dict[str, int] = {market: 0 for market in markets}
    for exclusion in replay.get("exclusions", []):
        market = str(exclusion.get("market") or "").upper()
        if not market:
            source_index = exclusion.get("source_index")
            if isinstance(source_index, int) and 0 <= source_index < len(observations):
                market = str(observations[source_index].get("market") or "").upper()
        if market in exclusions_by_market:
            exclusions_by_market[market] += 1
    rows = []
    for market in markets:
        report = metrics["markets"][market]
        if market in unauthorized_markets({"benchmark": {"market_tiers": {"N_WAY_UNAUTHORIZED_V1": {"markets": ["FIRST_HOME_RUN"]}}}}):
            policy_disposition = "N_WAY_UNAUTHORIZED_V1"
        elif market in NO_DIRECT_PROVIDER_KEY:
            policy_disposition = "NO_DIRECT_THE_ODDS_API_KEY_OTHER_SOURCE_REQUIRED"
        else:
            policy_disposition = "DIRECT_THE_ODDS_API_KEY_AVAILABLE"
        rows.append({
            "market": market,
            "provider_key": PROVIDER_KEY_BY_MARKET.get(market),
            "provider_disposition": NO_DIRECT_PROVIDER_KEY.get(market) or policy_disposition,
            "replay_rows": int(report.get("n") or 0),
            "binary_score_rows": int(report.get("binary_score_n") or 0),
            "clv_rows": int((report.get("clv") or {}).get("n") or 0),
            "clv_slate_clusters": int((report.get("clv") or {}).get("clusters") or 0),
            "roi_rows": int((report.get("roi") or {}).get("n") or 0),
            "roi_slate_clusters": int((report.get("roi") or {}).get("clusters") or 0),
            "scoring_status": report.get("status"),
            "replay_exclusion_count": exclusions_by_market[market],
            "missing_evidence_disposition": "MISSING_OR_INADMISSIBLE_EVIDENCE" if exclusions_by_market[market] else "NONE_RECORDED",
            "promotion_authority": False,
            "forward_evidence_satisfied": False,
        })
    return {
        "schema_version": 1,
        "canonical_market_count": len(markets),
        "rows": rows,
        "promotion_authority": False,
        "official_authority": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-root", type=Path, required=True)
    ap.add_argument("--pit-observations", type=Path, required=True)
    ap.add_argument("--policy", type=Path, default=Path("config/mlb_replay_policy_v1.json"))
    ap.add_argument("--catalog", type=Path, default=Path("config/mlb_market_catalog.json"))
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--policy-commit", required=True, help="full Git commit SHA containing the frozen replay policy blob")
    args = ap.parse_args()

    policy_raw = args.policy.read_bytes()
    policy = json.loads(policy_raw)
    if policy.get("policy_id") != "MLB_REPLAY_POLICY_V1" or policy.get("status") != "FROZEN_PRE_REPLAY":
        raise MLB38MarketReplayError("FROZEN_REPLAY_POLICY_IDENTITY_MISMATCH")
    stats = policy.get("statistics", {}).get("primary_standard_error", {})
    if stats.get("estimator") != "ONE_WAY_CLUSTER_ROBUST_CR1" or stats.get("cluster_key") != "slate_date_ct" or stats.get("iid_fallback_allowed") is not False:
        raise MLB38MarketReplayError("FROZEN_CR1_CONTRACT_MISMATCH")

    catalog = _json(args.catalog)
    if not isinstance(catalog, Mapping):
        raise MLB38MarketReplayError("MARKET_CATALOG_MAPPING_REQUIRED")
    markets = flatten_catalog(dict(catalog))
    provider_coverage = validate_provider_coverage(catalog)
    if provider_coverage["status"] != "COMPLETE":
        raise MLB38MarketReplayError("PROVIDER_COVERAGE_DISPOSITION_INCOMPLETE")

    observations = _load_observations(args.pit_observations)
    quotes, materialization = _materialize_archive(args.archive_root)
    generated = datetime.now(timezone.utc)
    replay = build_mlb_promotion_replay(
        pit_observations=observations,
        quote_rows=quotes,
        replay_policy=policy,
        replay_policy_raw_bytes=policy_raw,
        generated_at=generated,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    coverage_path = args.out_dir / "provider_coverage.json"
    materialization_path = args.out_dir / "materialization_manifest.json"
    replay_path = args.out_dir / "promotion_replay.json"
    scorer_csv = args.out_dir / "scorer_input.csv"
    metrics_path = args.out_dir / "metrics.json"
    matrix_path = args.out_dir / "market_matrix.json"
    manifest_path = args.out_dir / "run_manifest.json"

    _write_json(coverage_path, provider_coverage)
    _write_json(materialization_path, materialization)
    _write_json(replay_path, replay)
    scorer_rows = [_to_scorer_row(row) for row in replay.get("rows", [])]
    _write_scorer_csv(scorer_csv, scorer_rows)
    metrics = _score_all(
        scorer_rows=scorer_rows,
        markets=markets,
        policy=policy,
        policy_path=args.policy,
        catalog_path=args.catalog,
        scorer_csv=scorer_csv,
        policy_commit=args.policy_commit,
    )
    _write_json(metrics_path, metrics)
    matrix = _matrix(markets, metrics, replay, observations)
    _write_json(matrix_path, matrix)

    artifacts = [coverage_path, materialization_path, replay_path, scorer_csv, metrics_path, matrix_path]
    manifest = {
        "schema_version": 1,
        "generated_at_utc": generated.isoformat(),
        "status": "COMPLETED_EVIDENCE_PREPARATION_NOT_PROMOTION",
        "canonical_market_count": 38,
        "pit_observation_count": len(observations),
        "canonical_quote_count": len(quotes),
        "replay_eligible_row_count": replay.get("eligible_row_count", 0),
        "replay_exclusion_count": replay.get("exclusion_count", 0),
        "artifacts": {path.name: sha256_file(path) for path in artifacts},
        "governance": {
            "promotion_authority": False,
            "forward_evidence_created": False,
            "floor_changed": False,
            "eligibility_changed": False,
            "truth_gate_pass_granted": False,
            "official_status_granted": False,
        },
    }
    _write_json(manifest_path, manifest)
    print(json.dumps({
        "status": manifest["status"],
        "markets": 38,
        "quotes": len(quotes),
        "replay_rows": replay.get("eligible_row_count", 0),
        "out_dir": str(args.out_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())