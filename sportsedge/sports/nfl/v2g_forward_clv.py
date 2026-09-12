"""Prospective, research-only CLV plumbing for frozen NFL V2G predictions."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from sportsedge.core.clv.nfl_forward_capture import build_forward_close_rows

POLICY_SCHEMA = "SPORTSEDGE_NFL_V2G_FORWARD_CLV_POLICY_V1"
PREDICTION_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1"
DECISION_SCHEMA = "SPORTSEDGE_NFL_V2G_FORWARD_DECISION_V1"
CLV_SCHEMA = "SPORTSEDGE_NFL_V2G_FORWARD_CLV_V1"
_GIT_RE = re.compile(r"^[0-9a-f]{40}$")

TEAM_CODE_BY_NAME = {
    "Arizona Cardinals":"ARI","Atlanta Falcons":"ATL","Baltimore Ravens":"BAL","Buffalo Bills":"BUF",
    "Carolina Panthers":"CAR","Chicago Bears":"CHI","Cincinnati Bengals":"CIN","Cleveland Browns":"CLE",
    "Dallas Cowboys":"DAL","Denver Broncos":"DEN","Detroit Lions":"DET","Green Bay Packers":"GB",
    "Houston Texans":"HOU","Indianapolis Colts":"IND","Jacksonville Jaguars":"JAX","Kansas City Chiefs":"KC",
    "Las Vegas Raiders":"LV","Los Angeles Chargers":"LAC","Los Angeles Rams":"LA","Miami Dolphins":"MIA",
    "Minnesota Vikings":"MIN","New England Patriots":"NE","New Orleans Saints":"NO","New York Giants":"NYG",
    "New York Jets":"NYJ","Philadelphia Eagles":"PHI","Pittsburgh Steelers":"PIT","San Francisco 49ers":"SF",
    "Seattle Seahawks":"SEA","Tampa Bay Buccaneers":"TB","Tennessee Titans":"TEN","Washington Commanders":"WAS",
}


def _dt(value: Any) -> datetime:
    raw = str(value or "").strip()
    out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("NFL_V2G_FORWARD_TIMESTAMP_NAIVE")
    return out.astimezone(timezone.utc)


def _num(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if not isfinite(out):
        raise ValueError(code)
    return out


def implied(price: Any) -> float:
    p = _num(price, "NFL_V2G_FORWARD_PRICE_INVALID")
    if p == 0:
        raise ValueError("NFL_V2G_FORWARD_PRICE_INVALID")
    return 100.0 / (100.0 + p) if p > 0 else (-p) / ((-p) + 100.0)


def novig(price: Any, other: Any) -> float:
    a, b = implied(price), implied(other)
    return a / (a + b)


def profit_per_unit(price: Any) -> float:
    p = _num(price, "NFL_V2G_FORWARD_PRICE_INVALID")
    if p == 0:
        raise ValueError("NFL_V2G_FORWARD_PRICE_INVALID")
    return p / 100.0 if p > 0 else 100.0 / (-p)


def _hash_json(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA or policy.get("status") != "FROZEN_BEFORE_FIRST_WEEK2_MARKET_DECISION":
        raise ValueError("NFL_V2G_FORWARD_POLICY_INVALID")
    if policy.get("promotion_authority") is not False or policy.get("may_create_model_p") is not False or policy.get("official_status_granted") is not False:
        raise ValueError("NFL_V2G_FORWARD_POLICY_AUTHORITY_INVALID")
    clv = policy.get("clv") or {}
    if clv.get("metric") != "CLOSING_NOVIG_MINUS_DECISION_NOVIG" or clv.get("probability_reference") != "ORIGINAL_DECISION_THRESHOLD":
        raise ValueError("NFL_V2G_FORWARD_CLV_POLICY_INVALID")
    if clv.get("same_book_required") is not True or clv.get("model_probability_is_not_clv_reference") is not True:
        raise ValueError("NFL_V2G_FORWARD_CLV_POLICY_INVALID")


def validate_prediction(pred: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    if pred.get("schema_version") != PREDICTION_SCHEMA:
        raise ValueError("NFL_V2G_FORWARD_PREDICTION_SCHEMA_INVALID")
    if pred.get("candidate_id") != policy.get("candidate_id") or pred.get("artifact_sha256") != policy.get("frozen_research_artifact_sha256"):
        raise ValueError("NFL_V2G_FORWARD_PREDICTION_IDENTITY_MISMATCH")
    if pred.get("market_prices_consumed") is not False:
        raise ValueError("NFL_V2G_FORWARD_PREDICTION_MARKET_LEAKAGE")
    if _dt(pred.get("captured_at_utc")) >= _dt(pred.get("kickoff_utc")):
        raise ValueError("NFL_V2G_FORWARD_PREDICTION_NOT_PREGAME")
    for key in ("promotion_authority","may_create_model_p","market_eligibility_changed","official_status_granted"):
        if pred.get(key) is not False:
            raise ValueError(f"NFL_V2G_FORWARD_PREDICTION_AUTHORITY_INVALID:{key}")


def weighted_probs(rows: Iterable[Mapping[str, Any]], market: str, side: str, line: float) -> tuple[float,float,float]:
    win = push = loss = total_weight = 0.0
    for row in rows:
        weight = _num(row.get("weight"), "NFL_V2G_FORWARD_WEIGHT_INVALID")
        if weight < 0:
            raise ValueError("NFL_V2G_FORWARD_WEIGHT_INVALID")
        margin = _num(row.get("margin"), "NFL_V2G_FORWARD_MARGIN_INVALID")
        total = _num(row.get("total"), "NFL_V2G_FORWARD_TOTAL_INVALID")
        if market == "spread":
            value = (margin if side == "home" else -margin) + line
        elif market == "total":
            value = total - line if side == "over" else line - total
        else:
            raise ValueError("NFL_V2G_FORWARD_MARKET_UNSUPPORTED")
        total_weight += weight
        if value > 0: win += weight
        elif value < 0: loss += weight
        else: push += weight
    if abs(total_weight - 1.0) > 1e-8:
        raise ValueError(f"NFL_V2G_FORWARD_WEIGHT_SUM_INVALID:{total_weight}")
    return win, push, loss


def _find_game(pred: Mapping[str, Any], opener: Mapping[str, Any]) -> Mapping[str, Any]:
    matches = []
    kickoff = _dt(pred.get("kickoff_utc"))
    for row in opener.get("games") or []:
        try:
            away = TEAM_CODE_BY_NAME[str(row.get("away_team") or "")]
            home = TEAM_CODE_BY_NAME[str(row.get("home_team") or "")]
        except KeyError as exc:
            raise ValueError(f"NFL_V2G_FORWARD_UNKNOWN_TEAM:{exc.args[0]}") from exc
        if away == pred.get("away_team") and home == pred.get("home_team") and abs((_dt(row.get("commence_time")) - kickoff).total_seconds()) <= 60:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"NFL_V2G_FORWARD_GAME_MATCH_COUNT:{len(matches)}")
    return matches[0]


def _quote_choices(row: Mapping[str, Any], market: str) -> list[dict[str, Any]]:
    if market == "spread":
        spread = row.get("spread") or {}
        if spread.get("status") != "OK": raise ValueError("NFL_V2G_FORWARD_SPREAD_NOT_OK")
        hp, ap = _num(spread.get("home_point"),"NFL_V2G_FORWARD_LINE_INVALID"), _num(spread.get("away_point"),"NFL_V2G_FORWARD_LINE_INVALID")
        if abs(hp + ap) > 1e-9: raise ValueError("NFL_V2G_FORWARD_SPREAD_LINE_MISMATCH")
        hprice, aprice = spread.get("home_price"), spread.get("away_price")
        return [
            {"side_key":"home","side":TEAM_CODE_BY_NAME[str(row["home_team"])],"provider_side_name":row["home_team"],"line":hp,"price":hprice,"other":aprice},
            {"side_key":"away","side":TEAM_CODE_BY_NAME[str(row["away_team"])],"provider_side_name":row["away_team"],"line":ap,"price":aprice,"other":hprice},
        ]
    total = row.get("total") or {}
    if total.get("status") != "OK": raise ValueError("NFL_V2G_FORWARD_TOTAL_NOT_OK")
    point = _num(total.get("point"),"NFL_V2G_FORWARD_LINE_INVALID")
    op, up = total.get("over_price"), total.get("under_price")
    return [
        {"side_key":"over","side":"over","provider_side_name":"Over","line":point,"price":op,"other":up},
        {"side_key":"under","side":"under","provider_side_name":"Under","line":point,"price":up,"other":op},
    ]


def build_decisions(pred: Mapping[str, Any], opener: Mapping[str, Any], policy: Mapping[str, Any], *, code_git_sha: str) -> list[dict[str, Any]]:
    validate_policy(policy); validate_prediction(pred, policy)
    if not _GIT_RE.fullmatch(str(code_git_sha or "").lower()): raise ValueError("NFL_V2G_FORWARD_CODE_SHA_INVALID")
    if opener.get("capture_kind") != "OPENER" or opener.get("book") != "draftkings" or set(opener.get("markets") or []) != {"spreads","totals"}:
        raise ValueError("NFL_V2G_FORWARD_OPENER_CONTRACT_INVALID")
    if opener.get("lock_status") not in set(policy["decision_source"]["required_lock_status"]):
        raise ValueError("NFL_V2G_FORWARD_OPENER_LOCK_INVALID")
    decision_ts, kickoff = _dt(opener.get("retrieved_at_utc")), _dt(pred.get("kickoff_utc"))
    if decision_ts >= kickoff: raise ValueError("NFL_V2G_FORWARD_DECISION_NOT_PREGAME")
    row = _find_game(pred, opener)
    output = []
    for market in ("spread","total"):
        choices = []
        for quote in _quote_choices(row, market):
            win,push,loss = weighted_probs(pred.get("score_distribution") or [], market, quote["side_key"], float(quote["line"]))
            active = win + loss
            active_win = win / active if active > 0 else 0.0
            ev = win * profit_per_unit(quote["price"]) - loss
            q = dict(quote); q.update(win=win,push=push,loss=loss,active_win=active_win,ev=ev,novig=novig(quote["price"],quote["other"]))
            choices.append(q)
        selected = max(choices, key=lambda q: (q["ev"], q["side_key"]))
        output.append({
            "schema_version":DECISION_SCHEMA,"decision_ts":decision_ts.isoformat(),"game_start_ts":kickoff.isoformat(),"game_id":pred["game_id"],"sport":"nfl",
            "market":market,"side":selected["side"],"book":"draftkings","line_at_decision":selected["line"],"price_at_decision":selected["price"],
            "model_prob":selected["active_win"],"model_win_prob":selected["win"],"model_push_prob":selected["push"],"model_loss_prob":selected["loss"],
            "novig_prob":selected["novig"],"edge":selected["active_win"]-selected["novig"],"ev":selected["ev"],
            "gate_result":"SHADOW_QUALIFIED" if selected["ev"] > 0 else "REJECTED_NO_POSITIVE_EV","stake_units":0.0,
            "provider_event_id":str(row.get("event_id") or ""),"provider_home_team":row["home_team"],"provider_away_team":row["away_team"],"provider_side_name":selected["provider_side_name"],
            "model_id":pred["candidate_id"],"feature_contract":PREDICTION_SCHEMA,"code_git_sha":str(code_git_sha).lower(),
            "prediction_sha256":pred.get("prediction_sha256"),"artifact_sha256":pred.get("artifact_sha256"),"schedule_snapshot_sha256":pred.get("schedule_snapshot_sha256"),
            "opener_capture_sha256":_hash_json(opener),"market_prices_consumed_by_model":False,"promotion_authority":False,"may_create_model_p":False,"official_status_granted":False,
        })
    return output


def grade_close(decisions: Iterable[Mapping[str, Any]], event: Mapping[str, Any], *, captured_at: str) -> list[dict[str, Any]]:
    output=[]
    for decision in decisions:
        try:
            close = build_forward_close_rows([decision], event, captured_at=captured_at)[0]
        except ValueError as exc:
            if "NFL_FORWARD_ORIGINAL_THRESHOLD_QUOTE_MISSING" not in str(exc): raise
            output.append({"schema_version":CLV_SCHEMA,"game_id":decision["game_id"],"market":decision["market"],"side":decision["side"],"status":"INCONCLUSIVE_CLV_REFERENCE_LINE_MISMATCH","probability_line":decision.get("line_at_decision"),"promotion_authority":False,"may_create_model_p":False,"official_status_granted":False})
            continue
        decision_novig = _num(decision.get("novig_prob"), "NFL_V2G_FORWARD_DECISION_NOVIG_INVALID")
        closing_novig = _num(close.get("closing_novig_prob"), "NFL_V2G_FORWARD_CLOSING_NOVIG_INVALID")
        clv = closing_novig - decision_novig
        output.append({**close,"schema_version":CLV_SCHEMA,"status":"CLV_ELIGIBLE" if decision.get("gate_result")=="SHADOW_QUALIFIED" else "RESEARCH_REFERENCE_ONLY","decision_model_prob":decision["model_prob"],"decision_novig_prob":decision_novig,"decision_edge":decision["edge"],"decision_ev":decision["ev"],"clv":clv,"promotion_authority":False,"may_create_model_p":False,"official_status_granted":False})
    return output
