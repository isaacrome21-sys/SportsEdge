#!/usr/bin/env python3
"""Audit append-only CFB market/weather observations for future PIT-bundle use."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.core.validation.evidence_receipt import build_evidence_receipt
from sportsedge.sports.cfb.forward_evidence import audit_cfb_forward_market_weather_evidence


def _read_ndjson(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception as exc:
                raise SystemExit(f"CFB_FORWARD_EVIDENCE_NDJSON_INVALID:{path}:{number}") from exc
            if not isinstance(payload, dict):
                raise SystemExit(f"CFB_FORWARD_EVIDENCE_ROW_INVALID:{path}:{number}")
            rows.append(payload)
    return rows


def _receipt_files(
    root: Path,
    market_paths: list[Path],
    weather_paths: list[Path],
    market_rows: list[dict[str, Any]],
    weather_rows: list[dict[str, Any]],
    report_path: Path,
) -> list[tuple[str, Path]]:
    bound: dict[str, Path] = {}
    for path in [*market_paths, *weather_paths]:
        rel = path.relative_to(root).as_posix()
        bound[f"observations/{rel}"] = path
    for row in market_rows:
        rel = row.get("fetch_payload_path")
        if isinstance(rel, str) and rel.strip():
            candidate = root / rel
            if candidate.is_file() and not Path(rel).is_absolute() and ".." not in Path(rel).parts:
                bound[f"raw/{Path(rel).as_posix()}"] = candidate
    for row in weather_rows:
        rel = row.get("raw_relative_path")
        if isinstance(rel, str) and rel.strip():
            candidate = root / rel
            if candidate.is_file() and not Path(rel).is_absolute() and ".." not in Path(rel).parts:
                bound[f"raw/{Path(rel).as_posix()}"] = candidate
    bound["outputs/report.json"] = report_path
    return sorted(bound.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=".")
    parser.add_argument("--out", default="artifacts/cfb_forward_evidence/report.json")
    parser.add_argument("--receipt-out", default="artifacts/cfb_forward_evidence/receipt.json")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.data_root)
    market_dir = root / "archive" / "closing-lines" / "americanfootball_ncaaf"
    weather_dir = root / "history" / "cfb" / "weather"
    market_paths = sorted(p for p in market_dir.glob("*.ndjson") if p.is_file()) if market_dir.is_dir() else []
    weather_paths = sorted(p for p in weather_dir.glob("*.ndjson") if p.is_file()) if weather_dir.is_dir() else []
    market_rows = _read_ndjson(market_paths)
    weather_rows = _read_ndjson(weather_paths)
    report = audit_cfb_forward_market_weather_evidence(market_rows, weather_rows, data_root=root)
    report["market_files_scanned"] = [p.relative_to(root).as_posix() for p in market_paths]
    report["weather_files_scanned"] = [p.relative_to(root).as_posix() for p in weather_paths]
    report["market_rows_scanned"] = len(market_rows)
    report["weather_rows_scanned"] = len(weather_rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    receipt = build_evidence_receipt(
        _receipt_files(root, market_paths, weather_paths, market_rows, weather_rows, out),
        sport="cfb",
        purpose="forward_market_weather_chain_of_custody",
        metadata={
            "contract": report.get("contract"),
            "target_direction": report.get("target_direction"),
            "market_weather_evidence_ready": report.get("market_weather_evidence_ready"),
        },
    )
    receipt_out = Path(args.receipt_out)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    receipt_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({**report, "evidence_receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    if args.require_ready and report.get("market_weather_evidence_ready") is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
