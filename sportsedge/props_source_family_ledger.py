"""Research-only source-family ledger for third-party prop cards and price radar.

This module is deliberately upstream of SportsEdge prop validation/market binding.
It can preserve what an outside source claimed and what price was observed, but it
cannot manufacture SportsEdge Model_P, no-vig edge, confirmation independence, or
bettor-facing authority.
"""
from __future__ import annotations

from datetime import datetime
from math import ceil, floor, isfinite
from typing import Iterable, Mapping, Sequence

from sportsedge.props_market_binding_stage7 import (
    NO_VIG_ONE_SIDED,
    american_to_decimal,
    proportional_devig,
    raw_implied_probability,
)

SCHEMA_VERSION = "PROP_SOURCE_FAMILY_LEDGER_V1"
AUTHORITY = "RESEARCH_CONTEXT_ONLY"
NFL_PROPS_ENGINE = "NO_ENGINE"
MIN_SOURCE_FAMILY_EVIDENCE_N = 100

ZERO_AUTHORITY = {
    "market_prices_used_as_model_inputs": False,
    "can_create_model_p": False,
    "can_create_sportsedge_ev": False,
    "can_promote": False,
    "staking_authority": False,
    "run_it_direction_authority": False,
    "official_authority": False,
    "independent_confirmation_authority": False,
}


def _identity(value: object, name: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ValueError(f"SOURCE_LEDGER_IDENTITY_REQUIRED:{name}")
    return out


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"SOURCE_LEDGER_NUMBER_INVALID:{name}")
    out = float(value)
    if not isfinite(out):
        raise ValueError(f"SOURCE_LEDGER_NUMBER_INVALID:{name}")
    return out


def _probability(value: object, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 < out < 1.0:
        raise ValueError(f"SOURCE_LEDGER_PROBABILITY_INVALID:{name}")
    return out


def _timestamp(value: object, name: str) -> str:
    raw = _identity(value, name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"SOURCE_LEDGER_TIMESTAMP_INVALID:{name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"SOURCE_LEDGER_TIMESTAMP_MUST_BE_AWARE:{name}")
    return raw


def _optional_odds(value: object | None, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or -99 <= value <= 99:
        raise ValueError(f"SOURCE_LEDGER_AMERICAN_ODDS_INVALID:{name}")
    return value


def _directional_projection_delta(side: str, projection: float, line: float) -> float | None:
    if side == "OVER":
        return projection - line
    if side == "UNDER":
        return line - projection
    return None


def build_candidate_observation(
    *,
    source_family_id: str,
    candidate_id: str,
    entity_id: str,
    market_id: str,
    side: str,
    line: float | None = None,
    projection: float | None = None,
    source_model_probability: float | None = None,
    offered_odds: int | None = None,
    paired_other_side_odds: int | None = None,
    source_claimed_grade: str | None = None,
    source_claimed_edge_percent: float | None = None,
) -> dict[str, object]:
    """Normalize one outside prop card without granting SportsEdge authority.

    `source_model_probability` is explicitly the outside source's probability.  It
    may be compared with an offered price descriptively, but that comparison is
    never SportsEdge Model_P or SportsEdge EV.
    """
    family = _identity(source_family_id, "source_family_id")
    candidate = _identity(candidate_id, "candidate_id")
    entity = _identity(entity_id, "entity_id")
    market = _identity(market_id, "market_id")
    resolved_side = _identity(side, "side").upper()
    if resolved_side not in {"OVER", "UNDER", "YES", "NO"}:
        raise ValueError("SOURCE_LEDGER_SIDE_INVALID")

    resolved_line = None if line is None else _finite(line, "line")
    resolved_projection = None if projection is None else _finite(projection, "projection")
    if (resolved_line is None) != (resolved_projection is None):
        raise ValueError("SOURCE_LEDGER_PROJECTION_LINE_PAIR_REQUIRED")
    if resolved_projection is not None and resolved_side not in {"OVER", "UNDER"}:
        raise ValueError("SOURCE_LEDGER_PROJECTION_ONLY_VALID_FOR_OVER_UNDER")

    source_p = None if source_model_probability is None else _probability(
        source_model_probability, "source_model_probability"
    )
    offered = _optional_odds(offered_odds, "offered_odds")
    paired = _optional_odds(paired_other_side_odds, "paired_other_side_odds")
    if paired is not None and offered is None:
        raise ValueError("SOURCE_LEDGER_PAIRED_QUOTE_REQUIRES_OFFERED_QUOTE")

    claimed_edge = None
    if source_claimed_edge_percent is not None:
        claimed_edge = _finite(source_claimed_edge_percent, "source_claimed_edge_percent")

    projection_delta = None
    projection_classification = "NO_PROJECTION_COMPARISON"
    if resolved_projection is not None and resolved_line is not None:
        projection_delta = _directional_projection_delta(
            resolved_side, resolved_projection, resolved_line
        )
        projection_classification = (
            "PROJECTION_LEAN" if projection_delta > 0 else
            "PROJECTION_OPPOSES_CARD" if projection_delta < 0 else
            "PROJECTION_AT_LINE"
        )

    raw_implied = None
    market_no_vig: float | str | None = None
    source_offer_gap = None
    source_offer_ev = None
    source_vs_novig_gap = None
    price_classification = "NO_PRICE_COMPARISON"
    pricing_evidence_class = "NO_PRICE_EVIDENCE"
    if offered is not None:
        raw_implied = raw_implied_probability(offered)
        market_no_vig = NO_VIG_ONE_SIDED if paired is None else proportional_devig(offered, paired)[0]
        pricing_evidence_class = (
            "MODEL_VS_OFFERED_PRICE_GAP" if paired is None else
            "SOURCE_MODEL_VS_PAIRED_NO_VIG_MARKET"
        )
        if source_p is not None:
            source_offer_gap = source_p - raw_implied
            source_offer_ev = source_p * american_to_decimal(offered) - 1.0
            price_classification = (
                "PRICE_EV_NEGATIVE" if source_offer_ev < 0 else
                "SOURCE_PROBABILITY_OFFER_EV_POSITIVE_UNVALIDATED" if source_offer_ev > 0 else
                "SOURCE_PROBABILITY_OFFER_EV_ZERO"
            )
            if isinstance(market_no_vig, float):
                source_vs_novig_gap = source_p - market_no_vig

    contradiction_flags: list[str] = []
    if projection_delta is not None and projection_delta > 0 and source_offer_ev is not None and source_offer_ev < 0:
        contradiction_flags.append("PROJECTION_PRICE_CONTRADICTION")
    if claimed_edge is not None and source_offer_gap is not None:
        claimed_edge_probability_points = claimed_edge / 100.0
        if (claimed_edge_probability_points > 0) != (source_offer_gap > 0) and source_offer_gap != 0:
            contradiction_flags.append("SOURCE_CLAIMED_EDGE_SIGN_CONTRADICTION")

    if "PROJECTION_PRICE_CONTRADICTION" in contradiction_flags:
        primary = "PROJECTION_LEAN_ONLY"
    elif paired is None and source_p is not None and offered is not None:
        primary = "MODEL_VS_OFFERED_PRICE_GAP"
    elif projection_delta is not None and projection_delta > 0:
        primary = "PROJECTION_LEAN_ONLY"
    else:
        primary = "CONTEXT_OBSERVATION_ONLY"

    return {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "source_family_id": family,
        "candidate_id": candidate,
        "entity_id": entity,
        "market_id": market,
        "side": resolved_side,
        "line": resolved_line,
        "projection": resolved_projection,
        "projection_directional_delta": projection_delta,
        "projection_classification": projection_classification,
        "source_model_probability": source_p,
        "offered_odds": offered,
        "raw_implied_probability": raw_implied,
        "paired_other_side_odds": paired,
        "market_no_vig_probability": market_no_vig,
        "source_model_minus_raw_implied_probability": source_offer_gap,
        "source_probability_offer_ev_per_unit": source_offer_ev,
        "source_model_minus_paired_no_vig_probability": source_vs_novig_gap,
        "pricing_evidence_class": pricing_evidence_class,
        "price_classification": price_classification,
        "primary_classification": primary,
        "source_claimed_grade": None if source_claimed_grade is None else str(source_claimed_grade),
        "source_claimed_edge_percent": claimed_edge,
        "contradiction_flags": contradiction_flags,
        "sportsedge_edge_percent": None,
        "nfl_props_engine": NFL_PROPS_ENGINE,
        **ZERO_AUTHORITY,
    }


def independent_source_class_count(rows: Iterable[Mapping[str, object]]) -> int:
    families: set[str] = set()
    for row in rows:
        families.add(_identity(row.get("source_family_id"), "source_family_id"))
    return len(families)


def source_family_confirmation_count(rows: Iterable[Mapping[str, object]]) -> int:
    """Alias with explicit semantics: same-family cards never stack votes."""
    return independent_source_class_count(rows)


def narrow_band_integer_centers(rows: Sequence[Mapping[str, object]]) -> tuple[int, ...]:
    """Return integer outcomes that make same-family OVER and UNDER cards both win."""
    if not rows:
        return ()
    families = {_identity(r.get("source_family_id"), "source_family_id") for r in rows}
    entities = {_identity(r.get("entity_id"), "entity_id") for r in rows}
    markets = {_identity(r.get("market_id"), "market_id") for r in rows}
    if len(families) != 1 or len(entities) != 1 or len(markets) != 1:
        raise ValueError("SOURCE_LEDGER_NARROW_BAND_IDENTITY_MISMATCH")

    over_lines: list[float] = []
    under_lines: list[float] = []
    for row in rows:
        side = _identity(row.get("side"), "side").upper()
        if side not in {"OVER", "UNDER"}:
            continue
        if row.get("line") is None:
            raise ValueError("SOURCE_LEDGER_NARROW_BAND_LINE_REQUIRED")
        line = _finite(row["line"], "line")
        (over_lines if side == "OVER" else under_lines).append(line)
    if not over_lines or not under_lines:
        return ()

    minimum_winner = max(floor(line) + 1 for line in over_lines)
    maximum_winner = min(ceil(line) - 1 for line in under_lines)
    if minimum_winner > maximum_winner:
        return ()
    return tuple(range(minimum_winner, maximum_winner + 1))


def narrow_band_classification(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    centers = narrow_band_integer_centers(rows)
    return {
        "classification": "NARROW_BAND_SAME_CENTER" if len(centers) == 1 else "NO_SINGLE_INTEGER_NARROW_BAND",
        "shared_winning_integer_outcomes": list(centers),
        "independent_source_classes": independent_source_class_count(rows) if rows else 0,
        "confirmation_votes": independent_source_class_count(rows) if rows else 0,
        **ZERO_AUTHORITY,
    }


def _reference_quote(raw: Mapping[str, object]) -> dict[str, object]:
    venue = _identity(raw.get("venue"), "reference_venue")
    odds = _optional_odds(raw.get("odds"), "reference_odds")
    if odds is None:
        raise ValueError("SOURCE_LEDGER_REFERENCE_ODDS_REQUIRED")
    observed = _timestamp(raw.get("observed_at_ts"), "reference_observed_at_ts")
    size = raw.get("available_size")
    if size is not None:
        size = _finite(size, "reference_available_size")
        if size < 0:
            raise ValueError("SOURCE_LEDGER_SIZE_NEGATIVE")
    return {
        "venue": venue,
        "odds": odds,
        "raw_implied_probability": raw_implied_probability(odds),
        "observed_at_ts": observed,
        "available_size": size,
    }


def _price_persisted(initial_odds: int, later_odds: int) -> bool:
    """True when the later quote is at least as favorable to the bettor."""
    return american_to_decimal(later_odds) >= american_to_decimal(initial_odds)


def build_radar_candidate(
    *,
    source_family_id: str,
    attempt_id: str,
    candidate_id: str,
    entity_id: str,
    market_id: str,
    soft_venue: str,
    soft_odds: int,
    observed_at_ts: str,
    reference_quotes: Sequence[Mapping[str, object]],
    persistence_30s_odds: int | None = None,
    persistence_180s_odds: int | None = None,
    usable_size: float | None = None,
    exchange_flow_prints: Sequence[float] = (),
) -> dict[str, object]:
    family = _identity(source_family_id, "source_family_id")
    attempt = _identity(attempt_id, "attempt_id")
    candidate = _identity(candidate_id, "candidate_id")
    entity = _identity(entity_id, "entity_id")
    market = _identity(market_id, "market_id")
    venue = _identity(soft_venue, "soft_venue")
    initial = _optional_odds(soft_odds, "soft_odds")
    if initial is None:
        raise ValueError("SOURCE_LEDGER_SOFT_ODDS_REQUIRED")
    first_seen = _timestamp(observed_at_ts, "observed_at_ts")
    refs = [_reference_quote(q) for q in reference_quotes]
    if not refs:
        raise ValueError("SOURCE_LEDGER_RADAR_REFERENCE_REQUIRED")

    initial_implied = raw_implied_probability(initial)
    max_reference_implied = max(float(q["raw_implied_probability"]) for q in refs)
    radar_shape = (
        "STALE_SOFT_PRICE_CANDIDATE" if max_reference_implied > initial_implied else
        "NO_STALE_SOFT_PRICE_SHAPE"
    )

    p30 = _optional_odds(persistence_30s_odds, "persistence_30s_odds")
    p180 = _optional_odds(persistence_180s_odds, "persistence_180s_odds")
    persisted_30 = None if p30 is None else _price_persisted(initial, p30)
    persisted_180 = None if p180 is None else _price_persisted(initial, p180)

    resolved_size = None if usable_size is None else _finite(usable_size, "usable_size")
    if resolved_size is not None and resolved_size < 0:
        raise ValueError("SOURCE_LEDGER_SIZE_NEGATIVE")

    if persisted_30 is False or persisted_180 is False:
        takeability = "TAKEABILITY_FAILED_PERSISTENCE"
    elif persisted_30 is True and persisted_180 is True and resolved_size is not None and resolved_size > 0:
        takeability = "TAKEABILITY_OBSERVED"
    else:
        takeability = "TAKEABILITY_UNVERIFIED"

    prints: list[float] = []
    for value in exchange_flow_prints:
        amount = _finite(value, "exchange_flow_print")
        if amount < 0:
            raise ValueError("SOURCE_LEDGER_FLOW_PRINT_NEGATIVE")
        prints.append(amount)

    return {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "source_family_id": family,
        "attempt_id": attempt,
        "candidate_id": candidate,
        "entity_id": entity,
        "market_id": market,
        "soft_venue": venue,
        "soft_odds": initial,
        "soft_raw_implied_probability": initial_implied,
        "observed_at_ts": first_seen,
        "reference_quotes": refs,
        "max_reference_raw_implied_probability": max_reference_implied,
        "radar_classification": radar_shape,
        "persistence_30s_odds": p30,
        "persistence_180s_odds": p180,
        "persisted_at_30s": persisted_30,
        "persisted_at_180s": persisted_180,
        "usable_size": resolved_size,
        "takeability_status": takeability,
        "exchange_flow_prints": prints,
        "exchange_flow_total": sum(prints),
        "exchange_flow_semantics": "FACTUAL_PRINTS_ONLY_NO_WHALE_INFERENCE",
        "projection_correctness_inferred_from_radar": False,
        "nfl_props_engine": NFL_PROPS_ENGINE,
        **ZERO_AUTHORITY,
    }


def append_radar_attempt(
    ledger: Sequence[Mapping[str, object]], new_attempt: Mapping[str, object]
) -> tuple[dict[str, object], ...]:
    """Append-only radar observation helper; existing attempts cannot be replaced."""
    rows = [dict(row) for row in ledger]
    attempt_id = _identity(new_attempt.get("attempt_id"), "attempt_id")
    if any(_identity(row.get("attempt_id"), "attempt_id") == attempt_id for row in rows):
        raise ValueError("SOURCE_LEDGER_RADAR_ATTEMPT_DUPLICATE")
    new_ts = datetime.fromisoformat(_timestamp(new_attempt.get("observed_at_ts"), "observed_at_ts").replace("Z", "+00:00"))
    if rows:
        prior_ts = datetime.fromisoformat(_timestamp(rows[-1].get("observed_at_ts"), "observed_at_ts").replace("Z", "+00:00"))
        if new_ts <= prior_ts:
            raise ValueError("SOURCE_LEDGER_RADAR_ATTEMPT_NOT_CHRONOLOGICAL")
    rows.append(dict(new_attempt))
    return tuple(rows)


def grade_source_family_evidence(sample_n: int) -> dict[str, object]:
    if isinstance(sample_n, bool) or not isinstance(sample_n, int) or sample_n < 0:
        raise ValueError("SOURCE_LEDGER_SAMPLE_N_INVALID")
    return {
        "sample_n": sample_n,
        "minimum_review_n": MIN_SOURCE_FAMILY_EVIDENCE_N,
        "status": (
            "INSUFFICIENT_EVIDENCE" if sample_n < MIN_SOURCE_FAMILY_EVIDENCE_N else
            "REVIEWABLE_CONTEXT_ONLY_NO_AUTHORITY"
        ),
        "nfl_props_engine": NFL_PROPS_ENGINE,
        **ZERO_AUTHORITY,
    }
