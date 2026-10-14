"""Milestone-ladder prop intake adapter (owner contract, Isaac Oct 14 2026).

DraftKings serves several headline prop families ONLY as milestone ladders
-- rungs "X+" with American odds on the event {stat >= X} -- not as
over/under pairs (MLB pitcher strikeouts; football passing yards; the
mirror "N or Fewer" form for earned runs). Canonical intake requires O/U
rows, so without this adapter those families die at intake instead of
reaching their pricers or their named blockers.

Conversion (SPEC revision 2,
~/workspace/sportsedge/milestone_ladder_ingestion_20261014/SPEC.md):
for integer-valued props a milestone threshold converts WITHOUT changing
its meaning -- "X+" is the event Over (X - 0.5); "N or Fewer" is the event
Under (N + 0.5). Each rung emits ONE canonical row carrying:

* the REAL offered price for that side (the milestone quote's American
  odds, unchanged),
* the ladder's single shared original ``quote_captured_at`` (never
  retimestamped),
* one-sided provenance: ``source_quote_form`` is ``MILESTONE_X_PLUS`` for
  a >= ladder and ``MILESTONE_OR_FEWER`` for a <= ladder, plus the
  original integer ``milestone_threshold``.

NO opposite-side price is ever invented. A milestone quote is one-sided:
it can support an EV calculation against an independently estimated
probability, but it cannot establish a two-sided no-vig market. This
module performs NO de-vigging, fair-line derivation, or complement-price
synthesis; any downstream component that requires an opposite quote
refuses the row with its own existing named blocker (e.g. the three-sport
research bridge's EXACT_PAIRED_DK_QUOTE_REQUIRED).

Fail-closed ladder validation (SPEC section 3; the whole ladder refuses,
never a partial emission):

* ``MILESTONE_LADDER_NON_MONOTONE`` -- implied probabilities not
  non-increasing in X for a >= ladder (non-decreasing for <=).
* ``MILESTONE_LADDER_DUPLICATE_RUNG`` -- same threshold twice.
* ``MILESTONE_LADDER_MIXED_CAPTURE`` -- rungs do not share one capture
  instant.
* ``MILESTONE_LADDER_PLAYER_MISMATCH`` -- a rung names a different player
  than the ladder row.
* ``MILESTONE_LADDER_MARKET_UNSUPPORTED`` -- ladder form submitted for a
  sport/market this adapter does not convert.
* ``MILESTONE_LADDER_MALFORMED`` -- structural defects (no rungs,
  non-integer threshold, invalid American odds, missing player, missing
  shared capture).

Irregular rung spacing is legal by design (DraftKings inserts main-line
rungs such as 226+); gaps are never interpolated. A ladder with a single
rung is a single milestone quote and converts as one binary row.

Input row shape (an ordinary intake row plus one extra key)::

    {"sport": "MLB", "market": "PITCHER_K", "player_name": "Blake Snell",
     "away": ..., "home": ..., "kickoff": ...,
     "book": "draftkings", "quote_captured_at": "<iso8601>",
     "milestone_ladder": {"form": "X_PLUS",
                          "rungs": [{"threshold": 3, "odds": -2600}, ...]}}

The mirror form uses ``"form": "OR_FEWER"`` and thresholds meaning
{stat <= N}. A rung may be a mapping (``threshold``/``value``,
``odds``/``price``, optional ``player_name``/``player``/``label``,
optional ``quote_captured_at``) or a ``(threshold, odds)`` pair.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Mapping, Sequence

# One-sided provenance values carried on every emitted row.
MILESTONE_X_PLUS = "MILESTONE_X_PLUS"
MILESTONE_OR_FEWER = "MILESTONE_OR_FEWER"

# Named whole-ladder refusals (SPEC section 3).
REFUSAL_NON_MONOTONE = "MILESTONE_LADDER_NON_MONOTONE"
REFUSAL_DUPLICATE_RUNG = "MILESTONE_LADDER_DUPLICATE_RUNG"
REFUSAL_MIXED_CAPTURE = "MILESTONE_LADDER_MIXED_CAPTURE"
REFUSAL_PLAYER_MISMATCH = "MILESTONE_LADDER_PLAYER_MISMATCH"
REFUSAL_MARKET_UNSUPPORTED = "MILESTONE_LADDER_MARKET_UNSUPPORTED"
REFUSAL_MALFORMED = "MILESTONE_LADDER_MALFORMED"

_FORM_X_PLUS = {"X_PLUS", "MILESTONE_X_PLUS", "PLUS", "GE"}
_FORM_OR_FEWER = {"OR_FEWER", "MILESTONE_OR_FEWER", "FEWER", "LE"}

# MLB integer counting-stat pitcher markets (single source of truth is
# sportsedge.mlb_phone_pitcher_pricing.PITCHER_MARKETS; imported lazily
# in _supported so this module stays dependency-light at import time).
_FOOTBALL_PASSING_MARKETS = frozenset({
    "PLAYER_PASSING_YARDS", "PLAYER_PASS_YARDS",
    "PASS_YARDS", "PASSING_YARDS",
})

# Keys that would assert a book price for a side DraftKings never quoted.
# Intake junk under these names is stripped from emitted rows so a
# milestone conversion can never smuggle in a fabricated opposite price.
_OPPOSITE_PRICE_KEYS = frozenset({
    "opposite_odds", "opposite_price", "under_odds", "over_odds",
    "paired_odds", "complement_odds", "complement_price",
    "no_vig_p", "dk_no_vig_p", "fair_odds", "fair_price",
})


def is_milestone_ladder_row(row) -> bool:
    """True when *row* carries a ``milestone_ladder`` mapping."""
    return isinstance(row, Mapping) and isinstance(
        row.get("milestone_ladder"), Mapping)


def _supported(sport: str, market: str) -> bool:
    if sport == "MLB":
        from .mlb_phone_pitcher_pricing import PITCHER_MARKETS
        return market in PITCHER_MARKETS
    if sport in {"NFL", "CFB"}:
        # CFB converts identically; its rows then die at the standing
        # identity/registry gates in the runner (HOLD -- no CFB pricing
        # path is created here).
        return market in _FOOTBALL_PASSING_MARKETS
    return False


def _implied_p(odds: int) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def _as_threshold(value):
    """Integer threshold or None when the value is not integer-valued."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if isfinite(value) and value.is_integer() else None
    if isinstance(value, str):
        text = value.strip().rstrip("+")
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _as_odds(value):
    """American odds as int, or None when not a valid book price."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        odds = value
    elif isinstance(value, float) and isfinite(value) and value.is_integer():
        odds = int(value)
    elif isinstance(value, str):
        try:
            odds = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    return odds if abs(odds) >= 100 else None


def _parse_instant(value):
    """Aware datetime for an ISO-8601 value, else None."""
    if value is None:
        return None
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if instant.tzinfo is None or instant.utcoffset() is None:
        return None
    return instant.astimezone(timezone.utc)


def _norm_name(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _refusal_row(base: dict, reason: str) -> dict:
    row = dict(base)
    row.pop("milestone_ladder", None)
    row["milestone_ladder_refusal"] = reason
    return row


def milestone_refusal_row(line) -> dict:
    """Fail-closed card row for a refused ladder (runner prop intake).

    Mirrors the phone pricers' blocked-row shape so refused ladders land
    in prop_unpriced with the named milestone reason and no price fields.
    """
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": str(line.get("milestone_ladder_refusal") or REFUSAL_MALFORMED),
        "sport": line.get("sport"),
        "market": line.get("market"),
        "selection": line.get("side") or line.get("selection"),
        "player_name": line.get("player_name") or line.get("label"),
        "source_quote_form": "MILESTONE_LADDER_REFUSED",
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }


def _expand_one(row: Mapping, *, default_sport=None) -> list:
    base = {k: v for k, v in row.items() if k != "milestone_ladder"}
    ladder = row.get("milestone_ladder") or {}
    sport = str(base.get("sport") or default_sport or "").upper().strip()
    market = str(base.get("market") or "").upper().strip()

    if not _supported(sport, market):
        return [_refusal_row(base, REFUSAL_MARKET_UNSUPPORTED)]

    form_raw = str(ladder.get("form") or "").upper().strip()
    if form_raw in _FORM_X_PLUS:
        form = "X_PLUS"
    elif form_raw in _FORM_OR_FEWER:
        form = "OR_FEWER"
    else:
        return [_refusal_row(base, REFUSAL_MALFORMED)]

    player = str(base.get("player_name") or base.get("label") or "").strip()
    if not player:
        return [_refusal_row(base, REFUSAL_MALFORMED)]

    raw_rungs = ladder.get("rungs")
    if not isinstance(raw_rungs, (list, tuple)) or not raw_rungs:
        return [_refusal_row(base, REFUSAL_MALFORMED)]

    ladder_capture = ladder.get("quote_captured_at") or base.get(
        "quote_captured_at")

    rungs = []  # (threshold:int, odds:int, effective_capture_raw)
    for raw in raw_rungs:
        if isinstance(raw, Mapping):
            threshold = _as_threshold(
                raw.get("threshold", raw.get("value")))
            odds = _as_odds(raw.get("odds", raw.get("price")))
            rung_player = (raw.get("player_name") or raw.get("player")
                           or raw.get("label"))
            capture = raw.get("quote_captured_at") or ladder_capture
        elif isinstance(raw, (list, tuple)) and len(raw) == 2:
            threshold = _as_threshold(raw[0])
            odds = _as_odds(raw[1])
            rung_player = None
            capture = ladder_capture
        else:
            return [_refusal_row(base, REFUSAL_MALFORMED)]
        if rung_player is not None and _norm_name(rung_player) != _norm_name(player):
            return [_refusal_row(base, REFUSAL_PLAYER_MISMATCH)]
        if threshold is None or odds is None:
            return [_refusal_row(base, REFUSAL_MALFORMED)]
        rungs.append((threshold, odds, capture))

    # One shared capture for the whole ladder (SPEC rule 3). Each rung's
    # effective capture already fell back to the ladder/row-level value,
    # so any remaining diversity is genuinely mixed. Distinct strings
    # naming the same instant still count as one shared capture.
    captures = {c for _, _, c in rungs}
    if captures == {None}:
        return [_refusal_row(base, REFUSAL_MALFORMED)]
    if len(captures) > 1:
        instants = {_parse_instant(c) for c in captures}
        if len(instants) == 1 and None not in instants:
            shared_capture = next(iter(captures))
            rungs = [(t, o, shared_capture) for t, o, _ in rungs]
        else:
            return [_refusal_row(base, REFUSAL_MIXED_CAPTURE)]
    else:
        shared_capture = next(iter(captures))
        if _parse_instant(shared_capture) is None:
            return [_refusal_row(base, REFUSAL_MALFORMED)]

    thresholds = [t for t, _, _ in rungs]
    if len(set(thresholds)) != len(thresholds):
        return [_refusal_row(base, REFUSAL_DUPLICATE_RUNG)]

    rungs.sort(key=lambda r: r[0])
    if len(rungs) > 1:
        probs = [_implied_p(o) for _, o, _ in rungs]
        if form == "X_PLUS":
            monotone = all(a >= b for a, b in zip(probs, probs[1:]))
        else:
            monotone = all(a <= b for a, b in zip(probs, probs[1:]))
        if not monotone:
            return [_refusal_row(base, REFUSAL_NON_MONOTONE)]

    emitted = []
    for threshold, odds, _ in rungs:
        out = {k: v for k, v in base.items()
               if k not in _OPPOSITE_PRICE_KEYS}
        out.pop("selection", None)
        out.pop("milestone_ladder", None)
        if form == "X_PLUS":
            out["side"] = "OVER"
            out["line"] = threshold - 0.5
            out["source_quote_form"] = MILESTONE_X_PLUS
        else:
            out["side"] = "UNDER"
            out["line"] = threshold + 0.5
            out["source_quote_form"] = MILESTONE_OR_FEWER
        out["odds"] = odds
        out["price"] = odds
        out["quote_captured_at"] = shared_capture
        out["milestone_threshold"] = threshold
        out["milestone_form"] = form
        emitted.append(out)
    return emitted


def expand_milestone_ladder_rows(rows: Sequence, *, default_sport=None) -> list:
    """Expand every milestone-ladder row in *rows* into canonical rows.

    Non-ladder rows pass through untouched. A valid ladder emits one
    canonical OVER (resp. UNDER) row per rung; a refused ladder emits a
    single row carrying ``milestone_ladder_refusal`` for the runner's
    prop intake to block by name. Row order is preserved: a ladder's
    emitted rows occupy the ladder row's position, rungs ascending.
    """
    out = []
    for row in rows:
        if is_milestone_ladder_row(row):
            out.extend(_expand_one(row, default_sport=default_sport))
        else:
            out.append(row)
    return out
