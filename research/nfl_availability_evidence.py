"""NFL research-only availability evidence validation. Never assumes healthy."""
from datetime import datetime, timezone

def assess(rows, *, game_id, player_id, cutoff):
    def parse(s):
        if not isinstance(s,str):
            raise ValueError("INVALID_TIME")
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("NAIVE_TIME")
        return dt.astimezone(timezone.utc)
    deadline=parse(cutoff)
    if not isinstance(rows,list) or not game_id or not player_id:
        raise ValueError("INVALID_INPUT")
    valid=[]
    rejected=[]
    for i,row in enumerate(rows):
        if not isinstance(row,dict) or row.get("game_id")!=game_id or row.get("player_id")!=player_id:
            rejected.append((i,"INVALID_IDENTITY"))
            continue
        url=row.get("source_url")
        kind=row.get("source_kind")
        state=row.get("availability")
        if not isinstance(url,str) or not url.startswith("https://") or kind not in ("OFFICIAL","VERIFIED_REPORTER","X_UNVERIFIED") or state not in ("ACTIVE","OUT","QUESTIONABLE"):
            rejected.append((i,"INVALID_SOURCE"))
            continue
        try:
            pub=parse(row.get("published_at"))
            obs=parse(row.get("observed_at"))
        except (ValueError,TypeError):
            rejected.append((i,"INVALID_TIME"))
            continue
        if pub>obs or obs>deadline:
            rejected.append((i,"TIME_CONFLICT_OR_AFTER_CUTOFF"))
            continue
        valid.append(row)
    official=[r["availability"] for r in valid if r["source_kind"]=="OFFICIAL"]
    if rejected or len(set(official))>1:
        status="BLOCKED_CONFLICT_OR_INVALID"
    elif official and official[0]=="OUT":
        status="OFFICIAL_OUT_UNAUTHENTICATED"
    elif official:
        status="PROVISIONAL_UNAUTHENTICATED"
    elif valid:
        status="UNCONFIRMED"
    else:
        status="UNKNOWN"
    return {"status":status,"accepted":len(valid),"rejected":rejected,
            "source_authenticity_verified":False,"availability_binding_eligible":False,
            "market_probability_verified":False,"play_authorized":False,"research_only":True}
