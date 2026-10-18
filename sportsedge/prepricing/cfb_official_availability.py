"""Forward-only *admission* of independently pinned official CFB availability reports.

This module does not fetch, scrape, create timestamps, or confer bet authority.
A caller must supply raw report bytes from a separately trusted capture and an
externally pinned SHA-256; an intake/board-provided digest is NOT an anchor.
The official SEC, Big Ten and Big 12 offer conference-game availability
reports. A verified report is NOT itself a starting-QB identity / market edge.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

# These are *landing-host* trust allowlists, not claims that any URL is genuine.
# The actual source document must also match an externally pinned raw digest.
OFFICIAL_HOST = {
    "SEC": "www.secsports.com",
    "BIG_TEN": "bigten.org",
    "BIG_12": "big12sports.com",
}
GAMEDAY_STATUSES = {
    "SEC": frozenset({"OUT", "GAME_TIME_DECISION", "OUT_FIRST_HALF", "AVAILABLE"}),
    "BIG_TEN": frozenset({"OUT", "GAME_TIME_DECISION", "OUT_FIRST_HALF"}),
    "BIG_12": frozenset({"OUT", "GAME_TIME_DECISION", "AVAILABLE"}),
}
MAX_REPORT_BYTES = 1_000_000
MAX_FINAL_REPORT_AGE = timedelta(hours=24)


class CFBAvailabilityError(ValueError):
    """Reject malformed or unanchored evidence, never substitute healthy."""


def _fail(reason):
    raise CFBAvailabilityError(reason)


def _utc(value, field):
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        _fail(field + "_INVALID")
    if d.tzinfo is None or d.utcoffset() is None:
        _fail(field + "_NAIVE")
    return d.astimezone(timezone.utc)


def _uniq(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            _fail("DUPLICATE_JSON_KEY")
        out[k] = v
    return out


def _reject_constant(_):
    _fail("NONFINITE_JSON")


def _id(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        _fail(field + "_INVALID")
    result = str(value)
    if not result.isascii() or not result.isdigit() or int(result) <= 0:
        _fail(field + "_INVALID")
    return str(int(result))


def admit_official_availability(report_bytes, *, trusted_sha256, conference,
                                event_id, home_team_id, away_team_id,
                                qb_team_id, qb_athlete_id, kickoff, as_of):
    """Return research-only QB availability semantics from a trusted final report.

    Raw JSON is an already parsed, externally recorded official publication, not
    a schema for user-provided sportsbook lines. The caller MUST independently
    pin trusted_sha256 from outside the report/source bundle. No output says
    starter confirmed, clean injury report, prediction validated, or PLAY.
    """
    if not isinstance(report_bytes, bytes) or not 0 < len(report_bytes) <= MAX_REPORT_BYTES:
        _fail("REPORT_BYTES_INVALID")
    if not isinstance(trusted_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", trusted_sha256):
        _fail("EXTERNAL_ANCHOR_REQUIRED")
    if hashlib.sha256(report_bytes).hexdigest() != trusted_sha256:
        _fail("EXTERNAL_ANCHOR_MISMATCH")
    if conference not in OFFICIAL_HOST:
        _fail("UNSUPPORTED_CONFERENCE")
    try:
        obj = json.loads(report_bytes.decode("utf-8"), object_pairs_hook=_uniq,
                         parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CFBAvailabilityError):
            raise
        _fail("REPORT_JSON_INVALID")
    if not isinstance(obj, dict) or obj.get("schema") != "SPORTSEDGE_OFFICIAL_CFB_AVAILABILITY_V1":
        _fail("REPORT_SCHEMA_INVALID")
    if obj.get("conference") != conference or obj.get("report_type") != "FINAL_GAMEDAY":
        _fail("REPORT_CONFERENCE_OR_PHASE_MISMATCH")
    try:
        url = urlsplit(obj.get("official_source_url"))
    except (TypeError, ValueError):
        _fail("OFFICIAL_SOURCE_URL_INVALID")
    if (url.scheme != "https" or url.hostname != OFFICIAL_HOST[conference]
            or url.username is not None or url.password is not None or url.port is not None
            or not url.path.startswith("/") or url.fragment):
        _fail("OFFICIAL_SOURCE_URL_INVALID")
    wanted_event = _id(event_id, "EVENT")
    if _id(obj.get("event_id"), "REPORT_EVENT") != wanted_event:
        _fail("EVENT_MISMATCH")
    home = _id(home_team_id, "HOME_TEAM")
    away = _id(away_team_id, "AWAY_TEAM")
    if home == away:
        _fail("NON_DISTINCT_TEAMS")
    if _id(obj.get("home_team_id"), "REPORT_HOME") != home or _id(obj.get("away_team_id"), "REPORT_AWAY") != away:
        _fail("FIXTURE_MISMATCH")
    qb_team = _id(qb_team_id, "QB_TEAM")
    if qb_team not in (home, away):
        _fail("QB_TEAM_NOT_IN_FIXTURE")
    qb_id = _id(qb_athlete_id, "QB_ATHLETE")
    start, cutoff = _utc(kickoff, "KICKOFF"), _utc(as_of, "AS_OF")
    published = _utc(obj.get("published_at_utc"), "PUBLISHED")
    fetched = _utc(obj.get("fetch_completed_at_utc"), "FETCH")
    if _utc(obj.get("kickoff_utc"), "REPORT_KICKOFF") != start:
        _fail("KICKOFF_MISMATCH")
    if not start > cutoff >= fetched >= published >= start - MAX_FINAL_REPORT_AGE:
        _fail("REPORT_NOT_AVAILABLE_AS_OF_OR_STALE")
    teams = obj.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        _fail("COMPLETE_TWO_TEAM_REPORT_REQUIRED")
    ids, statuses = set(), {}
    for team in teams:
        if not isinstance(team, dict) or team.get("complete_final_report") is not True:
            _fail("COMPLETE_TWO_TEAM_REPORT_REQUIRED")
        tid = _id(team.get("espn_team_id"), "REPORT_TEAM")
        if tid in ids or tid not in (home, away):
            _fail("TEAM_MISMATCH_OR_DUPLICATE")
        ids.add(tid)
        athletes = team.get("players")
        if not isinstance(athletes, list) or len(athletes) > 250:
            _fail("PLAYER_ARRAY_INVALID")
        distinct = set()
        for player in athletes:
            if not isinstance(player, dict):
                _fail("PLAYER_ROW_INVALID")
            athlete = _id(player.get("espn_athlete_id"), "REPORT_PLAYER")
            status = player.get("availability")
            if athlete in distinct or status not in GAMEDAY_STATUSES[conference]:
                _fail("PLAYER_DUPLICATE_OR_STATUS_INVALID")
            distinct.add(athlete)
            statuses[(tid, athlete)] = status
    if ids != {home, away}:
        _fail("COMPLETE_TWO_TEAM_REPORT_REQUIRED")
    actual = statuses.get((qb_team, qb_id))
    # Absence is intentionally *not* automatically a declaration of health:
    # official policies have roster/two-deep exemptions and coverage rules.
    verdict = actual if actual is not None else "NOT_LISTED_AVAILABILITY_UNKNOWN"
    return {
        "conference": conference, "event_id": wanted_event,
        "qb_team_id": qb_team, "qb_athlete_id": qb_id,
        "qb_availability": verdict, "qb_starter_identity_verified": False,
        "source": "OFFICIAL_CONFERENCE_FINAL_REPORT_EXTERNALLY_PINNED",
        "report_sha256": trusted_sha256, "published_at_utc": published.isoformat(),
        "fetch_completed_at_utc": fetched.isoformat(),
        "research_only": True, "eligible": False,
        "play_authority": False, "staking_authority": False,
        "activation_allowed": False,
    }
