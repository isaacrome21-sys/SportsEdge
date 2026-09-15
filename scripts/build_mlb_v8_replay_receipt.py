#!/usr/bin/env python3
"""Bind the MLB V8 replay policy, source bytes, and outputs into one receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.core.validation.evidence_receipt import build_evidence_receipt

POLICY = Path("config/mlb_v8_evidence_policy.json")
DEFAULT_INPUT = Path("artifacts/mlb_v8_replay_sources")
DEFAULT_ARCHIVE = Path("artifacts/mlb_v8_replay_archive")


def build(input_root: Path, archive_root: Path, policy: Path = POLICY) -> dict:
    manifest = archive_root / "manifest.json"
    gaps = archive_root / "gap_report.json"
    required = [policy, manifest, gaps]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("MLB_V8_RECEIPT_REQUIRED_FILE_MISSING:" + ",".join(missing))

    files: list[tuple[str, Path]] = [
        ("policy/mlb_v8_evidence_policy.json", policy),
        ("outputs/manifest.json", manifest),
        ("outputs/gap_report.json", gaps),
    ]
    if input_root.is_dir():
        for path in sorted(p for p in input_root.rglob("*") if p.is_file()):
            files.append((f"inputs/{path.relative_to(input_root).as_posix()}", path))

    receipt = build_evidence_receipt(
        files,
        sport="mlb",
        purpose="v8_replay_archive_chain_of_custody",
        metadata={
            "replay_authority": "NON_PROMOTIONAL_SUPPORTING_EVIDENCE",
            "target_direction": "EARLY_ONLY_AT_OR_BEFORE_TARGET",
            "forward_holdout_replacement_allowed": False,
        },
    )
    archive_root.mkdir(parents=True, exist_ok=True)
    (archive_root / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--policy", type=Path, default=POLICY)
    args = parser.parse_args()
    receipt = build(args.input_root, args.archive_root, args.policy)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
