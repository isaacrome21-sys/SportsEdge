"""Research-only chronological trailing-rate baseline, no pricing."""
from collections import defaultdict, deque
from math import log

def evaluate(rows, *, window=20, prior=.5):
    if type(window) is not int or window < 1 or not isinstance(prior, (int,float)) or not 0 < prior < 1:
        raise ValueError("INVALID_CONFIG")
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_ROWS")
    history = defaultdict(lambda: deque(maxlen=window))
    previous = None
    league_loss = trailing_loss = 0.
    from datetime import datetime
    for stamp, player, outcome in rows:
        if type(outcome) is not int or outcome not in (0,1) or not isinstance(player,(str,int)) or isinstance(player,bool):
            raise ValueError("INVALID_ROW")
        dt = datetime.fromisoformat(stamp.replace("Z","+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None or (previous is not None and dt <= previous):
            raise ValueError("NON_CHRONOLOGICAL")
        previous = dt
        past = history[player]
        p = sum(past)/len(past) if past else prior
        p = min(1-1e-12,max(1e-12,p))
        trailing_loss -= outcome*log(p)+(1-outcome)*log(1-p)
        league_loss -= outcome*log(prior)+(1-outcome)*log(1-prior)
        past.append(outcome)
    return {"n":len(rows),"trailing_log_loss":trailing_loss/len(rows),
            "league_log_loss":league_loss/len(rows),
            "beats_league":trailing_loss<league_loss,
            "research_only":True,"market_probability_verified":False,"play_authorized":False}
