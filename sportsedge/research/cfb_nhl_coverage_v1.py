"""Research-only existing-engine NHL view and CFB evidence readiness.

Does not run the CFB QB identity gate, authenticate DK quotes or
change deployed market registration. NHL rate v1 uses static priors and
is NOT a proven price/edge even when the research view is computable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

from sportsedge.nhl_rate_v1_card import (
    final_score_distribution, resolve_team, total_probs,
)

VERSION = "CFB_NHL_COVERAGE_RESEARCH_V1"


def _clock(value):
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise ValueError("COVERAGE_CLOCK_INVALID") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("COVERAGE_CLOCK_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def nhl_research_snapshot(*, away, home, event_id, event_start,
                          fixture_source_ref, as_of, total_line=5.5):
    """Read registered NHL rate-v1 foundation, NEVER activate RUN IT/PLAY."""
    if not str(event_id or "").strip() or not str(fixture_source_ref or "").strip():
        raise ValueError("NHL_FIXTURE_SOURCE_REQUIRED")
    start, clock = _clock(event_start), _clock(as_of)
    if clock >= start:
        return {"version": VERSION, "sport": "NHL",
                "status": "REFUSED", "reason": "NHL_EVENT_ALREADY_STARTED",
                "research_only": True, "play_authority": False}
    if not away or not home or str(away).casefold() == str(home).casefold():
        raise ValueError("NHL_FIXTURE_TEAMS_INVALID")
    # Raw aliases such as "Flyers" and "Philadelphia Flyers" differ as
    # strings but resolve to the SAME NHL franchise. Never simulate or
    # display a fictitious self-game as a legitimate fixture.
    away_id, home_id = resolve_team(away), resolve_team(home)
    if away_id is None or home_id is None:
        return {"version": VERSION, "sport": "NHL",
                "status": "REFUSED", "reason": "NHL_STATIC_RATE_TEAM_ID_UNMAPPED",
                "research_only": True, "play_authority": False}
    if away_id == home_id:
        raise ValueError("NHL_FIXTURE_SAME_CANONICAL_TEAM")
    # float("nan") compares neither above nor below any final goal total:
    # without validation, total_probs would falsely report 100% PUSH.
    if isinstance(total_line, bool):
        raise ValueError("NHL_TOTAL_LINE_INVALID")
    try:
        checked_line = float(total_line)
    except (TypeError, ValueError) as exc:
        raise ValueError("NHL_TOTAL_LINE_INVALID") from exc
    if not isfinite(checked_line) or checked_line <= 0:
        raise ValueError("NHL_TOTAL_LINE_INVALID")
    fsd = final_score_distribution(away_id, home_id)
    home_win = sum(p for (hg, ag), p in fsd["dist"].items() if hg > ag)
    away_win = sum(p for (hg, ag), p in fsd["dist"].items() if ag > hg)
    over, push, under = total_probs(fsd, checked_line)
    return {"version": VERSION, "sport": "NHL",
            "status": "RESEARCH_PROJECTION",
            "engine_ref": "sportsedge.nhl_rate_v1_card.final_score_distribution",
            "model_basis": "FROZEN_NHL_RATE_V1_STATIC_SEASON_PRIORS",
            "event_id": str(event_id), "fixture_source_ref": str(fixture_source_ref),
            "as_of_utc": clock.isoformat(), "start_utc": start.isoformat(),
            "p_home_win": home_win, "p_away_win": away_win,
            "total_line": checked_line, "p_over": over,
            "p_push": push, "p_under": under,
            "book_quote_status": "NOT_READ_NO_DK_PRICES",
            "market_validation": "NOT_VERIFIED",
            "capture_authentication": "CALLER_DECLARATION_NOT_VERIFIED",
            "research_only": True, "play_authority": False}


def cfb_readiness(*, away, home, event_id, event_start, as_of,
                  qb_manifest_pin=None, paired_dk_capture_ref=None):
    """Explain CFB evidence gaps without letting caller flags authenticate them."""
    if not str(event_id or "").strip() or not away or not home or away == home:
        raise ValueError("CFB_EVENT_IDENTITY_INVALID")
    start, clock = _clock(event_start), _clock(as_of)
    if clock >= start:
        return {"version": VERSION, "sport": "CFB", "status": "REFUSED",
                "event_id": str(event_id),
                "reason": "CFB_EVENT_ALREADY_STARTED", "research_only": True,
                "play_authority": False}
    absent = []
    if not str(qb_manifest_pin or "").strip():
        absent.append("CFB_QB_FORM2_EXTERNAL_MANIFEST_PIN_MISSING")
    if not str(paired_dk_capture_ref or "").strip():
        absent.append("CFB_PAIRED_DK_CAPTURE_MISSING")
    return {"version": VERSION, "sport": "CFB",
            "event_id": str(event_id),
            "status": "EVIDENCE_INTAKE_MISSING" if absent else
                      "EVIDENCE_SUBMITTED_NOT_INDEPENDENTLY_VERIFIED",
            "missing": absent,
            "authority": "NONE",
            "next": "EXISTING_CFB_FORM2_IDENTITY_AND_PAIRED_CAPTURE_GATE",
            "research_only": True, "play_authority": False}
