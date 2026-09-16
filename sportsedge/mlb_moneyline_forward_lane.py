"""Frozen identity binding for the prospective MLB MONEYLINE promotion lane.

The active Promotion Evidence Policy V2 requires every judged evidence row to be
bound to lane + model artifact + market definition + policy identities. This
module validates the precollection lane contract and exposes deterministic SHA256
bindings. It never grants promotion, staking, deployment, or OFFICIAL authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .edge_floors import (
    load_edge_floor_config,
    require_frozen_devig_policy,
    require_frozen_edge_floor,
)

LANE_SCHEMA_VERSION = "MLB_MONEYLINE_FORWARD_LANE_V1"
LANE_STATUS = "FROZEN_BEFORE_FIRST_GRADED_DECISION"
DEFAULT_LANE_PATH = Path("config/mlb_moneyline_forward_lane_v1.json")
EXPECTED_POLICY_ID = "PROMOTION_EVIDENCE_POLICY_V2"


class MLBMoneylineForwardLaneError(ValueError):
    pass


def _bytes_sha256(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MLBMoneylineForwardLaneError(f"lane dependency unreadable: {path}") from exc
    return hashlib.sha256(raw).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineForwardLaneError(f"{label} unreadable") from exc
    if not isinstance(value, dict):
        raise MLBMoneylineForwardLaneError(f"{label} must be an object")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _resolve(root: Path, value: Any, field: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise MLBMoneylineForwardLaneError(f"{field} required")
    path = Path(text)
    return path if path.is_absolute() else root / path


def load_forward_lane_binding(
    lane_path: str | Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
    lane_file = Path(lane_path) if lane_path is not None else DEFAULT_LANE_PATH
    if not lane_file.is_absolute():
        lane_file = root / lane_file
    lane = _load_json(lane_file, "MLB MONEYLINE forward lane")

    if lane.get("schema_version") != LANE_SCHEMA_VERSION:
        raise MLBMoneylineForwardLaneError("lane schema mismatch")
    if lane.get("status") != LANE_STATUS:
        raise MLBMoneylineForwardLaneError("lane not frozen before first graded decision")
    if lane.get("lane_id") != "MLB_MONEYLINE_DK_T30_V1":
        raise MLBMoneylineForwardLaneError("lane_id mismatch")
    if lane.get("sport") != "MLB" or lane.get("market") != "MONEYLINE":
        raise MLBMoneylineForwardLaneError("lane sport/market mismatch")
    if str(lane.get("sportsbook") or "").lower() != "draftkings":
        raise MLBMoneylineForwardLaneError("lane sportsbook must be draftkings")
    if lane.get("model_reference_side") != "HOME":
        raise MLBMoneylineForwardLaneError("lane reference side must be HOME")
    if lane.get("slate_cluster_key") != "UTC_EVENT_START_DATE":
        raise MLBMoneylineForwardLaneError("slate cluster key mismatch")

    pred = lane.get("prediction_window_minutes_before_start")
    decision = lane.get("decision_capture")
    paper = lane.get("paper_decision")
    close = lane.get("close_capture")
    authority = lane.get("authority")
    for value, name in (
        (pred, "prediction window"),
        (decision, "decision capture"),
        (paper, "paper decision"),
        (close, "close capture"),
        (authority, "authority"),
    ):
        if not isinstance(value, Mapping):
            raise MLBMoneylineForwardLaneError(f"{name} required")
    if (float(pred.get("low_exclusive", -1)), float(pred.get("high_inclusive", -1))) != (40.0, 60.0):
        raise MLBMoneylineForwardLaneError("prediction window mismatch")
    if float(decision.get("target_minutes_before_start", -1)) != 30.0 or float(
        decision.get("early_tolerance_minutes", -1)
    ) != 6.0:
        raise MLBMoneylineForwardLaneError("decision window mismatch")
    if (
        decision.get("direction") != "EARLY_ONLY_AT_OR_BEFORE_TARGET"
        or decision.get("two_sided_required") is not True
        or decision.get("must_be_before_start") is not True
        or decision.get("freeze_must_occur_at_or_before_target") is not True
        or decision.get("lock_once_recorded") is not True
        or decision.get("timestamp_basis") != "SPORTSEDGE_RECEIPT_TIME_IMMUTABLE_DATA_BRANCH"
    ):
        raise MLBMoneylineForwardLaneError("decision capture contract mismatch")
    if (
        paper.get("state") != "PAPER"
        or float(paper.get("stake_units", -1)) != 0.0
        or paper.get("require_positive_ev") is not True
        or paper.get("side_selection") != "MAX_MODEL_EDGE_FROM_FIXED_HOME_REFERENCE"
        or paper.get("graded_count_inclusion") != "PAPER_BET_FROZEN_ONLY"
        or paper.get("no_qualifying_side_disposition") != "PAPER_PASS_FROZEN"
    ):
        raise MLBMoneylineForwardLaneError("paper state contract mismatch")
    if (
        close.get("selection") != "LAST_VERIFIABLE_PAIRED_PRE_FIRST_PITCH_QUOTE"
        or close.get("two_sided_required") is not True
        or close.get("must_be_before_start") is not True
        or close.get("missing_close_policy") != "KEEP_GRADED_BET_IN_CHECKPOINT_DENOMINATOR_EXCLUDE_FROM_CLV"
        or close.get("clv_metric") != "SELECTED_SIDE_CLOSE_FAIR_PROBABILITY_MINUS_ENTRY_FAIR_PROBABILITY"
        or close.get("clv_positive_direction") != "POSITIVE_MEANS_MARKET_MOVED_TOWARD_SELECTED_SIDE"
        or close.get("devig_basis") != "SAME_FROZEN_DEVIG_POLICY_AT_ENTRY_AND_CLOSE"
    ):
        raise MLBMoneylineForwardLaneError("close capture contract mismatch")
    if any(
        authority.get(key) is not False
        for key in (
            "promotion_authority",
            "deployment_change_allowed",
            "staking_change_allowed",
            "official_change_allowed",
        )
    ):
        raise MLBMoneylineForwardLaneError("lane authority must remain false")

    policy_path = _resolve(root, lane.get("promotion_policy"), "promotion_policy")
    manifest_path = _resolve(root, lane.get("promotion_policy_manifest"), "promotion_policy_manifest")
    floor_path = _resolve(root, paper.get("edge_floor_config"), "edge_floor_config")
    policy = _load_json(policy_path, "promotion policy")
    manifest = _load_json(manifest_path, "promotion policy manifest")
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise MLBMoneylineForwardLaneError("active promotion policy mismatch")
    if manifest.get("active_policy_id") != EXPECTED_POLICY_ID:
        raise MLBMoneylineForwardLaneError("manifest active policy mismatch")
    if manifest.get("active_policy_path") != lane.get("promotion_policy"):
        raise MLBMoneylineForwardLaneError("manifest active policy path mismatch")
    if manifest.get("evidence_ref") != "refs/heads/main" or manifest.get("non_retroactive") is not True:
        raise MLBMoneylineForwardLaneError("promotion manifest evidence contract mismatch")

    floor_cfg = load_edge_floor_config(str(floor_path))
    floor = require_frozen_edge_floor(
        market=str(paper.get("edge_floor_market")), sport="MLB", config=floor_cfg
    )
    if float(floor.value_probability_points) != 0.03:
        raise MLBMoneylineForwardLaneError("MLB MONEYLINE frozen floor must be 0.03")
    devig = require_frozen_devig_policy(config=floor_cfg)
    floor_policy = (floor_cfg.get("truth_gate") or {}).get("floor_policy") or {}
    try:
        longshot_floor = float(floor_policy.get("longshot_or_one_sided_floor"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineForwardLaneError("longshot floor invalid") from exc
    if longshot_floor != 0.05:
        raise MLBMoneylineForwardLaneError("longshot/one-sided frozen floor must be 0.05")

    market_definition = {
        "sport": lane["sport"],
        "market": lane["market"],
        "sportsbook": lane["sportsbook"],
        "model_reference_side": lane["model_reference_side"],
        "slate_cluster_key": lane["slate_cluster_key"],
        "prediction_window_minutes_before_start": dict(pred),
        "decision_capture": dict(decision),
        "paper_decision": {
            "state": paper["state"],
            "stake_units": float(paper["stake_units"]),
            "edge_floor_market": paper["edge_floor_market"],
            "edge_floor_probability_points": float(floor.value_probability_points),
            "longshot_or_one_sided_floor_probability_points": longshot_floor,
            "devig_policy_id": devig.policy_id,
            "longshot_trigger_american_odds": devig.longshot_trigger_american_odds,
            "require_positive_ev": paper["require_positive_ev"],
            "side_selection": paper["side_selection"],
            "graded_count_inclusion": paper["graded_count_inclusion"],
            "no_qualifying_side_disposition": paper["no_qualifying_side_disposition"],
        },
        "close_capture": dict(close),
    }
    return {
        "lane_id": lane["lane_id"],
        "lane_schema_version": lane["schema_version"],
        "lane_status": lane["status"],
        "lane_definition_sha256": _canonical_sha256(lane),
        "market_definition_sha256": _canonical_sha256(market_definition),
        "policy_id": EXPECTED_POLICY_ID,
        "policy_sha256": _bytes_sha256(policy_path),
        "policy_manifest_sha256": _bytes_sha256(manifest_path),
        "edge_floor_config_sha256": _bytes_sha256(floor_path),
        "edge_floor_probability_points": float(floor.value_probability_points),
        "longshot_or_one_sided_floor_probability_points": longshot_floor,
        "devig_policy_id": devig.policy_id,
        "evidence_ref": "refs/heads/main",
        "promotion_authority": False,
    }


def require_record_binding(
    record: Mapping[str, Any], binding: Mapping[str, Any] | None = None
) -> None:
    expected = dict(binding or load_forward_lane_binding())
    for field in (
        "lane_id",
        "lane_definition_sha256",
        "market_definition_sha256",
        "policy_id",
        "policy_sha256",
        "policy_manifest_sha256",
        "edge_floor_config_sha256",
    ):
        if str(record.get(field) or "") != str(expected.get(field) or ""):
            raise MLBMoneylineForwardLaneError(f"forward lane binding mismatch: {field}")
    if record.get("promotion_authority") is not False:
        raise MLBMoneylineForwardLaneError("forward lane record authority must be false")
