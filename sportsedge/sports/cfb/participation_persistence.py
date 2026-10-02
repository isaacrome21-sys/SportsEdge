"""Deterministic persistence wrapper for prospective CFB participation captures.

GitHub rejects individual blobs above 100 MiB. Some upstream season CSV assets exceed
that limit even though the capture itself is valid. This module preserves the exact
captured bytes semantically by wrapping plain CSVs in deterministic gzip for storage,
while keeping the original source SHA-256 and capture classification unchanged.

The wrapper is storage plumbing only. It creates no retroactive PIT claim, no model
fit, no Model_P, and no promotion or betting authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import gzip
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, BinaryIO, Iterator, Mapping

from .participation_pit_readiness import audit_cfb_participation_snapshot

PERSISTENCE_SCHEMA = "CFB_FORWARD_PARTICIPATION_PERSISTENCE_V1"
GZIP_WRAPPER = "DETERMINISTIC_GZIP_MTIME0_V1"
IDENTITY = "IDENTITY"
DEFAULT_MAX_STORED_BYTES = 95 * 1024 * 1024


class CFBParticipationPersistenceError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBParticipationPersistenceError(code) from exc
    if not isinstance(payload, Mapping):
        raise CFBParticipationPersistenceError(code)
    return dict(payload)


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationPersistenceError(code)
    return text


def _safe_rel(value: Any, code: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise CFBParticipationPersistenceError(code)
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise CFBParticipationPersistenceError(code)
    return rel


def _copy_small(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _gzip_deterministic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with source.open("rb") as src, partial.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                compresslevel=6,
                mtime=0,
            ) as gz:
                shutil.copyfileobj(src, gz, length=1024 * 1024)
        partial.replace(target)
    except Exception:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise


def _decompressed_sha256(path: Path) -> str:
    digest = sha256()
    try:
        with gzip.open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, EOFError) as exc:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTED_GZIP_INVALID"
        ) from exc
    return digest.hexdigest()


def _pack_data_file(
    *,
    source: Path,
    output_root: Path,
    original_relative_path: Path,
    expected_source_sha256: str,
    kind: str,
    max_stored_bytes: int,
) -> dict[str, Any]:
    if not source.is_file():
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSIST_SOURCE_MISSING:{original_relative_path}"
        )
    actual_source_sha = _sha256_file(source)
    if actual_source_sha != expected_source_sha256:
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSIST_SOURCE_HASH_MISMATCH:{original_relative_path}"
        )

    # Upstream .gz assets are already efficiently persisted and their stored bytes
    # are exactly the captured source bytes. Plain CSVs get a deterministic wrapper.
    if source.name.endswith(".gz"):
        storage_rel = Path("source") / original_relative_path
        target = output_root / storage_rel
        _copy_small(source, target)
        compression = IDENTITY
    else:
        storage_rel = Path("source") / Path(str(original_relative_path) + ".gz")
        target = output_root / storage_rel
        _gzip_deterministic(source, target)
        compression = GZIP_WRAPPER

    stored_size = target.stat().st_size
    if stored_size > max_stored_bytes:
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSISTED_FILE_TOO_LARGE:{storage_rel}:{stored_size}"
        )
    return {
        "kind": kind,
        "original_relative_path": str(Path("source") / original_relative_path),
        "stored_relative_path": str(storage_rel),
        "source_sha256": expected_source_sha256,
        "stored_sha256": _sha256_file(target),
        "stored_size_bytes": stored_size,
        "compression": compression,
    }


def pack_participation_snapshot(
    *,
    capture_root: str | Path,
    output_root: str | Path,
    max_stored_bytes: int = DEFAULT_MAX_STORED_BYTES,
) -> dict[str, Any]:
    """Pack one already-validated capture into a Git-safe deterministic snapshot."""
    if isinstance(max_stored_bytes, bool) or not isinstance(max_stored_bytes, int) or max_stored_bytes <= 0:
        raise CFBParticipationPersistenceError("CFB_PARTICIPATION_MAX_STORED_BYTES_INVALID")

    root = Path(capture_root)
    out = Path(output_root)
    classification_path = root / "capture" / "classification.json"
    readiness = audit_cfb_participation_snapshot(classification_path)
    if readiness.get("participation_source_asof_ready") is not True:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_CAPTURE_NOT_READY_FOR_PERSISTENCE:"
            + ",".join(readiness.get("blockers") or [])
        )

    classification = _json(
        classification_path,
        "CFB_PARTICIPATION_CLASSIFICATION_INVALID",
    )
    if out.exists():
        shutil.rmtree(out)
    (out / "capture").mkdir(parents=True, exist_ok=True)
    for name in ("classification.json", "id.txt", "sources.json"):
        source = root / "capture" / name
        if source.is_file():
            _copy_small(source, out / "capture" / name)

    files: list[dict[str, Any]] = []
    assets = classification.get("assets")
    assert isinstance(assets, list)  # readiness audit already proved this

    for row in assets:
        assert isinstance(row, Mapping)
        dataset = str(row.get("dataset") or "").strip().lower()
        cache_rel = _safe_rel(
            row.get("cache_relative_path"),
            f"CFB_PARTICIPATION_CACHE_PATH_INVALID:{dataset}",
        )
        source_path = root / "source" / cache_rel
        source_sha = _hex64(
            row.get("content_sha256"),
            f"CFB_PARTICIPATION_CONTENT_SHA_INVALID:{dataset}",
        )
        files.append(
            _pack_data_file(
                source=source_path,
                output_root=out,
                original_relative_path=cache_rel,
                expected_source_sha256=source_sha,
                kind="RAW_SOURCE",
                max_stored_bytes=max_stored_bytes,
            )
        )

        manifest_source = source_path.parent / "manifest.json"
        if not manifest_source.is_file():
            raise CFBParticipationPersistenceError(
                f"CFB_PARTICIPATION_MANIFEST_MISSING:{dataset}"
            )
        manifest_target = (
            out
            / "provenance"
            / dataset
            / str(row.get("season"))
            / "manifest.json"
        )
        _copy_small(manifest_source, manifest_target)
        files.append(
            {
                "kind": "SOURCE_MANIFEST",
                "dataset": dataset,
                "original_relative_path": str(
                    Path("source") / cache_rel.parent / "manifest.json"
                ),
                "stored_relative_path": str(manifest_target.relative_to(out)),
                "source_sha256": _sha256_file(manifest_source),
                "stored_sha256": _sha256_file(manifest_target),
                "stored_size_bytes": manifest_target.stat().st_size,
                "compression": IDENTITY,
            }
        )

        projection = row.get("predictive_projection")
        if isinstance(projection, Mapping):
            projection_rel = _safe_rel(
                projection.get("projection_relative_path"),
                "CFB_PARTICIPATION_PROJECTION_PATH_INVALID",
            )
            projection_source = root / "source" / projection_rel
            projection_sha = _hex64(
                projection.get("projection_sha256"),
                "CFB_PARTICIPATION_PROJECTION_SHA_INVALID",
            )
            files.append(
                _pack_data_file(
                    source=projection_source,
                    output_root=out,
                    original_relative_path=projection_rel,
                    expected_source_sha256=projection_sha,
                    kind="PREDICTIVE_PROJECTION",
                    max_stored_bytes=max_stored_bytes,
                )
            )

    manifest = {
        "schema_version": PERSISTENCE_SCHEMA,
        "sport": "CFB",
        "capture_id": (out / "capture" / "id.txt").read_text(encoding="utf-8").strip()
        if (out / "capture" / "id.txt").is_file()
        else None,
        "classification_sha256": _sha256_file(out / "capture" / "classification.json"),
        "storage_rule": (
            "Plain captured CSVs are wrapped in deterministic gzip (mtime=0); "
            "already-gzipped upstream assets are stored byte-identically. "
            "source_sha256 always names the exact pre-wrapper captured bytes."
        ),
        "max_stored_bytes": int(max_stored_bytes),
        "files": sorted(
            files,
            key=lambda row: (
                str(row.get("kind")),
                str(row.get("original_relative_path")),
            ),
        ),
        "retroactive_point_in_time_claim": False,
        "model_fit_performed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
    }
    unsigned = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    manifest["manifest_sha256"] = sha256(unsigned).hexdigest()
    (out / "capture" / "persistence.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    audit_persisted_participation_snapshot(out)
    return manifest


def _verify_wrapped_file(root: Path, row: Mapping[str, Any]) -> None:
    stored_rel = _safe_rel(
        row.get("stored_relative_path"),
        "CFB_PARTICIPATION_PERSISTED_PATH_INVALID",
    )
    target = root / stored_rel
    if not target.is_file():
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSISTED_FILE_MISSING:{stored_rel}"
        )
    stored_sha = _hex64(
        row.get("stored_sha256"),
        "CFB_PARTICIPATION_PERSISTED_SHA_INVALID",
    )
    if _sha256_file(target) != stored_sha:
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSISTED_HASH_MISMATCH:{stored_rel}"
        )
    source_sha = _hex64(
        row.get("source_sha256"),
        "CFB_PARTICIPATION_PERSISTED_SOURCE_SHA_INVALID",
    )
    compression = row.get("compression")
    if compression == IDENTITY:
        restored_sha = stored_sha
    elif compression == GZIP_WRAPPER:
        restored_sha = _decompressed_sha256(target)
    else:
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSISTED_COMPRESSION_INVALID:{stored_rel}"
        )
    if restored_sha != source_sha:
        raise CFBParticipationPersistenceError(
            f"CFB_PARTICIPATION_PERSISTED_RESTORED_HASH_MISMATCH:{stored_rel}"
        )


def audit_persisted_participation_snapshot(
    persisted_root: str | Path,
) -> dict[str, Any]:
    root = Path(persisted_root)
    manifest_path = root / "capture" / "persistence.json"
    manifest = _json(
        manifest_path,
        "CFB_PARTICIPATION_PERSISTENCE_MANIFEST_INVALID",
    )
    if manifest.get("schema_version") != PERSISTENCE_SCHEMA:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTENCE_SCHEMA_INVALID"
        )
    if str(manifest.get("sport") or "").upper() != "CFB":
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTENCE_SPORT_INVALID"
        )
    if any(
        manifest.get(field) is not False
        for field in (
            "retroactive_point_in_time_claim",
            "model_fit_performed",
            "model_p_created",
            "promotion_authority",
            "eligibility_changed",
        )
    ):
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTENCE_AUTHORITY_INVALID"
        )
    claimed = _hex64(
        manifest.pop("manifest_sha256", None),
        "CFB_PARTICIPATION_PERSISTENCE_MANIFEST_SHA_INVALID",
    )
    actual = sha256(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if actual != claimed:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTENCE_MANIFEST_HASH_MISMATCH"
        )
    classification_path = root / "capture" / "classification.json"
    if not classification_path.is_file():
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTED_CLASSIFICATION_MISSING"
        )
    expected_classification = _hex64(
        manifest.get("classification_sha256"),
        "CFB_PARTICIPATION_PERSISTED_CLASSIFICATION_SHA_INVALID",
    )
    if _sha256_file(classification_path) != expected_classification:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTED_CLASSIFICATION_HASH_MISMATCH"
        )

    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTENCE_FILES_EMPTY"
        )
    data_rows = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("kind") in {"RAW_SOURCE", "PREDICTIVE_PROJECTION"}
    ]
    for row in data_rows:
        _verify_wrapped_file(root, row)

    classification = _json(
        classification_path,
        "CFB_PARTICIPATION_CLASSIFICATION_INVALID",
    )
    assets = classification.get("assets") or []
    expected_sources = {
        str(Path("source") / _safe_rel(row.get("cache_relative_path"), "CFB_PARTICIPATION_CACHE_PATH_INVALID"))
        for row in assets
        if isinstance(row, Mapping)
    }
    stored_sources = {
        str(row.get("original_relative_path"))
        for row in data_rows
        if row.get("kind") == "RAW_SOURCE"
    }
    if expected_sources != stored_sources:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTED_SOURCE_SET_MISMATCH"
        )
    expected_projections = {
        str(Path("source") / _safe_rel(
            projection.get("projection_relative_path"),
            "CFB_PARTICIPATION_PROJECTION_PATH_INVALID",
        ))
        for row in assets
        if isinstance(row, Mapping)
        for projection in [row.get("predictive_projection")]
        if isinstance(projection, Mapping)
    }
    stored_projections = {
        str(row.get("original_relative_path"))
        for row in data_rows
        if row.get("kind") == "PREDICTIVE_PROJECTION"
    }
    if expected_projections != stored_projections:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_PERSISTED_PROJECTION_SET_MISMATCH"
        )
    return {
        "schema_version": PERSISTENCE_SCHEMA,
        "status": "PERSISTED_SNAPSHOT_VERIFIED",
        "raw_source_count": len(stored_sources),
        "projection_count": len(stored_projections),
        "max_stored_size_bytes": max(
            int(row.get("stored_size_bytes") or 0) for row in data_rows
        ),
        "retroactive_point_in_time_claim": False,
        "model_fit_performed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
    }


def restore_participation_snapshot(
    *,
    persisted_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Recreate the original validated capture layout from a persisted wrapper."""
    root = Path(persisted_root)
    audit = audit_persisted_participation_snapshot(root)
    manifest = _json(
        root / "capture" / "persistence.json",
        "CFB_PARTICIPATION_PERSISTENCE_MANIFEST_INVALID",
    )
    out = Path(output_root)
    if out.exists():
        shutil.rmtree(out)
    (out / "capture").mkdir(parents=True, exist_ok=True)
    for name in ("classification.json", "id.txt", "sources.json"):
        source = root / "capture" / name
        if source.is_file():
            _copy_small(source, out / "capture" / name)

    for row in manifest.get("files") or []:
        if not isinstance(row, Mapping):
            continue
        kind = row.get("kind")
        if kind == "SOURCE_MANIFEST":
            original_rel = _safe_rel(
                row.get("original_relative_path"),
                "CFB_PARTICIPATION_ORIGINAL_PATH_INVALID",
            )
            target = out / original_rel
            _copy_small(root / _safe_rel(row.get("stored_relative_path"), "CFB_PARTICIPATION_PERSISTED_PATH_INVALID"), target)
            continue
        if kind not in {"RAW_SOURCE", "PREDICTIVE_PROJECTION"}:
            continue
        original_rel = _safe_rel(
            row.get("original_relative_path"),
            "CFB_PARTICIPATION_ORIGINAL_PATH_INVALID",
        )
        stored = root / _safe_rel(
            row.get("stored_relative_path"),
            "CFB_PARTICIPATION_PERSISTED_PATH_INVALID",
        )
        target = out / original_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        compression = row.get("compression")
        if compression == IDENTITY:
            shutil.copyfile(stored, target)
        elif compression == GZIP_WRAPPER:
            with gzip.open(stored, "rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        else:
            raise CFBParticipationPersistenceError(
                "CFB_PARTICIPATION_PERSISTED_COMPRESSION_INVALID"
            )
        if _sha256_file(target) != _hex64(
            row.get("source_sha256"),
            "CFB_PARTICIPATION_PERSISTED_SOURCE_SHA_INVALID",
        ):
            raise CFBParticipationPersistenceError(
                f"CFB_PARTICIPATION_RESTORE_HASH_MISMATCH:{original_rel}"
            )

    restored = audit_cfb_participation_snapshot(out / "capture" / "classification.json")
    if restored.get("participation_source_asof_ready") is not True:
        raise CFBParticipationPersistenceError(
            "CFB_PARTICIPATION_RESTORE_READINESS_FAILED"
        )
    return {**audit, "restored_participation_source_asof_ready": True}


__all__ = [
    "CFBParticipationPersistenceError",
    "DEFAULT_MAX_STORED_BYTES",
    "GZIP_WRAPPER",
    "IDENTITY",
    "PERSISTENCE_SCHEMA",
    "audit_persisted_participation_snapshot",
    "pack_participation_snapshot",
    "restore_participation_snapshot",
]
