#!/usr/bin/env python3
"""NHL official public API research collector (api-web.nhle.com).

REGISTERED RESEARCH SOURCE — archive/intake only, zero pricing impact.
The NHL's public API is free and needs no key. This collector stores
standings, scores, schedules, and club stats as research envelopes.
Output is never a pricing input: every envelope carries
``pricing_input: false`` and ``play_eligible: false``, no pricing path
imports this module, and no model probability is ever produced here.

Live calls happen only with an explicit ``--live`` flag naming one
endpoint; the default run makes zero network requests. The upstream
``/v1/standings/now`` path 307-redirects to a dated URL, which urllib
follows. Historical depth verified 2026-10-24: standings by date back
to at least 2000-04-08, club stats back to season 20102011.

Cross-checks recorded at admission (2026-10-24): NHL final scores vs
ESPN scoreboard agreed on 14/14 completed games across 2026-10-22 and
2026-10-23 (ESPN abbreviates SJ/NJ/LA where the NHL uses SJS/NJD/LAK;
scores matched exactly). MoneyPuck's shot-derived goals-against for
EDM 2024-25 is 235 vs the API's official 236 — the difference is the
shootout-deciding goal, which official standings count and shot data
does not (EDM shootout record 0W-1L that season).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://api-web.nhle.com/v1"
SOURCE = "nhl_api"
USER_AGENT = "sportsedge-research-collector (nhl_api; archive only)"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEASON_RE = re.compile(r"^(\d{4})(\d{4})$")
TEAM_RE = re.compile(r"^[A-Z]{2,4}$")
GAME_TYPES = (1, 2, 3)  # 1 preseason, 2 regular season, 3 playoffs


class IntakeRefusal(ValueError):
    """Expected fail-closed source, argument, or payload refusal."""


def _localized(value):
    """NHL name fields arrive as {'default': str, ...} or plain str."""
    if isinstance(value, dict):
        return value.get("default")
    return value


def validate_date(value, field="date"):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise IntakeRefusal(f"{field} must be YYYY-MM-DD, got {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise IntakeRefusal(f"{field} is not a real calendar date: {value!r}")
    return value


def validate_season(value):
    match = SEASON_RE.match(value) if isinstance(value, str) else None
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise IntakeRefusal(
            f"season must be an 8-digit YYYYZZZZ pair (ZZZZ = YYYY + 1), got {value!r}")
    if not 1917 <= int(match.group(1)) <= 2100:
        raise IntakeRefusal(f"season start year out of range: {value!r}")
    return value


def validate_team(value):
    if not isinstance(value, str) or not TEAM_RE.match(value):
        raise IntakeRefusal(f"team must be a 2-4 letter uppercase abbrev, got {value!r}")
    return value


def validate_game_type(value):
    if value not in GAME_TYPES:
        raise IntakeRefusal(f"game_type must be one of {GAME_TYPES}, got {value!r}")
    return value


def build_url(kind, *, date=None, team=None, season=None, game_type=2):
    """Return the upstream URL for one registered endpoint kind."""
    if kind == "standings":
        if date in (None, "now"):
            return f"{API}/standings/now"
        return f"{API}/standings/{validate_date(date)}"
    if kind in ("score", "schedule"):
        return f"{API}/{kind}/{validate_date(date)}"
    if kind == "club-stats":
        return (f"{API}/club-stats/{validate_team(team)}/"
                f"{validate_season(season)}/{validate_game_type(game_type)}")
    raise IntakeRefusal(f"unknown endpoint kind: {kind!r}")


def fetch_json(url, opener=None, timeout=30):
    """GET one JSON document, failing closed on any transport or shape error."""
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept": "application/json"})
    open_fn = opener or urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        raise IntakeRefusal(f"GET {url} -> HTTP {exc.code}") from exc
    except URLError as exc:
        raise IntakeRefusal(f"GET {url} -> {exc.reason}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise IntakeRefusal(f"GET {url} -> non-JSON body") from exc
    if not isinstance(payload, dict):
        raise IntakeRefusal(f"GET {url} -> JSON body is not an object")
    return payload


def normalize_scores(payload):
    """Final/live score rows from a /v1/score/{date} payload."""
    rows = []
    for game in payload.get("games") or []:
        away, home = game.get("awayTeam") or {}, game.get("homeTeam") or {}
        if not away.get("abbrev") or not home.get("abbrev"):
            continue
        rows.append({
            "game_id": game.get("id"),
            "game_date": game.get("gameDate"),
            "season": game.get("season"),
            "game_state": game.get("gameState"),
            "away_abbrev": away["abbrev"],
            "away_score": away.get("score"),
            "home_abbrev": home["abbrev"],
            "home_score": home.get("score"),
        })
    return rows


def normalize_standings(payload):
    """One row per team from a /v1/standings payload."""
    rows = []
    for row in payload.get("standings") or []:
        abbrev = _localized(row.get("teamAbbrev"))
        if not abbrev:
            continue
        rows.append({
            "team_abbrev": abbrev,
            "team_name": _localized(row.get("teamName")),
            "season_id": row.get("seasonId"),
            "games_played": row.get("gamesPlayed"),
            "wins": row.get("wins"),
            "losses": row.get("losses"),
            "ot_losses": row.get("otLosses"),
            "points": row.get("points"),
            "goals_for": row.get("goalFor"),
            "goals_against": row.get("goalAgainst"),
        })
    return rows


def _player_name(row):
    first = _localized(row.get("firstName")) or ""
    last = _localized(row.get("lastName")) or ""
    return f"{first} {last}".strip() or None


def normalize_club_stats(payload):
    """Skater/goalie season rows from a /v1/club-stats payload."""
    skaters = [{
        "player_id": row.get("playerId"),
        "name": _player_name(row),
        "position": row.get("positionCode"),
        "games_played": row.get("gamesPlayed"),
        "goals": row.get("goals"),
        "assists": row.get("assists"),
        "points": row.get("points"),
        "shots": row.get("shots"),
    } for row in payload.get("skaters") or []]
    goalies = [{
        "player_id": row.get("playerId"),
        "name": _player_name(row),
        "games_played": row.get("gamesPlayed"),
        "games_started": row.get("gamesStarted"),
        "wins": row.get("wins"),
        "losses": row.get("losses"),
        "save_percentage": row.get("savePercentage"),
        "goals_against_average": row.get("goalsAgainstAverage"),
        "shutouts": row.get("shutouts"),
    } for row in payload.get("goalies") or []]
    return {"season": payload.get("season"),
            "game_type": payload.get("gameType"),
            "skaters": skaters,
            "goalies": goalies}


NORMALIZERS = {"standings": normalize_standings,
               "score": normalize_scores,
               "club-stats": normalize_club_stats}


def envelope(kind, url, payload, fetched_at):
    """Wrap one upstream payload with research-only provenance labels."""
    body = {"source": SOURCE,
            "kind": kind,
            "url": url,
            "fetched_at_utc": fetched_at.astimezone(timezone.utc).isoformat(),
            "research_only": True,
            "pricing_input": False,
            "play_eligible": False,
            "model_p": None,
            "payload": payload}
    normalizer = NORMALIZERS.get(kind)
    if normalizer is not None:
        body["rows"] = normalizer(payload)
    return body


def collect(kind, *, date=None, team=None, season=None, game_type=2,
            live=False, out_dir=None, opener=None, now=None):
    """Plan or perform one collection. Default performs zero requests."""
    url = build_url(kind, date=date, team=team, season=season,
                    game_type=game_type)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not live:
        return {"status": "NO_LIVE_CALL", "source": SOURCE, "kind": kind,
                "url": url, "requests": 0}
    payload = fetch_json(url, opener=opener)
    body = envelope(kind, url, payload, stamp)
    rows = body.get("rows")
    row_count = (len(rows.get("skaters", [])) + len(rows.get("goalies", []))
                 if isinstance(rows, dict) else len(rows or []))
    result = {"status": "RESEARCH_CAPTURED", "source": SOURCE, "kind": kind,
              "url": url, "requests": 1, "rows": row_count}
    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        name = f"nhl_{kind}_{stamp.strftime('%Y%m%dT%H%M%SZ')}.json"
        (out_path / name).write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["file"] = name
    return result


def _add_common(parser):
    parser.add_argument("--live", action="store_true",
                        help="perform the request (default: zero requests)")
    parser.add_argument("--out-dir", default=None,
                        help="directory for the research envelope JSON")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    p_standings = sub.add_parser("standings")
    p_standings.add_argument("--date", default="now",
                             help="YYYY-MM-DD or 'now' (default)")
    _add_common(p_standings)
    for kind in ("score", "schedule"):
        p = sub.add_parser(kind)
        p.add_argument("--date", required=True, help="YYYY-MM-DD")
        _add_common(p)
    p_club = sub.add_parser("club-stats")
    p_club.add_argument("--team", required=True, help="team abbrev, e.g. EDM")
    p_club.add_argument("--season", required=True, help="e.g. 20242025")
    p_club.add_argument("--game-type", type=int, default=2,
                        help="1 preseason, 2 regular season, 3 playoffs")
    _add_common(p_club)
    args = parser.parse_args(argv)
    try:
        result = collect(args.kind,
                         date=getattr(args, "date", None),
                         team=getattr(args, "team", None),
                         season=getattr(args, "season", None),
                         game_type=getattr(args, "game_type", 2),
                         live=args.live, out_dir=args.out_dir)
    except IntakeRefusal as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
