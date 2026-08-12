"""NRFI/YRFI live inference for a Statcast-attested SportsEdge artifact.

The trained positive class remains YRFI (any first-inning run). New production
artifacts are required to prove Statcast features are part of the actual model
feature contract before any Model_P can be emitted.
"""
from __future__ import annotations

from typing import Any, Mapping
import numpy as np
from .statcast_contract import require_statcast_artifact

ENGINE_VERSION = "nrfi_yrfi_live_v2_statcast_required"
ARTIFACT_POSITIVE_CLASS = "YRFI"
SUPPORTED_PERIOD = "1ST"
REQUIRED_LINE = 0.5
BANNED_FEATURE_PATTERNS = (
    "market_prob", "novig", "implied_prob", "dk_prob", "sportsbook_prob",
    "consensus_prob", "closing_prob", "american_odds", "price", "odds",
)

class NrfiInferenceError(ValueError):
    pass

def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))

def assert_no_sportsbook_contamination(feature_row: Mapping[str, Any] | None) -> None:
    if feature_row is None:
        return
    if not isinstance(feature_row, Mapping):
        raise NrfiInferenceError("feature payload must be a mapping")
    for key in feature_row:
        low = str(key).lower()
        if any(pat in low for pat in BANNED_FEATURE_PATTERNS):
            raise NrfiInferenceError(f"SPORTSBOOK_FEATURE_BANNED: {key}")

def first_inning_model_p(artifact: Mapping[str, Any], fi_row: list[float]) -> dict[str, float]:
    require_statcast_artifact(artifact, kind="nrfi")
    features = tuple(artifact.get("features") or ())
    if not features:
        raise NrfiInferenceError("FI_FEATURE_CONTRACT_MISSING")
    if not isinstance(fi_row, (list, tuple)) or len(fi_row) != len(features):
        raise NrfiInferenceError(f"FI_FEATURE_ROW_LENGTH_MISMATCH expected={len(features)} got={len(fi_row) if hasattr(fi_row,'__len__') else 'n/a'}")
    for i, v in enumerate(fi_row):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
            raise NrfiInferenceError(f"FI_FEATURE_INVALID index={i} name={features[i]} value={v!r}")
    X = np.array([list(fi_row)], dtype=float)
    raw = artifact["model"].predict_proba(X)[:, 1]
    calibrated = artifact["calibrator"].predict_proba(_logit(raw).reshape(-1, 1))[:, 1]
    yrfi = float(calibrated[0])
    if not (0.0 <= yrfi <= 1.0):
        raise NrfiInferenceError(f"MODEL_P_OUT_OF_RANGE: {yrfi}")
    return {"YRFI": yrfi, "NRFI": 1.0 - yrfi}

def price_first_inning_quote(artifact: Mapping[str, Any], fi_row: list[float], quote: Mapping[str, Any]) -> dict[str, Any]:
    market = str(quote.get("market") or "").upper()
    if market not in {"NRFI", "YRFI"}:
        raise NrfiInferenceError(f"UNSUPPORTED_MARKET_FOR_FIRST_INNING_ENGINE: {market}")
    period = str(quote.get("period") or "").upper()
    if period != SUPPORTED_PERIOD:
        raise NrfiInferenceError("QUOTE_PERIOD_MODEL_MISMATCH")
    line = quote.get("line")
    if line is None or isinstance(line, bool) or float(line) != REQUIRED_LINE:
        raise NrfiInferenceError("FIRST_INNING_LINE_NOT_HALF_RUN")
    probs = first_inning_model_p(artifact, fi_row)
    return {
        "engine_version": ENGINE_VERSION, "artifact_version": artifact.get("version"),
        "statcast_contract_version": artifact.get("statcast_contract_version"),
        "artifact_positive_class": ARTIFACT_POSITIVE_CLASS, "market": market,
        "period": period, "line": REQUIRED_LINE, "model_p": probs[market],
        "complement_p": probs["NRFI" if market == "YRFI" else "YRFI"],
    }
