#!/usr/bin/env python3
"""NBA props V2 - Candidate A (official NBA CDN box scores) admission battery.

Executes the admission protocol proposed in
research/nba_props_forward_20261020/NBA_PROPS_V2_INSEASON_SOURCE_ADMISSION_DESIGN.md
(PR #2474, merged on main) against the live NBA-operated CDN, from whatever
egress runs this script (designed for a GitHub Actions runner; the same
battery run from the SportsEdge VM on 2026-10-22 failed section 2 with
Akamai HTTP 403 - see the probe record referenced in the verdict output).

Battery sections (design numbering):
  1. Pin endpoints; archive unaltered response bytes with SHA-256, source
     URL, fetched-at timestamp and NBA game ID into an evidence manifest
     (staging only; in CI the evidence directory is uploaded as a workflow
     artifact and is never committed).
  2. Availability: >=8 FINAL 2026-27 regular-season games on >=3 distinct
     NBA game dates and >=80 eligible player-game observations.
  3. Integrity per game: season attribution, game start (UTC, timezone
     present), unique official game ID, team IDs, official player IDs,
     final status, integer non-negative PTS/REB/AST, parseable minutes;
     duplicate player-game rows rejected; DNP / minutes-zero excluded with
     explicit counts.
  4. Identity cross-check vs independently fetched ESPN finals: >=50
     separately identity-joined eligible observations across >=5 completed
     games, ZERO unresolved disagreements on PTS/REB/AST for the same game
     date / team / player. The join is NOT by name alone: the game is
     matched on date + both team tricodes, the team on tricode, and the
     player on team + jersey number with normalized-name agreement
     required. A missing independent record is MISSING_COMPARISON
     (the design's CROSSCHECK_UNAVAILABLE case), never agreement.
  5. Per-cell refusal counts for the design taxonomy, with denominators
     and the achieved date spread.

This is an admission probe only. It freezes nothing, starts no clock,
prices nothing, and never touches the frozen V1 construction. A refusal
(403, missing game, non-final document, schema drift) is recorded as a
refusal - never worked around, never silently switched to another feed.
ESPN is the independent check only, never a fallback source.

Exit codes: 0 = battery executed and a verdict was written (the verdict
JSON carries the per-section pass/fail; a green workflow run means the
battery RAN, not that the source was admitted). 2 = battery-internal
failure (no verdict could be produced).

Standard library only. Usage:
  python3 nba_cdn_admission_battery.py --out EVIDENCE_DIR [--max-games N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "SportsEdge-research/1.0"
PARSER_ID = "nba_cdn_admission_battery.py/1.0"

CDN_BASE = "https://cdn.nba.com/static/json"
SCHEDULE_URL = CDN_BASE + "/staticData/scheduleLeagueV2_1.json"
SCOREBOARD_URL = CDN_BASE + "/liveData/scoreboard/todaysScoreboard_00.json"
BOXSCORE_URL = CDN_BASE + "/liveData/boxscore/boxscore_{game_id}.json"

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

SEASON_GAME_ID_PREFIX = "00226"  # 2026-27 NBA regular season game IDs
SEASON_START_DATE = "2026-10-20"  # first date of the 2026-27 regular season

BAR_GAMES = 8
BAR_DATES = 3
BAR_OBSERVATIONS = 80
BAR_JOINED = 50
BAR_JOIN_GAMES = 5

# Canonical 30 NBA team IDs (stats/NBA team-id space).
NBA_TEAM_IDS = {
    1610612737, 1610612738, 1610612739, 1610612740, 1610612741, 1610612742,
    1610612743, 1610612744, 1610612745, 1610612746, 1610612747, 1610612748,
    1610612749, 1610612750, 1610612751, 1610612752, 1610612753, 1610612754,
    1610612755, 1610612756, 1610612757, 1610612758, 1610612759, 1610612760,
    1610612761, 1610612762, 1610612763, 1610612764, 1610612765, 1610612766,
}

# NBA tricode -> ESPN abbreviation where they differ (identity otherwise).
NBA_TO_ESPN_ABBR = {
    "GSW": "GS",
    "NOP": "NO",
    "NYK": "NY",
    "SAS": "SA",
    "UTA": "UTAH",
    "WAS": "WSH",
}

REFUSAL_CODES = (
    "SOURCE_UNAVAILABLE", "NOT_FINAL", "SCHEMA_INVALID", "GAME_ID_AMBIGUOUS",
    "PLAYER_ID_UNVERIFIED", "POSITION_UNKNOWN", "GAME_DATE_UNKNOWN",
    "DUPLICATE", "STAT_CONFLICT", "MISSING_COMPARISON", "DNP_EXCLUDED",
    "SOURCE_CHANGED_AFTER_SNAPSHOT",
)

SECTION3_INTEGRITY_CODES = (
    "SCHEMA_INVALID", "GAME_ID_AMBIGUOUS", "PLAYER_ID_UNVERIFIED",
    "POSITION_UNKNOWN", "GAME_DATE_UNKNOWN", "DUPLICATE", "NOT_FINAL",
)


def norm_name(value) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_minutes(value):
    """Return minutes as float seconds-parseable value, or None if unparseable.

    CDN box scores carry ISO-8601 durations ("PT36M05.00S"); older shapes
    use "MM:SS". Empty string is a real zero-minute case -> 0.0.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return 0.0
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", text)
    if m:
        if not any(group is not None for group in m.groups()):
            return None
        hours = int(m.group(1) or 0)
        mins = int(m.group(2) or 0)
        try:
            secs = float(m.group(3) or 0)
        except ValueError:
            return None
        if not isfinite(secs) or not 0 <= secs < 60:
            return None
        parsed = hours * 60.0 + mins + secs / 60.0
        return parsed if isfinite(parsed) and parsed >= 0 else None
    m = re.fullmatch(r"(\d+):(\d{2})", text)
    if m:
        seconds = int(m.group(2))
        if seconds >= 60:
            return None
        return int(m.group(1)) + seconds / 60.0
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if isfinite(parsed) and parsed >= 0 else None


def parse_played_flag(value):
    """Return a strict CDN played boolean; malformed states are not DNPs."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip() in {"0", "1"}:
        return value.strip() == "1"
    return None


def is_timezone_aware_utc(value) -> bool:
    """Require an ISO timestamp with an explicit zero UTC offset."""
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def section3_integrity_pass(games_verified: int, refusals: dict[str, int]) -> bool:
    """All declared Section 3 integrity refusals are admission-blocking."""
    return games_verified > 0 and all(
        int(refusals.get(code, 0)) == 0 for code in SECTION3_INTEGRITY_CODES
    )


def is_int_stat(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class Fetcher:
    """Single-attempt fetcher. A refusal is data, never retried or routed around."""

    def __init__(self, evidence_dir: Path):
        self.evidence_dir = evidence_dir
        self.manifest: list[dict] = []

    def fetch(self, url: str, tag: str, game_id: str | None = None):
        fetched_at = datetime.now(timezone.utc).isoformat()
        entry = {
            "tag": tag,
            "url": url,
            "game_id": game_id,
            "fetched_at_utc": fetched_at,
            "http_status": None,
            "byte_length": 0,
            "sha256": None,
            "archived_file": None,
            "error": None,
        }
        raw = None
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=30) as resp:
                entry["http_status"] = resp.status
                raw = resp.read()
        except HTTPError as exc:
            entry["http_status"] = exc.code
            try:
                raw = exc.read()
            except Exception:
                raw = None
            entry["error"] = f"HTTPError {exc.code}"
        except (URLError, OSError, TimeoutError) as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        if raw is not None:
            entry["byte_length"] = len(raw)
            entry["sha256"] = sha256_hex(raw)
            name = f"{tag}.json" if raw[:1] in (b"{", b"[") else f"{tag}.bin"
            path = self.evidence_dir / name
            path.write_bytes(raw)
            entry["archived_file"] = name
        self.manifest.append(entry)
        payload = None
        if entry["http_status"] == 200 and raw is not None:
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                payload = None
        return entry, payload


def select_final_games(schedule_payload, max_games: int):
    """Pick final 2026-27 regular-season games across >=3 dates from the schedule.

    Returns (selected, diagnostics). Selection: earliest dates first from
    SEASON_START_DATE, all finals on the earliest dates until max_games is
    reached; the schedule's own gameDate is the NBA game date.
    """
    diag = {"schedule_shape_ok": False, "finals_by_date": {}, "ot_hint_games": []}
    if not isinstance(schedule_payload, dict):
        return [], diag
    league = schedule_payload.get("leagueSchedule")
    if not isinstance(league, dict) or not isinstance(league.get("gameDates"), list):
        return [], diag
    diag["schedule_shape_ok"] = True
    diag["season_year"] = league.get("seasonYear")
    by_date: dict[str, list[dict]] = {}
    for day in league["gameDates"]:
        if not isinstance(day, dict):
            continue
        raw_date = str(day.get("gameDate") or "")
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", raw_date)
        if not m:
            continue
        iso_date = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
        if iso_date < SEASON_START_DATE:
            continue
        for game in day.get("games") or []:
            if not isinstance(game, dict):
                continue
            gid = str(game.get("gameId") or "")
            if not gid.startswith(SEASON_GAME_ID_PREFIX):
                continue
            if game.get("gameStatus") != 3:
                continue
            by_date.setdefault(iso_date, []).append({
                "game_id": gid,
                "game_date": iso_date,
                "game_datetime_utc": game.get("gameDateTimeUTC"),
                "home_tricode": (game.get("homeTeam") or {}).get("teamTricode"),
                "away_tricode": (game.get("awayTeam") or {}).get("teamTricode"),
                "home_team_id": (game.get("homeTeam") or {}).get("teamId"),
                "away_team_id": (game.get("awayTeam") or {}).get("teamId"),
            })
    diag["finals_by_date"] = {d: len(v) for d, v in sorted(by_date.items())}
    selected: list[dict] = []
    for date in sorted(by_date):
        for game in sorted(by_date[date], key=lambda g: g["game_id"]):
            if len(selected) >= max_games:
                break
            selected.append(game)
        if len(selected) >= max_games:
            break
    return selected, diag


def parse_boxscore(payload, expected_game_id: str):
    """Parse + integrity-check one CDN box score.

    Returns (game_record, issues) where game_record is None when the payload
    is unusable as a final box score; issues is a list of (code, detail).
    Player observations land in game_record["observations"] (eligible) and
    game_record["dnp_count"] counts excluded DNP / zero-minute rows.
    """
    issues: list[tuple[str, str]] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("game"), dict):
        return None, [("SCHEMA_INVALID", "payload has no 'game' object")]
    game = payload["game"]
    gid = str(game.get("gameId") or "")
    if gid != expected_game_id:
        issues.append(("GAME_ID_AMBIGUOUS",
                       f"boxscore gameId {gid!r} != requested {expected_game_id!r}"))
        return None, issues
    if not gid.startswith(SEASON_GAME_ID_PREFIX):
        issues.append(("SCHEMA_INVALID", f"gameId {gid} fails 2026-27 season attribution"))
    if game.get("gameStatus") != 3:
        issues.append(("NOT_FINAL", f"gameStatus={game.get('gameStatus')!r}"))
        return None, issues
    start_utc = game.get("gameTimeUTC")
    if not is_timezone_aware_utc(start_utc):
        issues.append(("GAME_DATE_UNKNOWN", "gameTimeUTC missing, invalid, timezone-less, or not UTC"))
    record = {
        "game_id": gid,
        "game_time_utc": start_utc,
        "periods": game.get("period"),
        "is_overtime": isinstance(game.get("period"), int) and game["period"] > 4,
        "teams": {},
        "observations": [],
        "dnp_count": 0,
        "player_rows_total": 0,
    }
    seen_players: set[tuple[str, int]] = set()
    for side in ("homeTeam", "awayTeam"):
        team = game.get(side)
        if not isinstance(team, dict):
            issues.append(("SCHEMA_INVALID", f"{side} missing"))
            return None, issues
        team_id = team.get("teamId")
        tricode = team.get("teamTricode")
        if team_id not in NBA_TEAM_IDS:
            issues.append(("SCHEMA_INVALID", f"{side} teamId {team_id!r} not a canonical NBA team id"))
        record["teams"][side] = {"team_id": team_id, "tricode": tricode}
        for player in team.get("players") or []:
            if not isinstance(player, dict):
                issues.append(("SCHEMA_INVALID", "player row not an object"))
                continue
            record["player_rows_total"] += 1
            person_id = player.get("personId")
            if not isinstance(person_id, int) or isinstance(person_id, bool) or person_id <= 0:
                issues.append(("PLAYER_ID_UNVERIFIED",
                               f"{tricode} player {player.get('name')!r} personId {person_id!r}"))
                continue
            key = (gid, person_id)
            if key in seen_players:
                issues.append(("DUPLICATE", f"duplicate player-game row {key}"))
                continue
            seen_players.add(key)
            stats = player.get("statistics") or {}
            if not isinstance(stats, dict):
                issues.append(("SCHEMA_INVALID",
                               f"{tricode} personId {person_id} statistics not an object"))
                continue
            minutes = parse_minutes(stats.get("minutes"))
            played = parse_played_flag(player.get("played"))
            if played is None:
                issues.append(("SCHEMA_INVALID",
                               f"{tricode} personId {person_id} played flag invalid: "
                               f"{player.get('played')!r}"))
                continue
            if minutes is None:
                issues.append(("SCHEMA_INVALID",
                               f"{tricode} personId {person_id} minutes invalid: "
                               f"{stats.get('minutes')!r}"))
                continue
            if not played and minutes > 0:
                issues.append(("SCHEMA_INVALID",
                               f"{tricode} personId {person_id} played=0 with positive minutes"))
                continue
            if not played or minutes == 0:
                record["dnp_count"] += 1
                continue
            if not player.get("position"):
                issues.append(("POSITION_UNKNOWN",
                               f"{tricode} personId {person_id} has no position"))
            pts, reb, ast = stats.get("points"), stats.get("reboundsTotal"), stats.get("assists")
            if not (is_int_stat(pts) and is_int_stat(reb) and is_int_stat(ast)):
                issues.append(("SCHEMA_INVALID",
                               f"{tricode} personId {person_id} non-integer/negative PTS/REB/AST: "
                               f"{pts!r}/{reb!r}/{ast!r}"))
                continue
            record["observations"].append({
                "game_id": gid,
                "team_tricode": tricode,
                "team_id": team_id,
                "person_id": person_id,
                "name": player.get("name"),
                "jersey": str(player.get("jerseyNum") or "").strip(),
                "position": player.get("position"),
                "minutes": minutes,
                "pts": pts,
                "reb": reb,
                "ast": ast,
            })
    return record, issues


def espn_events_for_date(fetcher: Fetcher, iso_date: str, cache: dict):
    if iso_date in cache:
        return cache[iso_date]
    ymd = iso_date.replace("-", "")
    url = ESPN_SCOREBOARD + "?" + urlencode({"dates": ymd, "limit": 50})
    entry, payload = fetcher.fetch(url, f"espn_scoreboard_{ymd}")
    events = []
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        events = payload["events"]
    cache[iso_date] = (entry, events)
    return entry, events


def espn_game_boxscore(fetcher: Fetcher, event_id: str):
    """Parse an ESPN summary payload into {(team_abbr, jersey): row} for played athletes."""
    url = ESPN_SUMMARY + "?" + urlencode({"event": event_id})
    entry, payload = fetcher.fetch(url, f"espn_summary_{event_id}")
    players: dict[tuple[str, str], dict] = {}
    if not isinstance(payload, dict):
        return entry, players
    box = payload.get("boxscore") or {}
    for team_block in box.get("players") or []:
        if not isinstance(team_block, dict):
            continue
        abbr = ((team_block.get("team") or {}).get("abbreviation") or "").upper()
        for stat_block in team_block.get("statistics") or []:
            names = stat_block.get("names") or []
            if not all(k in names for k in ("PTS", "REB", "AST")):
                continue
            idx = {k: names.index(k) for k in ("PTS", "REB", "AST")}
            for row in stat_block.get("athletes") or []:
                if not isinstance(row, dict) or row.get("didNotPlay"):
                    continue
                athlete = row.get("athlete") or {}
                stats = row.get("stats") or []
                try:
                    parsed = {k: int(str(stats[idx[k]]).strip()) for k in idx}
                except (ValueError, IndexError, AttributeError):
                    continue
                players[(abbr, str(athlete.get("jersey") or "").strip())] = {
                    "espn_athlete_id": str(athlete.get("id") or ""),
                    "name": athlete.get("displayName"),
                    **parsed,
                }
    return entry, players


def match_espn_event(events, game: dict):
    """Match a CDN game to an ESPN event on both team abbreviations (unique)."""
    want_home = NBA_TO_ESPN_ABBR.get(game["home_tricode"], game["home_tricode"])
    want_away = NBA_TO_ESPN_ABBR.get(game["away_tricode"], game["away_tricode"])
    matches = []
    for event in events:
        if not isinstance(event, dict):
            continue
        status = ((event.get("status") or {}).get("type") or {})
        if status.get("completed") is not True:
            continue
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        abbrs = {}
        for comp in competitions[0].get("competitors") or []:
            team = comp.get("team") or {}
            abbrs[comp.get("homeAway")] = (team.get("abbreviation") or "").upper()
        if abbrs.get("home") == want_home and abbrs.get("away") == want_away:
            matches.append(event)
    if len(matches) != 1:
        return None
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="evidence output directory")
    parser.add_argument("--max-games", type=int, default=16)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(out_dir)
    run_started = datetime.now(timezone.utc).isoformat()

    refusals: dict[str, int] = {code: 0 for code in REFUSAL_CODES}
    verdict: dict = {
        "battery": "NBA_PROPS_V2_CANDIDATE_A_ADMISSION",
        "design_doc": "research/nba_props_forward_20261020/NBA_PROPS_V2_INSEASON_SOURCE_ADMISSION_DESIGN.md",
        "parser": PARSER_ID,
        "run_started_at_utc": run_started,
        "egress": "github-actions-runner" if __import__("os").environ.get("GITHUB_ACTIONS") else "local",
        "endpoints": {
            "schedule": SCHEDULE_URL,
            "scoreboard": SCOREBOARD_URL,
            "boxscore_pattern": BOXSCORE_URL,
            "espn_scoreboard": ESPN_SCOREBOARD,
            "espn_summary": ESPN_SUMMARY,
        },
    }

    # --- Canonical-path availability (the two paths probed from the VM) ---
    sched_entry, sched_payload = fetcher.fetch(SCHEDULE_URL, "cdn_scheduleLeagueV2_1")
    sb_entry, _ = fetcher.fetch(SCOREBOARD_URL, "cdn_todaysScoreboard_00")
    verdict["canonical_paths"] = {
        "scheduleLeagueV2_1": {"http_status": sched_entry["http_status"], "error": sched_entry["error"]},
        "todaysScoreboard_00": {"http_status": sb_entry["http_status"], "error": sb_entry["error"]},
    }
    if sched_entry["http_status"] != 200:
        refusals["SOURCE_UNAVAILABLE"] += 1

    # --- Section 2: selection ------------------------------------------------
    selected, sel_diag = select_final_games(sched_payload, args.max_games)
    verdict["selection_diagnostics"] = sel_diag
    games: dict[str, dict] = {}
    all_issues: list[dict] = []
    for game in selected:
        entry, payload = fetcher.fetch(
            BOXSCORE_URL.format(game_id=game["game_id"]),
            f"cdn_boxscore_{game['game_id']}", game_id=game["game_id"])
        if entry["http_status"] != 200 or payload is None:
            refusals["SOURCE_UNAVAILABLE"] += 1
            all_issues.append({"game_id": game["game_id"], "code": "SOURCE_UNAVAILABLE",
                               "detail": f"http_status={entry['http_status']} error={entry['error']}"})
            continue
        record, issues = parse_boxscore(payload, game["game_id"])
        for code, detail in issues:
            refusals[code] = refusals.get(code, 0) + 1
            all_issues.append({"game_id": game["game_id"], "code": code, "detail": detail})
        if record is not None:
            record["game_date"] = game["game_date"]
            games[game["game_id"]] = record

    dates = sorted({g["game_date"] for g in games.values()})
    observations = [o for g in games.values() for o in g["observations"]]
    dnp_total = sum(g["dnp_count"] for g in games.values())
    player_rows_total = sum(g["player_rows_total"] for g in games.values())
    refusals["DNP_EXCLUDED"] += dnp_total
    ot_games = [gid for gid, g in games.items() if g["is_overtime"]]
    verdict["section2_availability"] = {
        "bar": {"games": BAR_GAMES, "distinct_dates": BAR_DATES, "observations": BAR_OBSERVATIONS},
        "achieved": {"games": len(games), "distinct_dates": len(dates),
                     "dates": dates, "observations": len(observations)},
        "pass": len(games) >= BAR_GAMES and len(dates) >= BAR_DATES and len(observations) >= BAR_OBSERVATIONS,
        "overtime_games_in_sample": ot_games,
        "ot_not_in_sample": len(ot_games) == 0,
    }

    # --- Section 3: integrity summary ---------------------------------------
    verdict["section3_integrity"] = {
        "games_verified": len(games),
        "player_rows_total": player_rows_total,
        "eligible_observations": len(observations),
        "dnp_excluded": dnp_total,
        "violation_counts": {c: refusals.get(c, 0) for c in SECTION3_INTEGRITY_CODES},
        "pass": section3_integrity_pass(len(games), refusals),
    }

    # --- Section 4: ESPN identity cross-check --------------------------------
    espn_cache: dict = {}
    joined = 0
    joined_games: set[str] = set()
    disagreements: list[dict] = []
    compared_cells = 0
    for gid, game in sorted(games.items()):
        _, events = espn_events_for_date(fetcher, game["game_date"], espn_cache)
        event = match_espn_event(events, {
            "home_tricode": game["teams"]["homeTeam"]["tricode"],
            "away_tricode": game["teams"]["awayTeam"]["tricode"],
        })
        if event is None:
            refusals["MISSING_COMPARISON"] += len(game["observations"])
            all_issues.append({"game_id": gid, "code": "MISSING_COMPARISON",
                               "detail": "no unique completed ESPN event matched on date + both teams"})
            continue
        _, espn_players = espn_game_boxscore(fetcher, str(event.get("id")))
        if not espn_players:
            refusals["MISSING_COMPARISON"] += len(game["observations"])
            all_issues.append({"game_id": gid, "code": "MISSING_COMPARISON",
                               "detail": f"ESPN summary {event.get('id')} yielded no player rows"})
            continue
        for obs in game["observations"]:
            abbr = NBA_TO_ESPN_ABBR.get(obs["team_tricode"], obs["team_tricode"])
            hit = espn_players.get((abbr, obs["jersey"]))
            if hit is None or norm_name(hit["name"]) != norm_name(obs["name"]):
                refusals["MISSING_COMPARISON"] += 1
                all_issues.append({"game_id": gid, "code": "MISSING_COMPARISON",
                                   "detail": f"no identity join (team+jersey+name) for personId "
                                             f"{obs['person_id']} ({obs['name']}, {obs['team_tricode']} "
                                             f"#{obs['jersey']})"})
                continue
            joined += 1
            joined_games.add(gid)
            compared_cells += 1
            diffs = {k: (obs[k.lower()], hit[k]) for k in ("PTS", "REB", "AST")
                     if obs[k.lower()] != hit[k]}
            if diffs:
                refusals["STAT_CONFLICT"] += 1
                disagreements.append({
                    "game_id": gid, "game_date": game["game_date"],
                    "person_id": obs["person_id"], "name": obs["name"],
                    "team_tricode": obs["team_tricode"],
                    "espn_athlete_id": hit["espn_athlete_id"],
                    "diffs": {k: {"cdn": v[0], "espn": v[1]} for k, v in diffs.items()},
                })
    verdict["section4_crosscheck"] = {
        "bar": {"joined_observations": BAR_JOINED, "games": BAR_JOIN_GAMES,
                "unresolved_disagreements": 0},
        "achieved": {"joined_observations": joined, "games": len(joined_games),
                     "unresolved_disagreements": len(disagreements)},
        "disagreements": disagreements,
        "pass": joined >= BAR_JOINED and len(joined_games) >= BAR_JOIN_GAMES and not disagreements,
    }

    # --- Section 5: refusal table --------------------------------------------
    verdict["section5_refusals"] = {
        "counts": refusals,
        "denominators": {
            "SOURCE_UNAVAILABLE": "per retrieval attempted (see manifest)",
            "NOT_FINAL": f"per game payload parsed ({len(games)} verified final)",
            "SCHEMA_INVALID": f"per payload / row checked ({player_rows_total} player rows)",
            "GAME_ID_AMBIGUOUS": f"per box score fetched ({len(selected)} selected)",
            "PLAYER_ID_UNVERIFIED": f"per player row ({player_rows_total})",
            "POSITION_UNKNOWN": f"per verified player row ({player_rows_total - dnp_total})",
            "GAME_DATE_UNKNOWN": f"per game payload ({len(games)})",
            "DUPLICATE": f"per player-game row ({player_rows_total})",
            "STAT_CONFLICT": f"per identity-joined observation compared ({compared_cells})",
            "MISSING_COMPARISON": f"per eligible observation ({len(observations)})",
            "DNP_EXCLUDED": f"per player row ({player_rows_total})",
            "SOURCE_CHANGED_AFTER_SNAPSHOT": "single snapshot per payload; not testable in one pass (0 recorded)",
            "OT_NOT_IN_SAMPLE": "recorded in section2_availability.ot_not_in_sample",
        },
        "date_spread": dates,
    }
    verdict["issues"] = all_issues
    verdict["overall"] = {
        "section2_pass": verdict["section2_availability"]["pass"],
        "section3_pass": verdict["section3_integrity"]["pass"],
        "section4_pass": verdict["section4_crosscheck"]["pass"],
        "battery_complete": sched_entry["http_status"] == 200,
        "note": "Passing sections 2-4 is NOT admission: design section 6 requires an "
                "independent verifier reproduction from a pinned revision and an "
                "explicit owner ruling. This battery freezes nothing and starts no clock.",
    }
    verdict["run_finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    verdict["manifest"] = fetcher.manifest

    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")

    summary_lines = [
        "## NBA CDN admission battery (Candidate A)",
        "",
        f"- Egress: {verdict['egress']}; run {run_started}",
        f"- Schedule path HTTP: {verdict['canonical_paths']['scheduleLeagueV2_1']['http_status']}; "
        f"scoreboard path HTTP: {verdict['canonical_paths']['todaysScoreboard_00']['http_status']}",
        f"- S2 availability: games {len(games)}/{BAR_GAMES}, dates {len(dates)}/{BAR_DATES}, "
        f"observations {len(observations)}/{BAR_OBSERVATIONS} -> "
        f"{'PASS' if verdict['section2_availability']['pass'] else 'FAIL'}",
        f"- S3 integrity: {'PASS' if verdict['section3_integrity']['pass'] else 'FAIL'} "
        f"(violations: {verdict['section3_integrity']['violation_counts']})",
        f"- S4 ESPN cross-check: joined {joined}/{BAR_JOINED} across {len(joined_games)}/{BAR_JOIN_GAMES} "
        f"games, disagreements {len(disagreements)} -> "
        f"{'PASS' if verdict['section4_crosscheck']['pass'] else 'FAIL'}",
        f"- Refusals: {json.dumps(refusals, sort_keys=True)}",
        "",
        "Passing is not admission (design S6: independent verifier + owner ruling still required).",
    ]
    summary = "\n".join(summary_lines) + "\n"
    print(summary)
    import os
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
