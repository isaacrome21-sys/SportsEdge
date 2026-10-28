"""ESPN public JSON surfaces (free, keyless) for current-form context.

ESPN's site.api.espn.com v2 endpoints are publicly served JSON (the
same payloads espn.com's own pages render). No key, no account. They
are undocumented and can drift, so every parse is schema-checked and
fails closed.

Verified live 2026-10-27: NBA scoreboard JSON sha256
01b55e13c0e8799991fd4b4554a7fb18dfd27ec56c797089b9bd3ab3ac5bc403;
CBB scoreboard and CBB/NBA teams endpoints also returned 200 JSON.

WHAT IS WIRED HERE: scoreboard (results + upcoming fixtures with
timestamps) and standings (record / streak / last-ten where the league
payload carries it). From scoreboard results the fetcher derives each
team's last-N form (W/L and average margin) directly -- always computed
from completed events with an explicit as-of cutoff, never from a
precomputed field that could silently include a game in progress.

WHAT IS NOT WIRED: ESPN BPI / power index. Five candidate public JSON
endpoints were probed 2026-10-27 (fittwo v3 powerindex on site.api and
site.web.api for NBA and CBB, and site v2 /bpi) and all returned 404.
BPI is therefore DOCUMENTED-ONLY (public web pages) in the wiring
record -- no fetcher pretends an endpoint exists.

POINT-IN-TIME RULE: form is computed from events with start time <=
as_of (caller-supplied). An event whose status is not final is never
counted as a result.

RESEARCH-ONLY: labeled context only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .common import Opener, fetch_bytes, parse_json_body, receipt_of

SITE_API = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "cbb": "basketball/mens-college-basketball",
    "mlb": "baseball/mlb",
}


def _fetch_json(url: str, opener: Opener | None) -> dict[str, Any]:
    result = fetch_bytes(url, opener=opener)
    if result["status"] != "OK":
        return result
    try:
        payload = parse_json_body(result["body"])
    except Exception:
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    return {"status": "OK", "receipt": receipt_of(result), "payload": payload}


def fetch_scoreboard(league: str, *, dates: str | None = None, opener: Opener | None = None) -> dict[str, Any]:
    """Raw ESPN scoreboard payload for one league (optionally YYYYMMDD)."""
    if league not in LEAGUES:
        return {"status": "MISSING", "reason": "ESPN_UNKNOWN_LEAGUE"}
    url = f"{SITE_API}/{LEAGUES[league]}/scoreboard"
    if dates:
        url = f"{url}?dates={dates}"
    return _fetch_json(url, opener)


def _event_result(event: dict[str, Any]) -> tuple[str, str, int, int] | None:
    """(winner_abbr, loser_abbr, winner_score, loser_score) for finals."""
    try:
        competition = event["competitions"][0]
        if not event.get("status", {}).get("type", {}).get("completed"):
            return None
        competitors = competition["competitors"]
        if len(competitors) != 2:
            return None
        scored = []
        for competitor in competitors:
            scored.append(
                (
                    competitor["team"]["abbreviation"],
                    int(competitor["score"]),
                    bool(competitor.get("winner")),
                )
            )
        winner = next((row for row in scored if row[2]), None)
        loser = next((row for row in scored if not row[2]), None)
        if winner is None or loser is None:
            return None
        return winner[0], loser[0], winner[1], loser[1]
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def team_form_from_scoreboards(
    league: str,
    *,
    as_of: datetime,
    dates: list[str],
    last_n: int = 10,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """Last-N form per team from completed scoreboard events <= as_of.

    `dates` are the YYYYMMDD scoreboard pages to read (caller chooses a
    window covering at least last_n games per team). Returns per team:
    games counted, wins, losses, average margin (signed, team view),
    and the dates of the games used. Fails closed per-league only; a
    single bad date page is reported in `page_errors`, not hidden.
    """
    if league not in LEAGUES:
        return {"status": "MISSING", "reason": "ESPN_UNKNOWN_LEAGUE"}
    games: dict[str, list[dict[str, Any]]] = {}
    receipts: list[dict[str, Any]] = []
    page_errors: list[str] = []
    for date in dates:
        fetched = fetch_scoreboard(league, dates=date, opener=opener)
        if fetched["status"] != "OK":
            page_errors.append(date)
            continue
        receipts.append(fetched["receipt"])
        for event in fetched["payload"].get("events", []):
            start = event.get("date")
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
            except ValueError:
                start_dt = None
            if start_dt is None or start_dt > as_of:
                continue
            outcome = _event_result(event)
            if outcome is None:
                continue
            winner, loser, winner_score, loser_score = outcome
            margin = winner_score - loser_score
            games.setdefault(winner, []).append({"date": date, "margin": margin, "won": True})
            games.setdefault(loser, []).append({"date": date, "margin": -margin, "won": False})
    form: dict[str, dict[str, Any]] = {}
    for team, rows in sorted(games.items()):
        rows.sort(key=lambda row: row["date"])
        recent = rows[-last_n:]
        form[team] = {
            "games": len(recent),
            "wins": sum(1 for row in recent if row["won"]),
            "losses": sum(1 for row in recent if not row["won"]),
            "avg_margin": round(sum(row["margin"] for row in recent) / len(recent), 2) if recent else None,
            "dates": [row["date"] for row in recent],
        }
    return {
        "status": "OK",
        "source": "ESPN public JSON (site.api.espn.com v2 scoreboard)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "league": league,
        "as_of_utc": as_of.isoformat(),
        "page_errors": page_errors,
        "receipts": receipts,
        "teams": form,
    }


def fetch_standings(league: str, *, opener: Opener | None = None) -> dict[str, Any]:
    """Standings payload: records/streaks exactly as ESPN publishes them.

    The payload's per-entry stats are passed through keyed by their
    published stat names; nothing is recomputed or relabeled. Callers
    must treat any 'last ten' style field as ESPN's own as-of (payload
    retrieval time), stamped by the receipt.
    """
    if league not in LEAGUES:
        return {"status": "MISSING", "reason": "ESPN_UNKNOWN_LEAGUE"}
    fetched = _fetch_json(f"{SITE_API}/{LEAGUES[league]}/standings", opener)
    if fetched["status"] != "OK":
        return fetched
    teams: dict[str, dict[str, Any]] = {}
    try:
        for child in fetched["payload"].get("children", []):
            for entry in child.get("standings", {}).get("entries", []):
                abbr = entry["team"]["abbreviation"]
                teams[abbr] = {
                    stat["name"]: stat.get("displayValue")
                    for stat in entry.get("stats", [])
                    if "name" in stat
                }
    except (KeyError, TypeError):
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": fetched["receipt"]}
    return {
        "status": "OK",
        "source": "ESPN public JSON (site.api.espn.com v2 standings)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "league": league,
        "receipt": fetched["receipt"],
        "teams": teams,
    }
