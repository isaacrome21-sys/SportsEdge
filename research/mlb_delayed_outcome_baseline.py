"""Research-only MLB PIT baseline evaluation; synthetic-safe, no pricing or capture.

A forecast can learn from an earlier result only after that result's recorded
observation time strictly before forecast. Equal-time forecasts share history.
Caller-provided timestamps are checked structurally, not authenticated.
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
from heapq import heappush, heappop
from math import isfinite, log


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def evaluate(rows, *, training_cutoff, priors, window=20, pseudo_count=20):
    """Evaluate league, trailing-player, and Beta-shrunk rates on PIT rows.

    Each row: event_id, subject_id, market, forecast_at, event_time,
    outcome_observed_at, outcome (0 or 1). Forecasts must be in nondecreasing
    forecast_at order; no external data is fetched and no outcomes backfilled.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_ROWS")
    if type(window) is not int or window < 1 or type(pseudo_count) not in (int, float) or not isfinite(pseudo_count) or pseudo_count <= 0:
        raise ValueError("INVALID_CONFIG")
    if not isinstance(priors, dict) or not priors or any(
        not isinstance(m, str) or not m or type(p) not in (int, float)
        or not isfinite(p) or not 0 < p < 1 for m, p in priors.items()
    ):
        raise ValueError("INVALID_PRIORS")
    cutoff = _utc(training_cutoff)
    validated = []
    previous_forecast = cutoff
    seen = set()
    event_times = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_ROW")
        event_id, subject, market, outcome = (row.get(k) for k in ("event_id", "subject_id", "market", "outcome"))
        if (not isinstance(event_id, str) or not event_id or not isinstance(subject, str)
            or not subject or not isinstance(market, str) or market not in priors
            or type(outcome) is not int or outcome not in (0, 1)):
            raise ValueError("INVALID_ROW")
        key = (event_id, subject, market)
        if key in seen:
            raise ValueError("DUPLICATE_ROW")
        seen.add(key)
        forecast = _utc(row.get("forecast_at"))
        event = _utc(row.get("event_time"))
        observed = _utc(row.get("outcome_observed_at"))
        if not (cutoff <= forecast < event <= observed):
            raise ValueError("INVALID_PIT_ORDER")
        if event_id in event_times and event_times[event_id] != event:
            raise ValueError("CONFLICTING_EVENT_TIME")
        event_times[event_id] = event
        if forecast < previous_forecast:
            raise ValueError("NON_CHRONOLOGICAL_FORECAST")
        previous_forecast = forecast
        validated.append((forecast, event, observed, event_id, subject, market, outcome))

    history = defaultdict(lambda: deque(maxlen=window))
    pending = []
    sums = {name: {market: [0.0, 0.0, 0] for market in priors}
            for name in ("league", "trailing", "shrinkage")}
    predictions = []
    i = 0
    while i < len(validated):
        forecast = validated[i][0]
        # Strictly earlier observed outcomes only. Equality is not evidence
        # of pre-forecast availability.
        while pending and pending[0][0] < forecast:
            _, _, subject, market, outcome = heappop(pending)
            history[(subject, market)].append(outcome)
        j = i
        while j < len(validated) and validated[j][0] == forecast:
            _, event, observed, event_id, subject, market, outcome = validated[j]
            prior = priors[market]
            past = history[(subject, market)]
            league = prior
            trailing = sum(past) / len(past) if past else prior
            shrinkage = (sum(past) + pseudo_count * prior) / (len(past) + pseudo_count)
            for name, p in (("league", league), ("trailing", trailing), ("shrinkage", shrinkage)):
                clipped = min(1 - 1e-12, max(1e-12, p))
                score = sums[name][market]
                score[0] -= outcome * log(clipped) + (1 - outcome) * log(1 - clipped)
                score[1] += (p - outcome) ** 2
                score[2] += 1
            predictions.append({"event_id": event_id, "subject_id": subject, "market": market,
                                "forecast_at": forecast.isoformat(), "history_n": len(past),
                                "league": league, "trailing": trailing, "shrinkage": shrinkage})
            j += 1
        for k in range(i, j):
            _, _, observed, event_id, subject, market, outcome = validated[k]
            heappush(pending, (observed, event_id, subject, market, outcome))
        i = j
    metrics = {name: {market: {"n": v[2], "mean_log_loss": v[0] / v[2], "mean_brier": v[1] / v[2]}
                      for market, v in scores.items() if v[2]}
               for name, scores in sums.items()}
    return {"n": len(validated), "metrics": metrics, "predictions": predictions,
            "provenance_verified": False, "market_probability_verified": False,
            "play_authorized": False, "research_only": True}
