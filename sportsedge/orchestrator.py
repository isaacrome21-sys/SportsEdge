from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from .candidate_binding import bind_candidate
from .devig import multiplicative_devig
from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG, require_production_edge_floor
from .mlb_market_binding_v13 import (
    PRODUCTION_WIRED_MARKETS,
    runtime_full_binding_row,
    runtime_quote_binding_row,
    validate_binding,
    validate_quote_binding,
)
from .price_ttl import double_ttl_gate
from .truth_gate import BetDecision, decide_bet


class OrchestrationError(ValueError): pass
BANNED_MODEL_INPUT_KEYS={"sportsbook_probability","implied_probability","market_probability","american_odds","decimal_odds","sportsbook_price","dk_probability"}
@dataclass(frozen=True)
class RunResult:
    market:str; model_p:float|None; bet_status:str; decision:BetDecision|None; reason:str; model_input_hash:str|None=None; distribution_sha256:str|None=None; readout_sha256:str|None=None; readout_version:str|None=None; engine_version:str|None=None; runtime_path:str|None=None; seed_policy:str|None=None; mc_paths:int|None=None; book_key:str|None=None; sportsbook:str|None=None; quote_retrieved_at:str|None=None; offer_id:str|None=None

def _reject_market_leakage(model_input):
    present=BANNED_MODEL_INPUT_KEYS.intersection(model_input.keys())
    if present: raise OrchestrationError(f"sportsbook/market data prohibited in Model_Input: {sorted(present)}")
def _optional_sha256(output,key):
    value=output.get(key)
    if value is None:return None
    text=str(value).lower()
    if len(text)!=64 or any(ch not in "0123456789abcdef" for ch in text):raise OrchestrationError(f"engine output malformed {key}")
    return text
def _optional_text(output,key):
    value=output.get(key)
    if value is None:return None
    text=str(value).strip()
    if not text:raise OrchestrationError(f"engine output malformed {key}")
    return text
def _optional_nonnegative_int(output,key):
    value=output.get(key)
    if value is None:return None
    if isinstance(value,bool):raise OrchestrationError(f"engine output malformed {key}")
    try:parsed=int(value);numeric=float(value)
    except (TypeError,ValueError) as exc:raise OrchestrationError(f"engine output malformed {key}") from exc
    if parsed<0 or numeric!=parsed:raise OrchestrationError(f"engine output malformed {key}")
    return parsed
def _quote_identity(quote):
    book_key=str(quote.get("book_key") or "").strip()
    if not book_key:raise OrchestrationError("quote book_key missing")
    sportsbook_raw=quote.get("sportsbook");sportsbook=str(sportsbook_raw).strip() if sportsbook_raw not in (None,"") else None
    retrieved=quote.get("retrieved_at")
    if not isinstance(retrieved,datetime) or retrieved.tzinfo is None or retrieved.utcoffset() is None:raise OrchestrationError("quote retrieved_at must be timezone-aware")
    offer_raw=quote.get("offer_id");offer_id=str(offer_raw).strip() if offer_raw not in (None,"") else None
    return book_key,sportsbook,retrieved.isoformat(),offer_id

def _bind_readout_identity(output:dict[str,Any],model_input:Mapping[str,Any],market:str)->None:
    """Require explicit engine/readout identity on wired markets.

    Legacy/ineligible paths may still inherit the request identity for compatibility,
    but a market declared production-wired cannot be made self-validating by filling
    identity fields after the engine returns.
    """
    fields=("game_id","market","entity_id","line","side")
    if market in PRODUCTION_WIRED_MARKETS:
        missing=[key for key in fields if key not in output or output[key] in (None,"")]
        if missing:
            raise OrchestrationError(f"ENGINE_READOUT_IDENTITY_MISSING:{market}:{','.join(missing)}")
        return
    for key in fields:
        if key not in output and key in model_input:
            output[key]=model_input[key]

def run_candidate(*,model_input:Mapping[str,Any],quote:Mapping[str,Any],paired_quote:Mapping[str,Any]|None=None,deployment:Mapping[str,Any],engine_fn:Callable[[Mapping[str,Any]],Mapping[str,Any]],ingestion_now:datetime,finalization_now:datetime,edge_floor_config_path:str=DEFAULT_EDGE_FLOOR_CONFIG,kelly_multiplier:float=0.25)->RunResult:
    market=str(model_input.get("market","UNKNOWN"))
    try:
        _reject_market_leakage(model_input)
        # Quote/event identity was stamped at acquisition and is checked before
        # engine execution. Missing identity blocks this row.
        validate_quote_binding(runtime_quote_binding_row(quote))
        double_ttl_gate(quote,ingestion_now,finalization_now)
        book_key,sportsbook,quote_retrieved_at,offer_id=_quote_identity(quote)
        output=dict(engine_fn(model_input))
        if "model_p" not in output:raise OrchestrationError("engine output missing model_p")
        _bind_readout_identity(output,model_input,market)
        runtime_path=_optional_text(output,"runtime_path")
        if deployment.get("eligible") is True and runtime_path=="LEGACY_COMPAT":raise OrchestrationError("LEGACY_COMPAT_PATH_NOT_PROMOTABLE")
        # Full price-to-probability binding. A failure blocks only this row.
        validate_binding(runtime_full_binding_row(quote,output))
        bind_candidate(output,quote,deployment)
        model_input_hash=_optional_sha256(output,"model_input_hash");distribution_sha256=_optional_sha256(output,"distribution_sha256");readout_sha256=_optional_sha256(output,"readout_sha256");readout_version=_optional_text(output,"readout_version");engine_version=_optional_text(output,"engine_version");seed_policy=_optional_text(output,"seed_policy");mc_paths=_optional_nonnegative_int(output,"mc_paths")
        floor=require_production_edge_floor(market=market,path=edge_floor_config_path)
        if not isinstance(paired_quote,Mapping):raise OrchestrationError("PAIRED_PRICE_REQUIRED_FOR_DEVIG")
        validate_quote_binding(runtime_quote_binding_row(paired_quote))
        double_ttl_gate(paired_quote,ingestion_now,finalization_now)
        devig=multiplicative_devig(quote,paired_quote)
        decision=decide_bet(output["model_p"],quote["american_odds"],fair_market_probability=devig.candidate_fair_probability,bound=True,fresh=True,deployed=deployment.get("eligible") is True,edge_floor=float(floor.value_probability_points),kelly_multiplier=kelly_multiplier,push_probability=float(output.get("push_p",0.0)))
        return RunResult(market,float(output["model_p"]),decision.bet_status,decision,"ok",model_input_hash=model_input_hash,distribution_sha256=distribution_sha256,readout_sha256=readout_sha256,readout_version=readout_version,engine_version=engine_version,runtime_path=runtime_path,seed_policy=seed_policy,mc_paths=mc_paths,book_key=book_key,sportsbook=sportsbook,quote_retrieved_at=quote_retrieved_at,offer_id=offer_id)
    except Exception as exc:return RunResult(market,None,"BLOCKED",None,f"{type(exc).__name__}: {exc}")

def run_slate(candidates,*,engines,deployments,ingestion_now,finalization_now,edge_floor_config_path=DEFAULT_EDGE_FLOOR_CONFIG,kelly_multiplier=0.25):
    results=[]
    for item in candidates:
        model_input=item.get("model_input");quote=item.get("quote");paired_quote=item.get("paired_quote")
        if not isinstance(model_input,Mapping) or not isinstance(quote,Mapping):results.append(RunResult("UNKNOWN",None,"BLOCKED",None,"candidate missing model_input/quote"));continue
        market=model_input.get("market");engine=engines.get(market);deployment=deployments.get(market)
        if engine is None or deployment is None:results.append(RunResult(str(market),None,"BLOCKED",None,"unsupported or undeployed market"));continue
        results.append(run_candidate(model_input=model_input,quote=quote,paired_quote=paired_quote,deployment=deployment,engine_fn=engine,ingestion_now=ingestion_now,finalization_now=finalization_now,edge_floor_config_path=edge_floor_config_path,kelly_multiplier=kelly_multiplier))
    return results
