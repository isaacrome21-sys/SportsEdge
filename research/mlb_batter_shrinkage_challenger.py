"""Research-only beta-binomial shrinkage challenger for binary batter outcomes.

No market pricing, no PLAY eligibility, no holdout or capture activation.
"""
from math import isfinite, log


def shrink_probability(hits: int, opportunities: int, prior_rate: float, strength: float) -> float:
    """Posterior mean with fixed, pre-trained prior and pseudocount strength."""
    if type(hits) is not int or type(opportunities) is not int:
        raise ValueError("INVALID_COUNTS")
    if opportunities < 0 or hits < 0 or hits > opportunities:
        raise ValueError("INVALID_COUNTS")
    if not isinstance(prior_rate, (int, float)) or not isfinite(prior_rate) or not 0 < prior_rate < 1:
        raise ValueError("INVALID_PRIOR")
    if not isinstance(strength, (int, float)) or not isfinite(strength) or strength <= 0:
        raise ValueError("INVALID_STRENGTH")
    return (hits + strength * prior_rate) / (opportunities + strength)


def log_loss(probability: float, outcome: int) -> float:
    if type(outcome) is not int or outcome not in (0, 1):
        raise ValueError("INVALID_OUTCOME")
    if not isinstance(probability, (int, float)) or not isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("INVALID_PROBABILITY")
    p = min(1 - 1e-12, max(1e-12, probability))
    return -(outcome * log(p) + (1 - outcome) * log(1 - p))


def chronological_compare(records, *, prior_rate, strength):
    """Evaluate strictly ordered rows, using only prior rows for each prediction.

    Each row is (event_time_iso, player_id, outcome). Prior rate and strength
    must be fixed before the evaluated period. Ties are refused to prevent
    accidental same-timestamp leakage.
    """
    if not isinstance(records, list) or not records:
        raise ValueError("EMPTY_RECORDS")
    from datetime import datetime
    history = {}
    previous = None
    totals = {"challenger": 0.0, "league": 0.0}
    for stamp, player, outcome in records:
        if not isinstance(stamp, str) or not isinstance(player, (str, int)) or isinstance(player, bool):
            raise ValueError("INVALID_ROW")
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("INVALID_TIME") from exc
        if dt.tzinfo is None or dt.utcoffset() is None or (previous is not None and dt <= previous):
            raise ValueError("NON_CHRONOLOGICAL")
        previous = dt
        wins, n = history.get(player, (0, 0))
        p = shrink_probability(wins, n, prior_rate, strength)
        totals["challenger"] += log_loss(p, outcome)
        totals["league"] += log_loss(prior_rate, outcome)
        history[player] = (wins + outcome, n + 1)
    return {"n": len(records), "challenger_log_loss": totals["challenger"] / len(records),
            "league_log_loss": totals["league"] / len(records),
            "beats_league": totals["challenger"] < totals["league"],
            "market_probability_verified": False, "play_authorized": False,
            "research_only": True}
