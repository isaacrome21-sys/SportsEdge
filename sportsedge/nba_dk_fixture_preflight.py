"""Research-only NBA DraftKings player-to-fixture identity preflight.

This is a *screen*, not authenticated DraftKings evidence, a forward-clock
entry, a model, a roster archive, or a betting decision. It cross-checks
captured market rows against an independent ESPN fixture and its two team
rosters before any later pricing workflow may consider them. The calling
workflow must separately persist the raw source responses and prove PIT
timestamps before admission to a governed prospective ledger.

The legacy phone pricer and forward ledger are intentionally NOT changed:
integrating this screen into their production path needs a separate review
and a no-bypass invariant. Nothing here converts a quote into verified CLV.
"""
from __future__ import annotations

from datetime import timedelta

from sportsedge.sports.nba.espn_verified_source import (
    NBADataError, NBASource, _clock, _norm_name, team_by_id,
)

MAX_FIXTURE_TIME_DELTA = timedelta(minutes=30)
SCREEN_STATUS = "NBA_DK_FIXTURE_ROSTER_SCREENED_RESEARCH_ONLY"


def screen_nba_dk_player_rows(
    rows: list[dict],
    *,
    source: NBASource,
    dk_event_id: str,
    away_name: str,
    home_name: str,
    scheduled_tipoff: str,
    observed_at: str,
) -> dict:
    """Return research-only screened rows and explicit per-row refusals.

    The fixture and roster come from NBASource (ESPN); event/team names,
    player names, quote times and the DK event ID are input assertions that
    must reconcile. A good match is never a validated odds quote.
    """
    if type(rows) is not list or not isinstance(source, NBASource):
        raise NBADataError("NBA_DK_PREFLIGHT_INPUT_INVALID")
    event_id = str(dk_event_id or "").strip()
    if not event_id:
        raise NBADataError("NBA_DK_EVENT_ID_REQUIRED")
    observed = _clock(observed_at, "NBA_DK_PREFLIGHT_OBSERVED_AT")
    proposed = _clock(scheduled_tipoff, "NBA_DK_PREFLIGHT_TIPOFF")
    if observed >= proposed:
        raise NBADataError("NBA_DK_PREFLIGHT_NOT_PRE_EVENT")

    fixture = source.resolve_fixture(
        away_name=away_name, home_name=home_name,
        owner_tipoff=scheduled_tipoff, as_of=observed_at,
    )
    fixture_id = str(fixture.get("id") or "").strip()
    if not fixture_id:
        raise NBADataError("NBA_DK_ESPN_EVENT_ID_REQUIRED")
    actual_tip = _clock(fixture.get("date"), "NBA_DK_ESPN_TIPOFF")
    if (abs(actual_tip - proposed) > MAX_FIXTURE_TIME_DELTA
            or observed >= actual_tip):
        raise NBADataError("NBA_DK_ESPN_FIXTURE_CLOCK_MISMATCH")

    home, away = source._competitors(fixture)
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    home_id = str(home_team.get("id") or "").strip()
    away_id = str(away_team.get("id") or "").strip()
    if not home_id or not away_id or home_id == away_id:
        raise NBADataError("NBA_DK_FIXTURE_TEAM_IDS_UNVERIFIED")
    team_by_id(home_id)
    team_by_id(away_id)
    if (_norm_name(home_team.get("displayName")) != _norm_name(home_name)
            or _norm_name(away_team.get("displayName")) != _norm_name(away_name)):
        raise NBADataError("NBA_DK_FIXTURE_TEAM_NAMES_MISMATCH")
    teams = {home_id, away_id}

    screened, rejected = [], []
    for index, raw in enumerate(rows):
        reason = None
        resolved = None
        if not isinstance(raw, dict):
            reason = "NBA_DK_ROW_NOT_OBJECT"
        elif str(raw.get("sport") or "").upper() != "NBA":
            reason = "NBA_DK_ROW_WRONG_SPORT"
        elif str(raw.get("event_id") or "").strip() != event_id:
            reason = "NBA_DK_ROW_EVENT_MISMATCH"
        elif str(raw.get("book") or "").strip().lower() not in {"dk", "draftkings"}:
            reason = "NBA_DK_ROW_BOOK_UNVERIFIED"
        elif not str(raw.get("capture_id") or "").strip():
            reason = "NBA_DK_ROW_CAPTURE_ID_MISSING"
        elif (_norm_name(raw.get("home") or raw.get("home_team")) != _norm_name(home_name)
              or _norm_name(raw.get("away") or raw.get("away_team")) != _norm_name(away_name)):
            reason = "NBA_DK_ROW_MATCHUP_MISMATCH"
        elif not str(raw.get("player_name") or "").strip():
            reason = "NBA_DK_ROW_PLAYER_NAME_MISSING"
        else:
            try:
                raw_tip = _clock(
                    raw.get("commence_time") or raw.get("event_start"),
                    "NBA_DK_ROW_TIPOFF",
                )
                quote_at = _clock(
                    raw.get("quote_captured_at") or raw.get("captured_at"),
                    "NBA_DK_ROW_QUOTE_CAPTURED_AT",
                )
                if (abs(raw_tip - actual_tip) > MAX_FIXTURE_TIME_DELTA
                        or quote_at > observed or quote_at >= actual_tip):
                    reason = "NBA_DK_ROW_CLOCK_MISMATCH"
                else:
                    resolved = source.resolve_athlete(
                        str(raw["player_name"]), teams,
                    )
                    if (not str(resolved.get("id") or "").strip()
                            or str(resolved.get("team_id") or "") not in teams):
                        reason = "NBA_DK_ROW_PLAYER_NOT_ON_FIXTURE_ROSTER"
            except NBADataError:
                reason = "NBA_DK_ROW_PLAYER_OR_TIMESTAMP_UNVERIFIED"

        if reason is not None:
            rejected.append({
                "input_index": index,
                "reason": reason,
                "event_id": raw.get("event_id") if isinstance(raw, dict) else None,
                "player_name": raw.get("player_name") if isinstance(raw, dict) else None,
            })
            continue
        # Append immutable-to-caller row copies, never invented odds/probability.
        screened.append({
            "input_index": index,
            "raw": dict(raw),
            "espn_event_id": fixture_id,
            "espn_player_id": str(resolved["id"]),
            "espn_team_id": str(resolved["team_id"]),
            "status": SCREEN_STATUS,
            "research_only": True,
            "quote_admitted": False,
            "model_p_authority": False,
            "staking_authority": False,
        })

    return {
        "status": SCREEN_STATUS,
        "dk_event_id": event_id,
        "espn_event_id": fixture_id,
        "espn_fixture_team_ids": sorted(teams),
        "observed_at": observed_at,
        "screened": screened,
        "rejected": rejected,
        "accounting": {
            "raw_rows": len(rows),
            "screened_rows": len(screened),
            "rejected_rows": len(rejected),
            "conservation_ok": len(rows) == len(screened) + len(rejected),
        },
        "forward_clock_authority": False,
        "quote_admission_authority": False,
        "requires_independent_pit_roster_archive": True,
    }
