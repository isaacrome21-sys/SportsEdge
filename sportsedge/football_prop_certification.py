"""Artifact-bound V2 promotion certification for NFL/CFB player props.

Certification is deliberately separate from model inference and market pricing.
The active Promotion Evidence Policy owns promotion thresholds and checkpoint
semantics.  This adapter does not duplicate those numbers.  It only accepts an
OFFICIAL promotion attestation that is bound to the active policy bytes, one
frozen model artifact, one frozen market definition, one lane, and one genuine
forward-evidence identity.

A registry edit cannot turn PAPER evidence into OFFICIAL by supplying legacy
observation/CLV/ROI numbers: legacy V1 certification rows are rejected.  The
normal frozen-floor Truth Gate remains downstream of this certification layer.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

CERTIFICATION_SCHEMA = "FOOTBALL_PROP_CERTIFICATION_V2"
PROMOTION_ATTESTATION_SCHEMA = "FOOTBALL_PROP_PROMOTION_ATTESTATION_V2"
EVIDENCE_UNIT_SCHEMA = "PROMOTION_EVIDENCE_UNIT_V2"
EVIDENCE_UNIT_ALGORITHM = "CANONICAL_JSON_SHA256_V1"
DEFAULT_POLICY_PATH = Path("config/promotion_evidence_policy_v2.json")
DEFAULT_POLICY_MANIFEST_PATH = Path("config/promotion_evidence_policy_manifest.json")


class FootballPropCertificationError(ValueError):
    pass


def default_certification_path(sport: str) -> Path:
    resolved = str(sport or "").strip().lower()
    if resolved not in {"nfl", "cfb"}:
        raise FootballPropCertificationError(
            f"FOOTBALL_PROP_CERTIFICATION_SPORT_UNSUPPORTED:{sport}"
        )
    return Path(f"config/{resolved}_prop_certification.json")


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise FootballPropCertificationError(error)
    return raw


def _canonical_sha256(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_CANONICAL_HASH_INPUT_INVALID"
        ) from exc
    return sha256(raw).hexdigest()


def _read_json(path: Path, error: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise FootballPropCertificationError(error) from exc
    if not isinstance(payload, dict):
        raise FootballPropCertificationError(error)
    return payload, raw


def active_promotion_policy_binding(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    manifest_path: str | Path = DEFAULT_POLICY_MANIFEST_PATH,
) -> dict[str, Any]:
    """Resolve the exact active promotion-policy identity without reimplementing it."""
    policy_source = Path(policy_path)
    manifest_source = Path(manifest_path)
    policy, policy_raw = _read_json(
        policy_source, "FOOTBALL_PROP_PROMOTION_POLICY_UNREADABLE"
    )
    manifest, _ = _read_json(
        manifest_source, "FOOTBALL_PROP_PROMOTION_POLICY_MANIFEST_UNREADABLE"
    )

    policy_id = str(policy.get("policy_id") or "").strip()
    activation = policy.get("activation")
    checkpoints = policy.get("checkpoints")
    if not policy_id or not isinstance(activation, Mapping) or not isinstance(checkpoints, Mapping):
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_POLICY_INVALID"
        )
    evidence_ref = str(activation.get("evidence_ref") or "").strip()
    declared_policy_path = str(activation.get("policy_path") or "").strip()
    if (
        manifest.get("active_policy_id") != policy_id
        or manifest.get("active_policy_path") != declared_policy_path
        or manifest.get("evidence_ref") != evidence_ref
    ):
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_POLICY_NOT_ACTIVE"
        )
    if declared_policy_path != policy_source.as_posix():
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_POLICY_PATH_MISMATCH"
        )
    cp = checkpoints.get("checkpoint_150")
    if not isinstance(cp, Mapping):
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_OFFICIAL_CHECKPOINT_INVALID"
        )
    checkpoint = cp.get("min_graded_bets")
    if isinstance(checkpoint, bool) or not isinstance(checkpoint, int) or checkpoint <= 0:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_OFFICIAL_CHECKPOINT_INVALID"
        )
    evaluated = checkpoints.get("evaluate_only_at_graded_counts")
    if not isinstance(evaluated, list) or checkpoint not in evaluated:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_OFFICIAL_CHECKPOINT_NOT_FROZEN"
        )
    target_state = str(cp.get("target_state") or "").strip()
    if target_state != "OFFICIAL_CANDIDATE":
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_OFFICIAL_CHECKPOINT_TARGET_INVALID"
        )
    roi_role = policy.get("roi_role")
    if not isinstance(roi_role, Mapping) or roi_role.get("primary_promotion_metric") is not False:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_ROI_ROLE_INVALID"
        )
    return {
        "policy_id": policy_id,
        "policy_sha256": sha256(policy_raw).hexdigest(),
        "policy_path": declared_policy_path,
        "manifest_path": manifest_source.as_posix(),
        "evidence_ref": evidence_ref,
        "official_checkpoint_graded_bets": checkpoint,
    }


def promotion_evidence_unit_sha256(
    *,
    lane_id: str,
    model_artifact_sha256: str,
    market_definition_sha256: str,
    policy_sha256: str,
) -> str:
    lane = str(lane_id or "").strip()
    if not lane:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_PROMOTION_LANE_ID_REQUIRED"
        )
    artifact = _sha256(
        model_artifact_sha256,
        "FOOTBALL_PROP_PROMOTION_MODEL_ARTIFACT_SHA256_INVALID",
    )
    market_definition = _sha256(
        market_definition_sha256,
        "FOOTBALL_PROP_PROMOTION_MARKET_DEFINITION_SHA256_INVALID",
    )
    policy = _sha256(
        policy_sha256,
        "FOOTBALL_PROP_PROMOTION_POLICY_SHA256_INVALID",
    )
    return _canonical_sha256(
        {
            "schema_version": EVIDENCE_UNIT_SCHEMA,
            "lane_id": lane,
            "model_artifact_sha256": artifact,
            "market_definition_sha256": market_definition,
            "policy_sha256": policy,
        }
    )


def promotion_attestation_sha256(attestation: Mapping[str, Any]) -> str:
    payload = dict(attestation)
    payload.pop("attestation_sha256", None)
    return _canonical_sha256(payload)


def load_certification_registry(
    sport: str, *, path: str | Path | None = None
) -> dict[str, Any]:
    source = Path(path) if path is not None else default_certification_path(sport)
    payload, _ = _read_json(
        source, "FOOTBALL_PROP_CERTIFICATION_REGISTRY_UNREADABLE"
    )
    if payload.get("schema_version") != CERTIFICATION_SCHEMA:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_REGISTRY_SCHEMA_INVALID"
        )
    resolved = str(sport or "").strip().upper()
    if payload.get("sport") != resolved:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_REGISTRY_SPORT_MISMATCH"
        )
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_MARKETS_INVALID"
        )
    return payload


def _contradiction(market: str, reason: str) -> FootballPropCertificationError:
    return FootballPropCertificationError(
        f"FOOTBALL_PROP_CERTIFICATION_PASS_CONTRADICTION:{market}:{reason}"
    )


def assess_market_certification(
    *,
    sport: str,
    provider_market: str,
    model_artifact_sha256: str,
    registry: Mapping[str, Any] | None = None,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    manifest_path: str | Path = DEFAULT_POLICY_MANIFEST_PATH,
) -> dict[str, Any]:
    """Resolve one market from an immutable active-V2 promotion attestation.

    Missing evidence is a normal not-ready state. A row claiming PASS must be an
    internally immutable OFFICIAL attestation from the active policy. Any
    contradiction fails closed instead of falling back to legacy numeric gates.
    """
    resolved = str(sport or "").strip().upper()
    market = str(provider_market or "").strip()
    artifact_sha = _sha256(
        model_artifact_sha256,
        "FOOTBALL_PROP_CERTIFICATION_MODEL_ARTIFACT_SHA256_INVALID",
    )
    payload = dict(registry) if registry is not None else load_certification_registry(resolved)
    if payload.get("schema_version") != CERTIFICATION_SCHEMA:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_REGISTRY_SCHEMA_INVALID"
        )
    if payload.get("sport") != resolved:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_REGISTRY_SPORT_MISMATCH"
        )
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_MARKETS_INVALID"
        )
    row = markets.get(market)
    if row is None:
        return {
            "ready": False,
            "status": "MISSING",
            "blockers": [f"PROP_CERTIFICATION_MISSING:{market}"],
            "provider_market": market,
            "model_artifact_sha256": artifact_sha,
        }
    if not isinstance(row, Mapping):
        raise FootballPropCertificationError(
            f"FOOTBALL_PROP_CERTIFICATION_ROW_INVALID:{market}"
        )
    status = str(row.get("status") or "").strip().upper()
    if status == "MISSING":
        return {
            "ready": False,
            "status": status,
            "blockers": [f"PROP_CERTIFICATION_MISSING:{market}"],
            "provider_market": market,
            "model_artifact_sha256": artifact_sha,
        }
    if status == "BLOCKED":
        return {
            "ready": False,
            "status": status,
            "blockers": [f"PROP_CERTIFICATION_BLOCKED:{market}"],
            "provider_market": market,
            "model_artifact_sha256": artifact_sha,
        }
    if status != "PASS":
        raise FootballPropCertificationError(
            f"FOOTBALL_PROP_CERTIFICATION_STATUS_INVALID:{market}:{status}"
        )

    attestation = row.get("promotion_attestation")
    if not isinstance(attestation, Mapping):
        raise _contradiction(market, "PROMOTION_ATTESTATION_REQUIRED")
    if attestation.get("schema_version") != PROMOTION_ATTESTATION_SCHEMA:
        raise _contradiction(market, "PROMOTION_ATTESTATION_SCHEMA_INVALID")
    if str(attestation.get("sport") or "").strip().upper() != resolved:
        raise _contradiction(market, "PROMOTION_ATTESTATION_SPORT_MISMATCH")
    if str(attestation.get("provider_market") or "").strip() != market:
        raise _contradiction(market, "PROMOTION_ATTESTATION_MARKET_MISMATCH")

    bound_sha = _sha256(
        attestation.get("model_artifact_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_ARTIFACT_SHA256_INVALID:{market}",
    )
    if bound_sha != artifact_sha:
        return {
            "ready": False,
            "status": "BLOCKED",
            "blockers": [f"PROP_CERTIFICATION_ARTIFACT_MISMATCH:{market}"],
            "provider_market": market,
            "model_artifact_sha256": artifact_sha,
        }

    active = active_promotion_policy_binding(
        policy_path=policy_path, manifest_path=manifest_path
    )
    policy_sha = _sha256(
        attestation.get("policy_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_POLICY_SHA256_INVALID:{market}",
    )
    if str(attestation.get("policy_id") or "").strip() != active["policy_id"]:
        raise _contradiction(market, "PROMOTION_POLICY_ID_MISMATCH")
    if policy_sha != active["policy_sha256"]:
        raise _contradiction(market, "PROMOTION_POLICY_SHA256_MISMATCH")
    if str(attestation.get("evidence_ref") or "").strip() != active["evidence_ref"]:
        raise _contradiction(market, "PROMOTION_EVIDENCE_REF_MISMATCH")

    lane_id = str(attestation.get("lane_id") or "").strip()
    if not lane_id:
        raise _contradiction(market, "PROMOTION_LANE_ID_REQUIRED")
    market_definition_sha = _sha256(
        attestation.get("market_definition_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_MARKET_DEFINITION_SHA256_INVALID:{market}",
    )
    evidence_sha = _sha256(
        attestation.get("evidence_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_EVIDENCE_SHA256_INVALID:{market}",
    )
    unit_sha = _sha256(
        attestation.get("evidence_unit_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_EVIDENCE_UNIT_SHA256_INVALID:{market}",
    )
    if attestation.get("evidence_unit_algorithm") != EVIDENCE_UNIT_ALGORITHM:
        raise _contradiction(market, "PROMOTION_EVIDENCE_UNIT_ALGORITHM_INVALID")
    expected_unit = promotion_evidence_unit_sha256(
        lane_id=lane_id,
        model_artifact_sha256=artifact_sha,
        market_definition_sha256=market_definition_sha,
        policy_sha256=policy_sha,
    )
    if unit_sha != expected_unit:
        raise _contradiction(market, "PROMOTION_EVIDENCE_UNIT_MISMATCH")

    graded_bets = attestation.get("graded_bets")
    if (
        isinstance(graded_bets, bool)
        or not isinstance(graded_bets, int)
        or graded_bets != active["official_checkpoint_graded_bets"]
    ):
        raise _contradiction(market, "PROMOTION_OFFICIAL_CHECKPOINT_MISMATCH")
    result = attestation.get("promotion_result")
    if not isinstance(result, Mapping):
        raise _contradiction(market, "PROMOTION_RESULT_REQUIRED")
    if result.get("state") != "OFFICIAL" or result.get("decision") != "PROMOTE_OFFICIAL":
        raise _contradiction(market, "PROMOTION_RESULT_NOT_OFFICIAL")

    declared_attestation_sha = _sha256(
        attestation.get("attestation_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_ATTESTATION_SHA256_INVALID:{market}",
    )
    actual_attestation_sha = promotion_attestation_sha256(attestation)
    if declared_attestation_sha != actual_attestation_sha:
        raise _contradiction(market, "PROMOTION_ATTESTATION_SHA256_MISMATCH")

    return {
        "ready": True,
        "status": "PASS",
        "blockers": [],
        "provider_market": market,
        "model_artifact_sha256": artifact_sha,
        "evidence_sha256": evidence_sha,
        "promotion_attestation_sha256": declared_attestation_sha,
        "promotion": {
            "policy_id": active["policy_id"],
            "policy_sha256": policy_sha,
            "evidence_ref": active["evidence_ref"],
            "lane_id": lane_id,
            "market_definition_sha256": market_definition_sha,
            "evidence_unit_sha256": unit_sha,
            "graded_bets": graded_bets,
            "result": dict(result),
        },
    }
