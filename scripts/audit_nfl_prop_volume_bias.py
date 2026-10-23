#!/usr/bin/env python3
"""Print a research-only NFL prop direction and realized-volume bias report.

Input is an independently assembled JSON object with ``rows`` holding
pregame model/quote receipts joined to later results, plus the declarations
``source_type=JOINED_POSTGAME_DIAGNOSTIC_INPUT`` and ``research_only=true``.
The script fetches no live data, never fills in missing receipts, and never
produces a PLAY, Model_P, historical backfill, or forward-count admission.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.research.nfl_prop_volume_bias_audit_v1 import audit_nfl_prop_volume_bias


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Existing, timestamped postgame join JSON")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if (not isinstance(payload, dict)
                or payload.get("source_type") != "JOINED_POSTGAME_DIAGNOSTIC_INPUT"
                or payload.get("research_only") is not True):
            raise ValueError("RESEARCH_POSTGAME_JOIN_REQUIRED")
        result = audit_nfl_prop_volume_bias(payload.get("rows"))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
