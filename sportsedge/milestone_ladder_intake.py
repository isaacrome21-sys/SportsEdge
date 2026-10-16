"""Milestone-ladder prop intake adapter (owner contract, Isaac Oct 14 2026).

DraftKings serves several headline prop families ONLY as milestone ladders
-- rungs "X+" with American odds on the event {stat >= X} -- not as
over/under pairs (MLB pitcher strikeouts; MLB batter home runs,
extra-base hits, triples, batter strikeouts and runs+RBIs; football
passing yards; the mirror "N or Fewer" form for earned runs). Canonical
intake requires O/U
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
refuses the row with its own existing named blocker. The three-sport
research bridge binds a one-sided row only when the family's validation
state in the canonical coverage authority is VALIDATED, and otherwise
refuses it with MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:<state> --
naming the validation state, not the quote form (no family is VALIDATED
today, so converted rows still refuse downstream).

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

Per-rung duplicate disposition (Oct 14 2026 operative-run defect):
DraftKings hangs BOTH forms for some families -- a native two-sided
O/U at the main line AND the milestone ladder whose rung converts to
that same line (Snell K: native Over 6.5 and ladder 7+; ER: native
Under 1.5 and ladder "1 or Fewer"). The converted rung and the native
quote are the SAME book quote on the same pairing identity (sport,
game, player, market, side, line); emitting both hands the downstream
paired-quote bridge two quotes for one side and its exactly-one rule
refuses the genuine pair (EXACT_PAIRED_DK_QUOTE_REQUIRED). So a
converted rung that duplicates an existing NATIVE quote row in the
same intake list is NOT emitted as a quote: it is emitted as a named
disposition row (``LADDER_RUNG_DUPLICATES_NATIVE_QUOTE``) carrying
both prices in ``milestone_duplicate`` -- if the prices differ that is
a data conflict, recorded as such; prices are never merged, averaged
or silently picked between. Only exact-identity duplicates are
suppressed; every other rung converts normally and keeps its one-sided
fate downstream.

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
# Per-rung disposition (not a whole-ladder refusal): the converted rung
# duplicates an existing native quote row on the full pairing identity.
REFUSAL_DUPLICATES_NATIVE_QUOTE = "LADDER_RUNG_DUPLICATES_NATIVE_QUOTE"

_FORM_X_PLUS = {"X_PLUS", "MILESTONE_X_PLUS", "PLUS", "GE"}
_FORM_OR_FEWER = {"OR_FEWER", "MILESTONE_OR_FEWER", "FEWER", "LE"}

# MLB integer counting-stat pitcher AND batter markets (single sources
# of truth are sportsedge.mlb_phone_pitcher_pricing.PITCHER_MARKETS and
# sportsedge.mlb_phone_batter_pricing.BATTER_MARKETS; imported lazily
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
    # Presence of the key, even with malformed content, must be treated
    # as a ladder-intake attempt and refused by name, not passed onward.
    return isinstance(row, Mapping) and "milestone_ladder" in row


# Parser-only coverage is NOT a claim of an executable probability engine.
# Offered DK count-stat ladders with no engine behind them must reach an
# explicit downstream NO_ENGINE/NO_QUOTE refusal instead of dying at
# parser recognition. (The three families #2273 parked here --
# BATTER_EXTRA_BASE_HITS, BATTER_TRIPLES, PITCHER_PITCHES -- graduated
# to engine-backed phone market sets with the Oct 14 wiring completion:
# the empirical gamelog engine prices triples and the exact
# doubles+triples+home-runs sum, and the joint engine prices measured
# per-start pitch counts. The set is empty today; park future
# engine-less families here rather than widening the phone sets.)
_MLB_PARSER_ONLY = frozenset()


def _supported(sport: str, market: str) -> bool:
    if sport == "MLB":
        from .mlb_phone_pitcher_pricing import PITCHER_MARKETS
        from .mlb_phone_batter_pricing import BATTER_MARKETS
        return (market in PITCHER_MARKETS or market in BATTER_MARKETS
                or market in _MLB_PARSER_ONLY)
    if sport == "NFL":
        from .nfl_phone_player_pricing import NFL_PLAYER_MARKETS
        return market in NFL_PLAYER_MARKETS or market in _FOOTBALL_PASSING_MARKETS
    if sport == "CFB":
        from .cfb_phone_player_pricing import CFB_PLAYER_MARKETS
        # The family registry gate still refuses all CFB pricing before
        # any player-stat model stage is reached; syntax != authority.
        return market in CFB_PLAYER_MARKETS or market in _FOOTBALL_PASSING_MARKETS
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
    A per-rung duplicate disposition keeps its audit detail (both the
    ladder and native prices, and whether they conflict) so the
    suppression is visible in the card, never silent.
    """
    row = {
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
    if line.get("line") is not None:
        # A per-rung disposition names its converted line (a refused
        # whole ladder has no single line and stays without one).
        row["line"] = line.get("line")
    duplicate = line.get("milestone_duplicate")
    if isinstance(duplicate, Mapping):
        row["milestone_duplicate"] = dict(duplicate)
    return row


def _as_line(value):
    """Numeric line as float, or None when not a finite number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        line = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return line if isfinite(line) else None


def _game_key(row) -> tuple:
    """Game identity from raw intake fields: teams + start instant.

    The start instant is compared as a parsed instant when parseable
    (so equivalent spellings of one instant match) and as the raw
    string otherwise; a missing start compares as empty.
    """
    raw_start = row.get("kickoff") or row.get("commence_time")
    instant = _parse_instant(raw_start)
    start_key = (instant.isoformat() if instant is not None
                 else str(raw_start or "").strip())
    return (_norm_name(row.get("away")), _norm_name(row.get("home")),
            start_key)


def _quote_identity(row, *, default_sport=None):
    """Full pairing identity of a binary quote row, or None.

    (sport, game, market, player, side, line) -- the identity the
    downstream paired-quote bridge keys on, expressed in raw intake
    fields. Only OVER/UNDER rows with a named player and a numeric
    line have a prop pairing identity.
    """
    side = str(row.get("side") or row.get("selection") or "").upper().strip()
    if side not in {"OVER", "UNDER"}:
        return None
    player = _norm_name(row.get("player_name") or row.get("label"))
    if not player:
        return None
    line = _as_line(row.get("line"))
    if line is None:
        return None
    sport = str(row.get("sport") or default_sport or "").upper().strip()
    market = str(row.get("market") or "").upper().strip()
    if not sport or not market:
        return None
    return (sport, _game_key(row), market, player, side, line)


def _native_quote_index(rows, *, default_sport=None) -> dict:
    """Pairing identity -> native quote evidence, from non-ladder rows.

    A row counts as a native quote only when it carries a valid
    American price; a malformed native row must never suppress a rung.
    """
    index = {}
    for row in rows:
        if not isinstance(row, Mapping) or is_milestone_ladder_row(row):
            continue
        if row.get("milestone_ladder_refusal"):
            continue
        identity = _quote_identity(row, default_sport=default_sport)
        if identity is None:
            continue
        odds = _as_odds(row.get("odds", row.get("price")))
        if odds is None:
            continue
        index.setdefault(identity, []).append({
            "odds": odds,
            "quote_captured_at": row.get("quote_captured_at"),
        })
    return index


def _duplicate_disposition_row(converted: dict, native_matches: list) -> dict:
    """Named non-quote row for a converted rung duplicating a native quote.

    The rung's own price keys are removed so the row can never enter a
    quote set; both prices ride in ``milestone_duplicate`` for audit.
    A price difference is a data conflict and is flagged, never merged.
    """
    row = {k: v for k, v in converted.items() if k not in ("odds", "price")}
    ladder_odds = converted.get("odds")
    native_odds_values = sorted({m["odds"] for m in native_matches})
    row["milestone_ladder_refusal"] = REFUSAL_DUPLICATES_NATIVE_QUOTE
    row["milestone_duplicate"] = {
        "ladder_odds": ladder_odds,
        "native_odds": native_matches[0]["odds"],
        "native_odds_values": native_odds_values,
        "native_matches": len(native_matches),
        "native_quote_captured_at": native_matches[0]["quote_captured_at"],
        "price_conflict": any(m["odds"] != ladder_odds
                              for m in native_matches),
    }
    return row


def _expand_one(row: Mapping, *, default_sport=None,
                native_quotes=None) -> list:
    base = {k: v for k, v in row.items() if k != "milestone_ladder"}
    ladder = row.get("milestone_ladder")
    if not isinstance(ladder, Mapping):
        return [_refusal_row(base, REFUSAL_MALFORMED)]
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
    # Never hash untrusted capture objects: dict/list/malformed timestamps
    # must produce a named refusal, not a TypeError in the runner.
    captures = [c for _, _, c in rungs]
    parsed_instants = [_parse_instant(c) for c in captures]
    if any(instant is None for instant in parsed_instants):
        return [_refusal_row(base, REFUSAL_MALFORMED)]
    if len(set(parsed_instants)) != 1:
        return [_refusal_row(base, REFUSAL_MIXED_CAPTURE)]
    shared_capture = captures[0]  # deterministic original capture string
    rungs = [(t, o, shared_capture) for t, o, _ in rungs]

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
        if native_quotes:
            identity = _quote_identity(out, default_sport=default_sport)
            matches = native_quotes.get(identity) if identity else None
            if matches:
                # The book already hangs this exact quote natively;
                # the converted rung must not become a second quote
                # on the pairing identity. Emit the named disposition
                # instead -- the native row keeps its own provenance.
                emitted.append(_duplicate_disposition_row(out, matches))
                continue
        emitted.append(out)
    return emitted


def expand_milestone_ladder_rows(rows: Sequence, *, default_sport=None) -> list:
    """Expand every milestone-ladder row in *rows* into canonical rows.

    Non-ladder rows pass through untouched. A valid ladder emits one
    canonical OVER (resp. UNDER) row per rung; a refused ladder emits a
    single row carrying ``milestone_ladder_refusal`` for the runner's
    prop intake to block by name. Row order is preserved: a ladder's
    emitted rows occupy the ladder row's position, rungs ascending.

    A converted rung whose full pairing identity duplicates a native
    (non-ladder) quote row elsewhere in *rows* is emitted as a
    ``LADDER_RUNG_DUPLICATES_NATIVE_QUOTE`` disposition row instead of
    a second quote (see the module docstring); the native row itself
    is passed through untouched.
    """
    native_quotes = _native_quote_index(rows, default_sport=default_sport)
    out = []
    for row in rows:
        if is_milestone_ladder_row(row):
            out.extend(_expand_one(row, default_sport=default_sport,
                                   native_quotes=native_quotes))
        else:
            out.append(row)
    return out
