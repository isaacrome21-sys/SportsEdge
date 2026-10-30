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

   Gate V3 (Oct 29, 2026) makes the guard side-aware. A paired
   market's disagreement is ONE model claim, not two: the guard
   fires only on the side the model actually favors — the side
   whose raw model edge (the Lane A view's model probability minus
   the engine's break-even probability for that row's own price)
   is positive. The mirror side's disagreement is the same number
   read backwards; it does not trip the guard and classifies on
   its own merits through the normal gates below. Under the
   pair-blind V2 guard, both sides of all three totals pairs on
   the Oct 29, 2026 card were bucketed — a guaranteed 1-1 in legs
   that could only bleed the vig spread (see GRADE_RUNIT.md in
   operative_run_20261029_runit). An unpaired row has no mirror
   to reason about and keeps the pair-blind behavior, as does a
   paired row whose raw model edge cannot be read (fail-closed).

3. EXISTING CARD GATES, unchanged and applied on effective EV:
   >= +40% effective EV -> overconfidence bucket; price shorter than
   -165 -> excluded; >= +3% effective EV -> headline; otherwise
   excluded below threshold. Fact-based withholds (e.g. the Tier-1
   injury-blindness rule) remain a card-build step applied after
   these gates, exactly as before.

4. MARKET BASELINE — POWER_V1 DE-VIG (owner ruling, Oct 29, 2026;
   Isaac delegated the conformance-audit fix — "Just do what you
   would suggest" — and the ruling was issued on relay #2447,
   comment 6513411240; audit gap A2: three de-vig regimes coexisted
   and every family evaluator hand-rolled proportional de-vig while
   the frozen platform policy selects POWER_V1): the market
   probability the recalibration anchors on — the ``implied_p`` in
   ``p_used = implied + k * (model_p - implied)`` — is, for every row
   whose complementary side is present in the same row set, the
   POWER_V1 fair probability from the frozen platform implementation
   (``sportsedge.devig.devig_with_policy`` under
   ``EDGE_FLOOR_DEVIG_V1``, stable and longshot estimator both
   POWER_V1, haircut 0). The model side and the recalibration formula
   are untouched; only the anchor's source changes, from the engine's
   raw break-even probability of the row's own price to the pair's
   de-vigged fair probability. Basis is stamped on every row's
   ``card_gate.market_baseline`` block. Two fail-closed edges:

   - a pair the frozen policy's longshot sensitivity gate BLOCKs
     (a side >= +400 and the three methods spread > 1.0pp) cannot
     anchor any row: both rows of the pair are BLOCKED with
     ``DEVIG_SENSITIVITY_BLOCKED_POLICY`` — the platform policy's
     BLOCK is a refusal to name a market probability, and a card
     gate must not quietly fall back to a softer baseline for
     exactly the longshots the policy is protecting against;
   - a row with NO complementary side in the row set has no pair to
     de-vig (``sportsedge.devig`` itself refuses unpaired quotes).
     It keeps the engine's break-even anchor, stamped
     ``BREAK_EVEN_UNPAIRED`` so the mixed basis is on the record,
     never silent. Guard-scope placement rules for such rows are
     unchanged (an ML row without a spread pair still cannot
     headline).

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

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from sportsedge import lane_a_recalibration as rc
from sportsedge.devig import DevigError, devig_with_policy
from sportsedge.edge_floors import (
    FrozenDevigPolicy,
    load_edge_floor_config,
    require_frozen_devig_policy,
)

# V3 (Oct 29, 2026): the disagreement guard is side-aware — on a
# paired market it fires only on the model-favored side (positive
# raw model edge); the mirror side classifies on its own merits
# (module docstring, item 2). V2's pair-blind guard bucketed both
# sides of the Oct 29 totals pairs, a guaranteed 1-1 that could
# only bleed the vig. V2 cards stand as recorded; V3 applies
# prospectively only.
# V2 (Oct 29, 2026): the recalibration market baseline for paired rows
# is the frozen-policy POWER_V1 fair probability (module docstring,
# item 4). V1 cards (LANE_A_CARD_GATES_V1_ADOPTED_20261028) stand as
# recorded; the version bump keeps the basis change visible on every
# stamped row instead of silently re-basing under the V1 stamp.
GATE_VERSION = "LANE_A_CARD_GATES_V3_GUARD_FAVORED_SIDE_20261029"

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
REASON_DEVIG_SENSITIVITY_BLOCKED = "DEVIG_SENSITIVITY_BLOCKED_POLICY"

# Market-baseline sources stamped on every row (module docstring, 4).
BASELINE_POLICY_POWER_V1 = "POLICY_POWER_V1"
BASELINE_BREAK_EVEN_UNPAIRED = "BREAK_EVEN_UNPAIRED"
BASELINE_DEVIG_SENSITIVITY_BLOCKED = "DEVIG_SENSITIVITY_BLOCKED"
BASELINE_NONE = "NONE"

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


# ------------------------------------------------------- de-vig baseline
#
# The thinnest adapter between the card row set and the frozen
# platform de-vig (sportsedge.devig): devig speaks in paired quote
# mappings, the gates speak in priced card rows, so the adapter pairs
# rows within the set, builds the two quote mappings per pair, and
# asks the frozen policy (EDGE_FLOOR_DEVIG_V1) for the POWER_V1 fair
# probability of each side. Nothing else about the gates changes.

_FLOOR_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "truth_gate_floors.json"
)
_POLICY: Optional[FrozenDevigPolicy] = None

_DEVIG_MARKET = {
    "ML": "MONEYLINE",
    "SPREAD": "SPREAD",
    "RL": "RUN_LINE",
    "TOTAL": "GAME_TOTAL",
    "TEAM_TOTALS": "TEAM_TOTAL",
}
_DEVIG_TEAM_SIDE = {
    ("ML", "away"): "AWAY_ML",
    ("ML", "home"): "HOME_ML",
    ("SPREAD", "away"): "AWAY",
    ("SPREAD", "home"): "HOME",
    ("RL", "away"): "AWAY_RL",
    ("RL", "home"): "HOME_RL",
}
_SENSITIVITY_BLOCK_PREFIX = "LONGSHOT_DEVIG_SENSITIVITY_EXCEEDS_LIMIT"


def _devig_policy() -> FrozenDevigPolicy:
    """The frozen EDGE_FLOOR_DEVIG_V1 policy, loaded once, lazily.

    A load failure propagates (EdgeFloorError): a card build that
    cannot read the frozen policy must fail loudly, never fall back
    to an un-policy baseline in silence.
    """
    global _POLICY
    if _POLICY is None:
        _POLICY = require_frozen_devig_policy(
            config=load_edge_floor_config(str(_FLOOR_CONFIG_PATH))
        )
    return _POLICY


@dataclass(frozen=True)
class _Baseline:
    source: str
    fair_p: Optional[float] = None
    method: Optional[str] = None
    longshot_triggered: bool = False
    sensitivity_spread: Optional[float] = None


def _over_under_side(row: Mapping[str, Any]) -> Optional[str]:
    selection = row.get("selection")
    if not isinstance(selection, str):
        return None
    tokens = selection.upper().split()
    if "OVER" in tokens:
        return "OVER"
    if "UNDER" in tokens:
        return "UNDER"
    return None


def _ou_prefix(row: Mapping[str, Any]) -> str:
    """Selection minus its OVER/UNDER token and printed line — the
    team identity of a team-total row ("" for a game total)."""
    selection = row.get("selection")
    if not isinstance(selection, str):
        return ""
    line = _num(row.get("line"))
    kept = []
    for token in selection.split():
        if token.upper() in ("OVER", "UNDER"):
            continue
        try:
            value: Optional[float] = float(token.lstrip("+"))
        except ValueError:
            value = None
        if value is not None and line is not None and abs(value) == abs(line):
            continue
        kept.append(token)
    return " ".join(kept).strip().upper()


def _pair_key(row: Mapping[str, Any]) -> Optional[tuple[tuple, str]]:
    """(pair_key, side) locating a row's two-sided market, or None.

    side is "away"/"home" for team markets and "OVER"/"UNDER" for
    totals. The complement is the row in the same set with the same
    key and the opposite side. Lines are canonicalized (absolute
    value for team handicaps) so the two sides of one market key
    identically even though their printed lines carry opposite signs.
    """
    game = row.get("game")
    market = str(row.get("market") or "").upper()
    if not isinstance(game, str) or _num(row.get("odds_american")) is None:
        return None
    if market in ("ML", "SPREAD", "RL"):
        side = _selection_side(row)
        if side is None:
            return None
        line = _num(row.get("line"))
        canonical = abs(line) if line is not None else 0.0
        return (game, market, canonical), side
    if market in ("TOTAL", "TEAM_TOTALS"):
        side = _over_under_side(row)
        line = _num(row.get("line"))
        if side is None or line is None:
            return None
        return (game, market, line, _ou_prefix(row)), side
    return None


def _quote(row: Mapping[str, Any], key: tuple, side: str) -> dict[str, Any]:
    market = str(key[1])
    if market in ("TOTAL", "TEAM_TOTALS"):
        devig_side = side
    else:
        devig_side = _DEVIG_TEAM_SIDE[(market, side)]
    return {
        "game_id": str(key[0]),
        "period": "FG",
        "market": _DEVIG_MARKET[market],
        "entity_id": "|".join(str(part) for part in key),
        "book_key": "",
        "is_alternate": False,
        "line": key[2],
        "side": devig_side,
        "american_odds": row.get("odds_american"),
    }


def _pair_partners(rows: list[dict[str, Any]]) -> list[Optional[int]]:
    """Partner index per row under the in-set pairing (see _pair_key).

    The partner is the row in the same set with the same pair key
    and the opposite side, recorded only when BOTH sides of the pair
    are present exactly once; otherwise None (the row is unpaired —
    no complement, a duplicated side, or no readable pair key). The
    de-vig baseline adapter and the disagreement guard's
    favored-side rule (gate V3) reason over these same pairs, so
    the two mechanisms can never pair a market differently.
    """
    slots: dict[tuple[tuple, str], list[int]] = {}
    keyed: dict[int, tuple[tuple, str]] = {}
    for idx, row in enumerate(rows):
        found = _pair_key(row)
        if found is None:
            continue
        key, side = found
        keyed[idx] = (key, side)
        slots.setdefault((key, side), []).append(idx)
    partners: list[Optional[int]] = [None] * len(rows)
    for idx, (key, side) in keyed.items():
        if key[1] in ("ML", "SPREAD", "RL"):
            complement = "home" if side == "away" else "away"
        else:
            complement = "UNDER" if side == "OVER" else "OVER"
        others = slots.get((key, complement), [])
        if len(others) == 1 and len(slots.get((key, side), [])) == 1:
            partners[idx] = others[0]
    return partners


def _market_baselines(
    rows: list[dict[str, Any]], partners: list[Optional[int]]
) -> list[_Baseline]:
    """One baseline per row, aligned by index (module docstring, 4)."""
    out = [_Baseline(BASELINE_NONE) for _ in rows]
    keyed: dict[int, tuple[tuple, str]] = {}
    for idx, row in enumerate(rows):
        found = _pair_key(row)
        if found is None:
            continue
        keyed[idx] = found
    policy: Optional[FrozenDevigPolicy] = None
    resolved: set[int] = set()
    for idx, (key, side) in keyed.items():
        if idx in resolved:
            continue
        other = partners[idx]
        if other is None:
            out[idx] = _Baseline(BASELINE_BREAK_EVEN_UNPAIRED)
            resolved.add(idx)
            continue
        resolved.add(idx)
        resolved.add(other)
        if policy is None:
            policy = _devig_policy()
        results: dict[int, Any] = {}
        blocked = False
        for cand_idx, opp_idx in ((idx, other), (other, idx)):
            cand_key, cand_side = keyed[cand_idx]
            _, opp_side = keyed[opp_idx]
            try:
                results[cand_idx] = devig_with_policy(
                    _quote(rows[cand_idx], cand_key, cand_side),
                    _quote(rows[opp_idx], cand_key, opp_side),
                    policy=policy,
                )
            except DevigError as exc:
                if str(exc).startswith(_SENSITIVITY_BLOCK_PREFIX):
                    blocked = True
                    break
                raise
        if blocked:
            out[idx] = _Baseline(BASELINE_DEVIG_SENSITIVITY_BLOCKED)
            out[other] = _Baseline(BASELINE_DEVIG_SENSITIVITY_BLOCKED)
            continue
        for row_idx, result in results.items():
            out[row_idx] = _Baseline(
                BASELINE_POLICY_POWER_V1,
                fair_p=result.selected.candidate_fair_probability,
                method=result.selected.method,
                longshot_triggered=result.longshot_triggered,
                sensitivity_spread=(
                    result.sensitivity_spread_probability_points
                ),
            )
    return out


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


def _raw_model_edge(row: Mapping[str, Any]) -> Optional[float]:
    """The model's raw probability edge on one row, or None.

    Model probability minus the engine's break-even probability for
    the row's own price, both read from the row's Lane A view as the
    engine wrote it (row-level fields as fallback) — pre-gates
    values, never the POWER_V1-overridden anchor the recalibration
    consumes. Positive means the model's disagreement with the
    market supports THIS side of its market; that sign is what the
    guard's favored-side rule (gate V3) reads.
    """
    view = _lane_a_view(row)
    model_p = _num(view.get("estimate_p")) if view is not None else None
    break_even = (
        _num(view.get("book_break_even_p")) if view is not None else None
    )
    if model_p is None:
        model_p = _num(row.get("estimate_p"))
    if break_even is None:
        break_even = _num(row.get("book_break_even_p"))
    if model_p is None or break_even is None:
        return None
    return model_p - break_even


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
    partners = _pair_partners(rows)
    baselines = _market_baselines(rows, partners)
    # Paired rows are re-anchored on the frozen-policy POWER_V1 fair
    # probability: the recalibration layer reads its implied_p from
    # the Lane A view's book_break_even_p, so the override is written
    # there, on a copy (inputs never mutated), and the engine's own
    # break-even value is preserved in the card_gate stamp. The
    # recalibration formula and the model side are untouched.
    prepared: list[dict[str, Any]] = []
    baseline_applied: list[bool] = []
    for row, base in zip(rows, baselines):
        applied = False
        if base.source == BASELINE_POLICY_POWER_V1 and base.fair_p is not None:
            clone = copy.deepcopy(row)
            view = _lane_a_view(clone)
            if isinstance(view, dict):
                view["book_break_even_p"] = base.fair_p
                applied = True
                prepared.append(clone)
            else:
                prepared.append(row)
        else:
            prepared.append(row)
        baseline_applied.append(applied)
    recalibrated = rc.apply_recalibration_to_rows(prepared, estimate, enabled=True)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(recalibrated):
        base = baselines[idx]
        baseline_source = (
            base.source if baseline_applied[idx] or base.source != BASELINE_POLICY_POWER_V1
            else BASELINE_NONE
        )
        engine_view = _lane_a_view(rows[idx])
        engine_break_even = (
            _num(engine_view.get("book_break_even_p"))
            if engine_view is not None
            else None
        )
        sport = str(row.get("sport") or "").upper()
        in_guard_scope = sport in GUARD_SPORTS
        disagreement, kind, evaluable = row_disagreement(
            row, margins.get(str(row.get("game") or ""))
        )
        over_threshold = bool(
            in_guard_scope
            and evaluable
            and disagreement is not None
            and disagreement >= guard_threshold
        )
        # Gate V3 favored-side rule (module docstring, item 2): on a
        # paired market only the side whose raw model edge is
        # positive asserts the disagreement. The mirror side is
        # suppressed here and classifies on its own merits below.
        # Unpaired rows, and paired rows whose edge cannot be read,
        # keep the pair-blind trigger (fail-closed). The edge is
        # read from the ORIGINAL row: the recalibrated copy's view
        # may carry the POWER_V1 anchor in place of the engine's
        # break-even, and the raw edge is defined on engine values.
        model_edge = _raw_model_edge(rows[idx])
        mirror_suppressed = bool(
            over_threshold
            and partners[idx] is not None
            and model_edge is not None
            and model_edge <= 0.0
        )
        guard_triggered = over_threshold and not mirror_suppressed
        block = row.get("recalibration")
        recal_applied = (
            isinstance(block, Mapping) and block.get("status") == "APPLIED"
        )
        effective_ev = rc.effective_ev(row) if recal_applied else None
        price = _num(row.get("odds_american"))

        if not recal_applied:
            bucket, reason = "BLOCKED", REASON_RECALIBRATION_NOT_APPLIED
        elif base.source == BASELINE_DEVIG_SENSITIVITY_BLOCKED:
            bucket, reason = "BLOCKED", REASON_DEVIG_SENSITIVITY_BLOCKED
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
            "guard_paired": partners[idx] is not None,
            "guard_model_edge": (
                round(model_edge, 6) if model_edge is not None else None
            ),
            "guard_mirror_suppressed": mirror_suppressed,
            "market_baseline": {
                "source": baseline_source,
                "method": base.method,
                "policy_id": (
                    "EDGE_FLOOR_DEVIG_V1"
                    if baseline_source
                    in (BASELINE_POLICY_POWER_V1, BASELINE_DEVIG_SENSITIVITY_BLOCKED)
                    else None
                ),
                "fair_p": (
                    round(base.fair_p, 6) if base.fair_p is not None else None
                ),
                "engine_book_break_even_p": engine_break_even,
                "longshot_triggered": base.longshot_triggered,
                "sensitivity_spread_probability_points": (
                    base.sensitivity_spread
                    if baseline_source == BASELINE_POLICY_POWER_V1
                    else None
                ),
            },
            "bucket": bucket,
            "reason": reason,
        }
        out.append(row)
    return out
