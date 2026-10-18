"""Pure three-sport research pricing bridge: independent model p -> paired DK -> EV.

THIS IS NOT A MODEL. Only trusted internal model runtimes may call this with
their generated predictions. Never accept probabilities from the lines issue.
Missing prop predictions and unavailable/incoherent LIVE data fail closed.
No odds APIs, paid endpoints, Model_P, betting authority, or staking.

Single-side milestone binding (owner policy): a one-sided quote set for a
prop market -- exactly one own-side quote and no opposite-side quote at ANY
line, the shape milestone ladders convert into -- is priceable ONLY when the
family's validation state in the canonical coverage authority
(sportsedge.canonical_coverage.resolve_market, the same lookup
artifacts/run_it_full.py applies to every card row) is VALIDATED. EV then
binds the model probability against the single quoted price only; no de-vig
benchmark exists, so single-side rows carry NO dk_no_vig_p / edge_pp and are
labeled ev_basis=MODEL_PROBABILITY_VS_SINGLE_QUOTED_PRICE_NO_DEVIG. When the
family is not VALIDATED the row refuses with
MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:<state> -- the refusal names
the validation state, never the quote form. No family is VALIDATED in the
authority today, so one-sided rows still refuse, now for the stated reason.

Why _model still refuses a model row asserting validated_vs_close
(RESEARCH_AUTHORITY_ONLY): that flag is a SELF-assertion carried inside the
model row, and this bridge never lets a model row certify itself. Validation
is read from the external authority at quote-binding time, never from the
row. The two checks are complementary: self-asserted authority is refused;
authority-pronounced validation is honored for single-side binding. Paired
rows are unaffected either way -- their success status remains
RESEARCH_CANDIDATE_NOT_VALIDATED by construction of this research bridge,
and this bridge grants no official/staking authority on any row.
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


def _enforce_phase(model, now, freshness):
    """Pregame/live phase gate shared by the paired and single-side paths."""
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


def _family_validation_state(sport, market, validation_resolver):
    """Family validation state from the canonical coverage authority.

    The authority is sportsedge.canonical_coverage.resolve_market -- the
    same lookup the canonical card path applies to every market. Returns its
    validation_status (upper-cased), or "NO_COVERAGE_RESOLUTION" when the
    authority has no entry (or no status) for the family. Fail closed: any
    resolver error also yields "NO_COVERAGE_RESOLUTION", which is not
    VALIDATED, so single-side binding refuses. This is deliberately NOT read
    from the model row: a row asserting its own validation is refused in
    _model (RESEARCH_AUTHORITY_ONLY); validation is pronounced by the
    authority, never self-declared.
    """
    resolver = validation_resolver
    if resolver is None:
        from .canonical_coverage import resolve_market as resolver
    try:
        resolution = resolver(sport, market)
    except Exception:
        resolution = None
    if isinstance(resolution, Mapping):
        state = resolution.get("validation_status")
        if state:
            return str(state).upper()
    return "NO_COVERAGE_RESOLUTION"


def _single_side_row(*, identity, model, key, win, push, conditional, fair,
                     own, now, floor, validation_state):
    """Price a one-sided prop quote for a VALIDATED family.

    EV binds the model probability against the single quoted price only.
    There is no opposite side, hence no de-vig benchmark: the row carries no
    dk_no_vig_p and no edge_pp, and ev_basis labels the basis explicitly.
    Status ladder mirrors the paired path (freshness, price cap, EV floor);
    only the success status differs, naming the single-side validated basis
    instead of the paired path's RESEARCH_CANDIDATE_NOT_VALIDATED.
    """
    if own[4] is None:
        raise ResearchQuoteError("SINGLE_SIDE_QUOTE_CAPTURE_TIMESTAMP_REQUIRED")
    freshness = _bridge_quote_status(own[4], now=now)
    _enforce_phase(model, now, freshness)
    dec = _decimal(own[3])
    loss = 1 - win - push
    ev = win * (dec - 1) - loss
    row = {**identity, "model_source": model.get("model_source"),
           "model_probability": round(win, 6),
           "model_conditional_p": round(conditional, 6),
           "model_push_p": round(push, 6), "fair_american": fair,
           "dk_odds": own[3],
           "ev_per_dollar": round(ev, 6), "quote_status": freshness,
           "quote_form": "SINGLE_SIDE",
           "ev_basis": "MODEL_PROBABILITY_VS_SINGLE_QUOTED_PRICE_NO_DEVIG",
           "family_validation_status": validation_state,
           "validation_authority": "SPORTSEDGE_CANONICAL_COVERAGE",
           "quote_captured_at": own[4].isoformat(),
           "research_only": True, "official_authority": False,
           "model_p_authority": False, "staking_authority": False}
    if freshness != "RECENT_CAPTURED_QUOTE":
        row["status"] = "WATCH_QUOTE_NOT_CURRENT"
    elif own[3] < ODDS_CAP:
        row["status"] = "WATCH_PRICE_CAP"
    elif ev < floor:
        row["status"] = "WATCH_BELOW_EV_FLOOR"
    else:
        row["status"] = "RESEARCH_CANDIDATE_SINGLE_SIDE_VALIDATED"
    return row


def price_three_sport_research(model_rows: Sequence[Mapping], quotes: Sequence[Mapping],
                               *, as_of, ev_floor=EV_MIN, validation_resolver=None):
    """Return model-versus-DK research rows; never compute model p from odds.

    Source models must have verified their pregame/live feature provenance.
    This is only a quote-binding stage; a flag is NOT proof of model provenance.

    validation_resolver: optional (sport, market) -> resolution-mapping
    callable used ONLY by the single-side milestone stage to read a family's
    validation state. Production callers pass nothing and get the canonical
    coverage authority (sportsedge.canonical_coverage.resolve_market); the
    parameter exists so tests can fixture an authority verdict without
    editing any family's recorded state.
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
            if (len(ours) == 1 and len(others) == 0
                    and key[2] not in GAME_MARKETS
                    and not any(q[1][:4] == key[:4] and q[2] == _opposite(side)
                                for q in parsed_quotes)):
                # One-sided quote set: the book hung no opposite side for
                # this player/market at any line (the milestone-ladder
                # shape). An opposite quote at a MISMATCHED line is an
                # incoherent pair instead and keeps the paired refusal
                # below. Gate on the family's validation state, read from
                # the canonical coverage authority -- never on quote form
                # and never on the model row's self-assertion.
                validation_state = _family_validation_state(
                    key[0], key[2], validation_resolver)
                if validation_state != "VALIDATED":
                    raise ResearchQuoteError(
                        "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:"
                        + validation_state)
                rows.append(_single_side_row(
                    identity=identity, model=model, key=key, win=win,
                    push=push, conditional=conditional, fair=fair,
                    own=ours[0], now=now, floor=floor,
                    validation_state=validation_state))
                continue
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
            _enforce_phase(model, now, freshness)
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
