"""Early-season NBA prop research challenger, NOT frozen NBA_PROP_EMPIRICAL_V1.

A player identified across two seasons may have 0-9 current-season games.
A recent prior-season empirical distribution is blended with same-season
outcomes as games accrue. No market line influences the distribution;
quote-side probabilities are research-only, uncalibrated, and not Model_P.
The existing V1 10-current-season-history gate is NEVER changed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

_SLATE_TZ = ZoneInfo("America/Chicago")


ENGINE = "NBA_EARLY_SEASON_PROP_EMPIRICAL_CHALLENGER_V2"
MIN_PREVIOUS = 8
MAX_CURRENT = 9
SEASON_BLEND_PRIOR = 8.0
STATS = ("points", "rebounds", "assists", "pra")


def _aware(x):
    try:
        d = x if isinstance(x, datetime) else datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise ValueError("NBA_EARLY_PROP_RESULT_TIME_INVALID") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("NBA_EARLY_PROP_RESULT_TIME_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _stat(row, stat):
    try:
        if stat == "pra":
            values = [float(row[s]) for s in ("points", "rebounds", "assists")]
            v = sum(values)
        else:
            v = float(row[stat])
        m = float(row["minutes"])
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError("NBA_EARLY_PROP_STATS_INVALID") from e
    if not isfinite(v) or v < 0 or not isfinite(m) or m < 0:
        raise ValueError("NBA_EARLY_PROP_STATS_INVALID")
    return v, m


def project_early_prop(records, *, player_id, target_team_id, target_season,
                       target_date, as_of, stat, line, previous_season=None):
    if stat not in STATS:
        raise ValueError("NBA_EARLY_PROP_STAT_UNSUPPORTED")
    pid = str(player_id or "").strip()
    team = str(target_team_id or "").strip()
    if not pid or not team:
        raise ValueError("NBA_EARLY_PROP_IDENTITY_REQUIRED")
    try:
        year = int(target_season)
        prev = year - 1 if previous_season is None else int(previous_season)
        target = date.fromisoformat(str(target_date))
        threshold = float(line)
    except (ValueError, TypeError) as e:
        raise ValueError("NBA_EARLY_PROP_INPUT_INVALID") from e
    if prev != year-1 or not isfinite(threshold) or threshold < 0:
        raise ValueError("NBA_EARLY_PROP_INPUT_INVALID")
    clock = _aware(as_of)
    curr, older, prior_teams = [], [], set()
    excluded_future = 0
    ids = set()
    for row in records:
        if str(row.get("player_id") or "") != pid:
            continue
        gid = str(row.get("game_id") or "").strip()
        src = str(row.get("source_ref") or "").strip()
        position = str(row.get("position") or "").strip()
        played_for = str(row.get("team_id") or "").strip()
        if not gid or not src or not position or not played_for:
            raise ValueError("NBA_EARLY_PROP_HISTORY_PROVENANCE_REQUIRED")
        season = int(row.get("season"))
        if season not in (year, prev):
            continue
        key = (season, gid)
        if key in ids:
            raise ValueError("NBA_EARLY_PROP_DUPLICATE_GAME")
        ids.add(key)
        try:
            local_date = date.fromisoformat(str(row["game_date"]))
        except (TypeError, ValueError, KeyError) as e:
            raise ValueError("NBA_EARLY_PROP_GAME_DATE_INVALID") from e
        # Previous-season results must have an actual game start, not merely
        # a caller-declared calendar date and result timestamp. Without this
        # chronological witness, a future outcome can be labeled 'available'
        # before it happened and leak into the model's prior pool.
        if row.get("tipoff") is None:
            raise ValueError("NBA_EARLY_PROP_HISTORY_TIPOFF_REQUIRED")
        tipoff = _aware(row["tipoff"])
        available = _aware(row.get("observed_at"))
        if available <= tipoff:
            raise ValueError("NBA_EARLY_PROP_RESULT_RECEIPT_NOT_AFTER_TIPOFF")
        if tipoff.astimezone(_SLATE_TZ).date() != local_date:
            raise ValueError("NBA_EARLY_PROP_LOCAL_GAME_DATE_MISMATCH")
        value, minutes = _stat(row, stat)
        if local_date >= target or tipoff >= clock or available >= clock:
            excluded_future += 1
            continue
        if minutes == 0:
            continue
        if season == year:
            curr.append(value)
        else:
            older.append(value)
            prior_teams.add(played_for)
    if len(curr) >= MAX_CURRENT+1:
        return {"engine_id": ENGINE, "status": "REFUSED",
                "reason": "NBA_EARLY_PROP_USE_FROZEN_CURRENT_SEASON_V1",
                "current_season_prior_games": len(curr),
                "research_only": True, "play_authority": False}
    if len(older) < MIN_PREVIOUS:
        return {"engine_id": ENGINE, "status": "REFUSED",
                "reason": "NBA_EARLY_PROP_PRIOR_SEASON_HISTORY_INSUFFICIENT",
                "previous_season_games": len(older), "current_season_games": len(curr),
                "research_only": True, "play_authority": False}
    weight_current = len(curr)/(len(curr)+SEASON_BLEND_PRIOR)
    def mass(vals):
        n = len(vals)
        return (sum(v > threshold for v in vals)/n,
                sum(v == threshold for v in vals)/n,
                sum(v < threshold for v in vals)/n)
    po, pp, pu = mass(older)
    if curr:
        co, cp, cu = mass(curr)
        o = weight_current*co + (1-weight_current)*po
        p = weight_current*cp + (1-weight_current)*pp
        u = weight_current*cu + (1-weight_current)*pu
        mean_current = sum(curr)/len(curr)
    else:
        o, p, u = po, pp, pu
        mean_current = 0.0
    mean_old = sum(older)/len(older)
    mean = weight_current*mean_current + (1-weight_current)*mean_old
    transfer = bool(prior_teams and (prior_teams != {team}))
    return {"engine_id": ENGINE,
            "status": "WATCH_TRANSFER_NOT_MODELED" if transfer else "RESEARCH_PROJECTION",
            "player_id": pid, "stat": stat, "line": threshold,
            "p_over": o, "p_push": p, "p_under": u,
            "model_mean": mean, "weight_current": weight_current,
            "current_season_prior_games": len(curr),
            "previous_season_games": len(older),
            "previous_season": prev, "target_season": year,
            "previous_team_ids": sorted(prior_teams), "target_team_id": team,
            "transfer_unmodeled": transfer, "future_rows_excluded": excluded_future,
            "as_of_utc": clock.isoformat(),
            "market_test": "NOT_RUN", "availability": "NOT_WIRED",
            "construction_relation": "NEW_V2_NOT_FROZEN_NBA_PROP_EMPIRICAL_V1",
            "research_only": True, "play_authority": False}
