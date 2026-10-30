"""ESPN NFL final receipts bound to previously captured NFL games.

This is result evidence only, never a sportsbook quote. Source URL, actual
fetch time and hash of the unmodified HTTP response accompany each final.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SOURCE = "ESPN_SCOREBOARD"
ROOT = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={date}&limit=100"
SCHEMA = "sportsedge.nfl_final_receipt.v1"


class FinalReceiptError(ValueError):
    pass


def _instant(value: Any) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (ValueError, TypeError) as exc:
        raise FinalReceiptError("FINAL_TIME_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise FinalReceiptError("FINAL_TIME_OFFSET_REQUIRED")
    return result.astimezone(timezone.utc)


def scoreboard_url(kickoff: str) -> str:
    local = _instant(kickoff).astimezone(ZoneInfo("America/Chicago"))
    return ROOT.format(date=local.strftime("%Y%m%d"))


def _points(value: Any) -> int:
    if isinstance(value, bool):
        raise FinalReceiptError("FINAL_POINTS_INVALID")
    try:
        val = float(value)
    except (TypeError, ValueError) as exc:
        raise FinalReceiptError("FINAL_POINTS_INVALID") from exc
    if not math.isfinite(val) or val < 0 or not val.is_integer():
        raise FinalReceiptError("FINAL_POINTS_INVALID")
    return int(val)


def bind_espn_final(*, raw: bytes, source_url: str, fetched_at: str,
                    away: str, home: str, kickoff: str) -> dict:
    """Reject anything but an unambiguous ESPN FINAL for the exact fixture."""
    start, fetched = _instant(kickoff), _instant(fetched_at)
    if fetched <= start:
        raise FinalReceiptError("FINAL_FETCH_PREKICKOFF")
    if source_url != scoreboard_url(kickoff):
        raise FinalReceiptError("FINAL_SOURCE_URL_MISMATCH")
    if not isinstance(raw, bytes) or not raw or len(raw) > 4_000_000:
        raise FinalReceiptError("FINAL_SOURCE_BYTES_INVALID")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise FinalReceiptError("FINAL_JSON_INVALID") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise FinalReceiptError("FINAL_EVENTS_INVALID")
    matches = []
    for event in payload["events"]:
        comps = event.get("competitions") or []
        if len(comps) != 1:
            continue
        comp = comps[0]
        sides = {x.get("homeAway"): x for x in comp.get("competitors") or []}
        if set(sides) != {"home", "away"}:
            continue
        a_code = str((sides["away"].get("team") or {}).get("abbreviation") or "").upper()
        h_code = str((sides["home"].get("team") or {}).get("abbreviation") or "").upper()
        if (a_code, h_code) != (away.upper(), home.upper()):
            continue
        if _instant(event.get("date")) != start:
            raise FinalReceiptError("FINAL_KICKOFF_MISMATCH")
        status = ((comp.get("status") or event.get("status") or {}).get("type") or {})
        if not (status.get("completed") is True
                and str(status.get("name") or "").startswith("STATUS_FINAL")):
            raise FinalReceiptError("FINAL_NOT_COMPLETED")
        if not str(event.get("id") or "").isdigit():
            raise FinalReceiptError("FINAL_EVENT_ID_INVALID")
        matches.append((event, sides))
    if len(matches) != 1:
        raise FinalReceiptError("FINAL_MATCH_MISSING_OR_AMBIGUOUS")
    event, sides = matches[0]
    return {
        "schema": SCHEMA, "source": SOURCE, "source_status": "ESPN_FINAL",
        "url": source_url, "fetched_at": fetched.isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "event_id": str(event["id"]), "away": away, "home": home,
        "kickoff": start.isoformat(),
        "away_points": _points(sides["away"].get("score")),
        "home_points": _points(sides["home"].get("score")),
        "status": "PAPER", "pricing_input": False,
    }


def fetch_espn_final_with_bytes(*, away: str, home: str,
                                kickoff: str) -> tuple[dict, bytes]:
    """Fetch raw HTTP bytes once and retain them to verify the saved hash."""
    source_url = scoreboard_url(kickoff)
    req = Request(source_url, headers={"User-Agent": "SportsEdge-results/1.0"})
    with urlopen(req, timeout=30) as response:
        raw = response.read()
    fetched_at = datetime.now(timezone.utc).isoformat()
    receipt = bind_espn_final(raw=raw, source_url=source_url,
                              fetched_at=fetched_at, away=away, home=home,
                              kickoff=kickoff)
    return receipt, raw


def fetch_espn_final(*, away: str, home: str, kickoff: str) -> dict:
    return fetch_espn_final_with_bytes(away=away, home=home, kickoff=kickoff)[0]
