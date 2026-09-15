#!/usr/bin/env python3
"""Static audit for the free-provider migration branch."""
from __future__ import annotations

import json
from pathlib import Path

FROZEN = (
    "scripts/nfl_2026_line_capture.py",
    "config/nfl_2026_capture.json",
    ".github/workflows/nfl-2026-line-capture.yml",
)


def main() -> int:
    contract = json.loads(Path("config/market_provider_contract_v1.json").read_text())
    assert contract["non_silent_satisfaction"] is True
    espn = next(x for x in contract["rules"] if x["provider"] == "ESPN_SCOREBOARD")
    assert set(espn["markets"]) == {"MONEYLINE", "RUN_LINE", "TOTALS"}
    assert espn["freshness"] == {
        "basis": "SOURCE_NATIVE_TIMESTAMP",
        "ttl_seconds": 60,
        "timestamp_required": True,
    }
    assert espn["book_identity"]["fallback_satisfies_exact_book_contract"] is False
    for path in FROZEN:
        assert Path(path).is_file(), path
    print(json.dumps({
        "status": "PASS",
        "authority": "ROUTING_AND_PROVENANCE_ONLY",
        "espn_markets": espn["markets"],
        "espn_ttl_seconds": 60,
        "frozen_confirmation_files_expected_unchanged": list(FROZEN),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
