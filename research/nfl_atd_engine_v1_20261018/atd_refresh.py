"""NFL anytime-TD engine v1.1 — current-season refresh (PREREG_NFL_ATD_ENGINE_V1_1 §A).

DRAFT, pending owner freeze. The official nflverse stats_player_week_<season>
file enters the evidence once per slate (declared cadence: one refresh per
slate; the download step records sha256 + fetched_at (wall clock) in a
sidecar beside the file; fetched_at must satisfy
captured_at - REFRESH_MAX_AGE_HOURS <= fetched_at <= captured_at, for both
the stats file and the schedule). The pricing run's own start time must be
strictly before kickoff. Duplicate (player_id, game_id) rows, or a blank/TBD
schedule gametime, fail the refresh (REFRESH_FAILED).
Point-in-time: a current-season appearance is used only if its game is
completed before the entry capture time, where completed means the
schedule (nflverse games.csv) shows a result AND kickoff + COMPLETION_BUFFER
<= captured_at. The stats and schedule sha256 are written to the run record
BEFORE pricing. Any missing, failed, stale or inconsistent refresh raises
RefreshFailed and the run fails closed: there is NO 2025-only fallback.

The construction is unchanged: the engine's evidence window (current +
previous season, strictly earlier weeks, last 16) and point-in-time pool
already include earlier current-season weeks, exactly as the calibration
replay did; this module only supplies those weeks' rows.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import atd_engine as eng

COMPLETION_BUFFER = timedelta(hours=4)   # declared: kickoff + 4h = final
REFRESH_MAX_AGE_HOURS = 72               # declared per-slate cadence bound
SCHEDULE_TZ = ZoneInfo("America/New_York")  # nflverse gameday/gametime are ET


class RefreshFailed(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _utcnow() -> datetime:
    """Wall clock (UTC). The only source of fetched_at and run_started_at."""
    return datetime.now(timezone.utc)


def sidecar_path(path) -> Path:
    return Path(str(path) + ".fetch.json")


def record_download(path, *, source: str) -> dict:
    """Download step's record, written beside the file: its sha256 and the
    fetch time taken from the clock at download (never a caller argument)."""
    rec = {"file": Path(path).name, "sha256": _sha(path), "source": source,
           "fetched_at": _utcnow().isoformat()}
    sidecar_path(path).write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    return rec


def download(url: str, dest) -> dict:
    """Fetch an official nflverse file and record it (sha256 + fetched_at)."""
    dest = Path(dest)
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())
    return record_download(dest, source=url)


def _fetch_record(path) -> datetime:
    sc = sidecar_path(path)
    if not sc.exists():
        raise RefreshFailed("REFRESH_FETCH_RECORD_MISSING", str(sc))
    try:
        rec = json.loads(sc.read_text())
        t = datetime.fromisoformat(rec["fetched_at"])
    except (ValueError, KeyError, TypeError) as e:
        raise RefreshFailed("REFRESH_FETCH_RECORD_MISSING", f"unreadable {sc}: {e}")
    if t.tzinfo is None or rec.get("sha256") != _sha(path):
        raise RefreshFailed("REFRESH_FETCH_RECORD_MISMATCH", str(sc))
    return t


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ts(v, what):
    try:
        t = eng.parse_timestamp(v)
    except ValueError:
        t = None
    if t is None:
        raise RefreshFailed("REFRESH_TIMESTAMP_INVALID", what)
    return t


def _schedule(path: Path, season: int) -> dict:
    if not Path(path).exists():
        raise RefreshFailed("REFRESH_MISSING", f"schedule {path}")
    out = {}
    try:
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                if int(r["season"]) != season or r["game_type"] != "REG":
                    continue
                # blank / "TBD" gametime raises ValueError -> REFRESH_FAILED
                ko = datetime.strptime(f'{r["gameday"]} {r["gametime"]}',
                                       "%Y-%m-%d %H:%M").replace(tzinfo=SCHEDULE_TZ)
                out[r["game_id"]] = {"kickoff": ko,
                                     "has_result": (r.get("result") or "").strip() != ""}
    except (KeyError, ValueError, csv.Error, UnicodeDecodeError) as e:
        raise RefreshFailed("REFRESH_FAILED", f"schedule unreadable: {e}")
    if not out:
        raise RefreshFailed("REFRESH_FAILED", "schedule has no REG games")
    return out


def load_current_season(stats_path, schedule_path, *, season: int,
                        captured_at, fetched_at=None) -> dict:
    """fetched_at: optional {"stats": iso, "schedule": iso} injected by the
    replay (server push times of the data records) instead of sidecars."""
    cap = _ts(captured_at, "captured_at")
    stats_path = Path(stats_path)
    if not stats_path.exists():
        raise RefreshFailed("REFRESH_MISSING", str(stats_path))
    if not Path(schedule_path).exists():
        raise RefreshFailed("REFRESH_MISSING", f"schedule {schedule_path}")
    if fetched_at is not None:
        fet = _ts(fetched_at["stats"], "stats fetched_at")
        sfet = _ts(fetched_at["schedule"], "schedule fetched_at")
    else:
        fet = _fetch_record(stats_path)
        sfet = _fetch_record(schedule_path)
    for name, t in (("stats", fet), ("schedule", sfet)):
        if t > cap:
            raise RefreshFailed("REFRESH_FETCHED_AFTER_CAPTURE",
                                f"{name} fetched {t.isoformat()} after capture")
        if cap - t > timedelta(hours=REFRESH_MAX_AGE_HOURS):
            raise RefreshFailed("REFRESH_STALE",
                                f"{name} fetched {t.isoformat()} > {REFRESH_MAX_AGE_HOURS}h before capture")
    sched = _schedule(schedule_path, season)
    done = {g for g, s in sched.items()
            if s["has_result"] and s["kickoff"] + COMPLETION_BUFFER <= cap}
    apps, names, seen_games, keys = [], {}, set(), set()
    try:
        with gzip.open(stats_path, "rt") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG" or int(r["season"]) != season:
                    continue
                gid = r.get("game_id") or ""
                if gid not in sched:
                    raise RefreshFailed("REFRESH_SCHEDULE_MISMATCH", gid)
                seen_games.add(gid)
                key = (r["player_id"], gid)
                if key in keys:
                    raise RefreshFailed("REFRESH_FAILED",
                                        f"duplicate player-game row {key}")
                keys.add(key)
                if gid not in done:
                    continue  # point-in-time: not completed before capture
                f = eng._f
                apps.append({
                    "season": season, "week": int(r["week"]),
                    "pid": r["player_id"],
                    "position_group": r.get("position_group") or "",
                    "team": r.get("recent_team") or r.get("team") or "",
                    "opp": r.get("opponent_team") or "",
                    "td": 1 if f(r.get("rushing_tds")) + f(r.get("receiving_tds")) >= 1 else 0,
                    "st_td": 1 if f(r.get("special_teams_tds")) >= 1 else 0,
                    "game_id": gid})
                names[r["player_id"]] = r.get("player_display_name") or ""
    except RefreshFailed:
        raise
    except (OSError, EOFError, KeyError, ValueError, csv.Error) as e:
        raise RefreshFailed("REFRESH_FAILED", f"stats unreadable: {e}")
    missing = sorted(done - seen_games)
    if missing:
        raise RefreshFailed("REFRESH_STALE",
                            f"completed games absent from stats: {missing}")
    return {"appearances": apps, "names": names,
            "completed_games": sorted(done),
            "stats_sha256": _sha(stats_path),
            "schedule_sha256": _sha(schedule_path),
            "captured_at": cap.isoformat(), "fetched_at": fet.isoformat(),
            "schedule_fetched_at": sfet.isoformat()}


def schedule_kickoff(schedule_path, season, game_teams, board_kickoff) -> dict:
    """Cross-check a board's kickoff against the pinned schedule: exactly one
    REG game of `season` with these two teams within a day of the board
    kickoff, whose ET kickoff is the same instant. Else
    KICKOFF_SCHEDULE_MISMATCH. Returns {game_id, kickoff (UTC ISO), week}."""
    try:
        bko = eng.parse_timestamp(board_kickoff)
    except ValueError:
        bko = None
    if bko is None:
        raise RefreshFailed("KICKOFF_SCHEDULE_MISMATCH", "board kickoff unreadable")
    teams = set(game_teams or [])
    hits = []
    with open(schedule_path, newline="") as fh:
        for r in csv.DictReader(fh):
            if int(r["season"]) != int(season) or r["game_type"] != "REG":
                continue
            if {r["away_team"], r["home_team"]} != teams:
                continue
            try:
                ko = datetime.strptime(f'{r["gameday"]} {r["gametime"]}',
                                       "%Y-%m-%d %H:%M").replace(tzinfo=SCHEDULE_TZ)
            except ValueError:
                raise RefreshFailed("REFRESH_FAILED", f"gametime {r['game_id']}")
            if abs(ko - bko) <= timedelta(days=1):
                hits.append((r, ko))
    if len(hits) != 1 or hits[0][1] != bko:
        raise RefreshFailed("KICKOFF_SCHEDULE_MISMATCH",
                            f"{sorted(teams)} {board_kickoff}: {len(hits)} candidate(s)")
    r, ko = hits[0]
    return {"game_id": r["game_id"], "week": int(r["week"]),
            "kickoff": ko.astimezone(timezone.utc).isoformat()}


def merge_into(data: dict, apps: list, names: dict) -> dict:
    """Append current-season appearances to engine data (same shapes as
    atd_engine.load_data) and refresh each player's meta to his latest
    appearance, so the team-in-game check uses current-season teams."""
    for a in apps:
        data["by_player"].setdefault(a["pid"], []).append(a)
        data["by_season"].setdefault(a["season"], []).append(a)
        cur = data["meta"].get(a["pid"])
        key = (a["season"], a["week"])
        if cur is None or key >= (cur["last_season"], cur["last_week"]):
            data["meta"][a["pid"]] = {
                "display_name": names.get(a["pid"]) or (cur or {}).get("display_name", ""),
                "team": a["team"], "position_group": a["position_group"],
                "last_season": a["season"], "last_week": a["week"]}
    for pid in data["by_player"]:
        data["by_player"][pid].sort(key=lambda x: (x["season"], x["week"]))
    return data


def _write(path: Path, rec: dict):
    Path(path).write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")


def run_slate(*, stats_path, schedule_path, season, captured_at, kickoff,
              run_record_path, base_data, pricer, extra_record=None,
              now=None, fetched_at=None):
    """Refresh -> write run record with sha256 -> price. Fails closed.
    The run's start time must be strictly before kickoff; `now` is injected
    by the replay (never the wall clock there)."""
    started = now if now is not None else _utcnow()
    rec = {"engine": "nfl_atd_v1.1", "season": season,
           "captured_at": captured_at, "kickoff": kickoff,
           "run_started_at": started.isoformat(), **(extra_record or {})}
    try:
        ko = _ts(kickoff, "kickoff")
        if started >= ko:
            raise RefreshFailed("RUN_AFTER_KICKOFF",
                                f"run {started.isoformat()} >= kickoff {ko.isoformat()}")
        cur = load_current_season(stats_path, schedule_path, season=season,
                                  captured_at=captured_at, fetched_at=fetched_at)
    except RefreshFailed as e:
        rec.update(status="FAILED_CLOSED", failure=e.code, detail=e.detail)
        _write(run_record_path, rec)
        raise
    rec["refresh"] = {k: cur[k] for k in ("stats_sha256", "schedule_sha256",
                                          "fetched_at", "schedule_fetched_at",
                                          "completed_games")}
    rec["refresh"]["n_current_season_appearances"] = len(cur["appearances"])
    rec["status"] = "REFRESH_OK_PRICING_STARTED"
    _write(run_record_path, rec)          # hash on record BEFORE pricing
    data = base_data if base_data is not None else {
        "by_player": {}, "by_season": {}, "meta": {}}
    data = merge_into(data, cur["appearances"], cur["names"])
    result = pricer(data)
    rec["status"] = "PRICED"
    _write(run_record_path, rec)
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        raise SystemExit("usage: python3 atd_refresh.py URL DEST")
    print(json.dumps(download(sys.argv[1], sys.argv[2]), indent=1))
