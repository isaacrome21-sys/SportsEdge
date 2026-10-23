"""Research-only paired chronological probability evaluation. No pricing or PLAY."""
from datetime import datetime, timezone
from math import isfinite, log

def paired_evaluate(rows, *, train_cutoff):
    """Rows: event_time, outcome, challenger, league, trailing; ordered, post-cutoff.

    Predictions must be generated before each event using pre-event data.
    This function validates supplied records but cannot prove provenance.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_ROWS")
    def timestamp(s):
        if not isinstance(s, str):
            raise ValueError("INVALID_TIME")
        try:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("INVALID_TIME") from exc
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("NAIVE_TIME")
        return t.astimezone(timezone.utc)
    cutoff = timestamp(train_cutoff)
    last = cutoff
    losses = dict(challenger=0., league=0., trailing=0.)
    brier = dict(challenger=0., league=0., trailing=0.)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_ROW")
        t = timestamp(row.get("event_time"))
        if t <= last:
            raise ValueError("NON_CHRONOLOGICAL_OR_TRAIN_OVERLAP")
        last = t
        y = row.get("outcome")
        if type(y) is not int or y not in (0, 1):
            raise ValueError("INVALID_OUTCOME")
        for key in losses:
            p = row.get(key)
            if type(p) not in (int, float) or not isfinite(p) or not 0 <= p <= 1:
                raise ValueError("MISSING_OR_INVALID_PREDICTION")
            q = min(1 - 1e-12, max(1e-12, p))
            losses[key] -= y * log(q) + (1-y) * log(1-q)
            brier[key] += (p-y)**2
    n = len(rows)
    return {"n": n, "mean_log_loss": {k:v/n for k,v in losses.items()},
            "mean_brier": {k:v/n for k,v in brier.items()},
            "beats_both_log_loss": losses["challenger"] < min(losses["league"], losses["trailing"]),
            "provenance_verified": False, "market_probability_verified": False,
            "play_authorized": False, "research_only": True}
