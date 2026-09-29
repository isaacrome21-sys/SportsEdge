"""Public, point-in-time MLB bullpen workload context.

This source is descriptive context only. It uses only completed games observed by
StatsAPI before ``as_of`` and never creates or modifies Model_P. The target game
is explicitly excluded. Workload is summarized from the ordered pitcher list in
each prior boxscore: the first pitcher is treated as the starter and every later
pitcher as a bullpen appearance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from .mlb_source import _get_json, parse_game_start
from .source_lineage import canonical_json_sha256

SCHEMA_VERSION = "mlb_bullpen_workload_v1"
SOURCE = "MLB_STATSAPI_PRIOR_COMPLETED_GAMES"


class MLBBullpenWorkloadError(RuntimeError):
    pass


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _team_ids(live_payload: Mapping[str, Any]) -> dict[str, int | None]:
    game_data = live_payload.get("gameData") or {}
    teams = game_data.get("teams") if isinstance(game_data, Mapping) else {}
    out: dict[str, int | None] = {"away": None, "home": None}
    if not isinstance(teams, Mapping):
        return out
    for side in ("away", "home"):
        team = teams.get(side)
        if isinstance(team, Mapping):
            out[side] = _positive_int(team.get("id"))
    return out


def _schedule_url(team_id: int, *, start_date: str, end_date: str) -> str:
    query = urlencode({
        "sportId": 1,
        "teamId": int(team_id),
        "startDate": start_date,
        "endDate": end_date,
    })
    return f"https://statsapi.mlb.com/api/v1/schedule?{query}"


def _boxscore_url(game_pk: int) -> str:
    return f"https://statsapi.mlb.com/api/v1/game/{int(game_pk)}/boxscore"


def _prior_games(schedule_payload: Mapping[str, Any], *, target_game_pk: int, as_of: datetime,
                 max_games: int) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for date_block in schedule_payload.get("dates") or []:
        if not isinstance(date_block, Mapping):
            continue
        for game in date_block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            game_pk = _positive_int(game.get("gamePk"))
            if game_pk is None or game_pk == int(target_game_pk):
                continue
            status = game.get("status") or {}
            abstract = str(status.get("abstractGameState") if isinstance(status, Mapping) else "")
            if abstract != "Final":
                continue
            try:
                start = parse_game_start(game.get("gameDate"))
            except Exception:
                continue
            if start >= as_of:
                continue
            games.append({"game_pk": game_pk, "game_start_utc": start})
    games.sort(key=lambda row: row["game_start_utc"], reverse=True)
    return games[:max_games]


def _team_box(boxscore: Mapping[str, Any], team_id: int) -> Mapping[str, Any] | None:
    teams = boxscore.get("teams") or {}
    if not isinstance(teams, Mapping):
        return None
    for side in ("away", "home"):
        row = teams.get(side)
        if not isinstance(row, Mapping):
            continue
        team = row.get("team") or {}
        if isinstance(team, Mapping) and _positive_int(team.get("id")) == int(team_id):
            return row
    return None


def _pitching_stats(team_box: Mapping[str, Any]) -> dict[int, dict[str, int]]:
    raw_pitchers = team_box.get("pitchers")
    pitcher_ids = [_positive_int(value) for value in raw_pitchers] if isinstance(raw_pitchers, list) else []
    pitcher_ids = [value for value in pitcher_ids if value is not None]
    # First listed pitcher is the starter. Everything after is bullpen usage.
    bullpen_ids = pitcher_ids[1:] if pitcher_ids else []
    players = team_box.get("players") or {}
    if not isinstance(players, Mapping):
        players = {}
    out: dict[int, dict[str, int]] = {}
    for pid in bullpen_ids:
        player = players.get(f"ID{pid}") or players.get(str(pid)) or {}
        stats = player.get("stats") if isinstance(player, Mapping) else {}
        pitching = stats.get("pitching") if isinstance(stats, Mapping) else {}
        if not isinstance(pitching, Mapping):
            pitching = {}
        def n(name: str) -> int:
            value = pitching.get(name, 0)
            if isinstance(value, bool):
                return 0
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return 0
            return max(0, parsed)
        out[int(pid)] = {
            "pitches": n("pitchesThrown"),
            "outs": n("outs"),
            "batters_faced": n("battersFaced"),
        }
    return out


def _team_workload(*, team_id: int, target_game_pk: int, as_of: datetime,
                   opener: Callable, lookback_days: int, max_games: int) -> dict[str, Any]:
    start_day = (as_of.date() - timedelta(days=lookback_days)).isoformat()
    end_day = as_of.date().isoformat()
    schedule = _get_json(_schedule_url(team_id, start_date=start_day, end_date=end_day), opener=opener)
    prior = _prior_games(schedule, target_game_pk=target_game_pk, as_of=as_of, max_games=max_games)
    games: list[dict[str, Any]] = []
    by_pitcher: dict[int, dict[str, Any]] = {}
    for game in prior:
        box = _get_json(_boxscore_url(game["game_pk"]), opener=opener)
        team_box = _team_box(box, team_id)
        if team_box is None:
            continue
        relief = _pitching_stats(team_box)
        game_pitches = sum(row["pitches"] for row in relief.values())
        game_outs = sum(row["outs"] for row in relief.values())
        game_bf = sum(row["batters_faced"] for row in relief.values())
        games.append({
            "game_pk": int(game["game_pk"]),
            "game_start_utc": game["game_start_utc"].isoformat(),
            "bullpen_pitches": game_pitches,
            "bullpen_outs": game_outs,
            "bullpen_batters_faced": game_bf,
            "reliever_ids": sorted(relief),
        })
        age_hours = (as_of - game["game_start_utc"]).total_seconds() / 3600.0
        for pid, row in relief.items():
            agg = by_pitcher.setdefault(pid, {"appearances": 0, "pitches_48h": 0, "pitches_72h": 0})
            agg["appearances"] += 1
            if age_hours <= 48.0:
                agg["pitches_48h"] += row["pitches"]
            if age_hours <= 72.0:
                agg["pitches_72h"] += row["pitches"]

    def pitches_within(hours: float) -> int:
        total = 0
        for game in games:
            start = datetime.fromisoformat(game["game_start_utc"])
            if (as_of - start).total_seconds() <= hours * 3600.0:
                total += int(game["bullpen_pitches"])
        return total

    back_to_back = sorted(pid for pid, row in by_pitcher.items() if int(row["appearances"]) >= 2)
    high_usage = sorted(pid for pid, row in by_pitcher.items() if int(row["pitches_48h"]) >= 40)
    return {
        "status": "AVAILABLE" if games else "NO_PRIOR_COMPLETED_GAMES",
        "team_id": int(team_id),
        "prior_games_used": len(games),
        "games": games,
        "bullpen_pitches_24h": pitches_within(24.0),
        "bullpen_pitches_48h": pitches_within(48.0),
        "bullpen_pitches_72h": pitches_within(72.0),
        "back_to_back_reliever_ids": back_to_back,
        "high_usage_48h_reliever_ids": high_usage,
        "reliever_workload": {str(pid): row for pid, row in sorted(by_pitcher.items())},
    }


def acquire_bullpen_workload(*, game_pk: int, as_of: datetime,
                             live_payload: Mapping[str, Any], opener: Callable = urlopen,
                             lookback_days: int = 4, max_games: int = 3) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if lookback_days < 1 or max_games < 1:
        raise ValueError("lookback_days and max_games must be positive")
    current = as_of.astimezone(timezone.utc)
    ids = _team_ids(live_payload)
    teams: dict[str, Any] = {}
    errors: list[str] = []
    for side in ("away", "home"):
        team_id = ids.get(side)
        if team_id is None:
            teams[side] = {"status": "TEAM_ID_MISSING", "team_id": None}
            errors.append(f"{side.upper()}_TEAM_ID_MISSING")
            continue
        try:
            teams[side] = _team_workload(
                team_id=team_id, target_game_pk=int(game_pk), as_of=current,
                opener=opener, lookback_days=lookback_days, max_games=max_games,
            )
        except Exception as exc:
            teams[side] = {"status": "FETCH_FAILED", "team_id": int(team_id)}
            errors.append(f"{side.upper()}_BULLPEN_FETCH_FAILED:{type(exc).__name__}:{exc}")

    available = sum(1 for side in ("away", "home") if teams[side].get("status") in {"AVAILABLE", "NO_PRIOR_COMPLETED_GAMES"})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": current.isoformat(),
        "source": SOURCE,
        "lookback_days": int(lookback_days),
        "max_games_per_team": int(max_games),
        "teams": teams,
        "errors": errors,
        "status": "AVAILABLE" if available == 2 else ("PARTIAL" if available else "MISSING"),
        "model_p_eligible": False,
        "evidence_eligible": False,
        "target_game_excluded": True,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
