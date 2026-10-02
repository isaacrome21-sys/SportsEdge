"""Attach realized labels only after outcome-blind CFB predictive inputs exist."""
from __future__ import annotations
from typing import Any, Mapping, Sequence

class SDVTrainingRowError(ValueError): pass

def attach_training_labels(*, predictive_rows:Sequence[Mapping[str,Any]], completed_games:Sequence[Mapping[str,Any]]) -> list[dict[str,Any]]:
    labels={}
    for game in completed_games:
        try:
            season=int(game["season"]); week=int(game["week"]); gid=str(game["game_id"])
            home_id=int(game["home_id"]); away_id=int(game["away_id"])
            hs=int(game["home_score"]); aws=int(game["away_score"])
        except (KeyError,TypeError,ValueError) as exc:
            raise SDVTrainingRowError("CFB_SDV_LABEL_GAME_INVALID") from exc
        if season >= 2026:
            raise SDVTrainingRowError("CFB_SDV_2026_OUTCOMES_PROHIBITED")
        key=(season,week,gid)
        if key in labels:
            raise SDVTrainingRowError(f"CFB_SDV_LABEL_DUPLICATE:{gid}")
        labels[key]=(home_id,away_id,hs,aws)

    out=[]
    for row in predictive_rows:
        key=(int(row["season"]),int(row["week"]),str(row["game_id"]))
        label=labels.get(key)
        if label is None:
            raise SDVTrainingRowError(f"CFB_SDV_LABEL_MISSING:{row.get('game_id')}")
        home_id,away_id,hs,aws=label
        if int(row["home_id"])!=home_id or int(row["away_id"])!=away_id:
            raise SDVTrainingRowError(f"CFB_SDV_LABEL_IDENTITY_MISMATCH:{row.get('game_id')}")
        out.append({**dict(row),"home_score":hs,"away_score":aws})
    if len(out)!=len(labels):
        used={(int(r["season"]),int(r["week"]),str(r["game_id"])) for r in predictive_rows}
        extra=set(labels)-used
        if extra:
            raise SDVTrainingRowError("CFB_SDV_UNBOUND_LABELS:"+",".join(sorted(k[2] for k in extra)))
    return out
