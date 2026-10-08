"""2026 postseason K/outs prospective research receipts, strictly pregame.

These receipts preserve the *current* opponent-adjusted baseline and a frozen
2023–25 historical postseason logit-offset challenger. The challenger is
not validated for the full opponent/lineup-adjusted baseline. Neither probability
authorizes live bets, staking or a pricing deployment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp, isfinite, log
from re import fullmatch
from typing import Any, Mapping

from .mlb_generic_features import _outs_from_ip
from .mlb_source import GameSnapshot, parse_game_start
from .pitcher_joint_engine import price_pitcher_market

VERSION = "mlb_postseason_k_outs_2026_pit_shadow_v1"
SOURCE_AUDIT_SHA256 = "701d6d2bbac53f35f09bf2e292bafd58710b7cf1d1e333fc558f91c68bfb3c2d"
MODEL_PROVENANCE_PR = 1855
# 2023–2025 only; 2026 outcomes were not used. See original locked archive.
# Context-blind historical intercepts applied to a distinct serving model:
# this transfer is a research challenger, not certified calibration.
POSTSEASON_LOGIT_OFFSET = {"PITCHER_K": -0.787970267037,
                           "PITCHER_OUTS": -1.063038990566}
MARKET_LINES = {"PITCHER_K": (2.5, 4.5), "PITCHER_OUTS": (12.5, 15.5, 17.5)}

class ProspectiveShadowError(ValueError):
    pass

def _utc(value: str | datetime) -> datetime:
    if isinstance(value,datetime):
        result=value
    else:
        try: result=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        except (TypeError, ValueError) as exc: raise ProspectiveShadowError("BAD_TIME") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProspectiveShadowError("TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)

def _sha(row: Mapping[str, Any]) -> str:
    return sha256(json.dumps(row,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _p(p: Any) -> float:
    try: value=float(p)
    except (ValueError,TypeError) as exc: raise ProspectiveShadowError("INVALID_P") from exc
    if not isfinite(value) or not 0 <= value <= 1: raise ProspectiveShadowError("INVALID_P")
    return value

def postseason_shadow_p(p: float, market: str) -> float:
    if market not in POSTSEASON_LOGIT_OFFSET: raise ProspectiveShadowError("BAD_MARKET")
    value=min(1-1e-9,max(1e-9,_p(p)))
    logits=log(value/(1-value))+POSTSEASON_LOGIT_OFFSET[market]
    return 1/(1+exp(-logits))

def build_prediction(*, game: GameSnapshot, pitcher_id: int, team_side: str,
                     market: str, line: float, feature: Mapping[str, Any],
                     captured_at: datetime, schedule_sha256: str) -> dict[str, Any]:
    observed=_utc(captured_at)
    # A schedule obtained after the claimed capture cannot establish the
    # pitcher or matchup that was known at that point in time.
    if _utc(game.retrieved_at) > observed:
        raise ProspectiveShadowError("SCHEDULE_FETCH_AFTER_CAPTURE")
    scheduled=parse_game_start(game.game_date)
    if game.status!="Preview" or observed >= scheduled:
        raise ProspectiveShadowError("NOT_STRICTLY_PREGAME")
    if scheduled.year != 2026: raise ProspectiveShadowError("NOT_2026_POSTSEASON")
    if team_side not in ("away","home"): raise ProspectiveShadowError("BAD_TEAM_SIDE")
    expected=game.away_probable_pitcher_id if team_side=="away" else game.home_probable_pitcher_id
    if expected is None or int(expected)!=int(pitcher_id):
        raise ProspectiveShadowError("SCHEDULE_PITCHER_IDENTITY_MISMATCH")
    if market not in MARKET_LINES or float(line) not in MARKET_LINES[market]:
        raise ProspectiveShadowError("NOT_FIXED_RESEARCH_THRESHOLD")
    if feature.get("market")!=market or int(feature.get("game_pk") or 0)!=int(game.game_pk):
        raise ProspectiveShadowError("FEATURE_GAME_MARKET_IDENTITY_MISMATCH")
    if str(feature.get("entity_id") or "") != str(pitcher_id):
        raise ProspectiveShadowError("FEATURE_PITCHER_IDENTITY_MISMATCH")
    expected_team=game.away_id if team_side=="away" else game.home_id
    if feature.get("team_id") != expected_team:
        raise ProspectiveShadowError("FEATURE_TEAM_IDENTITY_MISMATCH")
    adj="opp_k_adjustment" if market=="PITCHER_K" else "opp_outs_adjustment"
    features=feature.get("features")
    if isinstance(features,Mapping) and isinstance(features.get("prior_fallback"),Mapping):
        pool=features.get("history_pool")
        starts=len(pool) if isinstance(pool,list) else "UNKNOWN"
        raise ProspectiveShadowError(
            f"POSTSEASON_BASELINE_UNSUPPORTED:FEW_STARTS_PRIOR_FALLBACK:own_starts={starts}"
        )
    if not isinstance(features,Mapping) or not isinstance(features.get(adj),Mapping):
        # Keep the hard block; include only the upstream fail-closed reason
        # already present in the PIT feature receipt. Never synthesize context.
        reason_key="opp_k_unadjusted" if market=="PITCHER_K" else "opp_outs_unadjusted"
        detail=str(feature.get(reason_key) or "UNSPECIFIED").splitlines()[0][:120]
        raise ProspectiveShadowError(f"OPPONENT_CONTEXT_MISSING:{detail}")
    expected_opponent=game.home_id if team_side=="away" else game.away_id
    if features[adj].get("opponent_team_id") != expected_opponent:
        raise ProspectiveShadowError("FEATURE_OPPONENT_IDENTITY_MISMATCH")
    retrieved=_utc(feature.get("retrieved_at"))
    if retrieved > observed: raise ProspectiveShadowError("FEATURE_FETCH_AFTER_CAPTURE")
    if not isinstance(feature.get("source_subset_hash"),str) or not fullmatch(r"[0-9a-fA-F]{64}",feature["source_subset_hash"]):
        raise ProspectiveShadowError("FEATURE_SOURCE_HASH_MISSING")
    if not isinstance(schedule_sha256,str) or not fullmatch(r"[0-9a-fA-F]{64}",schedule_sha256):
        raise ProspectiveShadowError("SCHEDULE_SOURCE_HASH_MISSING")
    priced=price_pitcher_market({"market":market,"side":"OVER","line":float(line),
        "game_id":str(game.game_pk),"entity_id":str(pitcher_id),
        "feature_source_hash":feature["source_subset_hash"],"features":features})
    baseline=_p(priced["model_p"])
    if priced["push_p"]!=0: raise ProspectiveShadowError("HALF_LINE_SHOULD_NOT_PUSH")
    record={
        "schema":VERSION, "status":"PREGAME_CAPTURED", "authority":"RESEARCH_ONLY",
        "game_pk":game.game_pk,"pitcher_id":int(pitcher_id),
        "team_side":team_side,"market":market,"line":float(line),
        "scheduled_first_pitch_utc":scheduled.isoformat(),
        "captured_at_utc":observed.isoformat(),
        "schedule_sha256":schedule_sha256,"feature_source_sha256":feature["source_subset_hash"],
        "baseline_engine":priced["engine_version"],"baseline_model_input_hash":priced["model_input_hash"],
        "baseline_opponent_adjusted_p_over":baseline,
        "postseason_shadow_research_p_over":postseason_shadow_p(baseline,market),
        "shadow_training_archive_sha256":SOURCE_AUDIT_SHA256,
        "shadow_training_provenance_pr":MODEL_PROVENANCE_PR,
        "shadow_transfer_validated":False, "live_market_price_bound":False,
        "allow_betting_card":False,
    }
    record["receipt_sha256"]=_sha(record)
    return record

def settle_prediction(*, game: GameSnapshot, prediction: Mapping[str,Any],
                      boxscore: Mapping[str,Any], settled_at: datetime,
                      final_source_sha256: str) -> dict[str,Any]:
    if prediction.get("schema")!=VERSION or prediction.get("status")!="PREGAME_CAPTURED":
        raise ProspectiveShadowError("PREDICTION_SCHEMA_MISMATCH")
    copy={k:v for k,v in prediction.items() if k!="receipt_sha256"}
    if _sha(copy)!=prediction.get("receipt_sha256"):
        raise ProspectiveShadowError("PREDICTION_BYTES_TAMPERED")
    if game.status!="Final" or int(prediction["game_pk"])!=game.game_pk:
        raise ProspectiveShadowError("NOT_MATCHING_FINAL_GAME")
    if _utc(prediction["captured_at_utc"])>=_utc(prediction["scheduled_first_pitch_utc"]):
        raise ProspectiveShadowError("PREDICTION_WAS_LATE")
    now=_utc(settled_at)
    if now<=_utc(prediction["scheduled_first_pitch_utc"]):
        raise ProspectiveShadowError("SETTLEMENT_BEFORE_GAME")
    if len(str(final_source_sha256))!=64:raise ProspectiveShadowError("FINAL_SOURCE_HASH_MISSING")
    side=prediction["team_side"]
    teams=boxscore.get("teams") or {}
    team=teams.get(side) or {}
    ids=team.get("pitchers") or []
    pid=int(prediction["pitcher_id"])
    result={
        "schema":"mlb_postseason_k_outs_2026_shadow_settlement_v1",
        "authority":"RESEARCH_ONLY", "game_pk":game.game_pk,
        "pitcher_id":pid, "market":prediction["market"],"line":prediction["line"],
        "prediction_receipt_sha256":prediction["receipt_sha256"],
        "settled_at_utc":now.isoformat(),"official_boxscore_sha256":final_source_sha256,
        "allow_betting_card":False,
    }
    if not ids or int(ids[0])!=pid:
        result.update({"status":"VOID_NOT_ACTUAL_STARTER","actual_count":None})
    else:
        raw=((team.get("players") or {}).get("ID"+str(pid)) or {}).get("stats") or {}
        stats=raw.get("pitching") or {}
        if prediction["market"]=="PITCHER_OUTS":
            raw_ip=stats.get("inningsPitched")
            if raw_ip is None: raise ProspectiveShadowError("MISSING_REALIZED_OUTS")
            if isinstance(raw_ip,bool): raise ProspectiveShadowError("NONINTEGER_OUTS")
            parsed=_outs_from_ip(raw_ip)
            if not isfinite(parsed) or parsed!=int(parsed):
                raise ProspectiveShadowError("NONINTEGER_OUTS")
            actual=int(parsed)
        elif prediction["market"]=="PITCHER_K":
            value=stats.get("strikeOuts")
            if value is None:raise ProspectiveShadowError("MISSING_REALIZED_STRIKEOUTS")
            if isinstance(value,bool) or not isinstance(value,int):
                raise ProspectiveShadowError("NONINTEGER_STRIKEOUTS")
            actual=value
        else: raise ProspectiveShadowError("UNKNOWN_MARKET")
        if actual<0 or (prediction["market"]=="PITCHER_OUTS" and actual>27):
            raise ProspectiveShadowError("UNPHYSICAL_PITCHER_STAT")
        y=float(actual>prediction["line"])
        baseline=_p(prediction["baseline_opponent_adjusted_p_over"])
        shadow=_p(prediction["postseason_shadow_research_p_over"])
        result.update({
            "status":"GRADED","actual_count":actual,"actual_over":bool(y),
            "baseline_brier":(baseline-y)**2,
            "shadow_brier":(shadow-y)**2,
            "shadow_minus_baseline_brier":(shadow-y)**2-(baseline-y)**2,
        })
    result["receipt_sha256"]=_sha(result)
    return result
