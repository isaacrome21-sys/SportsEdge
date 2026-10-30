#!/usr/bin/env python3
"""Evaluate preregistered prospective NHL prop receipts. No capture/backfill here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.sports.nhl.prop_forward_validation import (
    NHLPropForwardValidationError,
    evaluate,
    prediction_from_mapping,
    settlement_from_mapping,
)


def _jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NHLPropForwardValidationError(f"{path}:{number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise NHLPropForwardValidationError(f"{path}:{number}: object required")
        rows.append(value)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--settlements", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    predictions = [prediction_from_mapping(row) for row in _jsonl(args.predictions)]
    settlements = [settlement_from_mapping(row) for row in _jsonl(args.settlements)]
    report = evaluate(predictions, settlements)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
