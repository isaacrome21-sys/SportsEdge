"""Deterministic model-artifact identity for canonical MLB runtime engines.

MLB's current production candidates are primarily empirical/algorithmic models,
not fitted coefficient bundles. Their model artifact is therefore the frozen model
algorithm itself: the authoritative family policy, engine version/seed policy, and
exact bytes of every code file that defines the model family. Live features,
quotes, lines, prices, and per-candidate input hashes are deliberately excluded.

This identity is provenance only. It does not create promotion evidence or change
market eligibility.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_POLICY_PATH = "config/mlb_model_artifact_policy_v1.json"
POLICY_ID = "MLB_MODEL_ARTIFACT_POLICY_V1"
ARTIFACT_SCHEMA = "SPORTSEDGE_MLB_ALGORITHMIC_MODEL_ARTIFACT_V1"


class MLBModelArtifactError(ValueError):
    pass


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else _root() / value


def _sha256_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


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
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_CANONICAL_JSON_INVALID") from exc
    return _sha256_bytes(raw)


def load_mlb_model_artifact_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    resolved = _resolve(path)
    try:
        raw = resolved.read_bytes()
        policy = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_POLICY_UNREADABLE") from exc
    if policy.get("policy_id") != POLICY_ID:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_POLICY_ID_MISMATCH")
    if policy.get("artifact_schema") != ARTIFACT_SCHEMA:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_SCHEMA_MISMATCH")
    if policy.get("promotion_evidence") is not False or policy.get("eligibility_changed") is not False:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_POLICY_GOVERNANCE_INVALID")
    families = policy.get("families")
    if not isinstance(families, Mapping) or not families:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_FAMILIES_REQUIRED")
    universal = policy.get("universal_source_files")
    if not isinstance(universal, list):
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_UNIVERSAL_SOURCES_INVALID")
    policy = dict(policy)
    policy["_policy_sha256"] = _sha256_bytes(raw)
    return policy


def _family_index(policy: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    families = policy.get("families")
    if not isinstance(families, Mapping):
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_FAMILIES_REQUIRED")
    for family_id, raw in families.items():
        if not isinstance(raw, Mapping):
            raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_FAMILY_INVALID:{family_id}")
        markets = raw.get("markets")
        if not isinstance(markets, list) or not markets:
            raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_MARKETS_REQUIRED:{family_id}")
        for market in markets:
            key = str(market or "").strip().upper()
            if not key:
                raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_MARKET_INVALID:{family_id}")
            if key in out:
                raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_MARKET_DUPLICATE:{key}")
            out[key] = str(family_id)
    return out


def policy_markets(policy: Mapping[str, Any] | None = None) -> frozenset[str]:
    resolved = policy or load_mlb_model_artifact_policy()
    return frozenset(_family_index(resolved))


def _source_manifest(policy: Mapping[str, Any], family_id: str) -> tuple[dict[str, str], ...]:
    family = policy["families"][family_id]
    family_sources = family.get("source_files")
    universal = policy.get("universal_source_files")
    if not isinstance(family_sources, list) or not family_sources:
        raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_SOURCE_FILES_REQUIRED:{family_id}")
    if not isinstance(universal, list):
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_UNIVERSAL_SOURCES_INVALID")
    paths = []
    for raw in [*universal, *family_sources]:
        rel = str(raw or "").strip()
        if not rel or rel in paths:
            if not rel:
                raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_SOURCE_PATH_INVALID:{family_id}")
            continue
        paths.append(rel)
    manifest = []
    for rel in paths:
        path = _resolve(rel)
        try:
            digest = _sha256_bytes(path.read_bytes())
        except OSError as exc:
            raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_SOURCE_UNREADABLE:{rel}") from exc
        manifest.append({"path": rel, "sha256": digest})
    return tuple(manifest)


def build_mlb_model_artifact(
    *,
    market: str,
    engine_output: Mapping[str, Any],
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Build the immutable algorithmic model artifact used by one runtime family."""
    if not isinstance(engine_output, Mapping):
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_ENGINE_OUTPUT_REQUIRED")
    if str(engine_output.get("runtime_path") or "").strip().upper() == "LEGACY_COMPAT":
        raise MLBModelArtifactError("MLB_LEGACY_COMPAT_HAS_NO_MODEL_ARTIFACT")
    engine_version = str(engine_output.get("engine_version") or "").strip()
    seed_policy = str(engine_output.get("seed_policy") or "").strip()
    if not engine_version:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_ENGINE_VERSION_REQUIRED")
    if not seed_policy:
        raise MLBModelArtifactError("MLB_MODEL_ARTIFACT_SEED_POLICY_REQUIRED")

    key = str(market or "").strip().upper()
    policy = load_mlb_model_artifact_policy(policy_path)
    index = _family_index(policy)
    family_id = index.get(key)
    if family_id is None:
        raise MLBModelArtifactError(f"MLB_MODEL_ARTIFACT_NO_FAMILY:{key}")
    family = policy["families"][family_id]
    sources = _source_manifest(policy, family_id)
    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "sport": "MLB",
        "family_id": family_id,
        "markets": sorted(str(x).upper() for x in family["markets"]),
        "engine_version": engine_version,
        "seed_policy": seed_policy,
        "policy_id": POLICY_ID,
        "policy_sha256": policy["_policy_sha256"],
        "source_files": list(sources),
        "artifact_kind": "ALGORITHMIC_EMPIRICAL_MODEL_CODE_IDENTITY",
        "fitted_state_present": False,
        "live_features_in_artifact": False,
        "market_prices_in_artifact": False,
        "promotion_evidence": False,
    }
    artifact["model_artifact_sha256"] = _canonical_sha256(artifact)
    return artifact


def mlb_model_artifact_sha256(
    *,
    market: str,
    engine_output: Mapping[str, Any],
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> str:
    return str(build_mlb_model_artifact(
        market=market,
        engine_output=engine_output,
        policy_path=policy_path,
    )["model_artifact_sha256"])
