"""Deterministic CFB signal-quality evaluator.

This module deliberately does not fetch data and does not create Model_P. It consumes
already-captured inputs and reason-codes whether a row belongs in the OFFICIAL,
MODEL_CANDIDATE, HYBRID_CONTEXT, PROMO_VALUE, WATCH, or PASS lane.

The CFB Truth Gate remains authoritative for OFFICIAL status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional


KEY_NUMBERS = (3.0, 7.0)


@dataclass(frozen=True)
class SignalResult:
    lane: str
    tier: str
    official_eligible: bool
    model_authorized: bool
    boosted_break_even: Optional[float]
    material_line_move: bool
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def american_to_profit_multiplier(american_odds: float) -> float:
    """Return profit per unit stake for American odds."""
    if american_odds == 0:
        raise ValueError("American odds cannot be zero")
    if american_odds > 0:
        return american_odds / 100.0
    return 100.0 / abs(american_odds)


def american_implied_probability(american_odds: float) -> float:
    """Return raw implied probability for American odds."""
    if american_odds == 0:
        raise ValueError("American odds cannot be zero")
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def profit_multiplier_to_break_even(multiplier: float) -> float:
    """Return break-even probability for a profit multiplier."""
    if multiplier <= 0:
        raise ValueError("Profit multiplier must be positive")
    return 1.0 / (1.0 + multiplier)


def boosted_break_even(american_odds: float, boost_pct: float) -> float:
    """Break-even probability after a profit boost.

    A 50% profit boost multiplies the base profit by 1.50; stake return is unchanged.
    """
    if boost_pct < 0:
        raise ValueError("boost_pct must be non-negative")
    base_profit = american_to_profit_multiplier(american_odds)
    boosted_profit = base_profit * (1.0 + boost_pct / 100.0)
    return profit_multiplier_to_break_even(boosted_profit)


def crosses_key_number(reference_line: float, current_line: float, keys: Iterable[float] = KEY_NUMBERS) -> bool:
    """Return True when spread magnitude crosses key 3 or 7."""
    lo, hi = sorted((abs(reference_line), abs(current_line)))
    return any(lo < key <= hi for key in keys)


def material_line_move(
    market_type: str,
    reference_value: float,
    current_value: float,
    *,
    spread_points_material: float = 2.0,
    total_points_material: float = 1.5,
    moneyline_cents_material: float = 15.0,
) -> bool:
    market = market_type.upper()
    if market == "SPREAD":
        return abs(current_value - reference_value) >= spread_points_material or crosses_key_number(reference_value, current_value)
    if market == "TOTAL":
        return abs(current_value - reference_value) >= total_points_material
    if market == "MONEYLINE":
        return abs(current_value - reference_value) >= moneyline_cents_material
    raise ValueError(f"Unsupported market_type: {market_type}")


def adverse_move_ate_value(row: Mapping[str, Any], move_is_material: bool) -> bool:
    """Return True when a material move made this selection's number worse.

    Spread values are represented from the selected team's perspective. For totals,
    selection must identify OVER or UNDER. Moneyline values are American odds.
    """
    if not move_is_material:
        return False
    if row.get("reference_market_value") is None or row.get("current_market_value") is None:
        return False
    reference = float(row["reference_market_value"])
    current = float(row["current_market_value"])
    market = str(row.get("market_type", "")).upper()
    selection = str(row.get("selection", "")).strip().upper()
    if market == "SPREAD":
        return current < reference
    if market == "TOTAL":
        if selection.startswith("UNDER") or selection == "U":
            return current < reference
        if selection.startswith("OVER") or selection == "O":
            return current > reference
        return False
    if market == "MONEYLINE":
        return american_implied_probability(current) > american_implied_probability(reference)
    return False


def _fresh(age_minutes: Optional[float], max_age: float) -> bool:
    return age_minutes is not None and age_minutes >= 0 and age_minutes <= max_age


def _independent_source_families(
    sources: Iterable[Mapping[str, Any]],
    *,
    allowed_kinds: Iterable[str] | None = None,
) -> set[str]:
    allowed = {str(kind).strip().lower() for kind in (allowed_kinds or []) if str(kind).strip()}
    families: set[str] = set()
    for source in sources:
        if not source.get("independent", False):
            continue
        kind = str(source.get("kind", "")).strip().lower()
        if kind in {"capper", "opinion", "handicapper"}:
            continue
        if allowed and kind not in allowed:
            continue
        family = str(source.get("family", "")).strip().lower()
        if family:
            families.add(family)
    return families


def benchmark_disagreement(row: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    benchmarks = row.get("benchmarks") or []
    values = [float(item["value"]) for item in benchmarks if item.get("value") is not None]
    if len(values) < 2:
        return False

    market = str(row.get("market_type", "")).upper()
    cfg = policy["benchmark_diagnostics"]
    if market == "SPREAD":
        threshold = float(cfg["spread_disagreement_points_watch"])
    elif market == "TOTAL":
        threshold = float(cfg["total_disagreement_points_watch"])
    elif market == "MONEYLINE":
        threshold = float(cfg["moneyline_probability_disagreement_watch"])
    else:
        return False
    return (max(values) - min(values)) >= threshold


def evaluate_signal(row: Mapping[str, Any], policy: Mapping[str, Any]) -> SignalResult:
    """Evaluate one captured CFB candidate without manufacturing model authority."""
    reasons: list[str] = []

    model_cfg = policy["model_authority"]
    model_p = row.get("model_p")
    model_authorized = (
        row.get("model_registry_status") == model_cfg["required_registry_status_for_model_lane"]
        and bool(row.get("promotion_authority"))
        and model_p is not None
    )
    underlying_candidate = bool(row.get("underlying_candidate"))
    candidate_scope = underlying_candidate or model_authorized

    if row.get("model_registry_status") != model_cfg["required_registry_status_for_model_lane"]:
        reasons.append("MODEL_UNFROZEN")
    if model_p is None:
        reasons.append("MODEL_P_MISSING")

    move_is_material = False
    if row.get("reference_market_value") is not None and row.get("current_market_value") is not None:
        move_cfg = policy["market_movement"]
        move_is_material = material_line_move(
            str(row.get("market_type")),
            float(row["reference_market_value"]),
            float(row["current_market_value"]),
            spread_points_material=float(move_cfg["spread_points_material"]),
            total_points_material=float(move_cfg["total_points_material"]),
            moneyline_cents_material=float(move_cfg["moneyline_cents_material"]),
        )
        if move_is_material:
            reasons.append("MATERIAL_LINE_MOVE")
            if candidate_scope and adverse_move_ate_value(row, move_is_material):
                reasons.append("MOVE_ATE_VALUE")

    freshness = policy["freshness"]
    required_stale = False
    if candidate_scope and not _fresh(row.get("odds_age_minutes"), float(freshness["odds_max_age_minutes"])):
        reasons.append("ODDS_STALE_OR_MISSING")
        required_stale = True
    if candidate_scope and row.get("handles_required") and not _fresh(row.get("handles_age_minutes"), float(freshness["handles_max_age_minutes"])):
        reasons.append("HANDLES_STALE_OR_MISSING")
        required_stale = True

    injury_required = bool(row.get("injury_required", True))
    if candidate_scope and injury_required:
        injury_unknown = bool(row.get("required_starter_status_unknown"))
        injury_stale = not _fresh(row.get("injury_age_minutes"), float(freshness["injury_max_age_minutes"]))
        if injury_unknown or injury_stale:
            reasons.append("INJURY_STALE_OR_UNKNOWN")
            required_stale = True

    if candidate_scope and bool(row.get("outdoor_game")):
        weather_missing = row.get("weather_available") is False
        weather_stale = not _fresh(row.get("weather_age_minutes"), float(freshness["weather_max_age_minutes"]))
        if weather_missing or weather_stale:
            reasons.append("WEATHER_STALE_OR_MISSING")
            required_stale = True
        if bool(row.get("severe_weather")):
            reasons.append("SEVERE_WEATHER_REVIEW")
            required_stale = True

    if candidate_scope and benchmark_disagreement(row, policy):
        reasons.append("BENCHMARK_DISAGREEMENT")

    tickets_pct = row.get("tickets_pct")
    move_cfg = policy["market_movement"]
    if candidate_scope and tickets_pct is not None and float(tickets_pct) >= float(move_cfg["public_ticket_pct_material"]):
        families = _independent_source_families(
            row.get("sources") or [],
            allowed_kinds=move_cfg.get("public_confirmation_source_kinds") or [],
        )
        if len(families) < int(move_cfg["minimum_independent_source_families"]):
            reasons.append("PUBLIC_HEAVY_UNCONFIRMED")

    price_cfg = policy["price_quality"]
    reference_edge = row.get("reference_edge")
    current_edge = row.get("current_edge")
    if candidate_scope and reference_edge is not None and current_edge is not None and float(reference_edge) > 0:
        reference_edge_f = float(reference_edge)
        current_edge_f = float(current_edge)
        lost_fraction = max(0.0, (reference_edge_f - current_edge_f) / reference_edge_f)
        if lost_fraction >= float(price_cfg["max_fraction_of_reference_edge_lost_before_price_decay"]):
            reasons.append("PRICE_DECAY")
        if current_edge_f < float(price_cfg["truth_gate_edge_floor"]):
            reasons.append("PRICE_DECAY")

    current_odds = row.get("current_odds")
    best_same_line_odds = row.get("best_same_line_odds")
    if candidate_scope and current_odds is not None and best_same_line_odds is not None:
        gap = american_implied_probability(float(current_odds)) - american_implied_probability(float(best_same_line_odds))
        if gap >= float(price_cfg.get("max_same_line_implied_probability_gap", 0.015)):
            reasons.append("BAD_PRICE")

    promo = row.get("promo") or {}
    boost_pct = promo.get("boost_pct")
    be: Optional[float] = None
    if boost_pct is not None and current_odds is not None:
        be = boosted_break_even(float(current_odds), float(boost_pct))
        if candidate_scope and not model_authorized:
            reasons.append("PROMO_ONLY_EDGE")

    reasons = list(dict.fromkeys(reasons))

    truth_gate_pass = bool(row.get("truth_gate_pass"))
    official_eligible = model_authorized and truth_gate_pass

    watch_reasons = {
        "ODDS_STALE_OR_MISSING",
        "HANDLES_STALE_OR_MISSING",
        "INJURY_STALE_OR_UNKNOWN",
        "WEATHER_STALE_OR_MISSING",
        "SEVERE_WEATHER_REVIEW",
        "BENCHMARK_DISAGREEMENT",
        "PRICE_DECAY",
        "BAD_PRICE",
        "MOVE_ATE_VALUE",
        "PUBLIC_HEAVY_UNCONFIRMED",
    }
    has_watch_reason = required_stale or any(reason in watch_reasons for reason in reasons)

    if official_eligible:
        lane = "OFFICIAL"
        tier = "CORE"
    elif model_authorized and not truth_gate_pass:
        lane = "MODEL_CANDIDATE"
        tier = "WATCH" if has_watch_reason else "SECONDARY"
    elif underlying_candidate and has_watch_reason:
        lane = "WATCH"
        tier = "WATCH"
    elif underlying_candidate and boost_pct is not None:
        lane = "PROMO_VALUE"
        tier = "SECONDARY"
        reasons.append("QUALIFIED_CONTEXT")
    elif underlying_candidate:
        lane = "HYBRID_CONTEXT"
        tier = "SECONDARY"
        reasons.append("QUALIFIED_CONTEXT")
    else:
        lane = "PASS"
        tier = "PASS"

    if model_cfg.get("unfrozen_registry_forces_official_zero", True) and row.get("model_registry_status") != "FROZEN":
        official_eligible = False
        if lane == "OFFICIAL":
            lane = "WATCH"
            tier = "WATCH"

    return SignalResult(
        lane=lane,
        tier=tier,
        official_eligible=official_eligible,
        model_authorized=model_authorized,
        boosted_break_even=be,
        material_line_move=move_is_material,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def funnel_counts(results: Iterable[SignalResult]) -> dict[str, int]:
    """Return RUN IT funnel counts for a completed slate evaluation."""
    counts = {
        "scanned": 0,
        "model_candidates": 0,
        "price_context_qualified": 0,
        "truth_gate_eligible": 0,
        "official": 0,
        "watch": 0,
        "pass": 0,
    }
    for result in results:
        counts["scanned"] += 1
        if result.model_authorized:
            counts["model_candidates"] += 1
        if result.lane in {"OFFICIAL", "MODEL_CANDIDATE", "HYBRID_CONTEXT", "PROMO_VALUE"}:
            counts["price_context_qualified"] += 1
        if result.official_eligible:
            counts["truth_gate_eligible"] += 1
        if result.lane == "OFFICIAL":
            counts["official"] += 1
        elif result.lane == "WATCH":
            counts["watch"] += 1
        elif result.lane == "PASS":
            counts["pass"] += 1
    return counts
