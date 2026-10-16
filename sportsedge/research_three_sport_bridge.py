"""Pure three-sport research pricing bridge: independent model p -> paired DK -> EV.

THIS IS NOT A MODEL. Only trusted internal model runtimes may call this with
their generated predictions. Never accept probabilities from the lines issue.
Missing prop predictions and unavailable/incoherent LIVE data fail closed.
No odds APIs, paid endpoints, Model_P, betting authority, or staking.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import isfinite
from typing import Mapping, Sequence

from .quote_freshness import (
    MAX_QUOTE_AGE_SECONDS,
    QUOTE_FRESH,
    QUOTE_FUTURE,
    QUOTE_INVALID,
    QUOTE_STALE,
    QUOTE_UNVERIFIED,
    check_quote_freshness,
)

SPORTS = frozenset({"NFL", "MLB", "CFB"})
GAME_MARKETS = frozenset({
    "ML", "MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL",
    "F5_ML", "F5_SPREAD", "F5_TOTAL", "F5_TEAM_TOTAL",
    "TOTAL_1H", "SPREAD_1H", "TEAM_TOTAL_1H", "ML_1H", "NRFI", "YRFI",
})
ODDS_CAP = -165
EV_MIN = 0.02
# Legacy bound name kept for backward compatibility; the single source of
# truth is sportsedge.quote_freshness.MAX_QUOTE_AGE_SECONDS.
MAX_AGE_SECONDS = MAX_QUOTE_AGE_SECONDS


def _bridge_quote_status(captured_at, *, now):
    """Map the centralized freshness verdict onto this bridge's legacy labels.

    Labels are unchanged (STALE_QUOTE / RECENT_CAPTURED_QUOTE /
    UNVERIFIED_QUOTE_FRESHNESS) so downstream consumers keep working; the
    classification now comes from the one centralized check.
    """
    code = check_quote_freshness(captured_at, now=now)["code"]
    if code == QUOTE_FRESH:
        return "RECENT_CAPTURED_QUOTE"
    if code in (QUOTE_STALE, QUOTE_FUTURE):
        return "STALE_QUOTE"
    if code in (QUOTE_UNVERIFIED, QUOTE_INVALID):
        return "UNVERIFIED_QUOTE_FRESHNESS"
    raise ResearchQuoteError("QUOTE_FRESHNESS_CODE_UNRECOGNIZED:" + code)


class ResearchQuoteError(ValueError):
    pass


def _num(x, name):
    if isinstance(x, bool):
        raise ResearchQuoteError(name + ":BAD_NUMERIC")
    try:
        value = float(x)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ResearchQuoteError(name + ":BAD_NUMERIC") from exc
    if not isfinite(value):
        raise ResearchQuoteError(name + ":NONFINITE")
    return value


def _time(x, label):
    try:
        t = datetime.fromisoformat(str(x or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ResearchQuoteError(label + ":BAD_TIME") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ResearchQuoteError(label + ":TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def _decimal(price):
    p = _num(price, "AMERICAN_ODDS")
    if int(p) != p or abs(p) < 100:
        raise ResearchQuoteError("AMERICAN_ODDS:INVALID")
    return (1 + p / 100) if p > 0 else (1 + 100 / -p)


def _key(row):
    sport = str(row.get("sport") or "").upper()
    if sport not in SPORTS:
        raise ResearchQuoteError("SPORT_UNSUPPORTED")
    if sport == "CFB":
        # Illinois college betting restrictions also apply to player props.
        # Exact team aliases reuse the central free-model disallow list.
        from artifacts.free_models import IL_COLLEGE_NAMES
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        if not home or not away:
            raise ResearchQuoteError("CFB_TEAMS_REQUIRED_FOR_ILLINOIS_FILTER")
        def normalized(name):
            return " ".join("".join(c.lower() if c.isalnum() else " "
                                    for c in name).split())
        if normalized(home) in IL_COLLEGE_NAMES or normalized(away) in IL_COLLEGE_NAMES:
            raise ResearchQuoteError("ILLINOIS_COLLEGE_EXCLUDED")
    game = str(row.get("game_id") or "").strip()
    if not game:
        raise ResearchQuoteError("GAME_ID_REQUIRED")
    market = str(row.get("market") or "").upper().strip()
    if not market:
        raise ResearchQuoteError("MARKET_REQUIRED")
    player = str(row.get("player_id") or "").strip()
    if market not in GAME_MARKETS and not player:
        raise ResearchQuoteError("PROP_PLAYER_ID_REQUIRED")
    line = None if row.get("line") is None else _num(row["line"], "LINE")
    if market in {"ML", "MONEYLINE", "F5_ML", "ML_1H", "NRFI", "YRFI"}:
        if line is not None:
            raise ResearchQuoteError("LINE_MUST_BE_NULL")
    elif line is None:
        raise ResearchQuoteError("LINE_REQUIRED")
    return sport, game, market, player, line


def _side(row):
    side = str(row.get("selection") or row.get("side") or "").upper().strip()
    if side not in {"OVER", "UNDER", "HOME", "AWAY", "YES", "NO"}:
        raise ResearchQuoteError("SIDE_INVALID")
    return side


def _opposite(side):
    return {"OVER": "UNDER", "UNDER": "OVER", "HOME": "AWAY",
            "AWAY": "HOME", "YES": "NO", "NO": "YES"}[side]


def _matching_opposite(key, other):
    if key[:4] != other[:4]:
        return False
    if key[2] in {"SPREAD", "F5_SPREAD", "SPREAD_1H"}:
        return key[4] is not None and other[4] is not None and abs(key[4] + other[4]) < 1e-9
    return key[4] == other[4]


def _model(model, now):
    key = _key(model)
    if model.get("status") != "PRICED_RESEARCH":
        raise ResearchQuoteError("NO_INDEPENDENT_MODEL_PROBABILITY")
    if model.get("market_blind") is not True or not str(model.get("model_source") or "").strip():
        raise ResearchQuoteError("MARKET_BLIND_MODEL_SOURCE_REQUIRED")
    if model.get("validated_vs_close") is True or model.get("official_authority") is True:
        raise ResearchQuoteError("RESEARCH_AUTHORITY_ONLY")
    observed = _time(model.get("as_of_utc"), "MODEL_AS_OF")
    if observed > now:
        raise ResearchQuoteError("FUTURE_MODEL_SOURCE")
    win = _num(model.get("estimate_p"), "MODEL_P")
    push = _num(model.get("push_p", 0), "PUSH_P")
    if not 0 <= win <= 1 or not 0 <= push < 1 or win + push > 1 + 1e-9:
        raise ResearchQuoteError("MODEL_MASS_INVALID")
    conditional = win / (1 - push)
    if not 0 < conditional < 1:
        raise ResearchQuoteError("MODEL_CONDITIONAL_PROBABILITY_INVALID")
    fair = (-100 * conditional / (1 - conditional) if conditional >= .5
            else 100 * (1 - conditional) / conditional)
    return key, win, push, conditional, round(fair)


def price_three_sport_research(model_rows: Sequence[Mapping], quotes: Sequence[Mapping],
                               *, as_of, ev_floor=EV_MIN):
    """Return model-versus-DK research rows; never compute model p from odds.

    Source models must have verified their pregame/live feature provenance.
    This is only a quote-binding stage; a flag is NOT proof of model provenance.
    """
    now = _time(as_of, "AS_OF")
    floor = _num(ev_floor, "EV_FLOOR")
    if not 0 <= floor <= .15:
        raise ResearchQuoteError("EV_FLOOR_OUT_OF_RANGE")
    parsed_quotes = []
    for i, row in enumerate(quotes):
        try:
            key = _key(row)
            side = _side(row)
            if str(row.get("book") or "").lower() not in {"dk", "draftkings"}:
                continue
            price = _num(row.get("odds"), "DK_ODDS")
            _decimal(price)
            captured = (_time(row["quote_captured_at"], "QUOTE_AS_OF")
                        if row.get("quote_captured_at") else None)
            parsed_quotes.append((i, key, side, int(price), captured))
        except (ValueError, KeyError, TypeError):
            continue
    rows = []
    for i, model in enumerate(model_rows):
        identity = {"input_index": i, "sport": model.get("sport"), "game_id": model.get("game_id"),
                    "market": model.get("market"), "selection": model.get("selection"),
                    "player_id": model.get("player_id")}
        try:
            key, win, push, conditional, fair = _model(model, now)
            side = _side(model)
            ours = [q for q in parsed_quotes if q[1] == key and q[2] == side]
            others = [q for q in parsed_quotes
                      if _matching_opposite(key, q[1]) and q[2] == _opposite(side)]
            if len(ours) != 1 or len(others) != 1:
                raise ResearchQuoteError("EXACT_PAIRED_DK_QUOTE_REQUIRED")
            own, other = ours[0], others[0]
            # A pair is two independently captured quote ROWS, not a
            # screenshot assertion on just one side. Both timestamps must
            # be timezone-aware and at most 120 seconds apart; absent data
            # cannot support an exact two-sided no-vig benchmark.
            if own[4] is None or other[4] is None:
                raise ResearchQuoteError("PAIRED_QUOTES_CAPTURE_TIMESTAMPS_REQUIRED")
            pair_skew_seconds = abs((own[4] - other[4]).total_seconds())
            if pair_skew_seconds > 120:
                raise ResearchQuoteError("PAIRED_QUOTES_CAPTURE_WINDOW_EXCEEDED")
            # Both sides need individually fresh captures to surface a
            # current-price candidate. One recent side never refreshes an
            # old, future, or otherwise invalid opposite-side quote.
            own_freshness = _bridge_quote_status(own[4], now=now)
            other_freshness = _bridge_quote_status(other[4], now=now)
            freshness = ("RECENT_CAPTURED_QUOTE"
                         if own_freshness == other_freshness == "RECENT_CAPTURED_QUOTE"
                         else "STALE_QUOTE"
                         if "STALE_QUOTE" in (own_freshness, other_freshness)
                         else "UNVERIFIED_QUOTE_FRESHNESS")
            kickoff = _time(model.get("kickoff_utc"), "KICKOFF")
            phase = str(model.get("phase") or "PREGAME").upper()
            if phase == "PREGAME" and kickoff <= now:
                raise ResearchQuoteError("GAME_STARTED_REQUIRES_LIVE_MODEL_AND_LIVE_QUOTES")
            if phase == "LIVE":
                state = model.get("live_state")
                if (not isinstance(state, Mapping) or
                    not all(state.get(k) is not None
                            for k in ("period", "clock", "home_score", "away_score")) or
                    not state.get("verified_source") or
                    model.get("live_model") is not True or freshness != "RECENT_CAPTURED_QUOTE"):
                    raise ResearchQuoteError("VERIFIED_LIVE_MODEL_STATE_AND_QUOTES_REQUIRED")
            elif phase != "PREGAME":
                raise ResearchQuoteError("PHASE_UNSUPPORTED")
            dec, opposite_dec = _decimal(own[3]), _decimal(other[3])
            market = (1 / dec) / ((1 / dec) + (1 / opposite_dec))
            loss = 1 - win - push
            ev = win * (dec - 1) - loss
            row = {**identity, "model_source": model.get("model_source"),
                   "model_probability": round(win, 6),
                   "model_conditional_p": round(conditional, 6),
                   "model_push_p": round(push, 6), "fair_american": fair,
                   "dk_odds": own[3], "dk_no_vig_p": round(market, 6),
                   "edge_pp": round(100 * (conditional - market), 3),
                   "ev_per_dollar": round(ev, 6), "quote_status": freshness,
                   "paired_quote_skew_seconds": round(pair_skew_seconds, 3),
                   "paired_quote_captured_at": [own[4].isoformat(),
                                                other[4].isoformat()],
                   "research_only": True, "official_authority": False,
                   "model_p_authority": False, "staking_authority": False}
            if freshness != "RECENT_CAPTURED_QUOTE":
                row["status"] = "WATCH_QUOTE_NOT_CURRENT"
            elif own[3] < ODDS_CAP:
                row["status"] = "WATCH_PRICE_CAP"
            elif ev < floor:
                row["status"] = "WATCH_BELOW_EV_FLOOR"
            else:
                row["status"] = "RESEARCH_CANDIDATE_NOT_VALIDATED"
            rows.append(row)
        except (ValueError, KeyError, TypeError) as exc:
            rows.append({**identity, "status": "NO_MODEL_OR_MARKET",
                         "reason": str(exc)[:150], "research_only": True,
                         "official_authority": False, "staking_authority": False})
    rows.sort(key=lambda r: (r["status"] != "RESEARCH_CANDIDATE_NOT_VALIDATED",
                             -r.get("ev_per_dollar", -1e6), str(r.get("game_id"))))
    return {"schema": "SPORTSEDGE_THREE_SPORT_GAMES_PROPS_RESEARCH_V1",
            "sports": ["NFL", "MLB", "CFB"], "as_of_utc": now.isoformat(),
            "authority": {"research_only": True, "official": False,
                          "model_p": False, "staking": False},
            "price_cap": ODDS_CAP, "ev_floor": floor, "rows": rows,
            "status_counts": dict(Counter(r["status"] for r in rows))}
