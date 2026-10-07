#!/usr/bin/env python3
"""Finalize the frozen MLB pitcher-K forward validation exactly once when due."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.mlb_pitcher_k_forward_readout import (
    MIN_GRADED_UNITS,
    PitcherKForwardReadoutError,
    build_readout,
    select_judged_units,
)

ROOT = Path("data/mlb_pitcher_k_forward")
READOUT_PATH = ROOT / "readout_v1.json"


def _git_paths(prefix: str) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "origin/data", prefix],
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return sorted(path for path in raw.splitlines() if path.strip())


def _git_json(path: str) -> dict[str, Any]:
    raw = subprocess.check_output(["git", "show", f"origin/data:{path}"])
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise PitcherKForwardReadoutError(f"data branch payload not object: {path}")
    return value


def _local_jsons(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for file in sorted(path.rglob("*.json")):
        value = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise PitcherKForwardReadoutError(f"local payload not object: {file}")
        out.append(value)
    return out


def _merge_receipts(
    *,
    remote_prefix: str,
    local_path: Path,
    identity_field: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in _git_paths(remote_prefix):
        if not path.endswith(".json"):
            continue
        value = _git_json(path)
        identity = str(value.get(identity_field) or "")
        if not identity:
            raise PitcherKForwardReadoutError(f"receipt identity missing: {path}")
        if identity in merged and merged[identity] != value:
            raise PitcherKForwardReadoutError(f"conflicting remote receipt: {identity}")
        merged[identity] = value
    for value in _local_jsons(local_path):
        identity = str(value.get(identity_field) or "")
        if not identity:
            raise PitcherKForwardReadoutError("local receipt identity missing")
        if identity in merged and merged[identity] != value:
            raise PitcherKForwardReadoutError(f"remote/local receipt collision: {identity}")
        merged[identity] = value
    return [merged[key] for key in sorted(merged)]


def _existing_readout() -> dict[str, Any] | None:
    paths = [p for p in _git_paths(str(READOUT_PATH)) if p == str(READOUT_PATH)]
    if not paths:
        return None
    return _git_json(str(READOUT_PATH))


def run(*, root: Path = ROOT) -> dict[str, Any]:
    existing = _existing_readout()
    if existing is not None:
        return {
            "status": "ALREADY_FINALIZED",
            "readout_sha256": existing.get("readout_sha256"),
            "passes_forward_validation_gate": existing.get("passes_forward_validation_gate"),
            "graded_units": existing.get("graded_units"),
        }

    predictions = _merge_receipts(
        remote_prefix=str(root / "predictions"),
        local_path=root / "predictions",
        identity_field="receipt_sha256",
    )
    settlements = _merge_receipts(
        remote_prefix=str(root / "settlements"),
        local_path=root / "settlements",
        identity_field="receipt_sha256",
    )
    judged = select_judged_units(predictions, settlements)
    if len(judged) < MIN_GRADED_UNITS:
        return {
            "status": "NOT_DUE",
            "graded_units": len(judged),
            "minimum_graded_units": MIN_GRADED_UNITS,
        }

    readout = build_readout(predictions, settlements)
    path = root / "readout_v1.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior != readout:
            raise PitcherKForwardReadoutError("local readout create-only collision")
        return {
            "status": "ALREADY_FINALIZED_LOCAL",
            "readout_sha256": readout["readout_sha256"],
            "passes_forward_validation_gate": readout["passes_forward_validation_gate"],
            "graded_units": readout["graded_units"],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(readout, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "FINALIZED",
        "readout_sha256": readout["readout_sha256"],
        "passes_forward_validation_gate": readout["passes_forward_validation_gate"],
        "graded_units": readout["graded_units"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = run(root=args.root)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
