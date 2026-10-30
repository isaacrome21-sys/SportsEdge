"""Map official NHL boxscore counting stats onto rate-model feature slots.

This is the v1 stand-in documented in docs/research/nhl_rate_v1_prelock.md.
It does not invent xG or GSAx.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

MIN_PRIOR_GAMES = 10


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _per60(count: float, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return float(count) * 60.0 / float(minutes)


def prior_team_rates(games: Sequence[Mapping[str, Any]], *, team_id: str, asof: datetime) -> dict[str, Any] | None:
    hist = []
    for game in games:
        start = _utc(str(game["start_utc"]))
        if start >= asof:
            continue
        if str(game["home_id"]) == team_id:
            hist.append({
                "gf": float(game["home_gf"]),
                "ga": float(game["away_gf"]),
                "sf": float(game["home_sog"]),
                "sa": float(game["away_sog"]),
                "minutes": float(game.get("minutes") or 60.0),
                "start": start,
            })
        elif str(game["away_id"]) == team_id:
            hist.append({
                "gf": float(game["away_gf"]),
                "ga": float(game["home_gf"]),
                "sf": float(game["away_sog"]),
                "sa": float(game["home_sog"]),
                "minutes": float(game.get("minutes") or 60.0),
                "start": start,
            })
    if len(hist) < MIN_PRIOR_GAMES:
        return None
    minutes = sum(row["minutes"] for row in hist)
    last = max(row["start"] for row in hist)
    rest = max(0.0, (asof - last).total_seconds() / 86400.0)
    sf = sum(row["sf"] for row in hist)
    sa = sum(row["sa"] for row in hist)
    return {
        "gf60": _per60(sum(row["gf"] for row in hist), minutes),
        "ga60": _per60(sum(row["ga"] for row in hist), minutes),
        "sf60": _per60(sf, minutes),
        "sa60": _per60(sa, minutes),
        "rest_days": rest,
        "prior_games": len(hist),
    }


def feature_row(home: Mapping[str, float], away: Mapping[str, float], *, home_side: bool) -> tuple[float, ...]:
    team, opp = (home, away) if home_side else (away, home)
    denom = max(1e-9, team["sf60"] + opp["sa60"])
    shot_share = team["sf60"] / denom
    return (
        team["gf60"],
        opp["ga60"],
        shot_share,
        0.0,
        0.0,
        team["rest_days"],
        0.0,
        0.0,
        1.0 if home_side else 0.0,
    )
