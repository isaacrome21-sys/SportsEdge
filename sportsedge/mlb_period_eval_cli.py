"""Run research-only MLB first-3/first-7 historical walk-forward reports.

Example:
 python -m sportsedge.mlb_period_eval_cli --input historical.json --output report.json
No downloads, live pricing, quote fabrication, capture, or PLAY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sportsedge.mlb_period_historical_adapter import evaluate_historical_export


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Local evidenced historical export")
    parser.add_argument("--output", required=True, help="Output JSON report path")
    parser.add_argument("--min-train", type=int, default=20)
    parser.add_argument("--half-line", type=float, default=1.5)
    args = parser.parse_args(argv)
    source_sha256 = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
    reports = {
        f"first_{innings}": evaluate_historical_export(
            args.input, innings=innings,
            min_train=args.min_train, half_line=args.half_line)
        for innings in (3, 7)
    }
    result = {
        "schema": "MLB_PERIOD_WALKFORWARD_RESEARCH_REPORT_V1",
        "input_path": str(args.input),
        "input_sha256": source_sha256,
        "result_availability_authenticity_verified": False,
        "pit_evidence_verified": False,
        "market_evidence_paired": False,
        "research_only": True,
        "validated": False,
        "play_authorized": False,
        "reports": reports,
    }
    output = Path(args.output)
    if output.resolve() == Path(args.input).resolve():
        raise ValueError("OUTPUT_MUST_NOT_OVERWRITE_INPUT")
    if output.exists():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
