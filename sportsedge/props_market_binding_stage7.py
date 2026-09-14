"""Stage 7 prop market binding.

This adapter can price a posted market only after an independently validated
probability exists. It never creates Model_P from sportsbook prices. The legacy
boolean entrypoint remains research-only; the provenance entrypoint requires a
hash-verified Stage 6 validation attestation.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from math import isfinite
from typing import Mapping, Optional

from sportsedge.props_validation_provenance_stage6 import verify_validation_attestation

STATUS_RESEARCH="RESEARCH_ONLY_POST_VALIDATION_BINDING"
NO_VIG_ONE_SIDED="UNAVAILABLE_ONE_SIDED"

def _american_odds(value:object,name:str="odds")->int:
    if isinstance(value,bool) or not isinstance(value,int):
        raise ValueError(f"BAD_AMERICAN_ODDS_TYPE:{name}")
    if -99<=value<=99:
        raise ValueError(f"BAD_AMERICAN_ODDS_RANGE:{name}")
    return value

def _market_line(value:object|None)->float|None:
    if value is None:return None
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError("BAD_MARKET_LINE_TYPE")
    line=float(value)
    if not isfinite(line):raise ValueError("BAD_MARKET_LINE_NONFINITE")
    return line

def american_to_decimal(odds:int)->float:
    odds=_american_odds(odds)
    return 1.0+((100.0/abs(odds)) if odds<0 else (odds/100.0))

def raw_implied_probability(odds:int)->float:
    return 1.0/american_to_decimal(odds)

def probability_to_fair_american(p:float)->int:
    try:p=float(p)
    except (TypeError,ValueError) as exc:raise ValueError("FAIR_ODDS_REQUIRES_INTERIOR_PROBABILITY") from exc
    if not isfinite(p) or not 0<p<1: raise ValueError("FAIR_ODDS_REQUIRES_INTERIOR_PROBABILITY")
    return round(-100*p/(1-p)) if p>=.5 else round(100*(1-p)/p)

def proportional_devig(a:int,b:int)->tuple[float,float]:
    a=_american_odds(a,"side_a");b=_american_odds(b,"side_b")
    pa,pb=raw_implied_probability(a),raw_implied_probability(b); s=pa+pb
    if not isfinite(s) or s<=0:raise ValueError("BAD_TWO_SIDED_MARKET")
    return pa/s,pb/s

@dataclass(frozen=True)
class BoundProp:
    sport:str; market:str; entity_id:str; line:Optional[float]; model_probability:float
    fair_american_odds:int; offered_odds:int; decimal_odds:float; expected_value_per_unit:float
    market_no_vig_probability:float|str; validation_passed:bool
    validation_artifact_sha256:str|None=None; validation_model_id:str|None=None; validation_model_version:str|None=None
    status:str=STATUS_RESEARCH; official:bool=False; staking_authority:bool=False

def bind_prop_market(*,sport:str,market:str,entity_id:str,model_probability:float,offered_odds:int,validation_passed:bool,line:float|None=None,paired_other_side_odds:int|None=None)->BoundProp:
    """Legacy research binding utility.

    A literal True still means only that the caller asserts validation. It grants
    no production authority and deliberately carries no validation artifact hash.
    New evidence-bearing consumers should use `bind_prop_market_with_attestation`.
    """
    if validation_passed is not True:raise ValueError("BLOCKED_NO_VALIDATED_PROBABILITY_ENGINE")
    try:p=float(model_probability)
    except (TypeError,ValueError) as exc:raise ValueError("BAD_MODEL_PROBABILITY") from exc
    if not isfinite(p) or not 0<p<1:raise ValueError("BAD_MODEL_PROBABILITY")
    offered=_american_odds(offered_odds,"offered_odds")
    paired=None if paired_other_side_odds is None else _american_odds(paired_other_side_odds,"paired_other_side_odds")
    bound_line=_market_line(line)
    dec=american_to_decimal(offered); ev=p*(dec-1.0)-(1.0-p)
    nv:float|str=NO_VIG_ONE_SIDED if paired is None else proportional_devig(offered,paired)[0]
    return BoundProp(sport,market,entity_id,bound_line,p,probability_to_fair_american(p),offered,dec,ev,nv,True)

def bind_prop_market_with_attestation(*,sport:str,market:str,entity_id:str,model_probability:float,offered_odds:int,validation_attestation:Mapping[str,object],model_id:str,model_version:str,code_git_sha:str,line:float|None=None,paired_other_side_odds:int|None=None)->BoundProp:
    """Bind a market only after verifying the Stage 6 validation artifact identity."""
    attestation=verify_validation_attestation(validation_attestation)
    if attestation["passed"] is not True:raise ValueError("BLOCKED_VALIDATION_ATTESTATION_NOT_PASS")
    if str(attestation.get("sport"))!=str(sport).upper():raise ValueError("VALIDATION_ATTESTATION_SPORT_MISMATCH")
    if str(attestation.get("model_id"))!=str(model_id):raise ValueError("VALIDATION_ATTESTATION_MODEL_ID_MISMATCH")
    if str(attestation.get("model_version"))!=str(model_version):raise ValueError("VALIDATION_ATTESTATION_MODEL_VERSION_MISMATCH")
    if str(attestation.get("code_git_sha"))!=str(code_git_sha).lower():raise ValueError("VALIDATION_ATTESTATION_CODE_SHA_MISMATCH")
    rows = attestation.get("rows")
    if not isinstance(rows, list) or not rows or any(not isinstance(r, Mapping) or not str(r.get("market_id") or "").strip() for r in rows):
        raise ValueError("VALIDATION_ATTESTATION_MARKET_BINDING_REQUIRED")
    markets = {str(r["market_id"]) for r in rows}
    # Pooled calibration across different propositions cannot validate one market.
    if len(markets) != 1:
        raise ValueError("VALIDATION_ATTESTATION_MIXED_MARKETS_NOT_ADMITTED")
    if markets != {str(market)}:
        raise ValueError("VALIDATION_ATTESTATION_MARKET_MISMATCH")
    bound=bind_prop_market(
        sport=sport,market=market,entity_id=entity_id,model_probability=model_probability,
        offered_odds=offered_odds,validation_passed=True,line=line,
        paired_other_side_odds=paired_other_side_odds,
    )
    return replace(
        bound,
        validation_artifact_sha256=str(attestation["artifact_sha256"]),
        validation_model_id=str(attestation["model_id"]),
        validation_model_version=str(attestation["model_version"]),
    )
