#!/usr/bin/env python3
"""Capture prospective market-blind MLB MONEYLINE Model_P predictions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from zoneinfo import ZoneInfo

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_moneyline_forward_prediction import (
    EVIDENCE_DISPOSITION,
    MLBMoneylineForwardPredictionBlocked,
    capture_due_predictions,
)
from sportsedge.mlb_source import fetch_schedule

CHICAGO_TZ = ZoneInfo("America/Chicago")
DEFAULT_OUTPUT_DIR = "data/mlb_forward_predictions"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--simulations", type=int, default=100000)
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    slate_date = now.astimezone(CHICAGO_TZ).date().isoformat()
    try:
        schedule = fetch_schedule(slate_date, now=now)
        history = MLBGenericHistorySource(retrieved_at=now)
        result = capture_due_predictions(
            schedule=schedule,
            history=history,
            now=now,
            output_dir=args.output_dir,
            simulations=args.simulations,
        )
    except MLBMoneylineForwardPredictionBlocked as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": exc.reason,
            "detail": exc.detail,
            "evidence_disposition": EVIDENCE_DISPOSITION,
            "promotion_authority": False,
        }, indent=2, sort_keys=True))
        return 2
    except Exception as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "BLOCKED_MODEL_P_SOURCE_OR_RUNTIME",
            "detail": str(exc),
            "evidence_disposition": EVIDENCE_DISPOSITION,
            "promotion_authority": False,
        }, indent=2, sort_keys=True))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
