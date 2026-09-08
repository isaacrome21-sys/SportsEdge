"""Fail-closed canonical card pipeline for MLB game and joint prop markets."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .deployments import load_registry
from .devig import multiplicative_devig, validate_pair
from .engine_registry import engine_registry
from .f5_distribution import F5_MARKETS
from .generic_market_engine import BINARY_MARKETS, GAME_MARKETS
from .hitter_joint_engine import HITTER_MARKETS
from .mlb_binding_runtime import WIRED_MARKETS, probability_binding_row, quote_binding_row
from .mlb_market_binding import BindingError, validate_binding, validate_paired_quote, validate_quote_binding
from .orchestrator import run_candidate
from .pitcher_joint_engine import PITCHER_MARKETS
from .quote_bridge import validate_canonical_quote
from .truth_gate import american_to_decimal

GENERIC_MARKETS=frozenset(GAME_MARKETS|HITTER_MARKETS|PITCHER_MARKETS|BINARY_MARKETS)
BATTER_GENERIC_MARKETS=frozenset(HITTER_MARKETS|{"FIRST_HOME_RUN"})
PITCHER_GENERIC_MARKETS=frozenset(PITCHER_MARKETS|{"PITCHER_RECORD_WIN"})
TEAM_TOTAL_MARKETS=frozenset({"TEAM_TOTALS","F5_TEAM_TOTALS"})
DECISION_STATUSES=frozenset({"BET","OFFICIAL_BET","PASS"})

@dataclass(frozen=True)
class GenericCardResult:
    game_id:str; market:str; entity_id:str; line:Any; side:str; american_odds:Any; model_p:float|None; bet_status:str; reason:str; shadow_status:str|None=None; implied_probability:float|None=None; edge:float|None=None; ev_per_dollar:float|None=None; model_input_hash:str|None=None; distribution_sha256:str|None=None; readout_sha256:str|None=None; readout_version:str|None=None; engine_version:str|None=None; seed_policy:str|None=None; mc_paths:int|None=None; book_key:str|None=None; sportsbook:str|None=None; quote_retrieved_at:str|None=None; offer_id:str|None=None

def _game_index(games):
    out={}
    for game in games:
        key=str(game.game_pk)
        if key in out: raise ValueError("duplicate live game_pk")
        out[key]=game
    return out

def _feature_index(rows):
    out={}
    for row in rows:
        if not isinstance(row,Mapping): continue
        market=str(row.get("market","")); game_id=str(row.get("game_pk",row.get("game_id",""))); entity_id=str(row.get("entity_id",row.get("player_id","")))
        if market not in GENERIC_MARKETS or not game_id or not entity_id: continue
        key=(game_id,entity_id,market)
        if key in out and dict(out[key])!=dict(row): raise ValueError(f"conflicting generic feature identity {key}")
        out[key]=row
    return out

def _lineup_team(game,entity_id):
    try: pid=int(entity_id)
    except (TypeError,ValueError) as exc: raise ValueError("player entity_id must be numeric MLB id") from exc
    away=pid in game.away_lineup.player_ids; home=pid in game.home_lineup.player_ids
    if away and home: raise ValueError("player appears in both lineups")
    if away:return int(game.away_team_id)
    if home:return int(game.home_team_id)
    raise ValueError("player not present in MLB lineup snapshot")

def _team_side(game,entity_id):
    try: tid=int(entity_id)
    except (TypeError,ValueError) as exc: raise ValueError("team-total entity_id must be numeric MLB team id") from exc
    if tid==int(game.away_team_id):return "AWAY"
    if tid==int(game.home_team_id):return "HOME"
    raise ValueError("TEAM_TOTAL_ENTITY_NOT_IN_GAME")

def _bind_entity(game,market,entity_id,feature):
    if market in TEAM_TOTAL_MARKETS:_team_side(game,entity_id);return
    if market in BATTER_GENERIC_MARKETS:
        live=_lineup_team(game,entity_id); ft=feature.get("team_id")
        if ft is not None and int(ft)!=live: raise ValueError("PLAYER_TEAM_MISMATCH")
        return
    if market in PITCHER_GENERIC_MARKETS:
        if market.startswith("EITHER_PITCHER_"):
            if game.away_probable_pitcher_id is None or game.home_probable_pitcher_id is None:raise ValueError("BOTH_PROBABLE_PITCHERS_REQUIRED")
            expected=f"{int(game.away_probable_pitcher_id)}|{int(game.home_probable_pitcher_id)}"
            if entity_id!=expected:raise ValueError("EITHER_PITCHER_CANONICAL_PAIR_MISMATCH")
            return
        try:pid=int(entity_id)
        except (TypeError,ValueError) as exc:raise ValueError("pitcher entity_id must be numeric MLB id") from exc
        if pid not in {game.away_probable_pitcher_id,game.home_probable_pitcher_id}:raise ValueError("NON_PROBABLE_PITCHER")

def _model_input(*,game,quote,feature):
    market=str(quote["market"]); entity_id=str(quote["entity_id"]); _bind_entity(game,market,entity_id,feature)
    if str(feature.get("game_pk",feature.get("game_id")))!=str(game.game_pk):raise ValueError("feature game identity mismatch")
    if str(feature.get("entity_id",feature.get("player_id")))!=entity_id:raise ValueError("feature entity identity mismatch")
    if str(feature.get("market"))!=market:raise ValueError("feature market mismatch")
    out={"game_id":str(game.game_pk),"market":market,"entity_id":entity_id,"line":quote.get("line"),"side":quote.get("side")}
    if market in TEAM_TOTAL_MARKETS:out["team_side"]=_team_side(game,entity_id)
    if market=="HOME_RUNS":out["expected_count"]=feature.get("expected_count")
    elif market in F5_MARKETS or market=="FIRST_HOME_RUN":
        payload=feature.get("features")
        if not isinstance(payload,Mapping):raise ValueError(f"{market} state feature payload missing")
        out["features"]=dict(payload)
    elif market=="PITCHER_RECORD_WIN":
        payload=feature.get("features")
        if not isinstance(payload,Mapping):raise ValueError("PITCHER_RECORD_WIN state feature payload missing")
        out["features"]=dict(payload); out["team_side"]=feature.get("team_side"); out["away_mean_runs"]=feature.get("away_mean_runs"); out["home_mean_runs"]=feature.get("home_mean_runs")
    elif market in HITTER_MARKETS|PITCHER_MARKETS:
        payload=feature.get("features")
        if not isinstance(payload,Mapping):
            ignored={"game_pk","game_id","market","entity_id","player_id","team_id","retrieved_at","asof","generic_feature_version","joint_feature_version","feature_version","feature_source_hash","source_subset_hash","source"}; payload={k:v for k,v in feature.items() if k not in ignored}
        out["features"]=dict(payload)
    elif market in BINARY_MARKETS:out["event_probability"]=feature.get("event_probability")
    else:
        out.update({"away_mean_runs":feature.get("away_mean_runs"),"home_mean_runs":feature.get("home_mean_runs")})
        if market not in {"TOTALS","TEAM_TOTALS"}:out["total_line"]=feature.get("total_line",0.0)
    source_hash=feature.get("feature_source_hash",feature.get("source_subset_hash"))
    if source_hash is not None:out["feature_source_hash"]=source_hash
    return out

def _validated_quotes(quotes):
    out=[]
    for raw in quotes:
        try:out.append(validate_canonical_quote(raw))
        except Exception:pass
    return out

def _paired_quote(candidate,quotes):
    matches=[]
    for quote in quotes:
        if quote is candidate or dict(quote)==dict(candidate):continue
        try:validate_pair(candidate,quote);matches.append(quote)
        except Exception:pass
    if len(matches)!=1:raise ValueError(f"PAIRED_PRICE_REQUIRED_FOR_DEVIG: found={len(matches)}")
    return matches[0]

def _binding_paired_quote(candidate,quotes,game):
    candidate_row=quote_binding_row(game=game,quote=candidate); validate_quote_binding(candidate_row); matches=[]
    for quote in quotes:
        if quote is candidate or dict(quote)==dict(candidate):continue
        try:
            other_row=quote_binding_row(game=game,quote=quote); validate_paired_quote(candidate_row,other_row); matches.append(quote)
        except (BindingError,ValueError):pass
    if len(matches)!=1:raise BindingError(f"PAIRED_PRICE_REQUIRED_FOR_BINDING: found={len(matches)}")
    return matches[0]

def _shadow(model_p,push_p,quote,opposite):
    if model_p is None:return None,None,None,None
    try:
        fair=multiplicative_devig(quote,opposite).candidate_fair_probability;dec=american_to_decimal(quote["american_odds"]);p=float(model_p);push=float(push_p)
        if not isfinite(p) or not 0<=p<=1:raise ValueError("invalid Model_P")
        if not isfinite(push) or not 0<=push<1 or p+push>1+1e-12:raise ValueError("invalid push probability")
        loss=max(0,1-p-push);cw=p/(1-push);edge=cw-fair;ev=p*(dec-1)-loss;return ("SHADOW_BET" if edge>0 and ev>0 else "SHADOW_PASS",fair,edge,ev)
    except Exception:return None,None,None,None

def run_generic_card(*,games,feature_rows,quotes,ingestion_now,finalization_now,registry_path="config/deployments.json",edge_floor_config_path="config/truth_gate_floors.json",kelly_multiplier=0.25):
    games_by_id=_game_index(games);features=_feature_index(feature_rows);deployments=load_registry(registry_path)["markets"];engines=engine_registry();valid_quotes=_validated_quotes(quotes);results=[]
    for raw in quotes:
        try:
            quote=validate_canonical_quote(raw);market=str(quote["market"])
            if market not in GENERIC_MARKETS:raise ValueError(f"unsupported canonical market: {market}")
            game=games_by_id.get(str(quote["game_id"]));
            if game is None:raise ValueError("MLB_GAME_ID_NOT_FOUND")
            # Stage 1: real sportsbook quote + official MLB event identity, before model work.
            if market in WIRED_MARKETS:validate_quote_binding(quote_binding_row(game=game,quote=quote))
            feature=features.get((str(quote["game_id"]),str(quote["entity_id"]),market))
            if feature is None:raise ValueError("feature row missing")
            model_input=_model_input(game=game,quote=quote,feature=feature);engine=engines.get(market);deployment=deployments.get(market)
            if engine is None or deployment is None:raise ValueError("market missing engine/deployment registration")
            try:opposite=_binding_paired_quote(quote,valid_quotes,game) if market in WIRED_MARKETS else _paired_quote(quote,valid_quotes)
            except Exception as pair_exc:results.append(GenericCardResult(str(quote["game_id"]),market,str(quote["entity_id"]),quote["line"],str(quote["side"]),quote["american_odds"],None,"BLOCKED",str(pair_exc)));continue
            run=run_candidate(model_input=model_input,quote=quote,paired_quote=opposite,deployment=deployment,engine_fn=engine,ingestion_now=ingestion_now,finalization_now=finalization_now,edge_floor_config_path=edge_floor_config_path,kelly_multiplier=kelly_multiplier)
            if run.model_p is None or run.bet_status=="BLOCKED":results.append(GenericCardResult(str(quote["game_id"]),market,str(quote["entity_id"]),quote["line"],str(quote["side"]),quote["american_odds"],None,"BLOCKED",run.reason));continue
            if run.bet_status not in DECISION_STATUSES:raise RuntimeError(f"MODELED_ROW_WITHOUT_BET_PASS_DECISION: {run.bet_status}")
            p=float(run.model_p);push=float(run.decision.push_probability) if run.decision is not None else 0.0
            # Stage 2: bind the actual model probability identity and push mass to this offer.
            if market in WIRED_MARKETS:validate_binding(probability_binding_row(game=game,quote=quote,model_input=model_input,push_probability=push))
            shadow,implied,edge,ev=_shadow(p,push,quote,opposite)
            results.append(GenericCardResult(str(quote["game_id"]),market,str(quote["entity_id"]),quote["line"],str(quote["side"]),quote["american_odds"],p,run.bet_status,run.reason,shadow,implied,edge,ev,run.model_input_hash,run.distribution_sha256,run.readout_sha256,run.readout_version,run.engine_version,run.seed_policy,run.mc_paths,book_key=run.book_key,sportsbook=run.sportsbook,quote_retrieved_at=run.quote_retrieved_at,offer_id=run.offer_id))
        except Exception as exc:
            try:q=validate_canonical_quote(raw);identity=(str(q["game_id"]),str(q["market"]),str(q["entity_id"]),q["line"],str(q["side"]),q["american_odds"])
            except Exception:identity=("UNKNOWN","UNKNOWN","UNKNOWN",None,"UNKNOWN",None)
            results.append(GenericCardResult(*identity,None,"BLOCKED",f"{type(exc).__name__}: {exc}"))
    return results
