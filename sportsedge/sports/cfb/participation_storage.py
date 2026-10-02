"""Git-safe at-rest packing for prospective CFB participation snapshots.

The upstream release bytes remain the provenance identity. Large CSVs are stored as
reversible deterministic gzip members only after the capture has already passed the
raw-source PIT audit. The persisted manifest records both the original source SHA256
and the stored gzip SHA256 so a future consumer can verify exact round-trip identity.

This module never changes predictive columns, creates historical PIT, fits a model,
or grants Model_P/promotion/eligibility authority.
"""
from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

STORAGE_CONTRACT = "CFB_PARTICIPATION_GZIP_AT_REST_V1"
DEFAULT_PACK_THRESHOLD_BYTES = 40 * 1024 * 1024
DEFAULT_MAX_STORED_BYTES = 95 * 1024 * 1024


class CFBParticipationStorageError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _load_object(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBParticipationStorageError(code) from exc
    if not isinstance(payload, Mapping):
        raise CFBParticipationStorageError(code)
    return dict(payload)


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationStorageError(code)
    return text


def _gzip_deterministic(source: Path, target: Path) -> None:
    partial = target.with_name(target.name + ".part")
    try:
        with source.open("rb") as src, partial.open("wb") as raw_out:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_out,
                compresslevel=9,
                mtime=0,
            ) as gz:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    gz.write(chunk)
        partial.replace(target)
    except Exception:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise


def pack_participation_snapshot(
    classification_path: str | Path,
    *,
    threshold_bytes: int = DEFAULT_PACK_THRESHOLD_BYTES,
    max_stored_bytes: int = DEFAULT_MAX_STORED_BYTES,
) -> dict[str, Any]:
    """Pack large raw source CSVs while preserving exact decompressed source bytes."""
    if (
        isinstance(threshold_bytes, bool)
        or not isinstance(threshold_bytes, int)
        or threshold_bytes < 0
    ):
        raise CFBParticipationStorageError("CFB_PARTICIPATION_STORAGE_THRESHOLD_INVALID")
    if (
        isinstance(max_stored_bytes, bool)
        or not isinstance(max_stored_bytes, int)
        or max_stored_bytes <= 0
    ):
        raise CFBParticipationStorageError("CFB_PARTICIPATION_STORAGE_MAX_BYTES_INVALID")

    classification_file = Path(classification_path)
    classification = _load_object(
        classification_file,
        "CFB_PARTICIPATION_STORAGE_CLASSIFICATION_INVALID",
    )
    assets = classification.get("assets")
    if not isinstance(assets, list) or not assets:
        raise CFBParticipationStorageError("CFB_PARTICIPATION_STORAGE_ASSETS_REQUIRED")
    source_root = classification_file.parent.parent / "source"
    if not source_root.is_dir():
        raise CFBParticipationStorageError("CFB_PARTICIPATION_STORAGE_SOURCE_ROOT_MISSING")

    packed: list[dict[str, Any]] = []
    for raw_row in assets:
        if not isinstance(raw_row, Mapping):
            raise CFBParticipationStorageError("CFB_PARTICIPATION_STORAGE_ASSET_INVALID")
        row = raw_row  # mutate the classification's live dict in place
        cache_rel = str(row.get("cache_relative_path") or "").strip()
        if not cache_rel:
            raise CFBParticipationStorageError("CFB_PARTICIPATION_STORAGE_CACHE_PATH_MISSING")
        source_path = source_root / cache_rel
        if not source_path.is_file():
            raise CFBParticipationStorageError(
                f"CFB_PARTICIPATION_STORAGE_SOURCE_FILE_MISSING:{cache_rel}"
            )

        expected_source_sha = _hex64(
            row.get("content_sha256"),
            "CFB_PARTICIPATION_STORAGE_SOURCE_SHA_INVALID",
        )
        actual_source_sha = _sha256_file(source_path)
        if actual_source_sha != expected_source_sha:
            raise CFBParticipationStorageError(
                f"CFB_PARTICIPATION_STORAGE_SOURCE_SHA_MISMATCH:{cache_rel}"
            )

        source_size = source_path.stat().st_size
        if source_size <= threshold_bytes:
            continue
        if source_path.suffix == ".gz":
            raise CFBParticipationStorageError(
                f"CFB_PARTICIPATION_STORAGE_ALREADY_COMPRESSED_UNDECLARED:{cache_rel}"
            )

        stored_path = source_path.with_name(source_path.name + ".gz")
        if stored_path.exists():
            raise CFBParticipationStorageError(
                f"CFB_PARTICIPATION_STORAGE_TARGET_EXISTS:{stored_path.name}"
            )
        _gzip_deterministic(source_path, stored_path)
        stored_size = stored_path.stat().st_size
        if stored_size > max_stored_bytes:
            stored_path.unlink(missing_ok=True)
            raise CFBParticipationStorageError(
                f"CFB_PARTICIPATION_STORAGE_STILL_TOO_LARGE:{cache_rel}:{stored_size}"
            )
        stored_sha = _sha256_file(stored_path)

        manifest_path = source_path.parent / "manifest.json"
        manifest = _load_object(
            manifest_path,
            f"CFB_PARTICIPATION_STORAGE_MANIFEST_INVALID:{cache_rel}",
        )
        manifest_content_sha = _hex64(
            manifest.get("content_sha256"),
            "CFB_PARTICIPATION_STORAGE_MANIFEST_SOURCE_SHA_INVALID",
        )
        if manifest_content_sha != expected_source_sha:
            stored_path.unlink(missing_ok=True)
            raise CFBParticipationStorageError(
                f"CFB_PARTICIPATION_STORAGE_MANIFEST_SOURCE_SHA_MISMATCH:{cache_rel}"
            )

        stored_rel = stored_path.relative_to(source_root).as_posix()
        manifest["cache_relative_path"] = stored_rel
        manifest["storage_contract"] = STORAGE_CONTRACT
        manifest["storage_encoding"] = "gzip"
        manifest["stored_content_sha256"] = stored_sha
        manifest["stored_size_bytes"] = stored_size
        manifest["uncompressed_size_bytes"] = source_size
        manifest.pop("manifest_sha256", None)
        manifest_sha = _canonical_sha256(manifest)
        manifest["manifest_sha256"] = manifest_sha
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        row["cache_relative_path"] = stored_rel
        row["manifest_sha256"] = manifest_sha
        row["storage_contract"] = STORAGE_CONTRACT
        row["storage_encoding"] = "gzip"
        row["stored_content_sha256"] = stored_sha
        row["stored_size_bytes"] = stored_size
        row["uncompressed_size_bytes"] = source_size
        source_path.unlink()

        packed.append(
            {
                "dataset": str(row.get("dataset") or ""),
                "source_content_sha256": expected_source_sha,
                "stored_content_sha256": stored_sha,
                "uncompressed_size_bytes": source_size,
                "stored_size_bytes": stored_size,
                "cache_relative_path": stored_rel,
            }
        )

    classification["storage_contract"] = STORAGE_CONTRACT
    classification["storage_pack_threshold_bytes"] = threshold_bytes
    classification["storage_max_stored_bytes"] = max_stored_bytes
    classification["storage_packed_asset_count"] = len(packed)
    classification["storage_is_reversible"] = True
    classification["storage_changes_predictive_content"] = False
    classification_file.write_text(
        json.dumps(classification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "schema_version": "CFB_PARTICIPATION_STORAGE_PACK_V1",
        "status": "PACKED_FOR_GIT_PERSISTENCE",
        "storage_contract": STORAGE_CONTRACT,
        "packed_asset_count": len(packed),
        "packed_assets": packed,
        "threshold_bytes": threshold_bytes,
        "max_stored_bytes": max_stored_bytes,
        "model_fit_performed": False,
        "historical_pit_created": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
    }


__all__ = [
    "CFBParticipationStorageError",
    "DEFAULT_MAX_STORED_BYTES",
    "DEFAULT_PACK_THRESHOLD_BYTES",
    "STORAGE_CONTRACT",
    "pack_participation_snapshot",
]
