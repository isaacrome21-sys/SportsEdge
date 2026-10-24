"""Point-in-time, opponent-adjusted CFB scoring challenger. SCREEN only.

Each historical result contributes two equations:
  home score = base + HFA/2 + home attack - away defense
  away score = base - HFA/2 + away attack - home defense
Weighted ridge solves attack and defense separately against opponents.
Market lines never enter fit. QB, talent and efficiency evidence is
tracked but NEVER assigned unfitted point weights or PLAY authority.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import exp, log, erf, sqrt, isfinite
from typing import Mapping

SCHEMA = "SPORTSEDGE_CFB_OPPONENT_RIDGE_SCREEN_V1"
FACTOR_GROUPS = frozenset(
    "qb talent_depth success_rate epa_per_play offensive_efficiency defensive_efficiency "
    "yards_per_play explosive_play_rate havoc offensive_line defensive_front secondary "
    "pace scheme_fit special_teams field_position recent_form home_venue rest_travel "
    "weather injury_availability coaching red_zone third_down turnover_risk motivation "
    "officials market_context skill_positions"
    .split()
)

def utc(value):
    if isinstance(value, datetime):
        t = value
    else:
        try:
            t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError("CFB_TIME_INVALID") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("CFB_TIME_MUST_BE_AWARE")
    return t.astimezone(timezone.utc)

def name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CFB_TEAM_MISSING")
    return value.strip().casefold()

def factors_before_kickoff(factors, *, as_of):
    """Audit dated source assertions; NEVER authenticate them or score points."""
    accepted, refused = [], []
    for i, row in enumerate(factors):
        if not isinstance(row, Mapping):
            refused.append({"index": i, "reason": "NOT_OBJECT"})
            continue
        group, source, metric = row.get("group"), row.get("source_url"), row.get("name")
        if (group not in FACTOR_GROUPS or not isinstance(source, str)
                or not source.startswith("https://") or not isinstance(metric, str)
                or not metric.strip() or row.get("value") is None
                or isinstance(row["value"], bool)):
            refused.append({"index": i, "reason": "SOURCE_OR_VALUE_MISSING"})
            continue
        try:
            seen = utc(row.get("observed_at_utc"))
        except ValueError:
            refused.append({"index": i, "reason": "TIME_INVALID"})
            continue
        if seen >= as_of:
            refused.append({"index": i, "reason": "NOT_OBSERVED_PREGAME"})
            continue
        value = row["value"]
        if type(value) not in (str, int, float) or (type(value) in (int, float) and not isfinite(value)):
            refused.append({"index": i, "reason": "VALUE_INVALID"})
            continue
        accepted.append({
            "group": group, "name": metric.strip(), "value": value,
            "source_url": source, "observed_at_utc": seen.isoformat(),
            "usage": "COMPARISON_ONLY" if group == "market_context" else "CONTEXT_UNFITTED",
            "receipt_authenticated": False,
        })
    return {"accepted": accepted, "refused": refused,
            "point_adjustment": 0.0, "promotion_authority": False}

def fit(games, *, as_of, season, hfa=4.31, ridge=1.5,
        half_life_days=90.0, prior_weight=0.35, iterations=150):
    """Fit from observed finals only; no market data or current-game outcome."""
    now = utc(as_of)
    if (type(season) is not int or not isfinite(hfa) or not 0 <= hfa <= 12
            or not isfinite(ridge) or ridge <= 0
            or not isfinite(half_life_days) or half_life_days <= 0
            or not 0 <= prior_weight <= 1):
        raise ValueError("CFB_FIT_CONFIG_INVALID")
    previous = []
    seen_ids = set()
    for row in games:
        start, finished = utc(row.get("kickoff_utc")), utc(row.get("result_observed_at_utc"))
        yr = row.get("season")
        if type(yr) is not int:
            raise ValueError("CFB_SEASON_INVALID")
        if start >= finished or finished >= now or yr not in (season, season - 1):
            continue
        gid = str(row.get("game_id") or "").strip()
        if not gid or gid in seen_ids:
            raise ValueError("CFB_DUPLICATE_GAME")
        seen_ids.add(gid)
        h, a = name(row.get("home")), name(row.get("away"))
        if h == a:
            raise ValueError("CFB_IDENTICAL_TEAMS")
        hp, ap = row.get("home_points"), row.get("away_points")
        if any(type(v) not in (int, float) or not isfinite(v) or not 0 <= v <= 150
               for v in (hp, ap)) or type(row.get("neutral_site")) is not bool:
            raise ValueError("CFB_FINAL_OR_VENUE_INVALID")
        age = (now - finished).total_seconds() / 86400
        # Previous-season games decay on a bounded offseason clock; the
        # prior_weight is a separate, explicit roster-turnover discount.
        age = min(age, half_life_days) if yr < season else age
        w = exp(-log(2) * age / half_life_days) * (prior_weight if yr < season else 1)
        if w > 1e-9:
            previous.append((h, a, float(hp), float(ap), row["neutral_site"], w, finished))
    if not previous:
        raise ValueError("CFB_NO_PREGAME_FINALS")
    teams = sorted({g[0] for g in previous} | {g[1] for g in previous})
    ids = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    weight_sum = sum(g[5] for g in previous)
    base = sum((g[2] + g[3]) * g[5] for g in previous) / (2 * weight_sum)
    # Sparse coordinate-descent ridge: +attack and -defense per point row.
    incidence = [[] for _ in range(2 * n)]
    residual, weight = [], []
    for h, a, hp, ap, neutral, w, _ in previous:
        half = 0.0 if neutral else hfa / 2
        for off, defense, points, expected in (
            (h, a, hp, base + half), (a, h, ap, base - half)
        ):
            k = len(residual)
            residual.append(points - expected)
            weight.append(w)
            incidence[ids[off]].append((k, 1))
            incidence[n + ids[defense]].append((k, -1))
    coefficients = [0.0] * (2 * n)
    used_iterations = 0
    for iteration in range(iterations):
        largest = 0.0
        for j, edges in enumerate(incidence):
            if not edges:
                continue
            old = coefficients[j]
            numerator = sum(weight[k] * sign * (residual[k] + sign * old)
                            for k, sign in edges)
            new = numerator / (ridge + sum(weight[k] for k, _ in edges))
            change = new - old
            coefficients[j] = new
            for k, sign in edges:
                residual[k] -= sign * change
            largest = max(largest, abs(change))
        used_iterations = iteration + 1
        if largest < 1e-8:
            break
    counts = {team: 0 for team in teams}
    for h, a, *_ in previous:
        counts[h] += 1
        counts[a] += 1
    return {
        "schema": SCHEMA, "status": "SCREEN_NOT_VALIDATED",
        "as_of_utc": now.isoformat(), "trained_games": len(previous),
        "last_result_observed_at_utc": max(g[6] for g in previous).isoformat(),
        "baseline_points_per_team": round(base, 6), "home_advantage": hfa,
        "iterations": used_iterations,
        "ratings": {team: {"attack": round(coefficients[i], 6),
                            "defense": round(coefficients[n + i], 6),
                            "games": counts[team]}
                    for i, team in enumerate(teams)},
        "market_data_used": False, "play_authority": False, "promotion_authority": False,
    }

def predict(fitted, *, home, away, neutral_site=False, factors=()):
    if fitted.get("schema") != SCHEMA or fitted.get("market_data_used") is not False:
        raise ValueError("CFB_FIT_SOURCE_INVALID")
    h, a = name(home), name(away)
    if h == a or type(neutral_site) is not bool:
        raise ValueError("CFB_FIXTURE_INVALID")
    ratings = fitted["ratings"]
    hr, ar = ratings.get(h, {}), ratings.get(a, {})
    hf = 0.0 if neutral_site else fitted["home_advantage"] / 2
    base = fitted["baseline_points_per_team"]
    hp = max(0.0, base + hf + hr.get("attack", 0) - ar.get("defense", 0))
    ap = max(0.0, base - hf + ar.get("attack", 0) - hr.get("defense", 0))
    return {
        "schema": SCHEMA, "status": "SCREEN_NOT_VALIDATED",
        "home": home, "away": away, "margin_home": round(hp - ap, 5),
        "total": round(hp + ap, 5), "home_points": round(hp, 5),
        "away_points": round(ap, 5),
        "home_games": hr.get("games", 0), "away_games": ar.get("games", 0),
        "missing_team_history": not bool(hr) or not bool(ar),
        "factors": factors_before_kickoff(factors, as_of=utc(fitted["as_of_utc"])),
        "factor_weights_fitted": False, "market_data_used": False,
        "play_authority": False, "promotion_authority": False,
    }

def reference_probabilities(prediction, *, home_spread, total_line,
                            sd_margin=16.46, sd_total=16.34):
    """Push-aware SCREEN vs retrospective market numbers; not executable odds."""
    vals = (home_spread, total_line, sd_margin, sd_total)
    if prediction.get("schema") != SCHEMA or any(
        type(v) not in (int, float) or not isfinite(v) for v in vals
    ) or sd_margin <= 0 or sd_total <= 0:
        raise ValueError("CFB_REFERENCE_INVALID")
    def cdf(x, mu, sd):
        return (1 + erf((x - mu) / (sd * sqrt(2)))) / 2
    def tail(mu, threshold, sd):
        if threshold == round(threshold):
            low = cdf(threshold - 0.5, mu, sd)
            high = cdf(threshold + 0.5, mu, sd)
            push, above = high - low, 1 - high
        else:
            push, above = 0.0, 1 - cdf(threshold, mu, sd)
        return {"above": above, "push": push, "below": 1 - above - push}
    return {"schema": SCHEMA, "status": "SCREEN_NOT_VALIDATED",
            "spread_home": tail(prediction["margin_home"], -home_spread, sd_margin),
            "total_over": tail(prediction["total"], total_line, sd_total),
            "research_reference_only": True, "executable_quote": False,
            "play_authority": False, "promotion_authority": False}
