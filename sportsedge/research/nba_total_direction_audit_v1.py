"""Read-only direction/bias audit of an already-scored NBA V2 history screen.

This is descriptive research, not probability calibration, a backtest admission,
an entry in a forward ledger, or a candidate/PLAY gate. Its parent screen must
have done its own strict point-in-time filtering. No market total is ever used
to change a forecast, and there is no post-hoc OVER/UNDER balancing.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from random import Random
from statistics import mean
from zoneinfo import ZoneInfo

from .nba_totals_chronological_screen_v1 import SCREEN

AUDIT = "NBA_TOTAL_DIRECTION_AUDIT_V1"
BOOTSTRAP_SEED = 17
BOOTSTRAP_DRAWS = 500
SLATE_ZONE = ZoneInfo("America/Chicago")


def _number(value, label):
    if isinstance(value, bool):
        raise ValueError(label + "_INVALID")
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + "_INVALID") from exc
    if not isfinite(n):
        raise ValueError(label + "_INVALID")
    return n


def _date(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NBA_TOTAL_BIAS_EVENT_START_INVALID") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("NBA_TOTAL_BIAS_EVENT_START_NAIVE")
    # SportsEdge NBA slates use Chicago game dates; UTC would split late
    # evening games off from their local slate and distort day clusters.
    return t.astimezone(SLATE_ZONE).date().isoformat()


def _cluster_interval(rows, key):
    """Calendar-day resampling, descriptive only; preserves games per day."""
    groups = defaultdict(list)
    for r in rows:
        groups[r["day"]].append(r[key])
    if len(groups) < 2:
        return None
    strata = [(sum(g), len(g)) for _, g in sorted(groups.items())]
    rng = Random(BOOTSTRAP_SEED)
    estimates = []
    for _ in range(BOOTSTRAP_DRAWS):
        draws = [strata[rng.randrange(len(strata))] for _ in strata]
        estimates.append(sum(s for s, _ in draws) / sum(n for _, n in draws))
    estimates.sort()
    return [estimates[int((BOOTSTRAP_DRAWS - 1) * p)] for p in (0.025, 0.975)]


def audit_total_directions(screen):
    """Consume the untouched output of ``chronological_total_screen`` only.

    Compare forecast-minus-actual (absolute scoring-level bias) separately
    from forecast-minus-market (directional quote disagreement). A model can
    favor UNDER often without systematically underpredicting actual scores.
    These are diagnostic distinctions, not probabilities or betting results.
    """
    if (not isinstance(screen, dict) or screen.get("screen_id") != SCREEN
            or screen.get("status") != "HISTORICAL_SCREEN_ONLY"
            or screen.get("research_only") is not True
            or screen.get("play_authority") is not False
            or screen.get("market_admission") != "NOT_VERIFIED"):
        raise ValueError("NBA_TOTAL_BIAS_PARENT_SCREEN_NOT_RESEARCH_ONLY")
    source = screen.get("rows")
    if not isinstance(source, list) or not isinstance(screen.get("counts"), dict):
        raise ValueError("NBA_TOTAL_BIAS_PARENT_ROWS_MISSING")
    if (screen["counts"].get("model_priced") != len(source)
            or screen["counts"].get("paired_with_timestamped_market_reference")
            != sum(r.get("market_close") is not None for r in source if isinstance(r, dict))):
        raise ValueError("NBA_TOTAL_BIAS_PARENT_CONSERVATION_FAILED")

    seen = set()
    all_rows, paired = [], []
    directions = {"UNDER": {"rows": 0, "hit": 0, "loss": 0, "push": 0},
                  "OVER": {"rows": 0, "hit": 0, "loss": 0, "push": 0},
                  "TIE": {"rows": 0}}
    for row in source:
        if not isinstance(row, dict):
            raise ValueError("NBA_TOTAL_BIAS_ROW_INVALID")
        eid = str(row.get("event_id") or "").strip()
        if not eid or eid in seen:
            raise ValueError("NBA_TOTAL_BIAS_DUPLICATE_OR_MISSING_EVENT")
        seen.add(eid)
        day = _date(row.get("event_start"))
        actual = _number(row.get("actual"), "NBA_TOTAL_BIAS_ACTUAL")
        model = _number(row.get("candidate_total"), "NBA_TOTAL_BIAS_MODEL")
        clim = _number(row.get("climatology_total"), "NBA_TOTAL_BIAS_CLIMATOLOGY")
        if min(actual, model, clim) <= 0:
            raise ValueError("NBA_TOTAL_BIAS_NONPOSITIVE_TOTAL")
        if (abs(_number(row.get("candidate_error"), "NBA_TOTAL_BIAS_CANDIDATE_ERROR")
                - (model - actual)) > 1e-8
                or abs(_number(row.get("baseline_error"), "NBA_TOTAL_BIAS_BASELINE_ERROR")
                       - (clim - actual)) > 1e-8):
            raise ValueError("NBA_TOTAL_BIAS_PARENT_ERROR_MISMATCH")
        entry = {"day": day, "model_minus_actual": model - actual}
        all_rows.append(entry)
        if row.get("market_close") is None:
            if "market_reference_error" in row:
                raise ValueError("NBA_TOTAL_BIAS_UNPAIRED_MARKET_ERROR")
            continue
        market = _number(row["market_close"], "NBA_TOTAL_BIAS_MARKET")
        if (market <= 0 or row.get("independent_market_admission") != "NOT_VERIFIED"
                or abs(_number(row.get("market_reference_error"),
                               "NBA_TOTAL_BIAS_MARKET_ERROR") - (market - actual)) > 1e-8):
            raise ValueError("NBA_TOTAL_BIAS_MARKET_PAIR_INVALID")
        side = "UNDER" if model < market else "OVER" if model > market else "TIE"
        directions[side]["rows"] += 1
        if side != "TIE":
            outcome = "push" if actual == market else (
                "hit" if (actual < market if side == "UNDER" else actual > market)
                else "loss")
            directions[side][outcome] += 1
        paired.append({**entry, "model_minus_market": model - market,
                       "market_minus_actual": market - actual})

    directional = directions["UNDER"]["rows"] + directions["OVER"]["rows"]
    signed_bias = mean(r["model_minus_actual"] for r in all_rows) if all_rows else None
    quote_gap = mean(r["model_minus_market"] for r in paired) if paired else None
    scored_dates = len({r["day"] for r in paired})
    # A warning for the extreme behavior seen in the Oct 21 card. It has no
    # effect on ranking, candidate probabilities, promotions, or price gates.
    warning = (directional >= 20 and scored_dates >= 5
               and max(directions["UNDER"]["rows"], directions["OVER"]["rows"])
               / directional >= 0.8)
    return {"audit_id": AUDIT, "source_screen_id": SCREEN,
            "status": "RESEARCH_DIAGNOSTIC_ONLY",
            "all_model_rows": len(all_rows), "paired_rows": len(paired),
            "paired_distinct_dates": scored_dates,
            "direction": directions,
            "under_share_of_directional_rows": (
                directions["UNDER"]["rows"] / directional if directional else None),
            "mean_model_minus_actual": signed_bias,
            "mean_model_minus_market": quote_gap,
            "mean_market_minus_actual": (
                mean(r["market_minus_actual"] for r in paired) if paired else None),
            "model_vs_actual_day_bootstrap_95pct": _cluster_interval(all_rows, "model_minus_actual"),
            "model_vs_market_day_bootstrap_95pct": _cluster_interval(paired, "model_minus_market"),
            "one_direction_warning": warning,
            "warning_criteria": "AT_LEAST_20_NON_TIE_PAIRS_5_DATES_AND_80_PERCENT_ONE_DIRECTION",
            "market_admission": "NOT_VERIFIED",
            "no_betting_odds_or_roi": True,
            "source_receipts_reverified": False,
            "historical_entry_authority": False,
            "forward_entry_authority": False,
            "model_p_authority": False,
            "play_authority": False,
            "research_only": True}
