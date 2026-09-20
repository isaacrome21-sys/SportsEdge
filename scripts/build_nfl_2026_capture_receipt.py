#!/usr/bin/env python3
"""Build a read-only receipt for the live NFL 2026 confirmation capture lane.

This script deliberately does not write inside the hash-locked capture directory and
does not alter the live capture script/workflow. It only binds current control bytes
and whatever prospective evidence already exists.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.core.validation.evidence_receipt import build_evidence_receipt

CONFIG = Path("config/nfl_2026_capture.json")
CAPTURE_SCRIPT = Path("scripts/nfl_2026_line_capture.py")
CAPTURE_WORKFLOW = Path(".github/workflows/nfl-2026-line-capture.yml")
DEFAULT_OUT = Path("artifacts/nfl_2026_capture_receipt/receipt.json")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _lock_status(
    lock_path: Path,
    policy: Path,
    config_path: Path = CONFIG,
    capture_script: Path = CAPTURE_SCRIPT,
    capture_workflow: Path = CAPTURE_WORKFLOW,
) -> tuple[str, list[str]]:
    if not lock_path.is_file():
        return "NO_LOCK_YET", []
    try:
        saved = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return "LOCK_INVALID_JSON", ["capture_lock.json"]
    current = {
        "policy_sha256": _sha(policy),
        "config_sha256": _sha(config_path),
        "script_sha256": _sha(capture_script),
        "workflow_sha256": _sha(capture_workflow),
    }
    mismatches = [key for key, value in current.items() if saved.get(key) != value]
    return ("MATCH" if not mismatches else "MISMATCH"), mismatches


def _is_capture_record(path: Path, capture_root: Path) -> bool:
    rel = path.relative_to(capture_root)
    if len(rel.parts) == 2 and rel.parts[0].startswith("week") and rel.name == "opener.json":
        return True
    return (
        len(rel.parts) >= 3
        and rel.parts[0].startswith("week")
        and rel.parts[1] == "final"
        and rel.suffix == ".json"
    )


def build(config_path: Path = CONFIG, out: Path = DEFAULT_OUT) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    policy = Path(cfg["policy_path"])
    capture_root = Path(cfg["output_dir"])
    lock_path = capture_root / "capture_lock.json"

    evidence_files: list[Path] = []
    if capture_root.is_dir():
        evidence_files = sorted(p for p in capture_root.rglob("*") if p.is_file())
    capture_records = [path for path in evidence_files if _is_capture_record(path, capture_root)]

    lock_status, lock_mismatches = _lock_status(lock_path, policy, config_path)
    if lock_status == "NO_LOCK_YET" and capture_records:
        lock_status = "LOCK_MISSING_WITH_CAPTURE_RECORDS"
        lock_mismatches = ["capture_lock.json"]

    files: list[tuple[str, Path]] = [
        ("controls/config/nfl_2026_capture.json", config_path),
        ("controls/policy/nfl_research_search_policy_v1.json", policy),
        ("controls/scripts/nfl_2026_line_capture.py", CAPTURE_SCRIPT),
        ("controls/workflows/nfl-2026-line-capture.yml", CAPTURE_WORKFLOW),
    ]
    for path in evidence_files:
        files.append((f"capture/{path.relative_to(capture_root).as_posix()}", path))

    receipt = build_evidence_receipt(
        files,
        sport="nfl",
        purpose="2026_forward_confirmation_chain_of_custody",
        metadata={
            "capture_config_version": cfg.get("capture_config_version"),
            "bookmaker": cfg.get("bookmaker"),
            "first_week": cfg.get("first_week"),
            "no_backfill": True,
            "capture_file_count": len(evidence_files),
            "capture_record_count": len(capture_records),
            "capture_lock_status": lock_status,
            "capture_lock_mismatches": lock_mismatches,
            "live_capture_path_modified_by_receipt_builder": False,
        },
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--require-evidence", action="store_true")
    parser.add_argument("--require-lock-match", action="store_true")
    args = parser.parse_args()
    receipt = build(args.config, args.out)
    print(json.dumps(receipt, sort_keys=True))
    metadata = receipt["metadata"]
    if args.require_evidence and int(metadata["capture_record_count"]) == 0:
        return 2
    if args.require_lock_match and metadata["capture_lock_status"] not in {"MATCH", "NO_LOCK_YET"}:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
