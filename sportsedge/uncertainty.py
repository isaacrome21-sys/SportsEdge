#!/usr/bin/env python3
"""Uncertainty bands + sample-size flags for research cards.

Adopts the critique that point probabilities + EV alone overstate
confidence. Every priced row on a research card gets:

  * a 95% Wilson score interval around its model probability, with
    effective n = the VERIFIED sample size behind the estimate;
  * a sample-size flag -- LOW_SAMPLE / ADEQUATE_SAMPLE / UNKNOWN_SAMPLE --
    against declared per-market-type thresholds;
  * a visible ``sample_caution`` string on every LOW_SAMPLE / UNKNOWN_SAMPLE
    row.

METHOD + ASSUMPTIONS (stated, not hidden):

  1. Wilson score interval, z = 1.96 (95%). This is a DECLARED choice, not a
     calibrated one. It treats the n_eff verified observations as if they
     were independent Bernoulli draws with a constant true event
     probability theta, and the model probability p as an estimate of
     theta the way a sample proportion would be. The model's actual
     estimator is more complex (score means, anchoring, empirical
     distributions); the interval is an approximation of the sampling-noise
     floor, not a derived credible interval.
  2. The band is a SAMPLING-NOISE FLOOR, never the full uncertainty.
     Model misspecification, quote staleness, lineup/participation
     uncertainty, and every NOT_WIRED / MISSING factor are NOT captured.
     True uncertainty is strictly wider than the band.
  3. n_eff is CONSERVATIVE by construction. For game markets it is the
     MINIMUM of the two teams' verified prior-game history counts, so the
     band is never narrower than the thinner side's data supports.
  4. Fail closed: if n_eff cannot be determined from verified fields the
     row is flagged UNKNOWN_SAMPLE and NO band is invented. A probability
     outside [0,1], or n_eff < 1, likewise yields no band.

RESEARCH ONLY. The band describes model uncertainty; it is not a promise,
not wagering authority, not validation, and never narrower than the data
supports.
"""
from __future__ import annotations

import math
import re

Z95 = 1.96
METHOD = "WILSON_95_SAMPLING_FLOOR_V1"
SCHEMA = "SPORTSEDGE_UNCERTAINTY_V1"

LOW_SAMPLE = "LOW_SAMPLE"
ADEQUATE_SAMPLE = "ADEQUATE_SAMPLE"
UNKNOWN_SAMPLE = "UNKNOWN_SAMPLE"

# Declared adequacy thresholds: market_type -> (minimum n_eff for
# ADEQUATE_SAMPLE, sample unit). Every one is an UNFITTED, DECLARED
# heuristic, NOT a calibrated edge; each must earn production status
# through the backtest harness (chronological out-of-sample).
#
# Rationale, per type:
#   GAME: the team-strength proxy is a prior-five-game scoring-margin
#       heuristic; a team with fewer than 5 verified prior games is below
#       the model's own baseline input, so the weaker side's count < 5 is
#       LOW. (Early-season cards will legitimately flag LOW -- that is the
#       point.)
#   MLB_PITCHER_PROP >= 10: the collector gates at 5 starts; adequacy
#       demands more than the collection minimum (declared).
#   MLB_BATTER_PROP >= 10: the collector already gates at >= 10 games and
#       >= 20 plate appearances; adequacy sits at that gate.
#   NFL/CFB_PLAYER_PROP >= 10: the collector gates at 5 games (spanning 3
#       seasons); adequacy is declared higher so 5-9-game estimates carry
#       an explicit LOW_SAMPLE caution.
SAMPLE_ADEQUACY_THRESHOLDS = {
    "GAME": (5, "prior_games_min_side"),
    "MLB_PITCHER_PROP": (10, "prior_starts"),
    "MLB_BATTER_PROP": (10, "prior_games"),
    "NFL_PLAYER_PROP": (10, "prior_games"),
    "CFB_PLAYER_PROP": (10, "prior_games"),
}

_GAME_MARKETS = {"ML", "SPREAD", "TOTAL"}

_HISTORY_RE = {
    "home": re.compile(r"HOME_HISTORY_COUNT:(\d+)"),
    "away": re.compile(r"AWAY_HISTORY_COUNT:(\d+)"),
}

RESEARCH_ONLY_NOTE = (
    "Sampling-noise floor only: model misspecification, quote staleness, "
    "lineup/participation uncertainty, and every NOT_WIRED/MISSING factor "
    "are NOT captured. True uncertainty is strictly wider than the band. "
    "Research only; not a promise, not wagering authority, not validation."
)


# ---------------------------------------------------------------------------
# Band math
# ---------------------------------------------------------------------------
def wilson_interval(p, n, z=Z95):
    """Wilson score interval for a binomial proportion. Pure function.

    Returns (lo, hi) clamped to [0, 1]. Raises ValueError when p is not a
    probability, n < 1, or z is not positive. Hand-verified reference
    values: wilson_interval(0.5, 100) == (0.4038, 0.5962) and
    wilson_interval(1.0, 10) == (0.7224, 1.0) at z = 1.96.
    """
    if isinstance(p, bool) or isinstance(n, bool) or isinstance(z, bool):
        raise ValueError("WILSON_BOOL_INPUT_REJECTED")
    try:
        p = float(p)
        n = float(n)
        z = float(z)
    except (TypeError, ValueError) as exc:
        raise ValueError("WILSON_NON_NUMERIC_INPUT") from exc
    if not (0.0 <= p <= 1.0):
        raise ValueError("WILSON_P_OUT_OF_RANGE")
    if n < 1 or n != math.floor(n):
        raise ValueError("WILSON_N_MUST_BE_POSITIVE_INTEGER")
    if not (z > 0):
        raise ValueError("WILSON_Z_MUST_BE_POSITIVE")
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


# ---------------------------------------------------------------------------
# Row introspection
# ---------------------------------------------------------------------------
def resolve_market_type(row):
    """Map a card row to a declared sample-size market type (or None)."""
    if not isinstance(row, dict):
        return None
    sport = str(row.get("sport") or "").upper()
    market = str(row.get("market") or "").upper()
    if market in _GAME_MARKETS:
        return "GAME"
    if sport == "MLB" and market.startswith("PITCHER_"):
        return "MLB_PITCHER_PROP"
    if sport == "MLB" and market.startswith("BATTER_"):
        return "MLB_BATTER_PROP"
    if sport == "NFL" and market.startswith("PLAYER_"):
        return "NFL_PLAYER_PROP"
    if sport == "CFB" and market.startswith("PLAYER_"):
        return "CFB_PLAYER_PROP"
    return None


def probability_of(row):
    """Return (p, None) for a valid priced probability, else (None, reason).

    Prefers the quote-bound ``model_probability``; falls back to the game
    engine's ``estimate_p``. Both are research estimates, not authority.
    """
    if not isinstance(row, dict):
        return None, "ROW_NOT_OBJECT"
    for key in ("model_probability", "estimate_p"):
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool):
            return None, f"PROBABILITY_INVALID:{key}"
        try:
            p = float(raw)
        except (TypeError, ValueError):
            return None, f"PROBABILITY_NON_NUMERIC:{key}"
        if not (0.0 <= p <= 1.0):
            return None, f"PROBABILITY_OUT_OF_RANGE:{key}"
        return p, None
    return None, "NO_PROBABILITY_ON_ROW"


def _int_count(value):
    """Verified integer count >= 0, else None (fail closed, never coerced)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (math.inf, -math.inf):
        return None
    iv = int(value)
    if iv != value or iv < 0:
        return None
    return iv


def effective_sample(row, market_type):
    """Return (n_eff, unit, None) or (None, None, reason).

    n_eff is the CONSERVATIVE verified sample behind the row's probability:
    for games, the minimum of the two teams' verified prior-game history
    counts (never the sum, never the max -- the band must not be narrower
    than the thinner side's data supports). For player props, the verified
    prior-game/start count carried on the row.
    """
    if market_type == "GAME":
        notes = " ".join(str(x) for x in (row.get("context_notes") or []))
        home = _HISTORY_RE["home"].search(notes)
        away = _HISTORY_RE["away"].search(notes)
        if not home or not away:
            return None, None, "GAME_HISTORY_COUNTS_UNRESOLVED"
        return min(int(home.group(1)), int(away.group(1))), \
            "prior_games_min_side", None
    if market_type == "MLB_PITCHER_PROP":
        n = _int_count(row.get("prior_start_count"))
        return (n, "prior_starts", None) if n is not None else \
            (None, None, "PRIOR_START_COUNT_UNRESOLVED")
    if market_type in {"MLB_BATTER_PROP", "NFL_PLAYER_PROP", "CFB_PLAYER_PROP"}:
        n = _int_count(row.get("prior_game_count"))
        return (n, "prior_games", None) if n is not None else \
            (None, None, "PRIOR_GAME_COUNT_UNRESOLVED")
    return None, None, "NO_DECLARED_THRESHOLD_FOR_MARKET_TYPE"


def flag_sample(market_type, n_eff):
    """LOW_SAMPLE / ADEQUATE_SAMPLE / UNKNOWN_SAMPLE against the declared
    per-market-type threshold. Unresolvable n -> UNKNOWN_SAMPLE (fail
    closed)."""
    if n_eff is None or market_type not in SAMPLE_ADEQUACY_THRESHOLDS:
        return UNKNOWN_SAMPLE
    threshold, _unit = SAMPLE_ADEQUACY_THRESHOLDS[market_type]
    return ADEQUATE_SAMPLE if n_eff >= threshold else LOW_SAMPLE


# ---------------------------------------------------------------------------
# Card annotation
# ---------------------------------------------------------------------------
def _caution(flag, n_eff, unit, threshold):
    if flag == LOW_SAMPLE:
        return (f"LOW_SAMPLE: model probability rests on {n_eff} {unit} "
                f"(declared adequacy minimum {threshold}); the band is wide "
                f"by construction. Estimate and any EV are fragile -- "
                f"research only, not validated.")
    if flag == UNKNOWN_SAMPLE:
        return ("UNKNOWN_SAMPLE: verified sample size behind this "
                "probability could not be determined; no uncertainty band "
                "computed. Treat the estimate and any EV with extra caution "
                "-- research only.")
    return None


def annotate_row(row):
    """Build the uncertainty block for one card row, or None.

    Returns None when the row carries no priced probability (unpriced /
    blocked rows get no band fields at all). Never invents a band: bad
    probability or undeterminable sample -> band fields None with an
    explicit band_reason, and UNKNOWN_SAMPLE where the sample is unknown.
    """
    p, p_reason = probability_of(row)
    if p is None:
        return None
    market_type = resolve_market_type(row)
    n_eff, unit, sample_reason = effective_sample(row, market_type)
    threshold = SAMPLE_ADEQUACY_THRESHOLDS.get(
        market_type, (None, None))[0] if market_type else None
    flag = flag_sample(market_type, n_eff)
    band_lo = band_hi = band_width = None
    band_reason = None
    if p_reason is not None:
        band_reason = "PROBABILITY_INVALID_NO_BAND"
    elif n_eff is None:
        band_reason = f"SAMPLE_SIZE_UNDETERMINED_NO_BAND_INVENTED:{sample_reason}"
    elif n_eff < 1:
        band_reason = "N_EFF_ZERO_NO_BAND"
    else:
        lo, hi = wilson_interval(p, n_eff)
        band_lo, band_hi = round(lo, 6), round(hi, 6)
        band_width = round(hi - lo, 6)
    return {
        "schema": SCHEMA,
        "method": METHOD,
        "probability": round(p, 6),
        "market_type": market_type or "UNKNOWN_MARKET_TYPE",
        "n_eff": n_eff,
        "sample_unit": unit,
        "adequacy_threshold": threshold,
        "sample_flag": flag,
        "band_lo": band_lo,
        "band_hi": band_hi,
        "band_width": band_width,
        "band_reason": band_reason,
        "sample_caution": _caution(flag, n_eff, unit, threshold),
        "research_only_note": RESEARCH_ONLY_NOTE,
        "research_only": True,
    }


def attach_uncertainty(rows):
    """Annotate every priced row in place; return flag counts.

    Rows without a priced probability are left untouched and counted under
    NO_PROBABILITY. The visible ``sample_caution`` string is hoisted to
    the row top level for LOW_SAMPLE / UNKNOWN_SAMPLE rows.
    """
    counts = {LOW_SAMPLE: 0, ADEQUATE_SAMPLE: 0, UNKNOWN_SAMPLE: 0,
              "NO_PROBABILITY": 0}
    for row in rows or []:
        if not isinstance(row, dict):
            counts["NO_PROBABILITY"] += 1
            continue
        block = annotate_row(row)
        if block is None:
            counts["NO_PROBABILITY"] += 1
            continue
        row["uncertainty"] = block
        counts[block["sample_flag"]] += 1
        if block["sample_caution"]:
            row["sample_caution"] = block["sample_caution"]
    return counts


def methodology_block():
    """Card-level documentation of the method, thresholds, and limits."""
    return {
        "schema": "SPORTSEDGE_UNCERTAINTY_METHOD_V1",
        "method": METHOD,
        "confidence_level": "95% (z=1.96), declared not calibrated",
        "what_the_band_is": (
            "Wilson score interval around the row's model probability with "
            "n = verified effective sample size. It is a SAMPLING-NOISE "
            "FLOOR: the minimum uncertainty the data supports, never the "
            "full uncertainty."
        ),
        "what_the_band_is_not": (
            "Not a credible interval, not a promise, not wagering "
            "authority, not validation. Model misspecification, quote "
            "staleness, lineup/participation uncertainty, and every "
            "NOT_WIRED/MISSING factor are NOT captured; true uncertainty "
            "is strictly wider."
        ),
        "effective_sample_rules": {
            "GAME": ("min(home prior-game history count, away prior-game "
                     "history count) from verified context notes; never the "
                     "sum or max"),
            "MLB_PITCHER_PROP": "verified prior_start_count",
            "MLB_BATTER_PROP": "verified prior_game_count (>=10 games and "
                               ">=20 PA already gated upstream)",
            "NFL_PLAYER_PROP": "verified prior_game_count",
            "CFB_PLAYER_PROP": "verified prior_game_count",
        },
        "adequacy_thresholds_declared_unfitted": {
            mtype: {"minimum_n_eff": thr, "sample_unit": unit}
            for mtype, (thr, unit) in SAMPLE_ADEQUACY_THRESHOLDS.items()
        },
        "fail_closed_rules": [
            "Sample size undeterminable -> UNKNOWN_SAMPLE, no band invented.",
            "Probability missing or outside [0,1] -> no band.",
            "n_eff < 1 -> no band.",
            "Unpriced/blocked rows (no probability) get no uncertainty block.",
        ],
        "research_only": True,
    }
