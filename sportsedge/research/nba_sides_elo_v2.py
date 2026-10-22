"""Standalone NBA game sides challenger using the repo's neutral-site Elo.

This is not the failed V1 ratings model, not a frozen forward candidate,
and never a betting edge. Both moneyline and spread share one PIT Elo state;
the conversion from Elo to points and home court is DECLARED/UNVALIDATED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

from sportsedge.ratings.elo import EloTracker, expected_score
from sportsedge.ratings.params import get


ENGINE = "NBA_ELO_SIDES_PIT_CHALLENGER_V2"
MIN_TEAM_GAMES = 5
HCA_POINTS = 2.0


def _instant(value, field):
    if isinstance(value, datetime):
        when = value
    else:
        try:
            when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as e:
            raise ValueError(field + "_INVALID") from e
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError(field + "_TIMEZONE_REQUIRED")
    return when.astimezone(timezone.utc)


def project_sides(games, *, home, away, as_of, min_team_games=MIN_TEAM_GAMES):
    asof = _instant(as_of, "NBA_SIDE_AS_OF")
    home = str(home or "").strip()
    away = str(away or "").strip()
    if not home or not away or home.casefold() == away.casefold():
        raise ValueError("NBA_SIDE_TEAM_IDENTITY_INVALID")
    prior, excluded, ids = [], 0, set()
    for g in games:
        gid = str(g.get("game_id") or "").strip()
        src = str(g.get("source_ref") or "").strip()
        gh = str(g.get("home") or "").strip()
        ga = str(g.get("away") or "").strip()
        if not gid or not src or not gh or not ga or gh.casefold() == ga.casefold():
            raise ValueError("NBA_SIDE_HISTORY_PROVENANCE_OR_TEAMS_MISSING")
        if gid in ids:
            raise ValueError("NBA_SIDE_DUPLICATE_EVENT_ID")
        ids.add(gid)
        tip = _instant(g.get("tipoff"), "NBA_SIDE_TIPOFF")
        observed = _instant(g.get("observed_at"), "NBA_SIDE_RESULT_AVAILABLE")
        if observed <= tip:
            raise ValueError("NBA_SIDE_RESULT_NOT_AFTER_TIP")
        scores = []
        for key in ("home_score", "away_score"):
            x = g.get(key)
            if isinstance(x, bool) or not isinstance(x, int) or x < 0:
                raise ValueError("NBA_SIDE_SCORE_INVALID")
            scores.append(x)
        if tip >= asof or observed >= asof:
            excluded += 1
            continue
        prior.append((tip, gid, gh, ga, scores[0], scores[1], str(g.get("season") or "")))
    if not prior:
        return {"engine_id": ENGINE, "status": "REFUSED",
                "reason": "NBA_SIDE_NO_PIT_GAME_HISTORY", "research_only": True,
                "play_authority": False}
    prior.sort(key=lambda t: (t[0], t[1]))
    elo = EloTracker("NBA")
    for tip, gid, gh, ga, hs, aws, season in prior:
        elo.record_game(date=tip, home=gh, away=ga,
                        home_score=hs, away_score=aws, season=season)
    hr, hn = elo.rating_at(home, asof)
    ar, an = elo.rating_at(away, asof)
    if min(hn, an) < min_team_games:
        return {"engine_id": ENGINE, "status": "REFUSED",
                "reason": "NBA_SIDE_INSUFFICIENT_TEAM_GAMES",
                "team_game_counts": {home: hn, away: an},
                "research_only": True, "play_authority": False}
    conversion = get("NBA", "elo_per_point")
    margin = (hr - ar) / conversion + HCA_POINTS
    # Add HCA as declared Elo-equivalent to the raw logistic, not a fit.
    home_win = expected_score(hr + HCA_POINTS * conversion, ar, "NBA")
    if not isfinite(margin) or not 0 < home_win < 1:
        raise ValueError("NBA_SIDE_PROJECTION_NONFINITE")
    return {"engine_id": ENGINE, "status": "RESEARCH_PROJECTION",
            "home": home, "away": away, "projected_home_margin": margin,
            "raw_home_win_probability": home_win,
            "raw_away_win_probability": 1.0 - home_win,
            "team_game_counts": {home: hn, away: an},
            "history_games": len(prior), "future_excluded": excluded,
            "as_of_utc": asof.isoformat(),
            "parameter_source": "sportsedge.ratings.params.NBA",
            "price_or_market_used_in_prediction": False,
            "model_screen": "NOT_RUN", "calibration": "NOT_VALIDATED",
            "research_only": True, "play_authority": False}
