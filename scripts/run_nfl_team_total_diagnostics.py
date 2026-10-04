#!/usr/bin/env python3
"""Build an NFL team-total RUN IT diagnostic artifact from frozen run outputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nfl.team_total_diagnostic_bundle import (
    NFLTeamTotalDiagnosticBundleError,
    build_team_total_run_it_diagnostics,
)


def _json(path: Path, error: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NFLTeamTotalDiagnosticBundleError(error) from exc


def _asof(value: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_DIAGNOSTIC_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_DIAGNOSTIC_ASOF_TZ_REQUIRED")
    return out.astimezone(timezone.utc)


def _report(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_REPORT_MAPPING_REQUIRED")
    nested = payload.get("report")
    return nested if isinstance(nested, Mapping) else payload


def _handoffs(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping) and isinstance(payload.get("handoffs"), list):
        rows = payload["handoffs"]
    else:
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_HANDOFF_LIST_REQUIRED")
    if not all(isinstance(row, Mapping) for row in rows):
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_HANDOFF_LIST_INVALID")
    return list(rows)


def _events(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping) and isinstance(payload.get("events"), list):
        rows = payload["events"]
    else:
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_PROVIDER_EVENTS_REQUIRED")
    if not all(isinstance(row, Mapping) for row in rows):
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_PROVIDER_EVENTS_INVALID")
    return list(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--handoffs", type=Path, required=True)
    ap.add_argument("--event-odds", type=Path, required=True)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--book-key", default="draftkings")
    ap.add_argument("--ttl-seconds", type=int, default=180)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    try:
        result = build_team_total_run_it_diagnostics(
            report=_report(_json(args.report, "NFL_TEAM_TOTAL_REPORT_UNREADABLE")),
            handoffs=_handoffs(_json(args.handoffs, "NFL_TEAM_TOTAL_HANDOFFS_UNREADABLE")),
            provider_events=_events(_json(args.event_odds, "NFL_TEAM_TOTAL_EVENT_ODDS_UNREADABLE")),
            now=_asof(args.asof),
            book_key=args.book_key,
            ttl_seconds=int(args.ttl_seconds),
        )
    except (NFLTeamTotalDiagnosticBundleError, ValueError) as exc:
        result = {
            "schema_version": "NFL_TEAM_TOTAL_RUN_IT_DIAGNOSTICS_V1",
            "status": "BLOCKED",
            "blockers": [{"game_id": None, "reason": str(exc)}],
            "diagnostics": [],
            "bettor_card": [],
            "authority": {
                "creates_model_p": False,
                "truth_gate": False,
                "official": False,
                "promotion": False,
                "staking": False,
                "changes_engine_state": False,
                "inherits_game_total_promotion": False,
            },
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "diagnostic_game_count": len(result.get("diagnostics") or []),
        "blocked_game_count": len(result.get("blockers") or []),
        "bettor_card_count": len(result.get("bettor_card") or []),
        "output": str(args.output),
    }, sort_keys=True))
    return 0 if result["status"] == "DIAGNOSTICS_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
