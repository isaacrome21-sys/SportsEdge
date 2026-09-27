"""Non-authoritative NFL kickoff discovery for confirmation-window scheduling.

Schedule data identifies WHEN a FINAL obligation exists. It never supplies odds,
book/provider identity, quote timestamps, hashes, Model_P, or evidence authority.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_nfl_events(*, timeout: int = 20) -> list[dict]:
    req = urllib.request.Request(
        ESPN_SCOREBOARD,
        headers={"User-Agent": "SportsEdge-NFL-window-discovery/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    rows = []
    for event in payload.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]
        competitors = comp.get("competitors") or []
        home = next((x for x in competitors if x.get("homeAway") == "home"), None)
        away = next((x for x in competitors if x.get("homeAway") == "away"), None)
        kickoff = event.get("date")
        event_id = event.get("id")
        if not (event_id and kickoff and home and away):
            continue
        # Parse now so malformed/naive timestamps fail before they can define a window.
        _parse_iso(kickoff)
        rows.append({
            "id": str(event_id),
            "commence_time": kickoff,
            "home_team": home.get("team", {}).get("displayName") or home.get("team", {}).get("name"),
            "away_team": away.get("team", {}).get("displayName") or away.get("team", {}).get("name"),
            "schedule_source": "ESPN_PUBLIC_SCOREBOARD",
            "schedule_only": True,
        })
    return rows
