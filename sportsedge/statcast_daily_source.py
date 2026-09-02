"""Daily MLB Statcast acquisition and rolling batter/pitcher aggregation.

Source: Baseball Savant Statcast CSV search surface. This is an acquisition layer,
not a model. It records source/fetch timestamps and emits durable feature snapshots
for downstream market models. Downstream consumers should fail closed on stale
snapshots rather than silently using old Statcast data.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import csv
import io
import json
import math
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = "https://baseballsavant.mlb.com/statcast_search/csv"
SOURCE = "BASEBALL_SAVANT_STATCAST"
DEFAULT_TTL_SECONDS = 36 * 60 * 60
HARD_HIT_MPH = 95.0
# Baseball Savant game_date is a local MLB game date, not a UTC date. Pacific time
# is the latest regular MLB venue timezone, so using its current calendar date as
# the exclusive upper bound fail-closes current-day games across all MLB venues.
MLB_LATEST_VENUE_TZ = ZoneInfo("America/Los_Angeles")


class StatcastSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class StatcastSnapshot:
    start_date: str
    end_date: str
    retrieved_at: str
    source: str
    batter_rows: tuple[dict[str, Any], ...]
    pitcher_rows: tuple[dict[str, Any], ...]
    raw_pitch_rows: int


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _request_csv(url: str, *, opener: Callable = urlopen, timeout: int = 60) -> list[dict[str, str]]:
    req = Request(url, headers={
        "Accept": "text/csv,*/*",
        "User-Agent": "SportsEdge-Statcast/1.0",
        "Referer": "https://baseballsavant.mlb.com/",
    })
    try:
        with opener(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise StatcastSourceError(f"STATCAST_FETCH_FAILED:{type(exc).__name__}:{exc}") from exc
    if not raw.strip():
        raise StatcastSourceError("STATCAST_EMPTY_RESPONSE")
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except Exception as exc:
        raise StatcastSourceError("STATCAST_CSV_PARSE_FAILED") from exc
    if not rows:
        raise StatcastSourceError("STATCAST_NO_ROWS")
    required = {"game_date", "batter", "pitcher", "events", "description"}
    if not required.issubset(set(rows[0])):
        raise StatcastSourceError("STATCAST_SCHEMA_MISSING_CORE_FIELDS")
    return rows


def build_statcast_url(start_date: date, end_date: date) -> str:
    if end_date < start_date:
        raise ValueError("end_date before start_date")
    params = {
        "all": "true",
        "type": "details",
        "game_date_gt": start_date.isoformat(),
        "game_date_lt": end_date.isoformat(),
        "player_type": "batter",
    }
    return f"{BASE}?{urlencode(params)}"


def _new_acc() -> dict[str, Any]:
    return {
        "pitches": 0,
        "pa": 0,
        "ab": 0,
        "hits": 0,
        "hr": 0,
        "bb": 0,
        "k": 0,
        "batted_balls": 0,
        "hard_hit": 0,
        "barrels": 0,
        "launch_speed_sum": 0.0,
        "launch_speed_n": 0,
        "launch_angle_sum": 0.0,
        "launch_angle_n": 0,
        "xwoba_sum": 0.0,
        "xwoba_n": 0,
        "xba_sum": 0.0,
        "xba_n": 0,
        "xslg_sum": 0.0,
        "xslg_n": 0,
        "release_speed_sum": 0.0,
        "release_speed_n": 0,
        "max_release_speed": None,
        "vs_l_pa": 0,
        "vs_r_pa": 0,
        "latest_game_date": None,
    }


def _terminal_event(row: dict[str, str]) -> bool:
    return bool(str(row.get("events") or "").strip())


def _is_ab_event(event: str) -> bool:
    return event not in {
        "walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt",
        "catcher_interf", "field_error",
    }


def _is_hit(event: str) -> bool:
    return event in {"single", "double", "triple", "home_run"}


def _finish(entity_id: int, acc: dict[str, Any], *, role: str, retrieved_at: datetime, start_date: date, end_date: date) -> dict[str, Any]:
    pa = int(acc["pa"])
    bbe = int(acc["batted_balls"])
    def rate(num: int, den: int) -> float | None:
        return round(num / den, 6) if den > 0 else None
    def mean(total: float, n: int) -> float | None:
        return round(total / n, 4) if n > 0 else None
    row = {
        "entity_id": str(entity_id),
        "role": role,
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
        "latest_game_date": acc["latest_game_date"],
        "retrieved_at": retrieved_at.isoformat(),
        "source": SOURCE,
        "ttl_seconds": DEFAULT_TTL_SECONDS,
        "pitches": int(acc["pitches"]),
        "pa": pa,
        "ab": int(acc["ab"]),
        "hits": int(acc["hits"]),
        "hr": int(acc["hr"]),
        "bb": int(acc["bb"]),
        "k": int(acc["k"]),
        "batted_balls": bbe,
        "hard_hit": int(acc["hard_hit"]),
        "barrels": int(acc["barrels"]),
        "hard_hit_rate": rate(int(acc["hard_hit"]), bbe),
        "barrel_rate": rate(int(acc["barrels"]), bbe),
        "hr_per_pa": rate(int(acc["hr"]), pa),
        "bb_per_pa": rate(int(acc["bb"]), pa),
        "k_per_pa": rate(int(acc["k"]), pa),
        "avg_exit_velocity": mean(acc["launch_speed_sum"], int(acc["launch_speed_n"])),
        "avg_launch_angle": mean(acc["launch_angle_sum"], int(acc["launch_angle_n"])),
        "xwoba_contact": mean(acc["xwoba_sum"], int(acc["xwoba_n"])),
        "xba_contact": mean(acc["xba_sum"], int(acc["xba_n"])),
        "xslg_contact": mean(acc["xslg_sum"], int(acc["xslg_n"])),
        "avg_release_speed": mean(acc["release_speed_sum"], int(acc["release_speed_n"])),
        "max_release_speed": acc["max_release_speed"],
        "vs_l_pa": int(acc["vs_l_pa"]),
        "vs_r_pa": int(acc["vs_r_pa"]),
    }
    return row


def aggregate_statcast(rows: Iterable[dict[str, str]], *, start_date: date, end_date: date, retrieved_at: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    batters: dict[int, dict[str, Any]] = defaultdict(_new_acc)
    pitchers: dict[int, dict[str, Any]] = defaultdict(_new_acc)

    for row in rows:
        batter = _to_int(row.get("batter"))
        pitcher = _to_int(row.get("pitcher"))
        if batter is None or pitcher is None:
            continue
        event = str(row.get("events") or "").strip()
        game_date = str(row.get("game_date") or "").strip() or None
        terminal = _terminal_event(row)
        stand = str(row.get("stand") or "").upper().strip()
        p_throws = str(row.get("p_throws") or "").upper().strip()
        launch_speed = _to_float(row.get("launch_speed"))
        launch_angle = _to_float(row.get("launch_angle"))
        xwoba = _to_float(row.get("estimated_woba_using_speedangle"))
        xba = _to_float(row.get("estimated_ba_using_speedangle"))
        xslg = _to_float(row.get("estimated_slg_using_speedangle"))
        launch_speed_angle = _to_int(row.get("launch_speed_angle"))
        release_speed = _to_float(row.get("release_speed"))

        for role, entity_id, acc in (("BATTER", batter, batters[batter]), ("PITCHER", pitcher, pitchers[pitcher])):
            acc["pitches"] += 1
            if game_date and (acc["latest_game_date"] is None or game_date > acc["latest_game_date"]):
                acc["latest_game_date"] = game_date
            if terminal:
                acc["pa"] += 1
                if _is_ab_event(event):
                    acc["ab"] += 1
                if _is_hit(event):
                    acc["hits"] += 1
                if event == "home_run":
                    acc["hr"] += 1
                if event in {"walk", "intent_walk"}:
                    acc["bb"] += 1
                if event in {"strikeout", "strikeout_double_play"}:
                    acc["k"] += 1
                # Batter platoon is pitcher hand; pitcher platoon is batter side.
                hand = p_throws if role == "BATTER" else stand
                if hand == "L":
                    acc["vs_l_pa"] += 1
                elif hand == "R":
                    acc["vs_r_pa"] += 1
            if launch_speed is not None:
                acc["batted_balls"] += 1
                acc["launch_speed_sum"] += launch_speed
                acc["launch_speed_n"] += 1
                if launch_speed >= HARD_HIT_MPH:
                    acc["hard_hit"] += 1
                if launch_speed_angle == 6:
                    acc["barrels"] += 1
            if launch_angle is not None:
                acc["launch_angle_sum"] += launch_angle
                acc["launch_angle_n"] += 1
            if xwoba is not None:
                acc["xwoba_sum"] += xwoba
                acc["xwoba_n"] += 1
            if xba is not None:
                acc["xba_sum"] += xba
                acc["xba_n"] += 1
            if xslg is not None:
                acc["xslg_sum"] += xslg
                acc["xslg_n"] += 1
            if role == "PITCHER" and release_speed is not None:
                acc["release_speed_sum"] += release_speed
                acc["release_speed_n"] += 1
                current_max = acc["max_release_speed"]
                acc["max_release_speed"] = release_speed if current_max is None else max(current_max, release_speed)

    batter_rows = [_finish(k, v, role="BATTER", retrieved_at=retrieved_at, start_date=start_date, end_date=end_date) for k, v in batters.items()]
    pitcher_rows = [_finish(k, v, role="PITCHER", retrieved_at=retrieved_at, start_date=start_date, end_date=end_date) for k, v in pitchers.items()]
    batter_rows.sort(key=lambda x: int(x["entity_id"]))
    pitcher_rows.sort(key=lambda x: int(x["entity_id"]))
    return batter_rows, pitcher_rows


def _strict_prior_day_end(current_utc: datetime) -> date:
    """Return an exclusive Statcast game_date upper bound that excludes today's MLB games.

    Statcast's game_date is local to the game. Using the latest MLB venue timezone
    prevents UTC rollover from turning an in-progress U.S. game into a prior date.
    """
    return current_utc.astimezone(MLB_LATEST_VENUE_TZ).date()


def fetch_daily_statcast(*, end_date: date | None = None, days: int = 30, opener: Callable = urlopen, now: datetime | None = None) -> StatcastSnapshot:
    if days <= 0 or days > 90:
        raise ValueError("days must be between 1 and 90")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = end_date or _strict_prior_day_end(current)
    start = end - timedelta(days=days - 1)
    rows = _request_csv(build_statcast_url(start, end), opener=opener)
    batter_rows, pitcher_rows = aggregate_statcast(rows, start_date=start, end_date=end, retrieved_at=current)
    return StatcastSnapshot(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        retrieved_at=current.isoformat(),
        source=SOURCE,
        batter_rows=tuple(batter_rows),
        pitcher_rows=tuple(pitcher_rows),
        raw_pitch_rows=len(rows),
    )


def snapshot_manifest(snapshot: StatcastSnapshot) -> dict[str, Any]:
    return {
        "source": snapshot.source,
        "provider_tier": "PRIMARY_STATS",
        "retrieved_at": snapshot.retrieved_at,
        "window_start": snapshot.start_date,
        "window_end": snapshot.end_date,
        "ttl_seconds": DEFAULT_TTL_SECONDS,
        "raw_pitch_rows": snapshot.raw_pitch_rows,
        "batter_entities": len(snapshot.batter_rows),
        "pitcher_entities": len(snapshot.pitcher_rows),
        "status": "PASS" if snapshot.batter_rows and snapshot.pitcher_rows else "INCOMPLETE",
    }
