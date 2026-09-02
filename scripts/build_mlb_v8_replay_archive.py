#!/usr/bin/env python3
"""Build the MLB V8 March-August replay manifest without fabricating PIT evidence.

This standard-library tool is deliberately provider-neutral. Provider exports/raw API
responses are placed under the input root by source/date. The builder hashes every
file, classifies its evidence tier, and emits a deterministic manifest plus a gap
report. It never upgrades open/close records into decision-time PIT snapshots.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

POLICY = Path("config/mlb_v8_evidence_policy.json")
DEFAULT_INPUT = Path("artifacts/mlb_v8_replay_sources")
DEFAULT_OUTPUT = Path("artifacts/mlb_v8_replay_archive")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_policy(path: Path = POLICY) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("policy_id") != "MLB_V8_EVIDENCE_V1" or not value.get("fail_closed"):
        raise RuntimeError("unexpected or non-fail-closed V8 evidence policy")
    return value


def dates_between(start: str, end: str):
    current = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while current <= stop:
        yield current.isoformat()
        current += timedelta(days=1)


def classify_source(name: str, registry: list[dict[str, Any]]) -> str:
    upper = name.upper()
    for row in registry:
        if str(row["source"]).upper() in upper:
            return str(row["tier"])
    return "UNREGISTERED"


def build(input_root: Path, output_root: Path) -> dict[str, Any]:
    policy = load_policy()
    window = policy["replay_window"]
    registry = policy["source_registry"]
    files: list[dict[str, Any]] = []
    coverage: dict[str, set[str]] = {}

    if input_root.exists():
        for path in sorted(p for p in input_root.rglob("*") if p.is_file()):
            raw = path.read_bytes()
            rel = path.relative_to(input_root).as_posix()
            source_name = rel.split("/", 1)[0]
            tier = classify_source(source_name, registry)
            day = next((part for part in path.parts if len(part) == 10 and part[4:5] == "-" and part[7:8] == "-"), None)
            files.append({
                "path": rel,
                "source": source_name,
                "evidence_tier": tier,
                "observed_date": day,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "truth_gate_eligible_as_decision_snapshot": tier == "A_PIT_SNAPSHOT",
            })
            if day:
                coverage.setdefault(day, set()).add(tier)

    gaps = []
    for day in dates_between(window["start_date"], window["end_date"]):
        tiers = sorted(coverage.get(day, set()))
        gaps.append({
            "date": day,
            "tiers_present": tiers,
            "has_pit_snapshot_source": "A_PIT_SNAPSHOT" in tiers,
            "status": "PIT_SOURCE_PRESENT" if "A_PIT_SNAPSHOT" in tiers else "PIT_SOURCE_MISSING",
        })

    manifest = {
        "schema": "MLB_V8_REPLAY_MANIFEST_V1",
        "policy_sha256": sha256_bytes(POLICY.read_bytes()),
        "window": window,
        "files": files,
        "file_count": len(files),
        "pit_days": sum(row["has_pit_snapshot_source"] for row in gaps),
        "total_days": len(gaps),
        "promotion_eligible": False,
        "promotion_reason": "REPLAY_ARCHIVE_CANNOT_REPLACE_UNTOUCHED_V8_FORWARD_HOLDOUT",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output_root / "gap_report.json").write_text(json.dumps(gaps, indent=2, sort_keys=True) + "\n")
    return manifest


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        inp = root / "in"
        out = root / "out"
        (inp / "THE_ODDS_API_HISTORICAL" / "2026-03-01").mkdir(parents=True)
        (inp / "THE_ODDS_API_HISTORICAL" / "2026-03-01" / "raw.json").write_text("{}\n")
        (inp / "SPORTSGAMEODDS_OPEN_CLOSE" / "2026-03-02").mkdir(parents=True)
        (inp / "SPORTSGAMEODDS_OPEN_CLOSE" / "2026-03-02" / "raw.json").write_text("{}\n")
        manifest = build(inp, out)
        rows = json.loads((out / "gap_report.json").read_text())
        assert manifest["promotion_eligible"] is False
        assert rows[0]["status"] == "PIT_SOURCE_PRESENT"
        assert rows[1]["status"] == "PIT_SOURCE_MISSING"
        assert manifest["files"][1]["truth_gate_eligible_as_decision_snapshot"] is False
    print(json.dumps({"status": "SELF_TEST_OK"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(args.input_root, args.output_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
