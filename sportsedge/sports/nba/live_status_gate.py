"""Research-only reconciliation of NBA official event state and DK screen state.

This is a refusal gate, not a live feed adapter, pricing model, or an NBA
addition to LIVE_ENGINE_V1. Caller-supplied receipts are not independently
authenticated here; they must be admitted upstream with preserved source
evidence. No result carries Model_P, actionable PLAY, or staking authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sportsedge.live_policy import LIVE_QUOTE_TTL_SECONDS, LIVE_STATE_TTL_SECONDS


VERSION = "NBA_LIVE_STATE_RECON_RESEARCH_V1"
_ID = re.compile(r"[A-Za-z0-9:_-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-fA-F]{64}\Z")
_PHASES = frozenset({"PREGAME", "LIVE", "FINAL", "SUSPENDED", "UNKNOWN"})
_LIVE_SETTLEMENT_SCOPES = frozenset({
    "FULL_GAME_INCLUDING_PRIOR_PLAY",
    "REMAINDER_FROM_ACCEPTANCE",
    "CURRENT_PERIOD_ONLY",
})
_MAX_CLOCK_DISAGREEMENT_SECONDS = 45


@dataclass(frozen=True)
class NBAOfficialEventReceipt:
    event_id: str
    home_team_id: str
    away_team_id: str
    scheduled_tipoff_utc: datetime
    phase: str
    period: Optional[int]
    clock_seconds_remaining: Optional[int]
    source_as_of_utc: datetime
    captured_at_utc: datetime
    provider: str
    evidence_sha256: str


@dataclass(frozen=True)
class DKScreenEventReceipt:
    event_id: str
    home_team_id: str
    away_team_id: str
    scheduled_tipoff_utc: datetime
    phase: str
    period: Optional[int]
    clock_seconds_remaining: Optional[int]
    market_settlement_scope: Optional[str]
    source_as_of_utc: datetime
    captured_at_utc: datetime
    bookmaker: str
    evidence_sha256: str


@dataclass(frozen=True)
class NBAStateDecision:
    status: str
    reason_code: str
    version: str = VERSION
    model_p_authority: bool = False
    play_authority: bool = False
    staking_authority: bool = False


def _refuse(reason_code: str) -> NBAStateDecision:
    return NBAStateDecision(status="REFUSED", reason_code=reason_code)


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _utc(value: object) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _receipt_freshness(
    source_as_of: object, captured_at: object, cutoff: datetime, ttl: int, prefix: str,
) -> Optional[str]:
    source = _utc(source_as_of)
    captured = _utc(captured_at)
    if source is None or captured is None:
        return prefix + "_TIMESTAMP_INVALID"
    if source > captured or captured > cutoff:
        return prefix + "_FUTURE_OR_REORDERED_TIMESTAMP"
    if (cutoff - source).total_seconds() > ttl:
        return prefix + "_STALE"
    return None


def _live_clock_valid(period: object, remaining: object) -> bool:
    if type(period) is not int or not 1 <= period <= 20:
        return False
    maximum = 720 if period <= 4 else 300
    return type(remaining) is int and 0 <= remaining <= maximum


def reconcile_nba_state(
    official: NBAOfficialEventReceipt,
    sportsbook: DKScreenEventReceipt,
    *,
    pit_cutoff_utc: datetime,
) -> NBAStateDecision:
    """Classify phase agreement at a point in time; always research-only.

    Refusals are independent of any projection or odds. A screen's LIVE badge
    is never treated as proof of game state. Requires a pre-established *exact*
    event ID and two independent receipt hashes; does not infer fixture links.
    """
    cutoff = _utc(pit_cutoff_utc)
    if cutoff is None:
        return _refuse("NBA_LIVE_PIT_CUTOFF_INVALID")
    if not isinstance(official, NBAOfficialEventReceipt) or not isinstance(
        sportsbook, DKScreenEventReceipt
    ):
        return _refuse("NBA_LIVE_RECEIPT_TYPE_INVALID")
    if official.provider != "NBA_OFFICIAL" or sportsbook.bookmaker != "DraftKings":
        return _refuse("NBA_LIVE_SOURCE_PROVENANCE_UNVERIFIED")
    if not all(_identifier(s) for s in (
        official.event_id, sportsbook.event_id, official.home_team_id,
        official.away_team_id, sportsbook.home_team_id, sportsbook.away_team_id,
    )):
        return _refuse("NBA_LIVE_FIXTURE_IDENTITY_INVALID")
    if official.home_team_id == official.away_team_id:
        return _refuse("NBA_LIVE_FIXTURE_IDENTITY_INVALID")
    if (
        official.event_id != sportsbook.event_id
        or official.home_team_id != sportsbook.home_team_id
        or official.away_team_id != sportsbook.away_team_id
    ):
        return _refuse("NBA_LIVE_CROSS_EVENT_OR_TEAM_CONFLICT")
    if (
        not isinstance(official.evidence_sha256, str)
        or not _SHA.fullmatch(official.evidence_sha256)
        or not isinstance(sportsbook.evidence_sha256, str)
        or not _SHA.fullmatch(sportsbook.evidence_sha256)
        or official.evidence_sha256.lower() == sportsbook.evidence_sha256.lower()
    ):
        return _refuse("NBA_LIVE_INDEPENDENT_EVIDENCE_REQUIRED")
    tip_official = _utc(official.scheduled_tipoff_utc)
    tip_book = _utc(sportsbook.scheduled_tipoff_utc)
    if tip_official is None or tip_book is None:
        return _refuse("NBA_LIVE_TIPOFF_TIMESTAMP_INVALID")
    if abs((tip_official - tip_book).total_seconds()) > 60:
        return _refuse("NBA_LIVE_FIXTURE_START_CONFLICT")
    if not isinstance(official.phase, str) or not isinstance(sportsbook.phase, str) or official.phase not in _PHASES or sportsbook.phase not in _PHASES:
        return _refuse("NBA_LIVE_UNRECOGNIZED_PHASE")
    state_error = _receipt_freshness(
        official.source_as_of_utc, official.captured_at_utc,
        cutoff, LIVE_STATE_TTL_SECONDS, "NBA_LIVE_OFFICIAL",
    )
    if state_error:
        return _refuse(state_error)
    quote_error = _receipt_freshness(
        sportsbook.source_as_of_utc, sportsbook.captured_at_utc,
        cutoff, LIVE_QUOTE_TTL_SECONDS, "NBA_LIVE_DK",
    )
    if quote_error:
        return _refuse(quote_error)
    if official.phase != sportsbook.phase:
        return _refuse("NBA_LIVE_PHASE_CONFLICT")
    if official.phase in {"FINAL", "SUSPENDED", "UNKNOWN"}:
        return _refuse("NBA_LIVE_NONACTIONABLE_PHASE")
    if official.phase == "PREGAME":
        if cutoff >= tip_official:
            return _refuse("NBA_LIVE_PREGAME_PAST_SCHEDULED_TIP_UNVERIFIED")
        if official.period is not None or sportsbook.period is not None:
            return _refuse("NBA_LIVE_PREGAME_PERIOD_CONFLICT")
        if official.clock_seconds_remaining is not None or sportsbook.clock_seconds_remaining is not None:
            return _refuse("NBA_LIVE_PREGAME_CLOCK_CONFLICT")
        return NBAStateDecision("RESEARCH_ONLY_PHASE_RECONCILED", "NBA_LIVE_PREGAME_AGREEMENT")
    if cutoff < tip_official:
        return _refuse("NBA_LIVE_BEFORE_SCHEDULED_TIP_UNVERIFIED")
    if not _live_clock_valid(official.period, official.clock_seconds_remaining):
        return _refuse("NBA_LIVE_OFFICIAL_PERIOD_OR_CLOCK_INVALID")
    if not _live_clock_valid(sportsbook.period, sportsbook.clock_seconds_remaining):
        return _refuse("NBA_LIVE_DK_PERIOD_OR_CLOCK_UNVERIFIED")
    if official.period != sportsbook.period:
        return _refuse("NBA_LIVE_PERIOD_CONFLICT")
    if abs(official.clock_seconds_remaining - sportsbook.clock_seconds_remaining) > _MAX_CLOCK_DISAGREEMENT_SECONDS:
        return _refuse("NBA_LIVE_GAME_CLOCK_CONFLICT")
    if not isinstance(sportsbook.market_settlement_scope, str) or sportsbook.market_settlement_scope not in _LIVE_SETTLEMENT_SCOPES:
        return _refuse("NBA_LIVE_MARKET_SETTLEMENT_SCOPE_UNVERIFIED")
    return NBAStateDecision("RESEARCH_ONLY_PHASE_RECONCILED", "NBA_LIVE_PHASE_AGREEMENT")
