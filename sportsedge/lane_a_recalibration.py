"""Lane A vNext probability-recalibration layer (UNVALIDATED, ADOPTED).

Basis: the EV-band calibration diagnostic of 2026-10-28
(``calibration_diagnostic_20261028`` in the operative records). On the
pooled graded record Oct 23-27, 2026 (183 decided selection legs with a
printed model probability), Lane A's claimed probabilities were globally
inflated: pooled Brier score 0.2740 for the model vs 0.2404 for the raw
market-implied probabilities on the model's own selections, and a
least-squares shrink fit

    p_used = implied + k * (model_p - implied)

gave k = -0.46 -- the model's deviations from market price were
anti-informative in that sample. The diagnostic's one supported
adjustment, for the UNFROZEN Lane A research line only, is this layer:
re-estimate k from the trailing graded record, floor it at 0, and derive
EV from p_used. On the current record the fit floors to k = 0, i.e. the
layer would present ~zero claimed edge until future graded cards earn a
positive k. That consequence is the point of the diagnostic.

Status and limits:

- This layer is UNVALIDATED and ADOPTED. Adoption was an
  owner-delegated decision: Isaac presented the adoption question with
  the >=6-point disagreement guard and answered "Do what you think is
  best" (Oct 28, 2026, ~15:44 CT); Rocky adopted both, recorded in
  ``research/lane_a_recalibration_20261028/ADOPTION_RECORD.md``. Card
  production applies the layer through
  ``sportsedge.lane_a_card_gates`` (which passes ``enabled=True``
  explicitly); adoption changes placement of Lane A research rows
  only — it validates nothing.
- ``RECALIBRATION_ENABLED`` defaults to True since the adoption. With
  the flag off (callers may still pass ``enabled=False``),
  :func:`apply_recalibration` returns its input object unchanged (same
  object, no keys added, no mutation), so pricing output is
  byte-identical to the pre-layer engine.
- The layer wraps Lane A OUTPUT (the priced-result dicts produced by
  ``artifacts/free_models.calculate`` / ``run``). It deliberately does
  not edit ``artifacts/free_models.py``: the frozen NFL team-totals
  runner hash-pins that file (``sportsedge/nfl_team_total_runner.py``
  records ``artifacts_free_models_sha256``), and no frozen construction
  or evaluator is touched by this module.
- Raw numbers are never hidden: when the layer is applied, the raw
  Lane A ``estimate_p`` and ``ev_per_dollar`` stay exactly where the
  engine put them, the recalibration block carries both the raw and the
  recalibrated values, and a log line records model_p and p_used for
  every priced row processed.
- Honest sample-size rule: below ``MIN_DECIDED_LEGS_WITH_MODEL_P``
  (180) decided legs with a printed model probability -- the
  diagnostic's stated sufficiency for refitting k -- the estimate
  reports k = 0 with reason ``INSUFFICIENT_SAMPLE`` instead of a noisy
  point estimate. Per the diagnostic, roughly 180 FURTHER decided legs
  beyond the current 183 are needed before a refit interval is usable
  for an adoption decision; the standard error and 95% interval are
  reported with the estimate so that width is visible, never buried.
"""

from __future__ import annotations

import copy
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

LOGGER = logging.getLogger("sportsedge.lane_a_recalibration")

LAYER_NAME = "LANE_A_VNEXT_PROBABILITY_RECALIBRATION"

# Config flag. Defaults to TRUE since the owner-delegated adoption of
# Oct 28, 2026 (see ADOPTION_RECORD.md). The apply functions take
# ``enabled`` explicitly so tests never need to mutate this constant,
# and the card gates pass it explicitly regardless of this default.
RECALIBRATION_ENABLED = True

# Diagnostic sufficiency (2026-10-28 report, sections 4 and 6): a
# shrink-k refit needs ~180 decided selection legs carrying a printed
# model probability before a point estimate is reported at all.
MIN_DECIDED_LEGS_WITH_MODEL_P = 180

REASON_ESTIMATED = "ESTIMATED"
REASON_NEGATIVE_FIT_FLOORED_AT_ZERO = "NEGATIVE_FIT_FLOORED_AT_ZERO"
REASON_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
REASON_DEGENERATE_NO_MODEL_DEVIATION = "DEGENERATE_NO_MODEL_DEVIATION"

SOURCE_GRADED_ROWS_REFIT = "GRADED_ROWS_REFIT"
SOURCE_DIAGNOSTIC_SUMMARY_FIT = "DIAGNOSTIC_SUMMARY_FIT"

_BLOCK_KEY = "recalibration"


@dataclass(frozen=True)
class KEstimate:
    """One shrink-k estimate from a trailing graded record.

    ``k_raw`` is the unfloored least-squares fit, or None when no point
    estimate is reported (insufficient sample or a degenerate record
    with no model/market deviation). ``k_used`` is what the layer
    applies: the fit floored at 0, so the layer can only shrink claimed
    edges toward the market, never amplify them and never reverse them.
    """

    n_decided_legs: int
    k_raw: Optional[float]
    k_used: float
    reason: str
    source: str
    min_decided_legs: int = MIN_DECIDED_LEGS_WITH_MODEL_P
    se: Optional[float] = None
    ci95_low: Optional[float] = None
    ci95_high: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_decided_legs": self.n_decided_legs,
            "k_raw": self.k_raw,
            "k_used": self.k_used,
            "reason": self.reason,
            "source": self.source,
            "min_decided_legs": self.min_decided_legs,
            "se": self.se,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _probability(value: Any) -> Optional[float]:
    if _is_number(value) and 0.0 <= value <= 1.0:
        return float(value)
    return None


def _decided_legs(
    rows: Iterable[Mapping[str, Any]],
) -> list[tuple[float, float, float]]:
    """Extract (model_p, implied_p, outcome) for decided, p-carrying legs.

    A leg counts toward the refit only when it is decided (WIN/LOSS --
    pushes are undecided and excluded, exactly as in the diagnostic)
    and carries both a model probability (``model_p``, or the Lane A
    view's ``estimate_p``) and a market-implied probability
    (``implied_p`` / ``implied``). Rows missing either probability do
    not count toward the sample, mirroring the diagnostic's "decided
    selection legs with a printed model p" universe.
    """
    legs: list[tuple[float, float, float]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        model_p = _probability(row.get("model_p", row.get("estimate_p")))
        implied_p = _probability(row.get("implied_p", row.get("implied")))
        if model_p is None or implied_p is None:
            continue
        outcome = row.get("outcome", row.get("result"))
        won: Optional[float] = None
        if isinstance(outcome, str):
            token = outcome.strip().upper()
            if token in ("WIN", "WON", "W"):
                won = 1.0
            elif token in ("LOSS", "LOST", "L"):
                won = 0.0
            elif token in ("PUSH", "PUSHED", "VOID", "TIE"):
                won = None
        elif isinstance(row.get("won"), bool):
            won = 1.0 if row["won"] else 0.0
        if won is None:
            continue
        legs.append((model_p, implied_p, won))
    return legs


def _fit_shrink_k(
    legs: Sequence[tuple[float, float, float]],
) -> Optional[tuple[float, float]]:
    """Least-squares fit of p_used = implied + k*(model_p - implied).

    Regresses (outcome - implied) on (model_p - implied) through the
    origin -- the fit the diagnostic's section 4 reports. Returns
    (k, standard_error), or None when the record carries no model/market
    deviation at all (denominator zero: k is unidentified, not zero).
    """
    sdd = 0.0
    sdr = 0.0
    for model_p, implied_p, won in legs:
        d = model_p - implied_p
        sdd += d * d
        sdr += d * (won - implied_p)
    if sdd <= 0.0:
        return None
    k = sdr / sdd
    n = len(legs)
    if n > 1:
        sse = 0.0
        for model_p, implied_p, won in legs:
            resid = (won - implied_p) - k * (model_p - implied_p)
            sse += resid * resid
        sigma2 = sse / (n - 1)
        se = math.sqrt(sigma2 / sdd)
    else:
        se = float("nan")
    return k, se


def _floored(
    *,
    n: int,
    k_raw: Optional[float],
    se: Optional[float],
    source: str,
    min_decided_legs: int,
    insufficient_reason: str = REASON_INSUFFICIENT_SAMPLE,
) -> KEstimate:
    if n < min_decided_legs:
        return KEstimate(
            n_decided_legs=n,
            k_raw=None,
            k_used=0.0,
            reason=insufficient_reason,
            source=source,
            min_decided_legs=min_decided_legs,
        )
    if k_raw is None:
        return KEstimate(
            n_decided_legs=n,
            k_raw=None,
            k_used=0.0,
            reason=REASON_DEGENERATE_NO_MODEL_DEVIATION,
            source=source,
            min_decided_legs=min_decided_legs,
        )
    ci_low = ci_high = None
    if se is not None and math.isfinite(se):
        ci_low = k_raw - 1.96 * se
        ci_high = k_raw + 1.96 * se
    if k_raw < 0.0:
        reason = REASON_NEGATIVE_FIT_FLOORED_AT_ZERO
    else:
        reason = REASON_ESTIMATED
    return KEstimate(
        n_decided_legs=n,
        k_raw=k_raw,
        k_used=max(0.0, k_raw),
        reason=reason,
        source=source,
        min_decided_legs=min_decided_legs,
        se=se,
        ci95_low=ci_low,
        ci95_high=ci_high,
    )


def estimate_k(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_decided_legs: int = MIN_DECIDED_LEGS_WITH_MODEL_P,
) -> KEstimate:
    """Re-estimate shrink k from graded rows (the trailing record).

    Below ``min_decided_legs`` decided legs with a printed model
    probability, no point estimate is reported: k_used is 0 with reason
    INSUFFICIENT_SAMPLE. Otherwise the least-squares fit is reported
    unfloored as ``k_raw`` and applied floored at 0 as ``k_used``.
    """
    legs = _decided_legs(rows)
    fit = _fit_shrink_k(legs) if len(legs) >= min_decided_legs else None
    if fit is None and len(legs) >= min_decided_legs:
        return _floored(
            n=len(legs), k_raw=None, se=None,
            source=SOURCE_GRADED_ROWS_REFIT,
            min_decided_legs=min_decided_legs,
        )
    k_raw, se = fit if fit is not None else (None, None)
    return _floored(
        n=len(legs), k_raw=k_raw, se=se,
        source=SOURCE_GRADED_ROWS_REFIT,
        min_decided_legs=min_decided_legs,
    )


def estimate_k_from_summary(
    summary: Mapping[str, Any],
    *,
    min_decided_legs: int = MIN_DECIDED_LEGS_WITH_MODEL_P,
) -> KEstimate:
    """Apply the sufficiency + floor rules to a diagnostic summary fit.

    Accepts a summary.json-shaped mapping (the 2026-10-28 calibration
    diagnostic's shape): ``calibration.brier_n_legs`` is the count of
    decided legs with a printed model probability and
    ``calibration.shrink_fit_k_pooled`` is that record's published
    least-squares fit. The published fit is treated exactly like a
    refit: below sufficiency it is not surfaced as an estimate, and a
    negative fit floors to k_used = 0.
    """
    calibration = summary.get("calibration") if isinstance(summary, Mapping) else None
    if not isinstance(calibration, Mapping):
        raise ValueError("RECALIBRATION_SUMMARY_FIT_MISSING")
    n = calibration.get("brier_n_legs")
    k_fit = calibration.get("shrink_fit_k_pooled")
    if not _is_number(n) or not _is_number(k_fit):
        raise ValueError("RECALIBRATION_SUMMARY_FIT_MISSING")
    return _floored(
        n=int(n), k_raw=float(k_fit), se=None,
        source=SOURCE_DIAGNOSTIC_SUMMARY_FIT,
        min_decided_legs=min_decided_legs,
    )


def estimate_k_from_summary_file(
    path: str | Path,
    *,
    min_decided_legs: int = MIN_DECIDED_LEGS_WITH_MODEL_P,
) -> KEstimate:
    with open(path, encoding="utf-8") as handle:
        summary = json.load(handle)
    return estimate_k_from_summary(summary, min_decided_legs=min_decided_legs)


def recalibrate_probability(model_p: float, implied_p: float, k: float) -> float:
    """p_used = implied + k*(model_p - implied), bounded to [0, 1].

    ``k`` must already be floored (>= 0): the floor is a property of
    the layer, and a negative k reaching this function is a caller bug,
    refused loudly rather than silently applied (a negative k would
    reverse the model's deviations, which the diagnostic reports as an
    in-sample artifact, not an adopted rule).
    """
    if not _is_number(model_p) or not _is_number(implied_p) or not _is_number(k):
        raise ValueError("RECALIBRATION_INPUT_NOT_NUMERIC")
    if k < 0.0:
        raise ValueError("RECALIBRATION_K_NEGATIVE")
    p_used = implied_p + k * (model_p - implied_p)
    return min(1.0, max(0.0, p_used))


def _decimal_odds(american: Any) -> float:
    """American -> decimal odds, mirroring the engine's conversion."""
    if not _is_number(american) or american == 0:
        raise ValueError("RECALIBRATION_ODDS_INVALID")
    american = float(american)
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def ev_per_dollar(win_p: float, push_p: float, odds_american: Any) -> float:
    """EV per dollar at the quoted price, the engine's own formula.

    Mirrors ``artifacts/free_models._lane_view``: loss is the bounded
    complement of win + push, and ev = win*(dec - 1) - loss. At
    win_p == book break-even the value is exactly 0.
    """
    dec = _decimal_odds(odds_american)
    loss = min(1.0, max(0.0, 1.0 - win_p - push_p))
    return win_p * (dec - 1.0) - loss


def _lane_a_view(result: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    lanes = result.get("pricing_lanes")
    if isinstance(lanes, Mapping):
        view = lanes.get("lane_a_independent")
        if isinstance(view, Mapping):
            return view
    view = result.get("independent_projection")
    if isinstance(view, Mapping):
        return view
    return None


def apply_recalibration(
    result: dict[str, Any],
    estimate: KEstimate,
    *,
    enabled: bool = RECALIBRATION_ENABLED,
    logger: Optional[logging.Logger] = None,
) -> dict[str, Any]:
    """Apply the layer to one Lane A priced-result dict.

    Flag off (``enabled=False``): returns ``result`` itself --
    the same object, unmutated, no keys added -- so downstream pricing
    output is byte-identical to the pre-layer engine.

    Flag on: returns a deep copy carrying a ``recalibration`` block
    with p_used and the p_used-derived EV alongside the raw model
    values (which remain untouched everywhere the engine put them),
    and emits one log line per priced row recording both the raw
    model_p and p_used. A row whose Lane A view cannot supply the
    needed numbers is returned (as a copy) with the block marked
    NOT_APPLIED_INPUT_MISSING -- visibly not recalibrated, never
    silently passed off as recalibrated.
    """
    if not enabled:
        return result
    if not isinstance(result, dict):
        raise ValueError("RECALIBRATION_RESULT_NOT_OBJECT")
    log = logger or LOGGER
    out = copy.deepcopy(result)
    view = _lane_a_view(out)
    model_p = _probability(view.get("estimate_p")) if view is not None else None
    implied_p = (
        _probability(view.get("book_break_even_p")) if view is not None else None
    )
    push_p = _probability(view.get("push_p")) if view is not None else None
    if model_p is None or implied_p is None or push_p is None:
        out[_BLOCK_KEY] = {
            "layer": LAYER_NAME,
            "status": "NOT_APPLIED_INPUT_MISSING",
            "validation_status": "UNVALIDATED",
            "adoption_status": "ADOPTED_OWNER_DELEGATED_20261028",
            "k": estimate.k_used,
            "k_reason": estimate.reason,
        }
        log.warning(
            "RECALIBRATION_NOT_APPLIED game=%s selection=%s reason=LANE_A_VIEW_MISSING",
            out.get("game"), out.get("selection"),
        )
        return out
    p_used = recalibrate_probability(model_p, implied_p, estimate.k_used)
    raw_ev = view.get("ev_per_dollar")
    if not _is_number(raw_ev):
        raw_ev = ev_per_dollar(model_p, push_p, out.get("odds_american"))
    ev_used = ev_per_dollar(p_used, push_p, out.get("odds_american"))
    block = {
        "layer": LAYER_NAME,
        "status": "APPLIED",
        "validation_status": "UNVALIDATED",
        "adoption_status": "ADOPTED_OWNER_DELEGATED_20261028",
        "k": estimate.k_used,
        "k_raw": estimate.k_raw,
        "k_reason": estimate.reason,
        "k_source": estimate.source,
        "k_n_decided_legs": estimate.n_decided_legs,
        "model_p": model_p,
        "implied_p": implied_p,
        "push_p": push_p,
        "p_used": round(p_used, 6),
        "ev_per_dollar_model_p": raw_ev,
        "ev_per_dollar": round(ev_used, 6),
        "ev_basis_if_adopted": "P_USED",
        "raw_model_values_preserved": True,
    }
    out[_BLOCK_KEY] = block
    log.info(
        "RECALIBRATION game=%s selection=%s model_p=%.6f implied_p=%.6f "
        "p_used=%.6f k=%.6f k_reason=%s",
        out.get("game"), out.get("selection"), model_p, implied_p,
        p_used, estimate.k_used, estimate.reason,
    )
    return out


def apply_recalibration_to_rows(
    results: list[dict[str, Any]],
    estimate: KEstimate,
    *,
    enabled: bool = RECALIBRATION_ENABLED,
    logger: Optional[logging.Logger] = None,
) -> list[dict[str, Any]]:
    """Apply the layer to a card's priced rows.

    Flag off: returns the SAME list object. Flag on: a new list of
    recalibrated copies, one log line per priced row.
    """
    if not enabled:
        return results
    return [
        apply_recalibration(row, estimate, enabled=True, logger=logger)
        for row in results
    ]


def effective_probability(result: Mapping[str, Any]) -> Optional[float]:
    """The probability gates would use: p_used when the layer has been
    applied to this row, otherwise the raw Lane A model probability."""
    block = result.get(_BLOCK_KEY)
    if isinstance(block, Mapping) and block.get("status") == "APPLIED":
        return _probability(block.get("p_used"))
    view = _lane_a_view(result)
    if view is not None:
        return _probability(view.get("estimate_p"))
    return _probability(result.get("estimate_p"))


def effective_ev(result: Mapping[str, Any]) -> Optional[float]:
    """The EV gates would use: the p_used-derived EV when the layer
    has been applied to this row, otherwise the row's raw EV."""
    block = result.get(_BLOCK_KEY)
    if isinstance(block, Mapping) and block.get("status") == "APPLIED":
        value = block.get("ev_per_dollar")
        return float(value) if _is_number(value) else None
    value = result.get("ev_per_dollar")
    return float(value) if _is_number(value) else None
