"""Pure, replayable NFL forward decision/close capture logic."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import re
from typing import Any, Iterable, Mapping

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

NFL_FORWARD_SELECTION_CONTRACT = "NFL_FORWARD_SHADOW_EV_V1"
NFL_ODDS_SPORT_KEY = "americanfootball_nfl"
NFL_FORWARD_BOOK = "draftkings"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _dt(value: Any, error: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(error)
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise ValueError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError(error)
    return out.astimezone(timezone.utc)


def _num(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not isfinite(out):
        raise ValueError(error)
    return out


def _git(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError("NFL_FORWARD_CODE_SHA_INVALID")
    return raw


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _snapshot_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _implied(price: Any) -> float:
    p = _num(price, "NFL_FORWARD_PRICE_INVALID")
    if p == 0:
        raise ValueError("NFL_FORWARD_PRICE_INVALID")
    return 100.0 / (100.0 + p) if p > 0 else (-p) / ((-p) + 100.0)


def _profit(price: Any) -> float:
    p = _num(price, "NFL_FORWARD_PRICE_INVALID")
    if p == 0:
        raise ValueError("NFL_FORWARD_PRICE_INVALID")
    return p / 100.0 if p > 0 else 100.0 / (-p)


def _novig(price: Any, other: Any) -> float:
    a, b = _implied(price), _implied(other)
    return a / (a + b)


def _ev_kelly(win: float, loss: float, price: float) -> tuple[float, float]:
    b = _profit(price)
    ev = win * b - loss
    active = win + loss
    full = 0.0 if active <= 0 else ev / (b * active)
    return ev, min(0.25, max(0.0, full) * 0.25)


def _same_line(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _book(event: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = event.get("bookmakers")
    matches = [x for x in rows if isinstance(x, Mapping) and str(x.get("key") or "").lower() == NFL_FORWARD_BOOK] if isinstance(rows, list) else []
    if len(matches) != 1:
        raise ValueError("NFL_FORWARD_BOOKMAKER_COUNT_INVALID")
    return matches[0]


def _market(event: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    rows = _book(event).get("markets")
    matches = [x for x in rows if isinstance(x, Mapping) and str(x.get("key") or "").lower() == key] if isinstance(rows, list) else []
    if len(matches) != 1:
        raise ValueError(f"NFL_FORWARD_MARKET_COUNT_INVALID:{key}")
    return matches[0]


def _outs(market: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = market.get("outcomes")
    if not isinstance(rows, list):
        raise ValueError("NFL_FORWARD_OUTCOMES_MISSING")
    return [x for x in rows if isinstance(x, Mapping)]


def _validate_event(game: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[datetime, str, str]:
    if str(event.get("sport_key") or "") != NFL_ODDS_SPORT_KEY:
        raise ValueError("NFL_FORWARD_SPORT_KEY_MISMATCH")
    if not str(event.get("id") or "").strip():
        raise ValueError("NFL_FORWARD_EVENT_ID_MISSING")
    start = _dt(game.get("game_start_ts"), "NFL_FORWARD_GAME_START_INVALID")
    if _dt(event.get("commence_time"), "NFL_FORWARD_EVENT_START_INVALID") != start:
        raise ValueError("NFL_FORWARD_EVENT_START_MISMATCH")
    ph, pa = str(game.get("provider_home_team") or "").strip(), str(game.get("provider_away_team") or "").strip()
    if not ph or not pa:
        raise ValueError("NFL_FORWARD_PROVIDER_TEAM_IDENTITY_MISSING")
    if str(event.get("home_team") or "").strip() != ph or str(event.get("away_team") or "").strip() != pa:
        raise ValueError("NFL_FORWARD_PROVIDER_TEAM_MISMATCH")
    return start, ph, pa


def _identity(value: Mapping[str, Any]) -> dict[str, str]:
    if value.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_FORWARD_MODEL_ID_MISMATCH")
    if value.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_FORWARD_FEATURE_CONTRACT_MISMATCH")
    return {
        "code_git_sha": _git(value.get("code_git_sha")),
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "model_artifact_sha256": _hash(value.get("model_artifact_sha256"), "NFL_FORWARD_MODEL_ARTIFACT_SHA256_INVALID"),
    }


def _dist(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    out = [x for x in rows if isinstance(x, Mapping)]
    if not out:
        raise ValueError("NFL_FORWARD_SCORE_DISTRIBUTION_EMPTY")
    for row in out:
        for key in ("home_score", "away_score", "margin", "total"):
            _num(row.get(key), f"NFL_FORWARD_SCORE_DISTRIBUTION_INVALID:{key}")
    return out


def _probs(rows: list[Mapping[str, Any]], market: str, side: str, line: float | None) -> tuple[float, float, float]:
    w = p = l = 0
    for row in rows:
        margin, total = float(row["margin"]), float(row["total"])
        if market == "moneyline":
            v = margin if side == "home" else -margin
        elif market == "spread":
            if line is None: raise ValueError("NFL_FORWARD_LINE_REQUIRED")
            v = (margin if side == "home" else -margin) + float(line)
        elif market == "total":
            if line is None: raise ValueError("NFL_FORWARD_LINE_REQUIRED")
            v = total - float(line) if side == "over" else float(line) - total
        else:
            raise ValueError(f"NFL_FORWARD_MARKET_UNSUPPORTED:{market}")
        if v > 0: w += 1
        elif v < 0: l += 1
        else: p += 1
    n = float(len(rows))
    return w / n, p / n, l / n


def _main_pairs(event: Mapping[str, Any], market: str, ph: str, pa: str) -> list[dict[str, Any]]:
    if market == "moneyline":
        by = {str(x.get("name") or "").strip(): x for x in _outs(_market(event, "h2h"))}
        if ph not in by or pa not in by: raise ValueError("NFL_FORWARD_H2H_OUTCOME_MISSING")
        return [
            {"side_key":"home","provider_name":ph,"line":None,"price":_num(by[ph].get("price"),"NFL_FORWARD_PRICE_INVALID"),"other":_num(by[pa].get("price"),"NFL_FORWARD_PRICE_INVALID")},
            {"side_key":"away","provider_name":pa,"line":None,"price":_num(by[pa].get("price"),"NFL_FORWARD_PRICE_INVALID"),"other":_num(by[ph].get("price"),"NFL_FORWARD_PRICE_INVALID")},
        ]
    if market == "spread":
        by = {str(x.get("name") or "").strip(): x for x in _outs(_market(event, "spreads"))}
        if ph not in by or pa not in by: raise ValueError("NFL_FORWARD_SPREAD_OUTCOME_MISSING")
        return [
            {"side_key":"home","provider_name":ph,"line":_num(by[ph].get("point"),"NFL_FORWARD_LINE_INVALID"),"price":_num(by[ph].get("price"),"NFL_FORWARD_PRICE_INVALID"),"other":_num(by[pa].get("price"),"NFL_FORWARD_PRICE_INVALID")},
            {"side_key":"away","provider_name":pa,"line":_num(by[pa].get("point"),"NFL_FORWARD_LINE_INVALID"),"price":_num(by[pa].get("price"),"NFL_FORWARD_PRICE_INVALID"),"other":_num(by[ph].get("price"),"NFL_FORWARD_PRICE_INVALID")},
        ]
    if market == "total":
        by = {str(x.get("name") or "").strip().lower(): x for x in _outs(_market(event, "totals"))}
        if "over" not in by or "under" not in by: raise ValueError("NFL_FORWARD_TOTAL_OUTCOME_MISSING")
        if not _same_line(by["over"].get("point"), by["under"].get("point")): raise ValueError("NFL_FORWARD_TOTAL_LINE_MISMATCH")
        return [
            {"side_key":"over","provider_name":"Over","line":_num(by["over"].get("point"),"NFL_FORWARD_LINE_INVALID"),"price":_num(by["over"].get("price"),"NFL_FORWARD_PRICE_INVALID"),"other":_num(by["under"].get("price"),"NFL_FORWARD_PRICE_INVALID")},
            {"side_key":"under","provider_name":"Under","line":_num(by["under"].get("point"),"NFL_FORWARD_LINE_INVALID"),"price":_num(by["under"].get("price"),"NFL_FORWARD_PRICE_INVALID"),"other":_num(by["over"].get("price"),"NFL_FORWARD_PRICE_INVALID")},
        ]
    raise ValueError(f"NFL_FORWARD_MARKET_UNSUPPORTED:{market}")


def build_forward_decision_rows(game: Mapping[str, Any], event: Mapping[str, Any], distribution: Iterable[Mapping[str, Any]], *, captured_at: str | datetime, identity: Mapping[str, Any]) -> list[dict[str, Any]]:
    start, ph, pa = _validate_event(game, event)
    captured = _dt(captured_at, "NFL_FORWARD_DECISION_TS_INVALID")
    if captured >= start: raise ValueError("NFL_FORWARD_DECISION_NOT_PREGAME")
    ids, dist = _identity(identity), _dist(distribution)
    game_id, home, away = str(game.get("game_id") or "").strip(), str(game.get("home_team") or "").strip(), str(game.get("away_team") or "").strip()
    if not game_id or not home or not away: raise ValueError("NFL_FORWARD_GAME_IDENTITY_MISSING")
    event_hash = _snapshot_hash(event)
    out = []
    for market in ("moneyline", "spread", "total"):
        choices = []
        for q in _main_pairs(event, market, ph, pa):
            win, push, loss = _probs(dist, market, q["side_key"], q["line"])
            ev, kelly = _ev_kelly(win, loss, q["price"])
            choices.append({**q,"win":win,"push":push,"loss":loss,"ev":ev,"kelly":kelly})
        s = max(choices, key=lambda x: (float(x["ev"]), str(x["side_key"])))
        canonical = home if s["side_key"] == "home" else away if s["side_key"] == "away" else s["side_key"]
        out.append({
            "decision_ts":captured.isoformat(),"game_start_ts":start.isoformat(),"game_id":game_id,"sport":"nfl","market":market,"side":canonical,"book":NFL_FORWARD_BOOK,
            "line_at_decision":s["line"],"price_at_decision":s["price"],"model_prob":s["win"],"model_push_prob":s["push"],"model_loss_prob":s["loss"],
            "novig_prob":_novig(s["price"],s["other"]),"ev":s["ev"],"kelly_frac":s["kelly"],"stake_units":s["kelly"],
            "gate_result":"SHADOW_QUALIFIED" if float(s["ev"]) > 0 else "REJECTED_NO_POSITIVE_EV","selection_contract":NFL_FORWARD_SELECTION_CONTRACT,
            "provider_event_id":str(event["id"]),"provider_event_snapshot_sha256":event_hash,"provider_home_team":ph,"provider_away_team":pa,"provider_side_name":s["provider_name"],**ids,
        })
    return out


def _close_quote(event: Mapping[str, Any], d: Mapping[str, Any], ph: str, pa: str) -> tuple[float | None,float,float]:
    market, name, line = str(d.get("market") or "").lower(), str(d.get("provider_side_name") or "").strip(), d.get("line_at_decision")
    if market == "moneyline":
        q = next((x for x in _main_pairs(event,"moneyline",ph,pa) if x["provider_name"] == name), None)
        if q is None: raise ValueError("NFL_FORWARD_CLOSE_SIDE_MISSING")
        return None, float(q["price"]), _novig(q["price"],q["other"])
    if line is None: raise ValueError("NFL_FORWARD_LINE_REQUIRED")
    if market == "spread":
        opponent = pa if name == ph else ph
        headline = next((x["line"] for x in _main_pairs(event,"spread",ph,pa) if x["provider_name"] == name), None)
        for key in ("spreads","alternate_spreads"):
            try: rows = _outs(_market(event,key))
            except ValueError: continue
            a = [x for x in rows if str(x.get("name") or "").strip()==name and _same_line(x.get("point"),line)]
            b = [x for x in rows if str(x.get("name") or "").strip()==opponent and _same_line(x.get("point"),-float(line))]
            if len(a)==1 and len(b)==1:
                p, op = _num(a[0].get("price"),"NFL_FORWARD_PRICE_INVALID"), _num(b[0].get("price"),"NFL_FORWARD_PRICE_INVALID")
                return headline,p,_novig(p,op)
    elif market == "total":
        other = "Under" if name.lower()=="over" else "Over"
        headline = next((x["line"] for x in _main_pairs(event,"total",ph,pa) if x["provider_name"].lower()==name.lower()), None)
        for key in ("totals","alternate_totals"):
            try: rows = _outs(_market(event,key))
            except ValueError: continue
            a=[x for x in rows if str(x.get("name") or "").strip().lower()==name.lower() and _same_line(x.get("point"),line)]
            b=[x for x in rows if str(x.get("name") or "").strip().lower()==other.lower() and _same_line(x.get("point"),line)]
            if len(a)==1 and len(b)==1:
                p,op=_num(a[0].get("price"),"NFL_FORWARD_PRICE_INVALID"),_num(b[0].get("price"),"NFL_FORWARD_PRICE_INVALID")
                return headline,p,_novig(p,op)
    else:
        raise ValueError(f"NFL_FORWARD_MARKET_UNSUPPORTED:{market}")
    raise ValueError("NFL_FORWARD_ORIGINAL_THRESHOLD_QUOTE_MISSING")


def build_forward_close_rows(decisions: Iterable[Mapping[str, Any]], event: Mapping[str, Any], *, captured_at: str | datetime) -> list[dict[str, Any]]:
    rows=[dict(x) for x in decisions]
    if not rows: raise ValueError("NFL_FORWARD_DECISIONS_EMPTY")
    first=rows[0]
    game={"game_start_ts":first.get("game_start_ts"),"provider_home_team":first.get("provider_home_team"),"provider_away_team":first.get("provider_away_team")}
    start,ph,pa=_validate_event(game,event)
    captured=_dt(captured_at,"NFL_FORWARD_CLOSE_TS_INVALID")
    if captured>=start: raise ValueError("NFL_FORWARD_CLOSE_NOT_PREGAME")
    event_id=str(event.get("id") or "").strip(); event_hash=_snapshot_hash(event)
    out=[]
    for d in rows:
        if captured<=_dt(d.get("decision_ts"),"NFL_FORWARD_DECISION_TS_INVALID"): raise ValueError("NFL_FORWARD_CLOSE_NOT_AFTER_DECISION")
        if _dt(d.get("game_start_ts"),"NFL_FORWARD_GAME_START_INVALID")!=start: raise ValueError("NFL_FORWARD_GAME_START_MISMATCH")
        if str(d.get("provider_event_id") or "").strip()!=event_id: raise ValueError("NFL_FORWARD_PROVIDER_EVENT_ID_MISMATCH")
        if str(d.get("provider_home_team") or "").strip()!=ph or str(d.get("provider_away_team") or "").strip()!=pa: raise ValueError("NFL_FORWARD_PROVIDER_TEAM_MISMATCH")
        if str(d.get("book") or "").lower()!=NFL_FORWARD_BOOK: raise ValueError("NFL_FORWARD_BOOK_MISMATCH")
        close_line,price,novig=_close_quote(event,d,ph,pa)
        out.append({"close_ts":captured.isoformat(),"game_start_ts":start.isoformat(),"game_id":str(d.get("game_id") or ""),"sport":"nfl","market":str(d.get("market") or "").lower(),"side":str(d.get("side") or ""),"book":NFL_FORWARD_BOOK,"closing_line":close_line,"closing_price":price,"closing_novig_prob":novig,"probability_line":d.get("line_at_decision"),"model_id":d.get("model_id"),"feature_contract":d.get("feature_contract"),"code_git_sha":d.get("code_git_sha"),"provider_event_id":event_id,"provider_event_snapshot_sha256":event_hash})
    return out
