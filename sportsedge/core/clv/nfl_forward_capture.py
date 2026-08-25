"""Pure forward-capture logic for NFL promotion CLV.

This module does not perform network I/O. A scheduled collection workflow owns
provider acquisition and passes the exact raw event snapshot into these helpers.
That separation makes the time/identity contract replayable in tests while the
workflow run supplies external authenticity.

Only one side per game/market is selected for the forward sample. The selected
side is the side with the larger push-aware expected value. Positive-EV sides
are labelled ``SHADOW_QUALIFIED`` until the market itself is DEPLOYED; that label
is evidence collection only and never authorizes a user-facing bet.
"""
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
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise ValueError(error) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(error)
    return parsed.astimezone(timezone.utc)


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _sha256_text(value: Mapping[str, Any]) -> str:
    material = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _num(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not isfinite(out):
        raise ValueError(error)
    return out


def _american_implied(price: Any) -> float:
    p = _num(price, "NFL_FORWARD_PRICE_INVALID")
    if p == 0.0:
        raise ValueError("NFL_FORWARD_PRICE_INVALID")
    return 100.0 / (100.0 + p) if p > 0 else (-p) / ((-p) + 100.0)


def _unit_profit(price: Any) -> float:
    p = _num(price, "NFL_FORWARD_PRICE_INVALID")
    if p == 0.0:
        raise ValueError("NFL_FORWARD_PRICE_INVALID")
    return p / 100.0 if p > 0 else 100.0 / (-p)


def _novig(selected_price: Any, other_price: Any) -> float:
    left = _american_implied(selected_price)
    right = _american_implied(other_price)
    total = left + right
    if total <= 0.0:
        raise ValueError("NFL_FORWARD_NOVIG_INVALID")
    return left / total


def _push_aware_ev(*, p_win: float, p_loss: float, price: float) -> tuple[float, float]:
    b = _unit_profit(price)
    ev = p_win * b - p_loss
    active = p_win + p_loss
    if active <= 0.0:
        return ev, 0.0
    full_kelly = ev / (b * active)
    quarter = max(0.0, full_kelly) * 0.25
    return ev, min(0.25, quarter)


def _bookmaker(event: Mapping[str, Any]) -> Mapping[str, Any]:
    books = event.get("bookmakers")
    if not isinstance(books, list):
        raise ValueError("NFL_FORWARD_BOOKMAKERS_MISSING")
    matches = [row for row in books if isinstance(row, Mapping) and str(row.get("key") or "").strip().lower() == NFL_FORWARD_BOOK]
    if len(matches) != 1:
        raise ValueError("NFL_FORWARD_BOOKMAKER_COUNT_INVALID")
    return matches[0]


def _markets(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = _bookmaker(event).get("markets")
    if not isinstance(raw, list):
        raise ValueError("NFL_FORWARD_MARKETS_MISSING")
    return [row for row in raw if isinstance(row, Mapping)]


def _market(event: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    matches = [row for row in _markets(event) if str(row.get("key") or "").strip().lower() == key]
    if len(matches) != 1:
        raise ValueError(f"NFL_FORWARD_MARKET_COUNT_INVALID:{key}")
    return matches[0]


def _outcomes(market: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = market.get("outcomes")
    if not isinstance(raw, list):
        raise ValueError("NFL_FORWARD_OUTCOMES_MISSING")
    return [row for row in raw if isinstance(row, Mapping)]


def _same_line(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _provider_names(game: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[str, str]:
    provider_home = str(game.get("provider_home_team") or "").strip()
    provider_away = str(game.get("provider_away_team") or "").strip()
    if not provider_home or not provider_away:
        raise ValueError("NFL_FORWARD_PROVIDER_TEAM_IDENTITY_MISSING")
    if str(event.get("home_team") or "").strip() != provider_home or str(event.get("away_team") or "").strip() != provider_away:
        raise ValueError("NFL_FORWARD_PROVIDER_TEAM_MISMATCH")
    return provider_home, provider_away


def _validate_event(game: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[datetime, str, str]:
    if str(event.get("sport_key") or "").strip() != NFL_ODDS_SPORT_KEY:
        raise ValueError("NFL_FORWARD_SPORT_KEY_MISMATCH")
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise ValueError("NFL_FORWARD_EVENT_ID_MISSING")
    start = _dt(game.get("game_start_ts"), "NFL_FORWARD_GAME_START_INVALID")
    event_start = _dt(event.get("commence_time"), "NFL_FORWARD_EVENT_START_INVALID")
    if event_start != start:
        raise ValueError("NFL_FORWARD_EVENT_START_MISMATCH")
    home_name, away_name = _provider_names(game, event)
    return start, home_name, away_name


def _identity(identity: Mapping[str, Any]) -> dict[str, str]:
    if identity.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_FORWARD_MODEL_ID_MISMATCH")
    if identity.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_FORWARD_FEATURE_CONTRACT_MISMATCH")
    return {
        "code_git_sha": _git_sha(identity.get("code_git_sha"), "NFL_FORWARD_CODE_SHA_INVALID"),
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "model_artifact_sha256": _hash(identity.get("model_artifact_sha256"), "NFL_FORWARD_MODEL_ARTIFACT_SHA256_INVALID"),
    }


def _distribution(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    out = [row for row in rows if isinstance(row, Mapping)]
    if not out:
        raise ValueError("NFL_FORWARD_SCORE_DISTRIBUTION_EMPTY")
    for row in out:
        for field in ("home_score", "away_score", "margin", "total"):
            _num(row.get(field), f"NFL_FORWARD_SCORE_DISTRIBUTION_INVALID:{field}")
    return out


def _probabilities(rows: list[Mapping[str, Any]], *, market: str, side: str, line: float | None) -> tuple[float, float, float]:
    wins = pushes = losses = 0
    for row in rows:
        margin = float(row["margin"])
        total = float(row["total"])
        if market == "moneyline":
            value = margin if side == "home" else -margin
        elif market == "spread":
            if line is None:
                raise ValueError("NFL_FORWARD_LINE_REQUIRED")
            value = (margin if side == "home" else -margin) + float(line)
        elif market == "total":
            if line is None:
                raise ValueError("NFL_FORWARD_LINE_REQUIRED")
            value = (total - float(line)) if side == "over" else (float(line) - total)
        else:
            raise ValueError(f"NFL_FORWARD_MARKET_UNSUPPORTED:{market}")
        if value > 0:
            wins += 1
        elif value < 0:
            losses += 1
        else:
            pushes += 1
    n = float(len(rows))
    return wins / n, pushes / n, losses / n


def _quote_pair(event: Mapping[str, Any], *, market: str, provider_home: str, provider_away: str) -> list[dict[str, Any]]:
    if market == "moneyline":
        source = _market(event, "h2h")
        outcomes = _outcomes(source)
        by_name = {str(row.get("name") or "").strip(): row for row in outcomes}
        if provider_home not in by_name or provider_away not in by_name:
            raise ValueError("NFL_FORWARD_H2H_OUTCOME_MISSING")
        return [
            {"side_key": "home", "provider_name": provider_home, "price": _num(by_name[provider_home].get("price"), "NFL_FORWARD_PRICE_INVALID"), "line": None, "other_price": _num(by_name[provider_away].get("price"), "NFL_FORWARD_PRICE_INVALID")},
            {"side_key": "away", "provider_name": provider_away, "price": _num(by_name[provider_away].get("price"), "NFL_FORWARD_PRICE_INVALID"), "line": None, "other_price": _num(by_name[provider_home].get("price"), "NFL_FORWARD_PRICE_INVALID")},
        ]
    if market == "spread":
        source = _market(event, "spreads")
        outcomes = _outcomes(source)
        by_name = {str(row.get("name") or "").strip(): row for row in outcomes}
        if provider_home not in by_name or provider_away not in by_name:
            raise ValueError("NFL_FORWARD_SPREAD_OUTCOME_MISSING")
        return [
            {"side_key": "home", "provider_name": provider_home, "price": _num(by_name[provider_home].get("price"), "NFL_FORWARD_PRICE_INVALID"), "line": _num(by_name[provider_home].get("point"), "NFL_FORWARD_LINE_INVALID"), "other_price": _num(by_name[provider_away].get("price"), "NFL_FORWARD_PRICE_INVALID")},
            {"side_key": "away", "provider_name": provider_away, "price": _num(by_name[provider_away].get("price"), "NFL_FORWARD_PRICE_INVALID"), "line": _num(by_name[provider_away].get("point"), "NFL_FORWARD_LINE_INVALID"), "other_price": _num(by_name[provider_home].get("price"), "NFL_FORWARD_PRICE_INVALID")},
        ]
    if market == "total":
        source = _market(event, "totals")
        outcomes = _outcomes(source)
        by_name = {str(row.get("name") or "").strip().lower(): row for row in outcomes}
        if "over" not in by_name or "under" not in by_name:
            raise ValueError("NFL_FORWARD_TOTAL_OUTCOME_MISSING")
        if not _same_line(by_name["over"].get("point"), by_name["under"].get("point")):
            raise ValueError("NFL_FORWARD_TOTAL_LINE_MISMATCH")
        return [
            {"side_key": "over", "provider_name": "Over", "price": _num(by_name["over"].get("price"), "NFL_FORWARD_PRICE_INVALID"), "line": _num(by_name["over"].get("point"), "NFL_FORWARD_LINE_INVALID"), "other_price": _num(by_name["under"].get("price"), "NFL_FORWARD_PRICE_INVALID")},
            {"side_key": "under", "provider_name": "Under", "price": _num(by_name["under"].get("price"), "NFL_FORWARD_PRICE_INVALID"), "line": _num(by_name["under"].get("point"), "NFL_FORWARD_LINE_INVALID"), "other_price": _num(by_name["over"].get("price"), "NFL_FORWARD_PRICE_INVALID")},
        ]
    raise ValueError(f"NFL_FORWARD_MARKET_UNSUPPORTED:{market}")


def build_forward_decision_rows(
    game: Mapping[str, Any],
    event: Mapping[str, Any],
    distribution: Iterable[Mapping[str, Any]],
    *,
    captured_at: str | datetime,
    identity: Mapping[str, Any],
) -> list[dict[str, Any]]:
    start, provider_home, provider_away = _validate_event(game, event)
    captured = _dt(captured_at, "NFL_FORWARD_DECISION_TS_INVALID")
    if captured >= start:
        raise ValueError("NFL_FORWARD_DECISION_NOT_PREGAME")
    ids = _identity(identity)
    rows = _distribution(distribution)
    event_hash = _sha256_text(event)
    game_id = str(game.get("game_id") or "").strip()
    home = str(game.get("home_team") or "").strip()
    away = str(game.get("away_team") or "").strip()
    if not game_id or not home or not away:
        raise ValueError("NFL_FORWARD_GAME_IDENTITY_MISSING")

    out: list[dict[str, Any]] = []
    for market in ("moneyline", "spread", "total"):
        evaluated: list[dict[str, Any]] = []
        for quote in _quote_pair(event, market=market, provider_home=provider_home, provider_away=provider_away):
            p_win, p_push, p_loss = _probabilities(rows, market=market, side=quote["side_key"], line=quote["line"])
            ev, quarter_kelly = _push_aware_ev(p_win=p_win, p_loss=p_loss, price=quote["price"])
            evaluated.append({**quote, "p_win": p_win, "p_push": p_push, "p_loss": p_loss, "ev": ev, "quarter_kelly": quarter_kelly})
        selected = max(evaluated, key=lambda row: (float(row["ev"]), str(row["side_key"])))
        side = selected["side_key"]
        canonical_side = home if side == "home" else away if side == "away" else side
        gate = "SHADOW_QUALIFIED" if float(selected["ev"]) > 0.0 else "REJECTED_NO_POSITIVE_EV"
        out.append({
            "decision_ts": captured.isoformat(),
            "game_start_ts": start.isoformat(),
            "game_id": game_id,
            "sport": "nfl",
            "market": market,
            "side": canonical_side,
            "book": NFL_FORWARD_BOOK,
            "line_at_decision": selected["line"],
            "price_at_decision": selected["price"],
            "model_prob": selected["p_win"],
            "model_push_prob": selected["p_push"],
            "model_loss_prob": selected["p_loss"],
            "novig_prob": _novig(selected["price"], selected["other_price"]),
            "ev": selected["ev"],
            "kelly_frac": selected["quarter_kelly"],
            "stake_units": selected["quarter_kelly"],
            "gate_result": gate,
            "selection_contract": NFL_FORWARD_SELECTION_CONTRACT,
            "provider_event_id": str(event["id"]),
            "provider_event_snapshot_sha256": event_hash,
            "provider_side_name": selected["provider_name"],
            **ids,
        })
    return out


def _find_close_quote(event: Mapping[str, Any], decision: Mapping[str, Any], provider_home: str, provider_away: str) -> tuple[float | None, float, float]:
    market = str(decision.get("market") or "").strip().lower()
    provider_name = str(decision.get("provider_side_name") or "").strip()
    decision_line = decision.get("line_at_decision")

    if market == "moneyline":
        pair = _quote_pair(event, market="moneyline", provider_home=provider_home, provider_away=provider_away)
        selected = next((row for row in pair if row["provider_name"] == provider_name), None)
        if selected is None:
            raise ValueError("NFL_FORWARD_CLOSE_SIDE_MISSING")
        return None, float(selected["price"]), _novig(selected["price"], selected["other_price"])

    if market == "spread":
        keys = ("spreads", "alternate_spreads")
        opponent = provider_away if provider_name == provider_home else provider_home
        headline_line = None
        try:
            headline = _market(event, "spreads")
            for row in _outcomes(headline):
                if str(row.get("name") or "").strip() == provider_name:
                    headline_line = _num(row.get("point"), "NFL_FORWARD_LINE_INVALID")
                    break
        except ValueError:
            pass
        for key in keys:
            try:
                outcomes = _outcomes(_market(event, key))
            except ValueError:
                continue
            selected_rows = [row for row in outcomes if str(row.get("name") or "").strip() == provider_name and _same_line(row.get("point"), decision_line)]
            other_rows = [row for row in outcomes if str(row.get("name") or "").strip() == opponent and _same_line(row.get("point"), -float(decision_line))]
            if len(selected_rows) == 1 and len(other_rows) == 1:
                price = _num(selected_rows[0].get("price"), "NFL_FORWARD_PRICE_INVALID")
                other_price = _num(other_rows[0].get("price"), "NFL_FORWARD_PRICE_INVALID")
                return headline_line, price, _novig(price, other_price)
        raise ValueError("NFL_FORWARD_ORIGINAL_THRESHOLD_QUOTE_MISSING")

    if market == "total":
        other_name = "Under" if provider_name.lower() == "over" else "Over"
        headline_line = None
        try:
            headline = _market(event, "totals")
            for row in _outcomes(headline):
                if str(row.get("name") or "").strip().lower() == provider_name.lower():
                    headline_line = _num(row.get("point"), "NFL_FORWARD_LINE_INVALID")
                    break
        except ValueError:
            pass
        for key in ("totals", "alternate_totals"):
            try:
                outcomes = _outcomes(_market(event, key))
            except ValueError:
                continue
            selected_rows = [row for row in outcomes if str(row.get("name") or "").strip().lower() == provider_name.lower() and _same_line(row.get("point"), decision_line)]
            other_rows = [row for row in outcomes if str(row.get("name") or "").strip().lower() == other_name.lower() and _same_line(row.get("point"), decision_line)]
            if len(selected_rows) == 1 and len(other_rows) == 1:
                price = _num(selected_rows[0].get("price"), "NFL_FORWARD_PRICE_INVALID")
                other_price = _num(other_rows[0].get("price"), "NFL_FORWARD_PRICE_INVALID")
                return headline_line, price, _novig(price, other_price)
        raise ValueError("NFL_FORWARD_ORIGINAL_THRESHOLD_QUOTE_MISSING")

    raise ValueError(f"NFL_FORWARD_MARKET_UNSUPPORTED:{market}")


def build_forward_close_rows(
    decisions: Iterable[Mapping[str, Any]],
    event: Mapping[str, Any],
    *,
    captured_at: str | datetime,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in decisions]
    if not rows:
        raise ValueError("NFL_FORWARD_DECISIONS_EMPTY")
    captured = _dt(captured_at, "NFL_FORWARD_CLOSE_TS_INVALID")
    first = rows[0]
    game = {
        "game_start_ts": first.get("game_start_ts"),
        "provider_home_team": event.get("home_team"),
        "provider_away_team": event.get("away_team"),
    }
    start, provider_home, provider_away = _validate_event(game, event)
    if captured >= start:
        raise ValueError("NFL_FORWARD_CLOSE_NOT_PREGAME")
    event_id = str(event.get("id") or "").strip()
    event_hash = _sha256_text(event)
    out: list[dict[str, Any]] = []
    for row in rows:
        decision_ts = _dt(row.get("decision_ts"), "NFL_FORWARD_DECISION_TS_INVALID")
        if captured <= decision_ts:
            raise ValueError("NFL_FORWARD_CLOSE_NOT_AFTER_DECISION")
        if _dt(row.get("game_start_ts"), "NFL_FORWARD_GAME_START_INVALID") != start:
            raise ValueError("NFL_FORWARD_GAME_START_MISMATCH")
        if str(row.get("provider_event_id") or "").strip() != event_id:
            raise ValueError("NFL_FORWARD_PROVIDER_EVENT_ID_MISMATCH")
        if str(row.get("book") or "").strip().lower() != NFL_FORWARD_BOOK:
            raise ValueError("NFL_FORWARD_BOOK_MISMATCH")
        closing_line, closing_price, closing_novig = _find_close_quote(event, row, provider_home, provider_away)
        out.append({
            "close_ts": captured.isoformat(),
            "game_start_ts": start.isoformat(),
            "game_id": str(row.get("game_id") or ""),
            "sport": "nfl",
            "market": str(row.get("market") or "").strip().lower(),
            "side": str(row.get("side") or "").strip(),
            "book": NFL_FORWARD_BOOK,
            "closing_line": closing_line,
            "closing_price": closing_price,
            "closing_novig_prob": closing_novig,
            "probability_line": row.get("line_at_decision"),
            "model_id": row.get("model_id"),
            "feature_contract": row.get("feature_contract"),
            "code_git_sha": row.get("code_git_sha"),
            "provider_event_id": event_id,
            "provider_event_snapshot_sha256": event_hash,
        })
    return out
