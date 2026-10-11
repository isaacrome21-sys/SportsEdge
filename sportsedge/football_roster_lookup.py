"""Verify NFL/CFB athlete identity using *matchup-team* ESPN rosters.

ESPN global search is not a reliable team-membership source: some hits omit
team.id. Only a unique exact-name athlete on one of the independently verified
fixture teams is accepted. Roster failures remain fail-closed.
"""
from __future__ import annotations

from urllib.parse import quote

ESPN_ROSTERS = "https://site.api.espn.com/apis/site/v2/sports/football"


class FootballRosterAmbiguity(ValueError):
    pass


def _normalize(name):
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in str(name or "")).split())


def lookup_matchup_roster_player(fetch, *, league, team_ids, player_name):
    """Find a single verified player within the two independently bound teams.

    Returns None when data are absent/no unique name, never guesses an ID.
    A name present on two different team rosters raises instead of picking one.
    """
    if league not in {"nfl", "college-football"}:
        raise FootballRosterAmbiguity("INVALID_FOOTBALL_LEAGUE")
    ids = {str(x) for x in team_ids}
    if len(ids) != 2 or "" in ids:
        raise FootballRosterAmbiguity("UNVERIFIED_MATCHUP_TEAM_IDS")
    wanted = _normalize(player_name)
    if not wanted:
        return None
    candidates = {}
    for tid in sorted(ids):
        url = f"{ESPN_ROSTERS}/{league}/teams/{quote(tid, safe='')}/roster"
        payload = fetch(url)
        if not isinstance(payload, dict):
            continue
        roster_team = payload.get("team") or {}
        if isinstance(roster_team, dict) and roster_team.get("id") is not None:
            if str(roster_team["id"]) != tid:
                continue
        groups = payload.get("athletes")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            entries = group.get("items")
            if not isinstance(entries, list):
                entries = [group] if group.get("id") else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete") or entry
                if not isinstance(athlete, dict):
                    continue
                name = athlete.get("displayName") or athlete.get("fullName")
                aid = str(athlete.get("id") or "")
                if not aid or _normalize(name) != wanted:
                    continue
                claimed_team = athlete.get("team") or entry.get("team") or {}
                if isinstance(claimed_team, dict) and claimed_team.get("id") is not None:
                    if str(claimed_team["id"]) != tid:
                        continue
                candidates[(tid, aid)] = {"id": aid, "displayName": name,
                                           "team": {"id": tid}}
    if len(candidates) > 1:
        raise FootballRosterAmbiguity("PLAYER_DUPLICATE_MATCHUP_ROSTERS")
    return next(iter(candidates.values())) if candidates else None
