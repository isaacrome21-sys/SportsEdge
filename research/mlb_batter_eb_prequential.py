"""MLB batter binary milestone empirical-Bayes research evaluator (NO betting authority).

Only caller-supplied, contemporaneously observed historical outcomes are admitted.
No network/odds/holdout/capture access. This is a prequential backtest design,
not proof that supplied provenance or a model's predictions are validated.

Each outcome must be backed by a historical source observation time. A modern
box score cannot be retroactively assigned a pregame observation timestamp.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from heapq import heappop, heappush
from math import isfinite, log
import re
from urllib.parse import urlparse

_MARKET = re.compile(r"MLB_BATTER:(HITS|HR|TB|RBI|RUNS|WALKS|SINGLES|DOUBLES|TRIPLES|KS):GE:([1-9][0-9]?)\Z")
_MIN_MARKET_HISTORY = 40  # research warm-up, NOT a validation/promotion threshold
_MIN_SUBJECTS = 4
_EPS = 1e-12


def _time(s):
    if not isinstance(s, str):
        raise ValueError("TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)


def _source(s):
    if not isinstance(s, str) or len(s) > 2048:
        raise ValueError("SOURCE_URL_INVALID")
    try:
        u = urlparse(s)
        host = u.hostname or ""
        # Restrict this particular outcome-training adapter to official MLB
        # hosts; X rumors and generic search snippets cannot become results.
        if (u.scheme != "https" or not (host == "mlb.com" or host.endswith(".mlb.com"))
                or u.username is not None or u.password is not None
                or u.port not in (None, 443)):
            raise ValueError("SOURCE_URL_INVALID")
    except (ValueError, TypeError) as exc:
        raise ValueError("SOURCE_URL_INVALID") from exc
    return s


def _validate(rows, *, evaluation_start):
    if not isinstance(rows, list) or not rows:
        raise ValueError("ROWS_REQUIRED")
    validated, seen, event_times = [], set(), {}
    previous = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ROW_INVALID")
        event, subject, market = (row.get(k) for k in ("event_id", "subject_id", "market"))
        if not all(isinstance(x, str) and x.strip() for x in (event, subject, market)):
            raise ValueError("IDENTITY_INVALID")
        if not _MARKET.fullmatch(market):
            raise ValueError("BINARY_MILESTONE_MARKET_REQUIRED")
        if type(row.get("outcome")) is not int or row["outcome"] not in (0, 1):
            raise ValueError("BINARY_OUTCOME_REQUIRED")
        key = (event, subject, market)
        if key in seen:
            raise ValueError("DUPLICATE_OUTCOME")
        seen.add(key)
        forecast, start, observed = (_time(row.get(k)) for k in
                                     ("forecast_at", "event_time", "outcome_observed_at"))
        published, source_seen = (_time(row.get(k)) for k in
                                  ("source_published_at", "source_observed_at"))
        _source(row.get("source_url"))
        if not (forecast < start <= published <= source_seen <= observed):
            raise ValueError("PIT_SOURCE_ORDER_INVALID")
        if event in event_times and event_times[event] != start:
            raise ValueError("EVENT_START_CONFLICT")
        event_times[event] = start
        if previous is not None and forecast < previous:
            raise ValueError("FORECAST_ORDER_INVALID")
        previous = forecast
        validated.append((forecast, start, observed, event, subject, market, row["outcome"]))
    if not any(x[0] >= evaluation_start for x in validated):
        raise ValueError("NO_EVALUATION_ROWS")
    return validated


def _loss(p, y):
    p = min(1 - _EPS, max(_EPS, p))
    return -(y * log(p) + (1 - y) * log(1 - p))


def evaluate(rows, *, evaluation_start, prior_strength=20, window=20):
    """Compare online league, player trailing, and hierarchical Beta shrinkage.

    Pre-registered prior_strength and window must not be chosen on this
    evaluation fold. This module intentionally has no auto-tuning/GO function.
    Prior is a leave-player-out league rate, computed only from observed prior
    events, with Jeffreys Beta(0.5,0.5) for finite cold starts. Model updates
    after evaluation games are allowed only once the outcome is observed.
    """
    if (type(prior_strength) not in (int, float) or not isfinite(prior_strength)
            or prior_strength <= 0 or type(window) is not int or window < 1):
        raise ValueError("HYPERPARAMETER_INVALID")
    boundary = _time(evaluation_start)
    records = _validate(rows, evaluation_start=boundary)
    pending = []
    market_count = defaultdict(int)
    market_wins = defaultdict(int)
    player_count = defaultdict(int)
    player_wins = defaultdict(int)
    player_recent = defaultdict(lambda: deque(maxlen=window))
    subjects = defaultdict(set)
    forecasts = []
    blocked = defaultdict(int)
    i = 0
    while i < len(records):
        t = records[i][0]
        while pending and pending[0][0] < t:
            _, _, _, subject, market, outcome = heappop(pending)
            market_count[market] += 1
            market_wins[market] += outcome
            player_count[(subject, market)] += 1
            player_wins[(subject, market)] += outcome
            player_recent[(subject, market)].append(outcome)
            subjects[market].add(subject)
        j = i
        while j < len(records) and records[j][0] == t:
            _, start, observed, event, subject, market, outcome = records[j]
            if t >= boundary:
                n = market_count[market]
                # Require real historical market coverage, not an arbitrary
                # prior-only 0.5 masquerading as a player projection.
                if n < _MIN_MARKET_HISTORY or len(subjects[market]) < _MIN_SUBJECTS:
                    blocked["INSUFFICIENT_PRIOR_MARKET_HISTORY"] += 1
                else:
                    player_key = (subject, market)
                    n_player = player_count[player_key]
                    # Exclude this player's history from the league anchor;
                    # if all prior records are this player, refuse.
                    other_n = n - n_player
                    if other_n < 1:
                        blocked["NO_LEAVE_PLAYER_OUT_PRIOR"] += 1
                    else:
                        anchor = (market_wins[market] - player_wins[player_key] + 0.5) / (other_n + 1)
                        recent = player_recent[player_key]
                        trailing = sum(recent) / len(recent) if recent else anchor
                        shrunk = (sum(recent) + prior_strength * anchor) / (len(recent) + prior_strength)
                        # All three are compared on identical, strictly
                        # pre-event observations, with no price anchoring.
                        forecasts.append({
                            "event_id": event, "subject_id": subject, "market": market,
                            "forecast_at": t.isoformat(), "outcome": outcome,
                            "history_market_n": n, "history_player_n": n_player,
                            "history_player_recent_n": len(recent),
                            "league": anchor, "trailing": trailing,
                            "shrinkage": shrunk,
                        })
            j += 1
        # No same-time or same-event results can influence another forecast.
        for k in range(i, j):
            _, start, observed, event, subject, market, outcome = records[k]
            heappush(pending, (observed, start, event, subject, market, outcome))
        i = j
    scores = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))
    for pred in forecasts:
        market, y = pred["market"], pred["outcome"]
        for name in ("league", "trailing", "shrinkage"):
            p = pred[name]
            scores[market][name][0] += _loss(p, y)
            scores[market][name][1] += (p - y) ** 2
            scores[market][name][2] += 1
    metrics = {m: {name: {"n": v[2], "log_loss": v[0] / v[2], "brier": v[1] / v[2]}
                   for name, v in methods.items()}
               for m, methods in scores.items()}
    for m, methods in metrics.items():
        for name in ("trailing", "shrinkage"):
            methods[name]["delta_log_loss_vs_league"] = (
                methods[name]["log_loss"] - methods["league"]["log_loss"])
    return {
        "schema": "MLB_BATTER_BINARY_EB_PREQUENTIAL_RESEARCH_V1",
        "evaluation_start": boundary.isoformat(),
        "hyperparameters_predeclared_by_caller_not_independently_verified": True,
        "metrics": metrics, "predictions": forecasts,
        "blocked": dict(blocked), "n_evaluated": len(forecasts),
        "source_provenance_authenticated": False,
        "independent_validation_completed": False,
        "market_probability_verified": False,
        "eligible_as_bet": False, "picks": [], "research_only": True,
    }
