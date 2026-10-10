"""Prospective 2026 SportsDataverse-native CFB scoring inputs (not historical training).

Use the same *numeric ESPN team IDs* and per-game metric definitions as the
selected historical SportsDataverse candidate. Never use current-game outcomes,
future weeks, market data, fuzzy team matches, or files observed after as-of.
A source bundle is captured by fetch_cfb_sdv_live.py with immutable SHA receipts.
This is an unvalidated model research lane, not a promotion of betting authority.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from .sportsdataverse_history import (
    TeamSnapshot, SOURCE_CONTRACT, _mean, _pos_team_id,
    build_prior_season_fallback_snapshots,
)
from .sportsdataverse_materializer import _snapshot_to_metrics

DATASETS = ("adv_team", "adv_situational", "adv_drives", "cfb_schedules")
YEARS = (2025, 2026)
FILES = {
    (year, name): f"{name}_{year}.csv.gz" if name == "cfb_schedules"
    else f"{name}_{year}.csv"
    for year in YEARS for name in DATASETS
}
LIVE_CONTRACT = "CFB_SDV_PUBLIC_PROSPECTIVE_2026_V1"


class SDVLiveError(ValueError):
    pass


def _utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("timezone missing")
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SDVLiveError("CFB_SDV_LIVE_TIMESTAMP_INVALID") from exc


def _boolean(value):
    if type(value) is bool:
        return value
    val = str(value).strip().lower()
    if val in {"true", "1", "t"}:
        return True
    if val in {"false", "0", "f"}:
        return False
    raise SDVLiveError("CFB_SDV_LIVE_BOOLEAN_INVALID")


def _team_id(value):
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    if not raw.isdecimal() or int(raw) <= 0:
        raise SDVLiveError("CFB_SDV_LIVE_TEAM_ID_INVALID")
    return int(raw)


def _read_bundle(directory: Path, now: datetime):
    path = directory / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != LIVE_CONTRACT:
        raise SDVLiveError("CFB_SDV_LIVE_RECEIPT_SCHEMA_INVALID")
    observed = _utc(receipt.get("captured_at"))
    if observed > now:
        raise SDVLiveError("CFB_SDV_LIVE_RECEIPT_AFTER_ASOF")
    files = receipt.get("files")
    if not isinstance(files, dict) or set(files) != set(FILES.values()):
        raise SDVLiveError("CFB_SDV_LIVE_RECEIPT_INCOMPLETE")
    rows = {}
    for (year, name), filename in FILES.items():
        info = files[filename]
        data = (directory / filename).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if info.get("sha256") != digest:
            raise SDVLiveError("CFB_SDV_LIVE_SHA_MISMATCH:" + filename)
        if not str(info.get("url") or "").startswith(
            "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
        ):
            raise SDVLiveError("CFB_SDV_LIVE_PROVIDER_INVALID")
        if data.startswith(b"\x1f\x8b"):
            data = gzip.decompress(data)
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
        if not reader.fieldnames:
            raise SDVLiveError("CFB_SDV_LIVE_HEADER_MISSING:" + filename)
        if name != "cfb_schedules" and not {
            "game_id", "season", "pos_team"
        }.issubset(reader.fieldnames):
            raise SDVLiveError("CFB_SDV_LIVE_ADV_HEADER_MISSING:" + filename)
        if name == "cfb_schedules" and not {
            "game_id", "season", "week", "home_id", "away_id",
            "home_team", "away_team", "start_date", "completed", "fbs_game",
            "season_type", "neutral_site",
        }.issubset(reader.fieldnames):
            raise SDVLiveError("CFB_SDV_LIVE_SCHEDULE_HEADER_MISSING")
        dataset_rows = list(reader)
        if not dataset_rows or any(int(row.get("season") or 0) != year for row in dataset_rows):
            raise SDVLiveError("CFB_SDV_LIVE_SEASON_INVALID:" + filename)
        rows[(year, name)] = dataset_rows
    return rows, {"capture_time": observed.isoformat(),
                  "file_sha256": {name: files[name]["sha256"] for name in sorted(files)},
                  "source_contract": LIVE_CONTRACT}


def _completed_fbs_prior_schedule(schedules, *, season: int, week: int, now: datetime):
    out = {}
    for row in schedules:
        if int(row["season"]) != season or int(row["week"]) >= week:
            continue
        if str(row["season_type"]).lower() not in {"regular", "2"}:
            continue
        if not _boolean(row["fbs_game"]) or not _boolean(row["completed"]):
            continue
        if _utc(row["start_date"]) >= now:
            raise SDVLiveError("CFB_SDV_LIVE_PRIOR_GAME_AFTER_ASOF")
        gid = str(row["game_id"])
        if gid in out:
            raise SDVLiveError("CFB_SDV_LIVE_GAME_DUPLICATE")
        out[gid] = row
    return out


def _current_snapshots(data, *, season: int, target_week: int, now: datetime):
    schedule = _completed_fbs_prior_schedule(
        data[(season, "cfb_schedules")], season=season, week=target_week, now=now
    )
    allowed = set(schedule)
    by_type = {}
    for name in ("adv_team", "adv_situational", "adv_drives"):
        group = defaultdict(dict)
        for row in data[(season, name)]:
            gid = str(row["game_id"])
            if gid not in allowed:
                continue
            tid = _pos_team_id(row)
            if tid in group[gid]:
                raise SDVLiveError(f"CFB_SDV_LIVE_DUPLICATE:{name}:{gid}:{tid}")
            group[gid][tid] = row
        by_type[name] = group

    t, s, d = defaultdict(list), defaultdict(list), defaultdict(list)
    opp_t, opp_s = defaultdict(list), defaultdict(list)
    for gid, game in schedule.items():
        home, away = _team_id(game["home_id"]), _team_id(game["away_id"])
        teams = {home, away}
        for name in by_type:
            if set(by_type[name].get(gid, {})) != teams:
                raise SDVLiveError(f"CFB_SDV_LIVE_PRIOR_GAME_COVERAGE:{name}:{gid}")
        for own, opponent in ((home, away), (away, home)):
            t[own].append(by_type["adv_team"][gid][own])
            s[own].append(by_type["adv_situational"][gid][own])
            d[own].append(by_type["adv_drives"][gid][own])
            opp_t[own].append(by_type["adv_team"][gid][opponent])
            opp_s[own].append(by_type["adv_situational"][gid][opponent])

    result = {}
    for tid in t:
        if not (len(t[tid]) == len(s[tid]) == len(d[tid]) == len(opp_t[tid]) == len(opp_s[tid])):
            raise SDVLiveError("CFB_SDV_LIVE_TEAM_COVERAGE_MISMATCH")
        snap = TeamSnapshot(
            team_id=tid, season=season, through_week=target_week-1,
            games_in_sample=len(t[tid]),
            off_ppa_rush=_mean(t[tid], "EPA_rushing_per_play"),
            off_ppa_dropback=_mean(t[tid], "EPA_passing_per_play"),
            off_success_rate=_mean(s[tid], "EPA_success_rate"),
            def_ppa_rush_allowed=_mean(opp_t[tid], "EPA_rushing_per_play"),
            def_ppa_dropback_allowed=_mean(opp_t[tid], "EPA_passing_per_play"),
            def_success_rate_allowed=_mean(opp_s[tid], "EPA_success_rate"),
            standard_down_ppa=_mean(s[tid], "EPA_standard_down_per_play"),
            passing_down_success_rate=_mean(s[tid], "EPA_success_passing_down_rate"),
            explosive_rate=_mean(t[tid], "EPA_explosive_rate"),
            net_field_position=-_mean(d[tid], "avg_field_position"),
        )
        result[tid] = snap
    return result


def build_live_rows(board, *, directory, now, expand_compact, normalize_name):
    """Return model-ready rows, source receipt; reject mismatches and late captures.

    The schedule determines actual competition week, not an assumed CFBD week
    number. Each target game receives strictly-prior-week native snapshots.
    """
    now = _utc(now.isoformat()) if isinstance(now, datetime) else _utc(now)
    data, provenance = _read_bundle(Path(directory), now)
    schedules = data[(2026, "cfb_schedules")]
    prior_snaps = build_prior_season_fallback_snapshots(
        adv_team_rows=data[(2025, "adv_team")],
        adv_situational_rows=data[(2025, "adv_situational")],
        adv_drive_rows=data[(2025, "adv_drives")],
        schedule_rows=data[(2025, "cfb_schedules")],
        target_season=2026,
    )
    prior_by_id = {snap.team_id: snap for snap in prior_snaps}
    results = []
    current_cache = {}
    for raw in board:
        selection = expand_compact(raw)
        home = normalize_name(selection.get("home", ""))
        away = normalize_name(selection.get("away", ""))
        if not home or not away or home == away:
            raise SDVLiveError("CFB_SDV_LIVE_BOARD_IDENTITIES_REQUIRED")
        matches = [
            g for g in schedules
            if int(g["season"]) == 2026 and
            normalize_name(g.get("home_team", "")) == home and
            normalize_name(g.get("away_team", "")) == away and
            _utc(g["start_date"]) > now and
            str(g.get("season_type", "")).lower() in {"regular", "2"} and
            _boolean(g.get("fbs_game"))
        ]
        if len(matches) != 1:
            raise SDVLiveError(f"CFB_SDV_LIVE_MATCH_NOT_UNIQUE:{away}@{home}:{len(matches)}")
        game = matches[0]
        week = int(game["week"])
        if week < 2:
            raise SDVLiveError("CFB_SDV_LIVE_WEEK_OUT_OF_RANGE")
        if week not in current_cache:
            current_cache[week] = _current_snapshots(
                data, season=2026, target_week=week, now=now
            )
        home_id, away_id = _team_id(game["home_id"]), _team_id(game["away_id"])
        current = current_cache[week]
        if any(tid not in current or tid not in prior_by_id for tid in (home_id, away_id)):
            raise SDVLiveError(f"CFB_SDV_LIVE_MISSING_SNAPSHOT:{away}@{home}")
        hp, ap = prior_by_id[home_id], prior_by_id[away_id]
        hc, ac = current[home_id], current[away_id]
        # The frozen prior/current blend expects both snapshots and the native
        # 10-feature scale; do not run the CFBD moment-matching transform here.
        row = {
            "game_id": str(game["game_id"]),
            "home_team": str(game["home_team"]),
            "away_team": str(game["away_team"]),
            "season": 2026, "week": week,
            "neutral_site": _boolean(game["neutral_site"]),
            "start_ts": _utc(game["start_date"]).isoformat(),
            "home_prior_metrics": _snapshot_to_metrics(hp, "PRIOR_SEASON_FALLBACK"),
            "away_prior_metrics": _snapshot_to_metrics(ap, "PRIOR_SEASON_FALLBACK"),
            "home_current_metrics": _snapshot_to_metrics(hc, "CURRENT_SEASON_PRIOR_WEEKS"),
            "away_current_metrics": _snapshot_to_metrics(ac, "CURRENT_SEASON_PRIOR_WEEKS"),
            "weather": {"game_indoor": False, "wind_speed": 6.89,
                        "temperature": 64.6, "fallback": "TRAINING_MEAN"},
            "quotes": selection["quotes"],
            "live_source_contract": LIVE_CONTRACT,
        }
        row["home_metrics"] = dict(row["home_current_metrics"])
        row["away_metrics"] = dict(row["away_current_metrics"])
        results.append(row)
    if not results:
        raise SDVLiveError("CFB_SDV_LIVE_NO_RESOLVED_GAMES")
    return results, provenance
