#!/usr/bin/env python3
"""Pack large prospective CFB participation source files for Git-safe persistence.

The snapshot must already have passed the raw-source PIT audit. Packing is reversible
and preserves the original upstream content SHA256; it changes storage only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.participation_storage import (
    CFBParticipationStorageError,
    DEFAULT_MAX_STORED_BYTES,
    DEFAULT_PACK_THRESHOLD_BYTES,
    pack_participation_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument(
        "--threshold-bytes",
        type=int,
        default=DEFAULT_PACK_THRESHOLD_BYTES,
    )
    parser.add_argument(
        "--max-stored-bytes",
        type=int,
        default=DEFAULT_MAX_STORED_BYTES,
    )
    args = parser.parse_args()

    try:
        result = pack_participation_snapshot(
            args.classification,
            threshold_bytes=args.threshold_bytes,
            max_stored_bytes=args.max_stored_bytes,
        )
    except CFBParticipationStorageError as exc:
        print(json.dumps({
            "status": "BLOCKED_PARTICIPATION_STORAGE",
            "reason": str(exc),
            "model_fit_performed": False,
            "historical_pit_created": False,
            "model_p_created": False,
            "promotion_authority": False,
            "eligibility_changed": False,
        }, sort_keys=True))
        return 2

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
