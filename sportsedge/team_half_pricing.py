"""Team totals and first-half markets from the same verified free_models means.

Uses the existing PublicContext + independent home/away score means already
computed for game ML/spread/total. No new league priors. Research only.
First-half is a declared 0.50 scale of the full-game mean with inflated
variance; it is not a fitted half model.
"""
from __future__ import annotations

from math import erf, sqrt
from typing import Any, Mapping

from artifacts.free_models import (
    PRIORS, model_probability, PublicContext, numeric, bounded, dt, odds_decimal,
)


def _cdf(x, mean, sd):
    return (1 + erf((x - mean) / (sd * sqrt(2)))) / 2


def price_team_or_half(
    row: Mapping[str, Any],
    *,
    now,
    getter=None,
) -> dict[str, Any]:
    """Price TEAM_TOTAL, TEAM_TOTAL_1H, TOTAL_1H, SPREAD_1H, ML_1H from free context."""
    sport = str(row.get("sport") or "").upper()
    market = str(row.get("market") or "").upper()
    side = str(row.get("side") or row.get("selection") or "").upper()
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    kickoff = dt(row.get("kickoff") or row.get("commence_time"))
    if sport not in PRIORS or not away or not home or kickoff is None:
        return {"status": "NO_MODEL_OR_MARKET", "reason": "IDENTITY_OR_SPORT_MISSING",
                "sport": sport, "market": market,
                "research_only": True}
    if kickoff <= now:
        return {"status": "BLOCKED_STARTED", "reason": "GAME_ALREADY_STARTED",
                "sport": sport, "market": market,
                "research_only": True}

    ctx = PublicContext(now, getter=getter)
    fixture = ctx.fixture(sport, away, home, kickoff)
    if fixture is None:
        return {"status": "NO_MODEL_OR_MARKET",
                "reason": "FREE_CONTEXT_FIXTURE_NOT_VERIFIED",
                "sport": sport, "market": market,
                "research_only": True}

    # Reuse the same mean construction as free_models.calculate (simplified).
    home_team = ctx.identify(sport, home)
    away_team = ctx.identify(sport, away)
    if not home_team or not away_team:
        return {"status": "NO_MODEL_OR_MARKET", "reason": "TEAM_IDENTITY_UNMATCHED",
                "sport": sport, "market": market,
                "research_only": True}

    base, _, _, hfa = PRIORS[sport]
    # Minimal context: prior-five margin proxy if available.
    home_hist = ctx.schedule(sport, home_team, kickoff)
    away_hist = ctx.schedule(sport, away_team, kickoff)
    def margin_proxy(hist):
        if len(hist) < 3:
            return 0.0
        diffs = [own - opp for _, own, opp in hist]
        return max(-4.0, min(4.0, sum(diffs) / len(diffs) * 0.15))
    home_rating = margin_proxy(home_hist)
    away_rating = margin_proxy(away_hist)
    home_mean = base + hfa / 2 + home_rating
    away_mean = base - hfa / 2 + away_rating
    if min(home_mean, away_mean) < 0.2:
        return {"status": "NO_MODEL_OR_MARKET", "reason": "IMPLAUSIBLE_SCORE_MEAN",
                "sport": sport, "market": market,
                "research_only": True}

    line = row.get("line")
    try:
        line_f = float(line) if line is not None else None
    except (TypeError, ValueError):
        return {"status": "NO_MODEL_OR_MARKET", "reason": "LINE_UNVERIFIED",
                "sport": sport, "market": market,
                "research_only": True}

    # Map to underlying model_probability call.
    if market in {"TEAM_TOTAL", "TEAM_TOTAL_POINTS"}:
        team = str(row.get("team") or "").upper()
        if team in {"HOME", home.upper()}:
            mean = home_mean
        elif team in {"AWAY", away.upper()}:
            mean = away_mean
        else:
            return {"status": "NO_MODEL_OR_MARKET", "reason": "TEAM_TOTAL_TEAM_UNRESOLVED",
                    "sport": sport, "market": market,
                "research_only": True}
        # Approximate team total as normal with sd from league total / sqrt(2).
        _, sd_total, _, _ = PRIORS[sport]
        sd = (sd_total or 12.0) / 1.4
        whole = line_f is not None and float(line_f).is_integer()
        push = _cdf(line_f + 0.5, mean, sd) - _cdf(line_f - 0.5, mean, sd) if whole else 0.0
        cut = line_f + (0.5 if whole else 0)
        win = (1 - _cdf(cut, mean, sd)) if side == "OVER" else _cdf(line_f - (0.5 if whole else 0), mean, sd)
        model_p, push_p = bounded(win, 0, 1), bounded(push, 0, 1)
    elif market in {"TOTAL_1H", "FIRST_HALF_TOTAL"}:
        # Declared half scale; not fitted.
        half_home, half_away = home_mean * 0.50, away_mean * 0.50
        model_p, push_p = model_probability(
            sport, "TOTAL", side, line_f, half_home, half_away)
    elif market in {"SPREAD_1H", "FIRST_HALF_SPREAD"}:
        half_home, half_away = home_mean * 0.50, away_mean * 0.50
        model_p, push_p = model_probability(
            sport, "SPREAD", side, line_f, half_home, half_away)
    elif market in {"ML_1H", "FIRST_HALF_ML"}:
        half_home, half_away = home_mean * 0.50, away_mean * 0.50
        model_p, push_p = model_probability(
            sport, "ML", side, None, half_home, half_away)
    else:
        return {"status": "NO_MODEL_OR_MARKET", "reason": "UNSUPPORTED_TEAM_HALF_MARKET",
                "sport": sport, "market": market,
                "research_only": True}

    try:
        dec = odds_decimal(row.get("odds") or row.get("price"))
    except ValueError:
        dec = None
    loss = bounded(1 - model_p - push_p, 0, 1)
    ev = (model_p * (dec - 1) - loss) if dec else None
    return {
        "status": "PRICED_RESEARCH",
        "sport": sport, "market": market, "selection": side,
        "estimate_p": model_p, "push_p": push_p,
        "ev_per_dollar": ev,
        "model_source": "free_models_means_team_half_v1",
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "home_mean": round(home_mean, 3), "away_mean": round(away_mean, 3),
    }
