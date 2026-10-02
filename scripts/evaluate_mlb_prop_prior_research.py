#!/usr/bin/env python3
"""Evaluate a frozen MLB prop-prior candidate JSONL file.

Input rows are deliberately simple and immutable.  Each JSON object must contain:
  target_at_utc, prior_max_at_utc, baseline_p, candidate_p, outcome

This command is research-only.  It never promotes a model or writes card outputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sportsedge.mlb_prop_prior_research import evaluate_heldout_rows


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"{path}:{line_number}: row must be a JSON object")
        rows.append(payload)
    if not rows:
        raise SystemExit(f"{path}: no held-out rows")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="frozen held-out JSONL rows")
    parser.add_argument("--noninferiority-margin", type=float, default=0.0)
    parser.add_argument("--tail-cutoff", type=float, default=0.90)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate_heldout_rows(
        _load_jsonl(args.input),
        noninferiority_margin=args.noninferiority_margin,
        tail_cutoff=args.tail_cutoff,
    )
    rendered = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["passes_research_gate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
