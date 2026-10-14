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
    a, h = resolve_team(directory, away), resolve_team(directory, home)
    if a["id"] == h["id"]:
        raise CBBIdentityError("DISTINCT_TEAMS_REQUIRED")
    if (not isinstance(as_of, datetime) or as_of.tzinfo is None
            or as_of.utcoffset() is None):
        raise CBBIdentityError("AS_OF_TIMEZONE_REQUIRED")
    as_of_utc = as_of.astimezone(timezone.utc)
    want = _utc(start)
    if not isinstance(scoreboard, Mapping):
        raise CBBIdentityError("SCOREBOARD_INVALID")
    events = scoreboard.get("events")
    if not isinstance(events, list):
        raise CBBIdentityError("SCOREBOARD_EVENTS_INVALID")
    matches = []
    for ev in events:
        if not isinstance(ev, Mapping):
            continue
        event_id = ev.get("id")
        # Missing, bool, zero or text sentinel IDs may not become "None"
        # or an apparently identified research fixture.
        id_text = str(event_id)
        if (type(event_id) not in (str, int) or len(id_text) > 20
                or not id_text.isascii() or not id_text.isdigit()
                or not any(ch != "0" for ch in id_text)):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or len(competitions) != 1:
            continue
        comp = competitions[0]
        if not isinstance(comp, Mapping):
            continue
        competitors = comp.get("competitors")
        if not isinstance(competitors, list) or any(
                not isinstance(c, Mapping) for c in competitors):
            continue
        # Never use last-wins dictionary construction for duplicate slots.
        home_slots = [c for c in competitors if c.get("homeAway") == "home"]
        away_slots = [c for c in competitors if c.get("homeAway") == "away"]
        if len(competitors) != 2 or len(home_slots) != 1 or len(away_slots) != 1:
            continue
        home_team = home_slots[0].get("team")
        away_team = away_slots[0].get("team")
        if not isinstance(home_team, Mapping) or not isinstance(away_team, Mapping):
            continue
        if str(home_team.get("id")) != h["id"] or str(away_team.get("id")) != a["id"]:
            continue
        try:
            st = _utc(ev.get("date") or comp.get("date"))
        except (CBBIdentityError, ValueError, TypeError):
            continue
        if abs((st - want).total_seconds()) <= KICKOFF_TOLERANCE_S:
            matches.append((str(event_id), st, bool(comp.get("neutralSite"))))
    if len(matches) != 1:
        raise CBBIdentityError("FIXTURE_NOT_UNIQUELY_VERIFIED:" + str(len(matches)))
    event_id, st, neutral = matches[0]
    if st <= as_of_utc:
        raise CBBIdentityError("GAME_STARTED_OR_PAST")
    excluded = [x["name"] for x in (a, h) if x["illinois_excluded"]]
    return {"event_id": event_id, "start_utc": st.isoformat(), "neutral_site": neutral,
            "home_id": h["id"], "away_id": a["id"],
            "playable_status": "BLOCKED" if excluded else "RESEARCH_ONLY",
            "reason": "ILLINOIS_COLLEGE_EXCLUDED" if excluded else None,
            "excluded_teams": excluded, "play_authority": False}
