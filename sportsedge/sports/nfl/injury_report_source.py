from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .context_autopull import NFLContextError

INJURY_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
REQUIRED_COLUMNS = frozenset({
    "season", "season_type", "team", "week", "gsis_id", "position", "full_name",
    "report_primary_injury", "report_secondary_injury", "report_status",
    "practice_primary_injury", "practice_secondary_injury", "practice_status", "date_modified",
})

_REPORT_STATUS = {
    "out": "OUT", "doubtful": "DOUBTFUL", "questionable": "QUESTIONABLE",
    "probable": "PROBABLE", "active": "ACTIVE", "inactive": "INACTIVE", "": "MISSING",
}
_PRACTICE_STATUS = {
    "did not participate": "DNP", "dnp": "DNP",
    "limited participation": "LP", "limited": "LP", "lp": "LP",
    "full participation": "FP", "full": "FP", "fp": "FP", "": "MISSING",
}


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise NFLContextError(f"{field} missing")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NFLContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        # nflverse injury date_modified has historically been UTC without an offset.
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _int(value: Any, field: str) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"{field} invalid") from exc


def _norm_report(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw not in _REPORT_STATUS:
        raise NFLContextError(f"NFLVERSE injury report status unsupported:{raw}")
    return _REPORT_STATUS[raw]


def _norm_practice(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw not in _PRACTICE_STATUS:
        raise NFLContextError(f"NFLVERSE practice status unsupported:{raw}")
    return _PRACTICE_STATUS[raw]


def fetch_nflverse_injuries(*, season: int, opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str, str]:
    """Fetch nflverse's NFL-API-derived weekly injury/practice reports.

    This is a near-official fallback, not an official-host claim. The upstream
    nflverse builder obtains the data through `nflapi::nflapi_injuries`; the raw
    release bytes are hash-bound here and each row is still PIT-filtered later by
    `date_modified` before it can enter an AUTO game bundle.
    """
    uri = INJURY_URL.format(season=int(season))
    req = Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"})
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise NFLContextError("NFLVERSE injury fetch failed") from exc
    try:
        rows = [dict(row) for row in csv.DictReader(StringIO(raw.decode("utf-8-sig")))]
    except Exception as exc:
        raise NFLContextError("NFLVERSE injury CSV invalid") from exc
    if not rows:
        raise NFLContextError("NFLVERSE injury CSV empty")
    columns = set(rows[0])
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise NFLContextError("NFLVERSE injury schema unsupported:" + ",".join(sorted(missing)))
    return rows, uri, sha256(raw).hexdigest()


def build_pit_injury_inputs(
    *, rows: Iterable[Mapping[str, Any]], season: int, target_week: int,
    team_ids: Iterable[str], as_of: Any, source_uri: str, source_sha256: str,
) -> list[dict[str, Any]]:
    """Normalize current-week injury rows without using any post-PIT update."""
    pit = _utc(as_of, "as_of")
    allowed_teams = {str(team).strip().upper() for team in team_ids if str(team).strip()}
    if not allowed_teams:
        return []
    latest: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
    for raw in rows:
        try:
            row_season = _int(raw.get("season"), "season")
            row_week = _int(raw.get("week"), "week")
        except NFLContextError:
            continue
        if row_season != int(season) or row_week != int(target_week):
            continue
        team = str(raw.get("team") or "").strip().upper()
        player_id = str(raw.get("gsis_id") or "").strip()
        if team not in allowed_teams or not player_id:
            continue
        modified_raw = raw.get("date_modified")
        if modified_raw in (None, ""):
            continue
        modified = _utc(modified_raw, "date_modified")
        if modified > pit:
            continue
        status = _norm_report(raw.get("report_status"))
        practice = _norm_practice(raw.get("practice_status"))
        payload = {
            "player_id": player_id, "team_id": team,
            "full_name": str(raw.get("full_name") or "").strip() or None,
            "position": str(raw.get("position") or "").strip() or None,
            "status": status, "practice_status": practice,
            "report_primary_injury": str(raw.get("report_primary_injury") or "").strip() or None,
            "report_secondary_injury": str(raw.get("report_secondary_injury") or "").strip() or None,
            "practice_primary_injury": str(raw.get("practice_primary_injury") or "").strip() or None,
            "practice_secondary_injury": str(raw.get("practice_secondary_injury") or "").strip() or None,
            "report_ts": modified.isoformat(), "season": int(season), "week": int(target_week),
            "confirmation_level": "NFLVERSE_NFLAPI_DERIVED", "official_host_confirmed": False,
        }
        key = (team, player_id)
        prior = latest.get(key)
        if prior is None or modified > prior[0]:
            latest[key] = (modified, payload)
    out = []
    for _, payload in sorted(latest.values(), key=lambda item: (item[1]["team_id"], item[1]["player_id"])):
        out.append({
            "team_id": payload["team_id"], "player_id": payload["player_id"],
            "source_uri": str(source_uri), "source_sha256": str(source_sha256),
            "source_payload": payload,
        })
    return out
