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
    # Every component must be a real nonnegative game observation. Summing
    # PRA first can mask a negative constituent (e.g. -2 PTS + 20 REB),
    # yielding an apparently valid combined stat; bool is not a stat.
    names = ("points", "rebounds", "assists") if stat == "pra" else (stat,)
    try:
        raw = [row[s] for s in (*names, "minutes")]
        if any(isinstance(x, bool) for x in raw):
            raise ValueError("boolean stat")
        vals = [float(x) for x in raw]
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError("NBA_EARLY_PROP_STATS_INVALID") from e
    if any(not isfinite(x) or x < 0 for x in vals):
        raise ValueError("NBA_EARLY_PROP_STATS_INVALID")
    return sum(vals[:-1]), vals[-1]


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
    # The league season is indexed by its opening year, not the year of
    # every included game. Check both target and history against Chicago
    # local dates; otherwise mislabeled January games can inflate priors.
    def belongs_to_season(day, start_year):
        return ((day.year == start_year and day.month >= 10) or
                (day.year == start_year + 1 and day.month <= 6))
    if not belongs_to_season(target, year):
        raise ValueError("NBA_EARLY_PROP_TARGET_SEASON_DATE_MISMATCH")
    curr, older, prior_teams, current_teams = [], [], set(), set()
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
        # Do not drop the final-state witness at the history->model seam.
        # A result "receipt" just one second after tipoff is insufficient
        # without explicit final status and a distinct finalization time.
        if row.get("event_state") != "FINAL" or row.get("result_state") != "FINAL":
            raise ValueError("NBA_EARLY_PROP_FINAL_WITNESS_REQUIRED")
        finalized = _aware(row.get("finalized_at"))
        if finalized <= tipoff or available < finalized:
            raise ValueError("NBA_EARLY_PROP_FINAL_WITNESS_CHRONOLOGY_INVALID")
        role_observed = _aware(row.get("role_observed_at"))
        if role_observed >= tipoff:
            raise ValueError("NBA_EARLY_PROP_PREGAME_ROLE_RECEIPT_REQUIRED")
        if tipoff.astimezone(_SLATE_TZ).date() != local_date:
            raise ValueError("NBA_EARLY_PROP_LOCAL_GAME_DATE_MISMATCH")
        if not belongs_to_season(local_date, season):
            raise ValueError("NBA_EARLY_PROP_HISTORY_SEASON_DATE_MISMATCH")
        value, minutes = _stat(row, stat)
        if local_date >= target or tipoff >= clock or available >= clock:
            excluded_future += 1
            continue
        if minutes == 0:
            continue
        if season == year:
            curr.append(value)
            current_teams.add(played_for)
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
    # Prior-season changes and same-season trades both change player role,
    # usage and minutes assumptions. A V2 empirical mixture cannot prove
    # stability merely because the old season used the target team.
    transfer = bool((prior_teams and prior_teams != {team}) or
                    (current_teams and current_teams != {team}))
    return {"engine_id": ENGINE,
            "status": "WATCH_TRANSFER_NOT_MODELED" if transfer else "RESEARCH_PROJECTION",
            "player_id": pid, "stat": stat, "line": threshold,
            "p_over": o, "p_push": p, "p_under": u,
            "model_mean": mean, "weight_current": weight_current,
            "current_season_prior_games": len(curr),
            "previous_season_games": len(older),
            "previous_season": prev, "target_season": year,
            "previous_team_ids": sorted(prior_teams),
            "current_team_ids": sorted(current_teams), "target_team_id": team,
            "transfer_unmodeled": transfer, "future_rows_excluded": excluded_future,
            "as_of_utc": clock.isoformat(),
            "market_test": "NOT_RUN", "availability": "NOT_WIRED",
            "construction_relation": "NEW_V2_NOT_FROZEN_NBA_PROP_EMPIRICAL_V1",
            "research_only": True, "play_authority": False}
