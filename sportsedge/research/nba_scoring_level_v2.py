"""NBA scoring-level / attack-defense challenger, separate from failed game V1.

No sportsbook line enters the construction. Use only independently sourced,
completed games AVAILABLE before the pricing instant. This module is a
research-only projected total; it has no distribution, EV or PLAY authority.
Its rolling league level adapts to score regime instead of anchoring to 226.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import fmean


ENGINE = "NBA_SCORING_LEVEL_PIT_CHALLENGER_V2"
MIN_HISTORY = 30
MIN_TEAM_HISTORY = 5
MAX_HISTORY = 450
SHRINK_GAMES = 20.0


def _dt(x, field):
    if isinstance(x, datetime):
        d = x
    else:
        try:
            d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except (ValueError, TypeError) as e:
            raise ValueError("NBA_TOTALS_" + field + "_INVALID") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("NBA_TOTALS_" + field + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _points(row, field):
    try:
        v = float(row[field])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("NBA_TOTALS_" + field.upper() + "_INVALID") from e
    if not isfinite(v) or v < 0:
        raise ValueError("NBA_TOTALS_" + field.upper() + "_INVALID")
    return v


def predict_total(history, *, home, away, as_of, min_games=MIN_HISTORY):
    """Predict with a PIT-adjusted league level and team attack/defense.

    Input record keys: game_id, tipoff, observed_at, source_ref,
    home, away, home_pts, away_pts. observed_at must be a genuine
    result-availability receipt, not reconstructed as tipoff.
    """
    asof = _dt(as_of, "AS_OF")
    home, away = str(home).strip(), str(away).strip()
    if not home or not away or home == away:
        raise ValueError("NBA_TOTALS_TEAM_IDENTITY_INVALID")
    eligible = []
    excluded_future = 0
    seen = set()
    for row in history:
        gid = str(row.get("game_id") or "").strip()
        h, a = str(row.get("home") or "").strip(), str(row.get("away") or "").strip()
        src = str(row.get("source_ref") or "").strip()
        if not gid or not h or not a or h == a or not src:
            raise ValueError("NBA_TOTALS_HISTORY_IDENTITY_OR_SOURCE_MISSING")
        if gid in seen:
            raise ValueError("NBA_TOTALS_DUPLICATE_GAME_ID")
        seen.add(gid)
        tip, observed = _dt(row.get("tipoff"), "TIPOFF"), _dt(row.get("observed_at"), "RESULT_AVAILABLE")
        if observed <= tip:
            raise ValueError("NBA_TOTALS_RESULT_NOT_AFTER_TIPOFF")
        hp, ap = _points(row, "home_pts"), _points(row, "away_pts")
        if tip >= asof or observed >= asof:
            excluded_future += 1
            continue
        eligible.append((tip, gid, h, a, hp, ap))
    eligible.sort(key=lambda g: (g[0], g[1]))
    recent = eligible[-MAX_HISTORY:]
    if len(recent) < min_games:
        return {"engine_id": ENGINE, "status": "REFUSED",
                "reason": "NBA_TOTALS_INSUFFICIENT_PIT_HISTORY",
                "history_games": len(recent), "future_excluded": excluded_future,
                "research_only": True, "play_authority": False}
    league = fmean((g[4] + g[5]) / 2.0 for g in recent)
    scored = {home: [], away: []}
    conceded = {home: [], away: []}
    for _, _, h, a, hp, ap in recent:
        if h in scored:
            scored[h].append(hp)
            conceded[h].append(ap)
        if a in scored:
            scored[a].append(ap)
            conceded[a].append(hp)
    if min(len(scored[home]), len(scored[away])) < MIN_TEAM_HISTORY:
        return {"engine_id": ENGINE, "status": "REFUSED",
                "reason": "NBA_TOTALS_INSUFFICIENT_TEAM_HISTORY",
                "team_games": {home: len(scored[home]), away: len(scored[away])},
                "research_only": True, "play_authority": False}
    def shrunk(values):
        n = len(values)
        return (fmean(values) - league) * n / (n + SHRINK_GAMES)
    # Both directions use symmetric team offense and opposing defense.
    hp = league + shrunk(scored[home]) + shrunk(conceded[away])
    ap = league + shrunk(scored[away]) + shrunk(conceded[home])
    return {"engine_id": ENGINE, "status": "RESEARCH_PROJECTION",
            "predicted_home": hp, "predicted_away": ap,
            "predicted_total": hp + ap, "league_points_per_team": league,
            "history_games": len(recent), "future_excluded": excluded_future,
            "team_games": {home: len(scored[home]), away: len(scored[away])},
            "as_of_utc": asof.isoformat(),
            "method": "PIT_LEAGUE_LEVEL_PLUS_SHRUNK_TEAM_OFFENSE_AND_DEFENSE",
            "season_role": "CROSS_SEASON_NEW_CHALLENGER_NOT_FROZEN_V1",
            "market_test": "NOT_RUN", "calibration_status": "NOT_TESTED",
            "research_only": True, "play_authority": False}
