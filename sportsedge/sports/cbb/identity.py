"""CBB fixture and ESPN team-ID binding with ID-based Illinois exclusion.

Research only; not wired into canonical routing (that needs ChatGPT review).
- A team name resolves only if it matches EXACTLY ONE ESPN directory team
  (displayName/shortDisplayName/abbreviation/location/location+name forms).
- A fixture binds only if exactly one scoreboard event has both resolved
  ESPN team IDs in the right home/away slots and a start within 15 minutes.
- Playability is decided on the verified ESPN team ID against
  ``artifacts.free_models.IL_COLLEGE_ESPN_IDS`` (#2148). Any Illinois
  school -> BLOCKED ILLINOIS_COLLEGE_EXCLUDED at intake, whatever the name form.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping

from artifacts.free_models import IL_COLLEGE_ESPN_IDS

KICKOFF_TOLERANCE_S = 900


class CBBIdentityError(ValueError):
    pass


def _norm(v: Any) -> str:
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _teams(directory: Mapping) -> list:
    out = []
    for sport in directory.get("sports") or []:
        for league in sport.get("leagues") or []:
            for t in league.get("teams") or []:
                out.append(t.get("team") or t)
    return out or list(directory.get("teams") or [])


def resolve_team(directory: Mapping, name: str) -> dict:
    needle = _norm(name)
    if not needle:
        raise CBBIdentityError("TEAM_NAME_REQUIRED")
    hits = {}
    for t in _teams(directory):
        tid = str(t.get("id") or "")
        if not tid:
            continue
        forms = {_norm(t.get(k)) for k in ("displayName", "shortDisplayName", "abbreviation", "location")}
        forms.add(_norm(f"{t.get('location', '')} {t.get('name', '')}"))
        if needle in forms - {""}:
            hits[tid] = t
    if len(hits) != 1:
        raise CBBIdentityError("TEAM_NOT_UNIQUELY_RESOLVED:" + str(len(hits)))
    tid, t = next(iter(hits.items()))
    return {"id": tid, "name": t.get("displayName"), "illinois_excluded": tid in IL_COLLEGE_ESPN_IDS}


def _utc(v: str) -> datetime:
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise CBBIdentityError("START_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def bind_fixture(directory: Mapping, scoreboard: Mapping, *, away: str, home: str,
                 start: str, as_of: datetime) -> dict:
    if (not isinstance(as_of, datetime) or as_of.tzinfo is None
            or as_of.utcoffset() is None):
        raise CBBIdentityError("AS_OF_TIMEZONE_REQUIRED")
    a, h = resolve_team(directory, away), resolve_team(directory, home)
    if a["id"] == h["id"]:
        raise CBBIdentityError("DISTINCT_TEAMS_REQUIRED")
    want = _utc(start)
    matches = []
    for ev in scoreboard.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        slots = {c.get("homeAway"): str((c.get("team") or {}).get("id"))
                 for c in comp.get("competitors") or []}
        if slots.get("home") != h["id"] or slots.get("away") != a["id"]:
            continue
        try:
            st = _utc(ev.get("date") or comp.get("date"))
        except (CBBIdentityError, ValueError, TypeError):
            continue
        if abs((st - want).total_seconds()) <= KICKOFF_TOLERANCE_S:
            matches.append((ev, st, bool(comp.get("neutralSite"))))
    if len(matches) != 1:
        raise CBBIdentityError("FIXTURE_NOT_UNIQUELY_VERIFIED:" + str(len(matches)))
    ev, st, neutral = matches[0]
    event_id = ev.get("id")
    # Missing ID must not silently become the string "None" or "null".
    # ESPN's numeric event IDs are positive decimal identifiers, not booleans.
    if (type(event_id) not in (str, int)
            or not re.fullmatch(r"[0-9]+", str(event_id))
            or int(event_id) <= 0):
        raise CBBIdentityError("EVENT_ID_INVALID")
    if st <= as_of:
        raise CBBIdentityError("GAME_STARTED_OR_PAST")
    excluded = [x["name"] for x in (a, h) if x["illinois_excluded"]]
    return {"event_id": str(event_id), "start_utc": st.isoformat(), "neutral_site": neutral,
            "home_id": h["id"], "away_id": a["id"],
            "playable_status": "BLOCKED" if excluded else "RESEARCH_ONLY",
            "reason": "ILLINOIS_COLLEGE_EXCLUDED" if excluded else None,
            "excluded_teams": excluded, "play_authority": False}
