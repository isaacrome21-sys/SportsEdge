"""Artifact I/O for the market-blind NFL scoring-composition prior."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any, Mapping
from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior

SCHEMA="NFL_SCORING_COMPOSITION_PRIOR_V1"

class ScoringCompositionArtifactError(ValueError): pass

def _core(prior: ScoringCompositionPrior)->dict[str,Any]:
    counts={}
    for score,bucket in sorted(prior.counts_by_score.items()):
        counts[str(int(score))]=[
            {"touchdowns":k[0],"extra_points_made":k[1],"two_point_made":k[2],
             "field_goals_made":k[3],"safeties":k[4],"count":int(v)}
            for k,v in sorted(bucket.items())
        ]
    return {"schema":SCHEMA,"as_of":prior.as_of,"training_rows":int(prior.training_rows),
            "counts_by_score":counts,"market_inputs_used":False}

def dump_prior(prior: ScoringCompositionPrior)->dict[str,Any]:
    core=_core(prior)
    digest=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {**core,"artifact_sha256":digest}

def load_prior(value: Mapping[str,Any])->ScoringCompositionPrior:
    row=dict(value)
    digest=str(row.pop("artifact_sha256",""))
    expected=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if digest!=expected: raise ScoringCompositionArtifactError("NFL_SCORING_PRIOR_HASH_MISMATCH")
    if row.get("schema")!=SCHEMA: raise ScoringCompositionArtifactError("NFL_SCORING_PRIOR_SCHEMA_MISMATCH")
    if row.get("market_inputs_used") is not False: raise ScoringCompositionArtifactError("NFL_SCORING_PRIOR_MARKET_INPUT_FORBIDDEN")
    buckets={}
    total=0
    for score,items in dict(row.get("counts_by_score") or {}).items():
        bucket={}
        for item in items:
            key=(int(item["touchdowns"]),int(item["extra_points_made"]),int(item["two_point_made"]),int(item["field_goals_made"]),int(item["safeties"]))
            count=int(item["count"])
            if count<=0: raise ScoringCompositionArtifactError("NFL_SCORING_PRIOR_COUNT_POSITIVE_REQUIRED")
            bucket[key]=count; total+=count
        buckets[int(score)]=bucket
    if total!=int(row.get("training_rows") or 0): raise ScoringCompositionArtifactError("NFL_SCORING_PRIOR_ROW_COUNT_MISMATCH")
    return ScoringCompositionPrior(as_of=str(row["as_of"]),training_rows=total,counts_by_score=buckets)

def load_prior_file(path:str|Path)->ScoringCompositionPrior:
    return load_prior(json.loads(Path(path).read_text(encoding="utf-8")))
