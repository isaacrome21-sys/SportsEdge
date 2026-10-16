"""Fail-closed external pin verification for the live NFL V1 path (t214u, Option A).

The NFL discrete-V2 freeze file only self-checks an ``artifact_sha256`` stored
inside itself, so anyone who can edit it can recompute that hash.  This module
verifies the freeze file and every locked V1 source file against hashes held in
an *external* manifest (``config/trusted/nfl_v1_live_pin_manifest.json``) whose
own SHA-256 is pinned in code here.  Neither the freeze file nor any V1 file
carries the expected values that protect it.

Any hash, probability-mass or evidence failure refuses the whole execution.
Nothing is renormalized, nothing falls back, V1 bytes are never modified and
callers are never rerouted to V2.  Research-only: grants no PLAY/Model_P/
staking/promotion authority.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_RELPATH = "config/trusted/nfl_v1_live_pin_manifest.json"
MANIFEST_SCHEMA = "SPORTSEDGE_NFL_V1_LIVE_PIN_MANIFEST_V1"
# SHA-256 of the exact manifest bytes.  Editing the manifest without a
# reviewed change to this constant refuses every live V1 execution.
PINNED_MANIFEST_SHA256 = "14c7c4e048ce9b3e50a9dad182d53b691add846e2d05dab1dca86cf5b8064821"

MASS_TOLERANCE = 1e-9

# Modules whose namespaces get the grid-mass guard (V1 files are not edited;
# only their already-imported attribute references are wrapped at runtime).
_GRID_GUARD_MODULES = (
    "sportsedge.sports.nfl.unified_run_it",
    "sportsedge.sports.nfl.unified_market_engine",
    "sportsedge.sports.nfl.residual_unified_run_it",
)


class V1LivePinError(RuntimeError):
    """Refuses the entire live V1 execution. Never caught to fall back."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _read(root: Path, rel: str, code: str) -> bytes:
    path = root / rel
    try:
        return path.read_bytes()
    except OSError as exc:
        raise V1LivePinError(f"{code}:{rel}") from exc


def load_manifest(root: Path | None = None, *, pinned_sha256: str | None = None) -> dict[str, Any]:
    root = Path(root or REPO_ROOT)
    raw = _read(root, MANIFEST_RELPATH, "NFL_V1_PIN_MANIFEST_MISSING")
    expected = pinned_sha256 or PINNED_MANIFEST_SHA256
    if _sha256_bytes(raw) != expected:
        raise V1LivePinError("NFL_V1_PIN_MANIFEST_HASH_MISMATCH")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise V1LivePinError("NFL_V1_PIN_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise V1LivePinError("NFL_V1_PIN_MANIFEST_SCHEMA_INVALID")
    files = manifest.get("locked_v1_files")
    if not isinstance(files, list) or len(files) != 7:
        raise V1LivePinError("NFL_V1_PIN_MANIFEST_SEVEN_FILES_REQUIRED")
    if not isinstance(manifest.get("freeze_file"), dict):
        raise V1LivePinError("NFL_V1_PIN_MANIFEST_FREEZE_REQUIRED")
    return manifest


def _check_file(root: Path, entry: Any) -> None:
    if not isinstance(entry, dict) or not entry.get("path"):
        raise V1LivePinError("NFL_V1_PIN_ENTRY_INVALID")
    rel = str(entry["path"])
    data = _read(root, rel, "NFL_V1_PINNED_FILE_MISSING")
    if _sha256_bytes(data) != entry.get("sha256"):
        raise V1LivePinError(f"NFL_V1_PINNED_FILE_SHA256_MISMATCH:{rel}")
    blob = entry.get("git_blob_sha1")
    if blob is not None and _git_blob_sha1(data) != blob:
        raise V1LivePinError(f"NFL_V1_PINNED_FILE_BLOB_MISMATCH:{rel}")


def _finite_positive(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise V1LivePinError(code) from exc
    if not math.isfinite(out) or out <= 0:
        raise V1LivePinError(code)
    return out


def _check_freeze_evidence(root: Path, rel: str) -> None:
    try:
        freeze = json.loads(_read(root, rel, "NFL_V1_FREEZE_MISSING").decode("utf-8"))
        shape = freeze["shape"]
        grid_max = shape["grid_max"]
        lifts = shape["margin_lifts"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise V1LivePinError("NFL_V1_FREEZE_EVIDENCE_INVALID") from exc
    if not isinstance(grid_max, int) or isinstance(grid_max, bool) or grid_max < 1:
        raise V1LivePinError("NFL_V1_FREEZE_GRID_MAX_INVALID")
    _finite_positive(shape.get("nb_r_home"), "NFL_V1_FREEZE_SHAPE_INVALID")
    _finite_positive(shape.get("nb_r_away"), "NFL_V1_FREEZE_SHAPE_INVALID")
    for key in ("0", "abs_3", "abs_7"):
        _finite_positive(lifts.get(key) if isinstance(lifts, dict) else None,
                         "NFL_V1_FREEZE_LIFT_INVALID")


def verify_v1_live_pins(root: Path | None = None, *, pinned_sha256: str | None = None) -> dict[str, Any]:
    """Verify manifest, freeze file and all seven locked V1 files. Raises on any failure."""
    root = Path(root or REPO_ROOT)
    manifest = load_manifest(root, pinned_sha256=pinned_sha256)
    freeze = manifest["freeze_file"]
    _check_file(root, freeze)
    _check_freeze_evidence(root, str(freeze["path"]))
    paths = set()
    for entry in manifest["locked_v1_files"]:
        _check_file(root, entry)
        paths.add(entry["path"])
    if len(paths) != 7:
        raise V1LivePinError("NFL_V1_PIN_MANIFEST_DUPLICATE_FILES")
    for entry in manifest.get("grid_dependencies") or []:
        _check_file(root, entry)
    return {
        "status": "NFL_V1_LIVE_PINS_VERIFIED",
        "manifest_sha256": pinned_sha256 or PINNED_MANIFEST_SHA256,
        "freeze_sha256": freeze["sha256"],
        "locked_v1_files": sorted(paths),
        "research_only": True,
        "play_authority": False,
    }


def validate_score_grid(grid: Any) -> None:
    """Refuse malformed/ragged/non-finite/negative or wrong-mass grids. Never renormalizes."""
    if not isinstance(grid, (list, tuple)) or not grid:
        raise V1LivePinError("NFL_V1_GRID_EMPTY_OR_INVALID")
    width = None
    total = 0.0
    for row in grid:
        if not isinstance(row, (list, tuple)) or not row:
            raise V1LivePinError("NFL_V1_GRID_ROW_INVALID")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise V1LivePinError("NFL_V1_GRID_RAGGED")
        for p in row:
            if isinstance(p, bool):
                raise V1LivePinError("NFL_V1_GRID_CELL_INVALID")
            try:
                value = float(p)
            except (TypeError, ValueError) as exc:
                raise V1LivePinError("NFL_V1_GRID_CELL_INVALID") from exc
            if not math.isfinite(value) or value < 0.0:
                raise V1LivePinError("NFL_V1_GRID_CELL_INVALID")
            total += value
    if len(grid) != width:
        raise V1LivePinError("NFL_V1_GRID_NOT_SQUARE")
    if abs(total - 1.0) > MASS_TOLERANCE:
        raise V1LivePinError("NFL_V1_GRID_MASS_INVALID")


def guard_score_grid(fn: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(fn, "_nfl_v1_mass_guarded", False):
        return fn

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        grid = fn(*args, **kwargs)
        validate_score_grid(grid)
        return grid

    wrapper._nfl_v1_mass_guarded = True  # type: ignore[attr-defined]
    return wrapper


def guard_sampler(fn: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(fn, "_nfl_v1_mass_guarded", False):
        return fn

    @functools.wraps(fn)
    def wrapper(grid: Any, *args: Any, **kwargs: Any) -> Any:
        validate_score_grid(grid)
        return fn(grid, *args, **kwargs)

    wrapper._nfl_v1_mass_guarded = True  # type: ignore[attr-defined]
    return wrapper


def install_v1_grid_mass_guard() -> list[str]:
    import importlib

    guarded = []
    for name in _GRID_GUARD_MODULES:
        module = sys.modules.get(name) or importlib.import_module(name)
        if hasattr(module, "score_grid"):
            module.score_grid = guard_score_grid(module.score_grid)
        if hasattr(module, "sample_score_paths"):
            module.sample_score_paths = guard_sampler(module.sample_score_paths)
        guarded.append(name)
    return guarded


def require_verified_v1_live(root: Path | None = None) -> dict[str, Any]:
    """Single live-entry preflight: pins + runtime grid-mass guard. Raises on failure."""
    receipt = verify_v1_live_pins(root)
    receipt["grid_mass_guard_modules"] = install_v1_grid_mass_guard()
    return receipt


def guarded_run_market_context_props(**kwargs: Any) -> Any:
    require_verified_v1_live()
    from sportsedge.sports.nfl.market_context_props import run_market_context_props
    return run_market_context_props(**kwargs)


def guarded_run_market_context_props_from_nflverse(**kwargs: Any) -> Any:
    require_verified_v1_live()
    from sportsedge.sports.nfl.market_context_props import run_market_context_props_from_nflverse
    return run_market_context_props_from_nflverse(**kwargs)


__all__ = [
    "MANIFEST_RELPATH", "PINNED_MANIFEST_SHA256", "V1LivePinError",
    "guarded_run_market_context_props", "guarded_run_market_context_props_from_nflverse",
    "install_v1_grid_mass_guard", "load_manifest", "require_verified_v1_live",
    "validate_score_grid", "verify_v1_live_pins",
]
