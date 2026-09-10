"""Production readiness and Truth Gate resolution for football player props."""
from __future__ import annotations

import math
from typing import Any, Mapping

from sportsedge.edge_floors import FrozenEdgeFloor, require_production_edge_floor
from sportsedge.football_prop_certification import (
    assess_market_certification,
    load_certification_registry,
)
from sportsedge.football_prop_evidence import assess_market_evidence, load_evidence_registry
from sportsedge.football_prop_extended_run_machine import (
    PROVIDER_MARKETS,
    run_football_extended_props,
)
from sportsedge.truth_gate import american_to_decimal, decide_bet


_ONE_SIDED_ANYTIME_TD_MARKET = "player_anytime_td"
_ONE_SIDED_ANYTIME_TD_LANE = "EXPERIMENTAL_ONE_SIDED_ANYTIME_TD"


def _present_provider_markets(odds_snapshot: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    events = odds_snapshot.get("events")
    if not isinstance(events, list):
        return out
    for event in events:
        if not isinstance(event, Mapping):
            continue
        books = event.get("bookmakers")
        if not isinstance(books, list):
            continue
        for book in books:
            if not isinstance(book, Mapping):
                continue
            markets = book.get("markets")
            if not isinstance(markets, list):
                continue
            for row in markets:
                if not isinstance(row, Mapping):
                    continue
                key = str(row.get("key") or "").strip()
                if key in PROVIDER_MARKETS:
                    out.add(key)
    return out


def _floor_key(sport: str, provider_market: str) -> str:
    resolved = str(sport or "").strip().upper()
    market = str(provider_market or "").strip()
    if resolved not in {"NFL", "CFB"} or not market:
        raise ValueError("FOOTBALL_PROP_FLOOR_IDENTITY_INVALID")
    return f"{resolved}_{market}"


def _paired_price_available(row: Mapping[str, Any]) -> bool:
    """Resolve both current and legacy paired-price field names."""
    if "paired_price_available" in row:
        return bool(row.get("paired_price_available"))
    return bool(row.get("paired_price_present"))


def _probability_to_american(probability: float) -> float | None:
    p = float(probability)
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        return None
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def _apply_one_sided_anytime_td_economics(row: dict[str, Any]) -> bool:
    """Add offer-vs-Model_P economics for a fresh one-sided Anytime TD quote.

    A missing No quote makes a no-vig market probability unavailable; it does
    not make EV unknowable when a genuine Model_P already exists.  This helper
    never creates Model_P, never invents a fair market probability, and never
    marks the row promotable.  It is deliberately limited to player_anytime_td.
    """
    if str(row.get("provider_market") or "").strip() != _ONE_SIDED_ANYTIME_TD_MARKET:
        return False
    if _paired_price_available(row):
        return False
    if row.get("quote_fresh") is not True or bool(row.get("stale_quote")):
        return False
    if row.get("model_p") is None or row.get("american_odds") is None:
        return False

    model_p = float(row["model_p"])
    push_p = float(row.get("push_p") or 0.0)
    if (
        not math.isfinite(model_p)
        or not math.isfinite(push_p)
        or not 0.0 <= model_p <= 1.0
        or not 0.0 <= push_p < 1.0
        or model_p + push_p > 1.0 + 1e-12
    ):
        raise ValueError("FOOTBALL_PROP_ONE_SIDED_ANYTIME_TD_MODEL_P_INVALID")

    decimal_odds = american_to_decimal(float(row["american_odds"]))
    non_push = 1.0 - push_p
    conditional_model_p = model_p / non_push
    p_loss = max(0.0, 1.0 - model_p - push_p)
    break_even_p = 1.0 / decimal_odds
    ev = model_p * (decimal_odds - 1.0) - p_loss

    # Keep fair_market_p absent.  A one-sided quote cannot be de-vigged into a
    # market belief without inventing the missing side.
    row["fair_market_p"] = None
    row["market_no_vig_p"] = "UNAVAILABLE_ONE_SIDED"
    row["raw_break_even_p"] = break_even_p
    row["conditional_model_p"] = conditional_model_p
    row["model_fair_american_odds"] = _probability_to_american(conditional_model_p)
    row["ev_per_dollar"] = ev
    row["edge"] = None
    row["economics_basis"] = "ONE_SIDED_OFFER_VS_MODEL_P"
    row["devig_status"] = "UNAVAILABLE_ONE_SIDED"
    row["promotion_lane"] = _ONE_SIDED_ANYTIME_TD_LANE
    return True


def run_football_props_ready(
    *,
    evidence_registry: Mapping[str, Any] | None = None,
    certification_registry: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the shared-path prop model and resolve all OFFICIAL gates.

    There is no manual deployment boolean. For every provider market present on
    the board, artifact-bound evidence and certification are resolved first. If
    both are PASS, its *sport-namespaced* frozen edge floor must resolve before
    predictive inference. After inference, normal promotable markets require a
    fresh paired quote and the SportsEdge Truth Gate makes the PASS/OFFICIAL_BET
    decision. A fresh one-sided player_anytime_td quote may report EV against an
    already-existing Model_P, but stays EXPERIMENTAL and cannot be OFFICIAL.
    """
    sport = str(kwargs.get("sport") or "").strip().upper()
    artifact_sha = str(kwargs.get("expected_artifact_sha256") or "").strip().lower()
    odds_snapshot = kwargs.get("odds_snapshot")
    if not isinstance(odds_snapshot, Mapping):
        odds_snapshot = {}
    floor_path = str(kwargs.get("floor_path") or "config/truth_gate_floors.json")

    evidence = (
        dict(evidence_registry)
        if evidence_registry is not None
        else load_evidence_registry(sport)
    )
    certification = (
        dict(certification_registry)
        if certification_registry is not None
        else load_certification_registry(sport)
    )

    preflight_floors: dict[str, FrozenEdgeFloor] = {}
    for provider_market in sorted(_present_provider_markets(odds_snapshot)):
        evidence_state = assess_market_evidence(
            sport=sport,
            provider_market=provider_market,
            model_artifact_sha256=artifact_sha,
            registry=evidence,
        )
        certification_state = assess_market_certification(
            sport=sport,
            provider_market=provider_market,
            model_artifact_sha256=artifact_sha,
            registry=certification,
        )
        if evidence_state["ready"] and certification_state["ready"]:
            preflight_floors[provider_market] = require_production_edge_floor(
                market=_floor_key(sport, provider_market),
                path=floor_path,
            )

    report = run_football_extended_props(**kwargs)
    sport = str(report["sport"])
    ready_rows = 0
    certified_rows = 0
    truth_gate_rows = 0
    experimental_one_sided_anytime_td_rows = 0
    official_bets = 0

    for row in report["results"]:
        provider_market = str(row["provider_market"])
        row_artifact_sha = str(row["model_artifact_sha256"])
        floor_key = _floor_key(sport, provider_market)
        one_sided_anytime_td = _apply_one_sided_anytime_td_economics(row)
        evidence_state = assess_market_evidence(
            sport=sport,
            provider_market=provider_market,
            model_artifact_sha256=row_artifact_sha,
            registry=evidence,
        )
        certification_state = assess_market_certification(
            sport=sport,
            provider_market=provider_market,
            model_artifact_sha256=row_artifact_sha,
            registry=certification,
        )

        row["evidence_ready"] = evidence_state["ready"]
        row["evidence_required_groups"] = evidence_state["required_groups"]
        row["evidence_passed_groups"] = evidence_state["passed_groups"]
        row["evidence_missing_groups"] = evidence_state["missing_groups"]
        row["evidence_blocked_groups"] = evidence_state["blocked_groups"]
        row["evidence_blockers"] = evidence_state["blockers"]
        row["certification_ready"] = certification_state["ready"]
        row["certification_status"] = certification_state["status"]
        row["certification_blockers"] = certification_state["blockers"]
        row["truth_gate_floor_key"] = floor_key
        row["official_eligible"] = False

        if evidence_state["ready"]:
            ready_rows += 1
        if certification_state["ready"]:
            certified_rows += 1

        if not evidence_state["ready"]:
            row["bet_status"] = "BLOCKED"
            row["reason"] = evidence_state["blockers"][0]
            continue
        if not certification_state["ready"]:
            row["bet_status"] = "BLOCKED"
            row["reason"] = certification_state["blockers"][0]
            continue

        # A one-sided Anytime TD quote can consume an existing Model_P for EV,
        # but it cannot manufacture fair market probability or enter OFFICIAL.
        if one_sided_anytime_td:
            experimental_one_sided_anytime_td_rows += 1
            row["bet_status"] = "BLOCKED"
            row["reason"] = f"{sport}_PROP_ONE_SIDED_ANYTIME_TD_EXPERIMENTAL"
            row["truth_gate"] = {
                "decision": "BLOCK",
                "reason": row["reason"],
                "promotion_lane": _ONE_SIDED_ANYTIME_TD_LANE,
                "market_no_vig_p": "UNAVAILABLE_ONE_SIDED",
                "raw_break_even_p": row["raw_break_even_p"],
                "ev_per_dollar": row["ev_per_dollar"],
            }
            continue

        floor = preflight_floors.get(provider_market)
        if floor is None:
            row["bet_status"] = "BLOCKED"
            row["reason"] = f"PROP_FROZEN_FLOOR_PREFLIGHT_MISSING:{floor_key}"
            continue

        if row.get("quote_fresh") is not True:
            row["bet_status"] = "BLOCKED"
            row["reason"] = f"{sport}_PROP_QUOTE_STALE"
            continue
        fair_market_p = row.get("fair_market_p")
        if fair_market_p is None:
            row["bet_status"] = "BLOCKED"
            row["reason"] = (
                f"{sport}_PROP_PAIRED_PRICE_REQUIRED"
                if not _paired_price_available(row)
                else f"{sport}_PROP_ECONOMICS_REQUIRED"
            )
            continue

        decision = decide_bet(
            float(row["model_p"]),
            float(row["american_odds"]),
            fair_market_probability=float(fair_market_p),
            bound=True,
            fresh=True,
            deployed=True,
            edge_floor=float(floor.value_probability_points),
            push_probability=float(row.get("push_p", 0.0)),
        )
        truth_gate_rows += 1
        row["official_eligible"] = True
        row["bet_status"] = decision.bet_status
        row["reason"] = "TRUTH_GATE_RESOLVED"
        row["truth_gate"] = {
            "floor_key": floor_key,
            "edge_floor": float(floor.value_probability_points),
            "floor_method_version": floor.method_version,
            "floor_evidence_sha256": floor.evidence_sha256,
            "edge": decision.edge,
            "ev_per_dollar": decision.ev_per_dollar,
            "kelly_fraction": decision.kelly_fraction,
            "bet_status": decision.bet_status,
        }
        if decision.bet_status == "OFFICIAL_BET":
            official_bets += 1

    report["summary"]["evidence_ready_rows"] = ready_rows
    report["summary"]["evidence_blocked_rows"] = len(report["results"]) - ready_rows
    report["summary"]["certified_rows"] = certified_rows
    report["summary"]["truth_gate_rows"] = truth_gate_rows
    report["summary"]["experimental_one_sided_anytime_td_rows"] = (
        experimental_one_sided_anytime_td_rows
    )
    report["summary"]["official_bets"] = official_bets
    report["evidence_resolution"] = {
        "schema_version": evidence.get("schema_version"),
        "sport": sport,
        "resolution_time_enforced": True,
        "registry_override_used": evidence_registry is not None,
        "can_create_model_p": False,
        "can_promote": True,
    }
    report["certification_resolution"] = {
        "schema_version": certification.get("schema_version"),
        "sport": sport,
        "registry_override_used": certification_registry is not None,
        "deployment_derivation": "EVIDENCE_AND_CERTIFICATION_AND_SPORT_NAMESPACED_FROZEN_FLOOR",
        "manual_eligible_toggle_required": False,
        "promotion_grade_markets": sorted(preflight_floors),
        "promotion_grade_floor_keys": sorted(
            _floor_key(sport, market) for market in preflight_floors
        ),
    }
    return report
