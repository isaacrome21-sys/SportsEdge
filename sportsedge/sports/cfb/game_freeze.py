"""Fail-closed CFB game-model freeze registry.

The registry is the runtime authority for whether a CFB game artifact is frozen.
An environment variable may not substitute for a registry-bound training source.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

_SHA64 = re.compile(r"^[0-9a-f]{64}$")
CFB_GAME_FREEZE_SCHEMA_VERSION = 1
CFB_GAME_FREEZE_PATH = Path("config/cfb_game_model_freeze.json")


class CFBGameFreezeError(ValueError):
    pass


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA64.fullmatch(text):
        raise CFBGameFreezeError(code)
    return text


def load_cfb_game_freeze(path: str | Path = CFB_GAME_FREEZE_PATH) -> dict[str, Any]:
    p = Path(path)
    try:
        raw = p.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CFBGameFreezeError("CFB_GAME_FREEZE_REGISTRY_UNREADABLE") from exc
    if not isinstance(value, Mapping):
        raise CFBGameFreezeError("CFB_GAME_FREEZE_REGISTRY_INVALID")
    row = dict(value)
    if row.get("schema_version") != CFB_GAME_FREEZE_SCHEMA_VERSION or str(row.get("sport") or "").upper() != "CFB":
        raise CFBGameFreezeError("CFB_GAME_FREEZE_REGISTRY_INVALID")
    status = str(row.get("status") or "").upper()
    if status not in {"UNFROZEN", "FROZEN"}:
        raise CFBGameFreezeError("CFB_GAME_FREEZE_STATUS_INVALID")
    row["registry_sha256"] = sha256(raw).hexdigest()
    if status != "FROZEN":
        blocker = str(row.get("blocker") or "CFB_GAME_MODEL_UNFROZEN")
        raise CFBGameFreezeError(blocker)
    for key, code in (
        ("artifact_sha256", "CFB_GAME_FREEZE_ARTIFACT_SHA_INVALID"),
        ("artifact_file_sha256", "CFB_GAME_FREEZE_ARTIFACT_FILE_SHA_INVALID"),
        ("model_code_sha256", "CFB_GAME_FREEZE_MODEL_CODE_SHA_INVALID"),
        ("training_source_sha256", "CFB_GAME_FREEZE_TRAINING_SOURCE_SHA_INVALID"),
        ("source_manifest_sha256", "CFB_GAME_FREEZE_SOURCE_MANIFEST_SHA_INVALID"),
        ("predictive_code_manifest_sha256", "CFB_GAME_FREEZE_PREDICTIVE_MANIFEST_SHA_INVALID"),
        ("acquisition_code_manifest_sha256", "CFB_GAME_FREEZE_ACQUISITION_MANIFEST_SHA_INVALID"),
    ):
        row[key] = _hex64(row.get(key), code)
    artifact_path = str(row.get("artifact_path") or "").strip()
    if artifact_path != "models/cfb_joint_v1.json":
        raise CFBGameFreezeError("CFB_GAME_FREEZE_ARTIFACT_PATH_INVALID")
    try:
        fit_max = int(row.get("fit_max_season"))
    except (TypeError, ValueError) as exc:
        raise CFBGameFreezeError("CFB_GAME_FREEZE_FIT_MAX_SEASON_INVALID") from exc
    if fit_max < 2000 or fit_max > 2100:
        raise CFBGameFreezeError("CFB_GAME_FREEZE_FIT_MAX_SEASON_INVALID")
    if row.get("promotion_authority") is not False or row.get("evidence_clock_authority") is not False:
        raise CFBGameFreezeError("CFB_GAME_FREEZE_AUTHORITY_INVALID")
    row["fit_max_season"] = fit_max
    return row


def verify_frozen_cfb_game_artifact(
    artifact_payload: Mapping[str, Any],
    *,
    artifact_bytes: bytes,
    registry: Mapping[str, Any],
) -> None:
    actual_file_sha = sha256(artifact_bytes).hexdigest()
    if actual_file_sha != str(registry.get("artifact_file_sha256") or "").lower():
        raise CFBGameFreezeError("CFB_GAME_FREEZE_ARTIFACT_FILE_SHA_MISMATCH")
    if str(artifact_payload.get("artifact_sha256") or "").lower() != str(registry.get("artifact_sha256") or "").lower():
        raise CFBGameFreezeError("CFB_GAME_FREEZE_ARTIFACT_SHA_MISMATCH")
    if str(artifact_payload.get("model_code_sha256") or "").lower() != str(registry.get("model_code_sha256") or "").lower():
        raise CFBGameFreezeError("CFB_GAME_FREEZE_MODEL_CODE_SHA_MISMATCH")
    if str(artifact_payload.get("training_source_sha256") or "").lower() != str(registry.get("training_source_sha256") or "").lower():
        raise CFBGameFreezeError("CFB_GAME_FREEZE_TRAINING_SOURCE_SHA_MISMATCH")


__all__ = [
    "CFB_GAME_FREEZE_PATH",
    "CFBGameFreezeError",
    "load_cfb_game_freeze",
    "verify_frozen_cfb_game_artifact",
]
