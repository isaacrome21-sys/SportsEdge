"""Evidence-derived promotion certification for NFL/CFB player props.

Certification is deliberately separate from model inference and market pricing.
A market can become promotable only from genuine, hash-bound held-out/forward
evidence that satisfies the frozen SportsEdge thresholds.  There is no manual
``eligible`` boolean in this contract: deployment readiness is derived from the
evidence itself, then the normal frozen-floor Truth Gate decides whether a live
priced candidate is an OFFICIAL_BET.
"""
from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

CERTIFICATION_SCHEMA = "FOOTBALL_PROP_CERTIFICATION_V1"
MIN_OBSERVATIONS = 200
CALIBRATION_SLOPE_MIN = 0.90
CALIBRATION_SLOPE_MAX = 1.10
CALIBRATION_INTERCEPT_ABS_MAX = 0.03
ECE_MAX = 0.025
MEAN_CLV_MIN = 0.005
AFTER_VIG_ROI_MIN = 0.02


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


def _finite(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FootballPropCertificationError(error) from exc
    if not isfinite(out):
        raise FootballPropCertificationError(error)
    return out


def load_certification_registry(
    sport: str, *, path: str | Path | None = None
) -> dict[str, Any]:
    source = Path(path) if path is not None else default_certification_path(sport)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_REGISTRY_UNREADABLE"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CERTIFICATION_SCHEMA:
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


def assess_market_certification(
    *,
    sport: str,
    provider_market: str,
    model_artifact_sha256: str,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one market's promotion certification from immutable evidence.

    Missing evidence is a normal not-ready state.  A claimed PASS row is held to
    the fixed numeric gates and exact artifact binding; contradictory PASS claims
    fail closed rather than being trusted as configuration.
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

    evidence_sha = _sha256(
        row.get("evidence_sha256"),
        f"FOOTBALL_PROP_CERTIFICATION_EVIDENCE_SHA256_INVALID:{market}",
    )
    bound_sha = _sha256(
        row.get("model_artifact_sha256"),
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

    observations = row.get("observations")
    if isinstance(observations, bool) or not isinstance(observations, int) or observations < 0:
        raise FootballPropCertificationError(
            f"FOOTBALL_PROP_CERTIFICATION_OBSERVATIONS_INVALID:{market}"
        )
    calibration = row.get("calibration")
    if not isinstance(calibration, Mapping):
        raise FootballPropCertificationError(
            f"FOOTBALL_PROP_CERTIFICATION_CALIBRATION_INVALID:{market}"
        )
    slope = _finite(
        calibration.get("slope"),
        f"FOOTBALL_PROP_CERTIFICATION_SLOPE_INVALID:{market}",
    )
    intercept = _finite(
        calibration.get("intercept"),
        f"FOOTBALL_PROP_CERTIFICATION_INTERCEPT_INVALID:{market}",
    )
    ece = _finite(
        calibration.get("ece"),
        f"FOOTBALL_PROP_CERTIFICATION_ECE_INVALID:{market}",
    )
    mean_clv = _finite(
        row.get("mean_clv"),
        f"FOOTBALL_PROP_CERTIFICATION_CLV_INVALID:{market}",
    )
    after_vig_roi = _finite(
        row.get("after_vig_roi"),
        f"FOOTBALL_PROP_CERTIFICATION_ROI_INVALID:{market}",
    )

    blockers: list[str] = []
    if observations < MIN_OBSERVATIONS:
        blockers.append(f"PROP_CERTIFICATION_MIN_OBSERVATIONS:{market}")
    if not CALIBRATION_SLOPE_MIN <= slope <= CALIBRATION_SLOPE_MAX:
        blockers.append(f"PROP_CERTIFICATION_CALIBRATION_SLOPE:{market}")
    if abs(intercept) > CALIBRATION_INTERCEPT_ABS_MAX:
        blockers.append(f"PROP_CERTIFICATION_CALIBRATION_INTERCEPT:{market}")
    if ece < 0.0 or ece > ECE_MAX:
        blockers.append(f"PROP_CERTIFICATION_ECE:{market}")
    if mean_clv < MEAN_CLV_MIN:
        blockers.append(f"PROP_CERTIFICATION_CLV:{market}")
    if after_vig_roi < AFTER_VIG_ROI_MIN:
        blockers.append(f"PROP_CERTIFICATION_ROI:{market}")

    # A PASS label that contradicts measured thresholds is invalid evidence, not
    # merely a soft blocker.  This prevents a config edit from manufacturing a
    # deployable state.
    if blockers:
        raise FootballPropCertificationError(
            "FOOTBALL_PROP_CERTIFICATION_PASS_CONTRADICTION:"
            + market
            + ":"
            + ",".join(blockers)
        )
    return {
        "ready": True,
        "status": "PASS",
        "blockers": [],
        "provider_market": market,
        "model_artifact_sha256": artifact_sha,
        "evidence_sha256": evidence_sha,
        "observations": observations,
        "calibration": {"slope": slope, "intercept": intercept, "ece": ece},
        "mean_clv": mean_clv,
        "after_vig_roi": after_vig_roi,
        "thresholds": {
            "min_observations": MIN_OBSERVATIONS,
            "calibration_slope": [CALIBRATION_SLOPE_MIN, CALIBRATION_SLOPE_MAX],
            "calibration_intercept_abs_max": CALIBRATION_INTERCEPT_ABS_MAX,
            "ece_max": ECE_MAX,
            "mean_clv_min": MEAN_CLV_MIN,
            "after_vig_roi_min": AFTER_VIG_ROI_MIN,
        },
    }
