"""Lane A card gates — ADOPTED recalibration + disagreement guard.

Adoption: owner-delegated decision, 2026-10-28. Isaac presented the two
proposals (recalibration adoption; a >=6-point model-vs-market
disagreement guard) with an options widget and answered "Do what you
think is best" (Oct 28, 2026, ~15:44 CT). Rocky adopted BOTH. Full
record: ``research/lane_a_recalibration_20261028/ADOPTION_RECORD.md``.

What this module does, at the card-build boundary, for every Lane A
priced row:

1. RECALIBRATION (adopted from PR #2874): the row is passed through
   ``sportsedge.lane_a_recalibration.apply_recalibration`` with the
   supplied trailing-record k estimate, and headline/bucket placement
   is derived from the recalibrated (effective) EV — never from the
   raw Lane A EV. With the adoption-time estimate (diagnostic fit
   k_raw = -0.461 on 183 decided legs, floored to k_used = 0), every
   effective EV is ~0 and no Lane A row headlines until future graded
   cards earn a positive k under the refit rule in the adoption
   record. Raw model values stay on the row, untouched.

2. DISAGREEMENT GUARD (adopted the same act): for point-spread sports
   (NBA, NFL, CFB), a row whose model projection disagrees with the
   market by >= ``GUARD_THRESHOLD_POINTS`` points goes to the
   overconfidence bucket REGARDLESS of EV — margin disagreement for
   SPREAD and ML rows (model projected home margin vs the market
   home margin implied by the game's spread pair), total disagreement
   for TOTAL rows (model projected total vs the market total line).
   This is the structural repair for the Oct 28, 2026 margin-
   compression failure, in which the Lane A heuristic projected every
   NBA margin inside ~4.5 points while market spreads ran to 13.5 and
   the compressed rows squeaked under the +40% EV wire at +33-39%.
   MLB is outside the guard's scope (the run line is a fixed 1.5
   handicap, not a market margin estimate); recalibration still
   applies to MLB rows.

3. EXISTING CARD GATES, unchanged and applied on effective EV:
   >= +40% effective EV -> overconfidence bucket; price shorter than
   -165 -> excluded; >= +3% effective EV -> headline; otherwise
   excluded below threshold. Fact-based withholds (e.g. the Tier-1
   injury-blindness rule) remain a card-build step applied after
   these gates, exactly as before.

Fail-closed rules: a row the recalibration layer cannot apply to
(missing Lane A view) is BLOCKED, never headlined on raw numbers; a
SPREAD/ML row in a guard-scope sport whose market margin cannot be
derived from the game's spread pair carries
``guard_evaluable = False`` and cannot headline either. Non-mapping
rows are refused by name — this is a build-time tool and a malformed
row must fail the build loudly, not slip onto a card.

This module changes PRESENTATION AND PLACEMENT of Lane A research
rows only. It validates nothing: the recalibration layer and Lane A
itself remain UNVALIDATED, research-only, PAPER / 0u. No frozen
construction, evaluator, or pin is touched.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Optional

from sportsedge import lane_a_recalibration as rc

GATE_VERSION = "LANE_A_CARD_GATES_V1_ADOPTED_20261028"

GUARD_THRESHOLD_POINTS = 6.0
HEADLINE_FLOOR_EV = 0.03
OVERCONFIDENCE_EV = 0.40
PRICE_CAP_AMERICAN = -165

# Sports whose spread is a market margin estimate and whose totals are
# on a comparable points scale. MLB run lines are excluded by design
# (see module docstring).
GUARD_SPORTS = frozenset({"NBA", "NFL", "CFB"})

REASON_GUARD_MARGIN = "GUARD_MARGIN_DISAGREEMENT_GE_6PT"
REASON_GUARD_TOTAL = "GUARD_TOTAL_DISAGREEMENT_GE_6PT"
REASON_EV_OVERCONFIDENCE = "EV_OVERCONFIDENCE_GE_40PCT"
REASON_PRICE_CAP = "PRICE_CAP"
REASON_BELOW_THRESHOLD = "BELOW_THRESHOLD_EFFECTIVE_EV_LT_3PCT"
REASON_GUARD_NOT_EVALUABLE = "GUARD_NOT_EVALUABLE_NO_MARKET_MARGIN"
REASON_RECALIBRATION_NOT_APPLIED = "RECALIBRATION_NOT_APPLIED"

# The adoption-time k estimate: the 2026-10-28 calibration diagnostic's
# published pooled fit (183 decided legs with a printed model p,
# k = -0.461, floored to k_used = 0). Refit rule: re-estimate from the
# trailing graded record once ~180 FURTHER decided legs with a printed
# model p have graded (the diagnostic's sufficiency), per the adoption
# record; until then this estimate governs.
ADOPTION_DIAGNOSTIC_SUMMARY = {
    "calibration": {
        "brier_n_legs": 183,
        "brier_model_p": 0.2740,
        "brier_market_implied": 0.2404,
        "shrink_fit_k_pooled": -0.461,
    }
}


def current_estimate() -> rc.KEstimate:
    """The k estimate card builds use until the refit rule fires."""
    return rc.estimate_k_from_summary(ADOPTION_DIAGNOSTIC_SUMMARY)


def _num(value: Any) -> Optional[float]:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return float(value)
    return None


def _lane_a_view(row: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    lanes = row.get("pricing_lanes")
    if isinstance(lanes, Mapping):
        view = lanes.get("lane_a_independent")
        if isinstance(view, Mapping):
            return view
    view = row.get("independent_projection")
    if isinstance(view, Mapping):
        return view
    return None


def _projected_home_margin(row: Mapping[str, Any]) -> Optional[float]:
    view = _lane_a_view(row)
    if view is not None:
        margin = _num(view.get("projected_home_margin"))
        if margin is not None:
            return margin
        home = _num(view.get("home_mean"))
        away = _num(view.get("away_mean"))
        if home is not None and away is not None:
            return home - away
    home = _num(row.get("home_mean"))
    away = _num(row.get("away_mean"))
    if home is not None and away is not None:
        return home - away
    return None


def _projected_total(row: Mapping[str, Any]) -> Optional[float]:
    view = _lane_a_view(row)
    if view is not None:
        total = _num(view.get("projected_total"))
        if total is not None:
            return total
        home = _num(view.get("home_mean"))
        away = _num(view.get("away_mean"))
        if home is not None and away is not None:
            return home + away
    home = _num(row.get("home_mean"))
    away = _num(row.get("away_mean"))
    if home is not None and away is not None:
        return home + away
    return None


def _game_teams(game: Any) -> Optional[tuple[str, str]]:
    if not isinstance(game, str) or " @ " not in game:
        return None
    away, home = game.split(" @ ", 1)
    away, home = away.strip(), home.strip()
    if not away or not home:
        return None
    return away, home


def _selection_side(row: Mapping[str, Any]) -> Optional[str]:
    """'away' / 'home' for a team-selection row, by longest name match."""
    teams = _game_teams(row.get("game"))
    selection = row.get("selection")
    if teams is None or not isinstance(selection, str):
        return None
    away, home = teams
    matches = []
    if selection.startswith(away):
        matches.append(("away", len(away)))
    if selection.startswith(home):
        matches.append(("home", len(home)))
    if not matches:
        return None
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[0][0]


def market_home_margins(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Optional[float]]:
    """Market-implied home margin per game, from its SPREAD pair.

    For a spread row, the market home margin is ``-line`` when the
    selection is the home team and ``+line`` when it is the away team
    (an away +10.5 line means the market prices the home team 10.5
    points better). Both sides of a pair must agree; a game whose
    spread rows disagree or cannot be sided maps to None (guard not
    evaluable for that game), never to a guessed margin.
    """
    margins: dict[str, set[float]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("market") or "").upper() != "SPREAD":
            continue
        game = row.get("game")
        line = _num(row.get("line"))
        side = _selection_side(row)
        if not isinstance(game, str) or line is None or side is None:
            continue
        market_home = -line if side == "home" else line
        margins.setdefault(game, set()).add(round(market_home, 6))
    out: dict[str, Optional[float]] = {}
    for game, values in margins.items():
        out[game] = values.pop() if len(values) == 1 else None
    return out


def row_disagreement(
    row: Mapping[str, Any],
    market_home_margin: Optional[float],
) -> tuple[Optional[float], Optional[str], bool]:
    """(disagreement_points, kind, evaluable) for one priced row.

    kind is "MARGIN" for SPREAD/ML rows and "TOTAL" for TOTAL rows.
    evaluable is False when the quantities the guard needs are not on
    the row set — the caller must not headline such a row in a
    guard-scope sport.
    """
    market = str(row.get("market") or "").upper()
    if market == "TOTAL":
        projected = _projected_total(row)
        line = _num(row.get("line"))
        if projected is None or line is None:
            return None, "TOTAL", False
        return abs(projected - line), "TOTAL", True
    if market == "SPREAD":
        line = _num(row.get("line"))
        side = _selection_side(row)
        projected_home = _projected_home_margin(row)
        if line is None or side is None or projected_home is None:
            return None, "MARGIN", False
        projected_selected = projected_home if side == "home" else -projected_home
        market_selected = -line
        return abs(projected_selected - market_selected), "MARGIN", True
    if market == "ML":
        projected_home = _projected_home_margin(row)
        if projected_home is None or market_home_margin is None:
            return None, "MARGIN", False
        return abs(projected_home - market_home_margin), "MARGIN", True
    return None, None, True  # market outside the guard's scope


def apply_card_gates(
    rows: list[dict[str, Any]],
    estimate: rc.KEstimate,
    *,
    guard_threshold: float = GUARD_THRESHOLD_POINTS,
) -> list[dict[str, Any]]:
    """Recalibrate Lane A rows and place them under the adopted gates.

    Returns new row dicts (inputs never mutated), each stamped with a
    ``card_gate`` block recording the effective EV, the disagreement
    measurement, and the bucket decision with its reason. Buckets:
    HEADLINE, OVERCONFIDENCE, EXCLUDED, BLOCKED.
    """
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("CARD_GATE_ROW_NOT_OBJECT")
    margins = market_home_margins(rows)
    recalibrated = rc.apply_recalibration_to_rows(rows, estimate, enabled=True)
    out: list[dict[str, Any]] = []
    for row in recalibrated:
        sport = str(row.get("sport") or "").upper()
        in_guard_scope = sport in GUARD_SPORTS
        disagreement, kind, evaluable = row_disagreement(
            row, margins.get(str(row.get("game") or ""))
        )
        guard_triggered = bool(
            in_guard_scope
            and evaluable
            and disagreement is not None
            and disagreement >= guard_threshold
        )
        block = row.get("recalibration")
        recal_applied = (
            isinstance(block, Mapping) and block.get("status") == "APPLIED"
        )
        effective_ev = rc.effective_ev(row) if recal_applied else None
        price = _num(row.get("odds_american"))

        if not recal_applied:
            bucket, reason = "BLOCKED", REASON_RECALIBRATION_NOT_APPLIED
        elif guard_triggered:
            bucket = "OVERCONFIDENCE"
            reason = REASON_GUARD_MARGIN if kind == "MARGIN" else REASON_GUARD_TOTAL
        elif effective_ev is not None and effective_ev >= OVERCONFIDENCE_EV:
            bucket, reason = "OVERCONFIDENCE", REASON_EV_OVERCONFIDENCE
        elif in_guard_scope and not evaluable:
            bucket, reason = "BLOCKED", REASON_GUARD_NOT_EVALUABLE
        elif price is not None and price < PRICE_CAP_AMERICAN:
            bucket, reason = "EXCLUDED", REASON_PRICE_CAP
        elif effective_ev is not None and effective_ev >= HEADLINE_FLOOR_EV:
            bucket, reason = "HEADLINE", None
        else:
            bucket, reason = "EXCLUDED", REASON_BELOW_THRESHOLD

        row["card_gate"] = {
            "gate_version": GATE_VERSION,
            "recalibration_status": (
                block.get("status") if isinstance(block, Mapping) else None
            ),
            "k_used": estimate.k_used,
            "effective_ev": effective_ev,
            "guard_scope": in_guard_scope,
            "guard_evaluable": evaluable,
            "disagreement_points": (
                round(disagreement, 4) if disagreement is not None else None
            ),
            "disagreement_kind": kind,
            "guard_threshold_points": guard_threshold,
            "guard_triggered": guard_triggered,
            "bucket": bucket,
            "reason": reason,
        }
        out.append(row)
    return out
