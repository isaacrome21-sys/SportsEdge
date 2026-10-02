"""RUN IT diagnostic bundling for NFL team totals.

This lane deliberately remains outside the bettor card. It consumes only an
already-produced canonical NFL report, the exact verified score-distribution
handoffs, and event-level sportsbook team-total quotes. Missing or ambiguous
inputs are surfaced as blockers; they are never silently skipped.

Nothing in this module can open the production team-total capability, create
Model_P authority, inherit GAME_TOTAL promotion, or emit an OFFICIAL bet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.team_total_handoff import NFLTeamTotalHandoffError
from sportsedge.sports.nfl.team_total_quotes import (
    NFLTeamTotalQuoteError,
    build_verified_team_total_diagnostics,
)

SCHEMA = "NFL_TEAM_TOTAL_RUN_IT_DIAGNOSTICS_V1"


class NFLTeamTotalDiagnosticBundleError(ValueError):
    pass


def _report_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(report, Mapping):
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_REPORT_MAPPING_REQUIRED")
    rows = report.get("results")
    if not isinstance(rows, list):
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_REPORT_RESULTS_REQUIRED")
    out = [dict(row) for row in rows if isinstance(row, Mapping)]
    if len(out) != len(rows):
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_REPORT_RESULT_INVALID")
    return out


def _game_ids(report: Mapping[str, Any]) -> list[str]:
    ids = sorted({str(row.get("game_id") or "").strip() for row in _report_rows(report)})
    if not ids or "" in ids:
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_REPORT_GAME_ID_INVALID")
    return ids


def _unique_index(
    rows: Sequence[Mapping[str, Any]],
    *,
    key: str,
    missing_error: str,
    duplicate_error: str,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise NFLTeamTotalDiagnosticBundleError(missing_error)
        value = str(raw.get(key) or "").strip()
        if not value:
            raise NFLTeamTotalDiagnosticBundleError(missing_error)
        if value in out:
            raise NFLTeamTotalDiagnosticBundleError(f"{duplicate_error}:{value}")
        out[value] = dict(raw)
    return out


def build_team_total_run_it_diagnostics(
    *,
    report: Mapping[str, Any],
    handoffs: Sequence[Mapping[str, Any]],
    provider_events: Sequence[Mapping[str, Any]],
    now: datetime,
    book_key: str = "draftkings",
    ttl_seconds: int = 180,
) -> dict[str, Any]:
    """Build a complete diagnostic board while keeping bettor output empty."""
    games = _game_ids(report)
    handoff_by_game = _unique_index(
        handoffs,
        key="game_id",
        missing_error="NFL_TEAM_TOTAL_HANDOFF_GAME_ID_REQUIRED",
        duplicate_error="NFL_TEAM_TOTAL_HANDOFF_GAME_ID_DUPLICATE",
    )
    event_by_id = _unique_index(
        provider_events,
        key="id",
        missing_error="NFL_TEAM_TOTAL_PROVIDER_EVENT_ID_REQUIRED",
        duplicate_error="NFL_TEAM_TOTAL_PROVIDER_EVENT_ID_DUPLICATE",
    )

    report_rows = _report_rows(report)
    diagnostics: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []

    for game_id in games:
        rows = [row for row in report_rows if str(row.get("game_id") or "").strip() == game_id]
        provider_ids = {str(row.get("provider_event_id") or "").strip() for row in rows}
        if len(provider_ids) != 1 or "" in provider_ids:
            blockers.append({
                "game_id": game_id,
                "reason": "NFL_TEAM_TOTAL_REPORT_EVENT_ID_INVALID",
            })
            continue
        event_id = next(iter(provider_ids))
        handoff = handoff_by_game.get(game_id)
        if handoff is None:
            blockers.append({
                "game_id": game_id,
                "reason": "NFL_TEAM_TOTAL_HANDOFF_MISSING",
            })
            continue
        event = event_by_id.get(event_id)
        if event is None:
            blockers.append({
                "game_id": game_id,
                "reason": "NFL_TEAM_TOTAL_PROVIDER_EVENT_MISSING",
            })
            continue
        try:
            result = build_verified_team_total_diagnostics(
                handoff=handoff,
                report=report,
                event=event,
                now=now,
                book_key=book_key,
                ttl_seconds=int(ttl_seconds),
            )
        except (
            NFLTeamTotalHandoffError,
            NFLTeamTotalQuoteError,
            NFLTeamTotalDiagnosticBundleError,
            TypeError,
            ValueError,
        ) as exc:
            blockers.append({"game_id": game_id, "reason": str(exc)})
            continue

        if any(bool(row.get("official_eligible")) for row in result.get("rows") or []):
            raise NFLTeamTotalDiagnosticBundleError(
                "NFL_TEAM_TOTAL_DIAGNOSTIC_OFFICIAL_AUTHORITY_LEAK"
            )
        diagnostics.append(result)

    expected = set(games)
    observed = {str(row.get("game_id") or "") for row in diagnostics}
    blocked_games = {row["game_id"] for row in blockers}
    if observed | blocked_games != expected or observed & blocked_games:
        raise NFLTeamTotalDiagnosticBundleError("NFL_TEAM_TOTAL_DIAGNOSTIC_GAME_ACCOUNTING_INVALID")

    status = "DIAGNOSTICS_READY" if not blockers else (
        "BLOCKED" if not diagnostics else "PARTIAL_DIAGNOSTICS"
    )
    return {
        "schema_version": SCHEMA,
        "status": status,
        "game_count": len(games),
        "diagnostic_game_count": len(diagnostics),
        "blocked_game_count": len(blockers),
        "diagnostics": diagnostics,
        "blockers": blockers,
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
        "governance": {
            "diagnostics_are_not_bettor_card": True,
            "all_games_accounted_for": True,
            "missing_inputs_are_not_silently_skipped": True,
            "team_total_capability_remains_no_engine": True,
        },
    }


__all__ = [
    "NFLTeamTotalDiagnosticBundleError",
    "SCHEMA",
    "build_team_total_run_it_diagnostics",
]
