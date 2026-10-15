"""Research-only, point-in-time (PIT) rolling binary-outcome baselines.

Historical results enter player/market history only after publication and
observation. URL and time checks do not establish source authenticity.
No pricing, odds, capture, or PLAY path exists here.
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
from heapq import heappop, heappush
from math import isfinite, log
from urllib.parse import urlsplit


def _time(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIME") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NAIVE_TIME")
    return parsed.astimezone(timezone.utc)


def _source(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_SOURCE")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("INVALID_SOURCE")


def _loss(probability, outcome):
    p = min(1 - 1e-12, max(1e-12, probability))
    return -(outcome * log(p) + (1 - outcome) * log(1 - p))


def evaluate(events, *, train_cutoff, league_rate, window=20, strength=20.0):
    """Evaluate league, trailing and shrinkage against PIT-eligible outcomes.

    Rows require event_id, player_id, market_key, outcome, event_time,
    prediction_source_url, prediction_published_at, prediction_observed_at,
    outcome_source_url, outcome_published_at, outcome_observed_at,
    lineup_status='CONFIRMED', event_status='FINAL'. Rows are sorted by
    prediction_observed_at; ties allowed. Past outcomes become usable strictly
    after their observed time. Hyperparameters must be frozen externally.
    For multi-market datasets league_rate MUST map market_key to frozen priors;
    a scalar prior is allowed only for a single market family. Event identity
    is (event_id, player_id, market_key), not the game ID alone.
    """
    if not isinstance(events, list) or not events:
        raise ValueError("EMPTY_EVENTS")
    if type(window) is not int or window < 1:
        raise ValueError("INVALID_WINDOW")
    if isinstance(league_rate, dict):
        if not league_rate or any(not isinstance(k, str) or not k or
                                  type(v) not in (int, float) or not isfinite(v) or
                                  not 0 < v < 1 for k, v in league_rate.items()):
            raise ValueError("INVALID_LEAGUE_RATE")
    elif type(league_rate) not in (int, float) or not isfinite(league_rate) or not 0 < league_rate < 1:
        raise ValueError("INVALID_LEAGUE_RATE")
    if type(strength) not in (int, float) or not isfinite(strength) or strength <= 0:
        raise ValueError("INVALID_STRENGTH")
    cutoff = _time(train_cutoff)
    parsed_rows = []
    last_prediction = cutoff
    ids = set()
    first_market = None
    for row in events:
        if not isinstance(row, dict):
            raise ValueError("INVALID_ROW")
        event_id, player, market = row.get("event_id"), row.get("player_id"), row.get("market_key")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("DUPLICATE_OR_INVALID_EVENT_ID")
        if not isinstance(player, (str, int)) or isinstance(player, bool) or not str(player):
            raise ValueError("INVALID_PLAYER")
        if not isinstance(market, str) or not market:
            raise ValueError("INVALID_MARKET")
        identity = (event_id, str(player), market)
        if identity in ids:
            raise ValueError("DUPLICATE_OR_INVALID_EVENT_ID")
        ids.add(identity)
        if first_market is None:
            first_market = market
        if isinstance(league_rate, dict):
            if market not in league_rate:
                raise ValueError("MISSING_MARKET_PRIOR")
            prior = league_rate[market]
        else:
            if market != first_market:
                raise ValueError("MARKET_PRIOR_MAPPING_REQUIRED")
            prior = league_rate
        y = row.get("outcome")
        if type(y) is not int or y not in (0, 1):
            raise ValueError("INVALID_OUTCOME")
        if row.get("lineup_status") != "CONFIRMED" or row.get("event_status") != "FINAL":
            raise ValueError("UNCONFIRMED_LINEUP_OR_EVENT")
        _source(row.get("prediction_source_url"))
        _source(row.get("outcome_source_url"))
        event = _time(row.get("event_time"))
        pred_pub = _time(row.get("prediction_published_at"))
        pred_obs = _time(row.get("prediction_observed_at"))
        out_pub = _time(row.get("outcome_published_at"))
        out_obs = _time(row.get("outcome_observed_at"))
        if not (pred_pub <= pred_obs < event <= out_pub <= out_obs):
            raise ValueError("INVALID_EVIDENCE_CHRONOLOGY")
        if pred_obs <= cutoff or pred_obs < last_prediction:
            raise ValueError("TRAIN_OVERLAP_OR_UNSORTED_PREDICTIONS")
        last_prediction = pred_obs
        parsed_rows.append((pred_obs, out_obs, (player, market), y, prior))

    history = defaultdict(lambda: deque(maxlen=window))
    pending = []
    scores = {"league": 0.0, "trailing": 0.0, "shrinkage": 0.0}
    brier = {"league": 0.0, "trailing": 0.0, "shrinkage": 0.0}
    for seq, (prediction_at, outcome_at, key, y, prior) in enumerate(parsed_rows):
        while pending and pending[0][0] < prediction_at:
            _, _, old_key, old_y = heappop(pending)
            history[old_key].append(old_y)
        past = history[key]
        count = len(past)
        rates = {
            "league": prior,
            "trailing": sum(past) / count if count else prior,
            "shrinkage": (sum(past) + strength * prior) / (count + strength),
        }
        for name, p in rates.items():
            scores[name] += _loss(p, y)
            brier[name] += (p - y) ** 2
        heappush(pending, (outcome_at, seq, key, y))
    n = len(parsed_rows)
    return {
        "n": n,
        "mean_log_loss": {k: v / n for k, v in scores.items()},
        "mean_brier": {k: v / n for k, v in brier.items()},
        "shrinkage_beats_both": scores["shrinkage"] < min(scores["league"], scores["trailing"]),
        "source_authenticity_verified": False,
        "prior_provenance_verified": False,
        "market_probability_verified": False,
        "play_authorized": False,
        "research_only": True,
    }
