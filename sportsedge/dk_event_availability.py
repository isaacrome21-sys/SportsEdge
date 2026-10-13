"""Fail-closed, fixture-specific DraftKings market availability inventory.

A catalog lists possible market contracts, NOT the selections offered in a
particular matchup. Provider maps (e.g. The Odds API) and deployment/model
readiness are separate dimensions; neither establishes DraftKings availability.
This module never fetches a sportsbook, prices a market, or grants authority.

Observation schema V1 (caller supplies already captured evidence):
    {
      "sport": "MLB", "event_id": "...", "book": "draftkings",
      "observed_at_utc": "2026-10-13T12:00:00Z",
      "source_url": "https://sportsbook.draftkings.com/...",
      "required_tabs": ["Popular", "Pitcher", "Batter"],
      "inspected_tabs": ["Popular", "Pitcher", "Batter"],
      "market_observations": [
        {"market": "F5_TEAM_TOTALS", "period": "FIRST_5",
         "offer_shape": "TWO_SIDED_OU", "source_tab": "Popular",
         "phase": "PREGAME", "settlement": "RULE_UNVERIFIED"}
      ],
      "explicit_absent_markets": [
        {"market": "F5_TOTALS", "source_tab": "Popular"}
      ]
    }

A completely inspected set of tabs does not by itself establish that an
unlisted market was absent. Explicit market-scoped negative evidence is
required. No source observation can prove the market is globally absent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

OFFER_SHAPES = frozenset({
    "TWO_SIDED_OU", "TWO_SIDED_SPREAD", "TWO_SIDED_MONEYLINE",
    "THREE_WAY", "LADDER_ONLY", "SINGLE_SIDED_YES_NO",
    "MULTIWAY_EXCLUSIVE",
})
SPORTS = frozenset({"MLB", "NFL", "CFB"})
LINE_VARIANTS = frozenset({"MAIN", "ALTERNATE", "LADDER", "UNSPECIFIED"})
CONTRACT_DIMS = ("period", "phase", "offer_shape", "settlement", "line_variant")
ENGINE_STATES = frozenset({
    "PRICED_PATH", "NO_ENGINE", "ENGINE_BLOCKED",
    "UNVALIDATED_RESEARCH_ONLY", "NOT_REGISTERED", "UNVERIFIED",
})


class DKObservationError(ValueError):
    pass


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DKObservationError(label + "_REQUIRED")
    return value.strip()


def _clock(value: Any) -> datetime:
    try:
        time = datetime.fromisoformat(
            _required_text(value, "OBSERVED_AT").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise DKObservationError("OBSERVED_AT_INVALID") from exc
    if time.tzinfo is None or time.utcoffset() is None:
        raise DKObservationError("OBSERVED_AT_TIMEZONE_REQUIRED")
    return time.astimezone(timezone.utc)


def _dimension(value: Any, label: str) -> str:
    # Do not count "first half", "FIRST-HALF" and "FIRST_HALF" as
    # separate period contracts. Syntactic normalization only: we never
    # infer a missing rule or settlement from ambiguous text.
    return _required_text(value, label).upper().replace(" ", "_").replace("-", "_")


def _market(value: Any) -> str:
    return _dimension(value, "MARKET")


def reconcile_dk_event(
    registry_markets: Sequence[str],
    board: Mapping[str, Any],
    *,
    engine_states: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return separate event-offer, registry, market-shape and engine states.

    Market presence does not assert an engine, two-sided no-vig or a validated
    edge. A missing category in one game's board is never a universal absence.
    """
    if not isinstance(board, Mapping):
        raise DKObservationError("BOARD_MUST_BE_OBJECT")
    sport = _required_text(board.get("sport"), "SPORT").upper()
    if sport not in SPORTS:
        raise DKObservationError("SPORT_OUT_OF_SCOPE")
    event_id = _required_text(board.get("event_id"), "EVENT_ID")
    if str(board.get("book") or "").strip().lower() != "draftkings":
        raise DKObservationError("BOOK_NOT_DRAFTKINGS")
    timestamp = _clock(board.get("observed_at_utc"))
    url = _required_text(board.get("source_url"), "SOURCE_URL")
    if not url.startswith(("https://sportsbook.draftkings.com/",
                           "https://sportsbook.draftkings.com?")):
        raise DKObservationError("DRAFTKINGS_SOURCE_URL_REQUIRED")
    required_tabs = board.get("required_tabs")
    inspected_tabs = board.get("inspected_tabs")
    if not isinstance(required_tabs, list) or not required_tabs:
        raise DKObservationError("REQUIRED_TABS_MISSING")
    if not isinstance(inspected_tabs, list):
        raise DKObservationError("INSPECTED_TABS_MISSING")
    if any(not isinstance(t, str) or not t.strip() for t in required_tabs + inspected_tabs):
        raise DKObservationError("TAB_NAME_INVALID")
    if len(set(required_tabs)) != len(required_tabs) or len(set(inspected_tabs)) != len(inspected_tabs):
        raise DKObservationError("TAB_NAME_DUPLICATE")
    if not set(inspected_tabs).issubset(set(required_tabs)):
        raise DKObservationError("INSPECTED_TAB_NOT_DECLARED")
    tabs_complete = set(required_tabs) == set(inspected_tabs)
    observations = board.get("market_observations")
    absences = board.get("explicit_absent_markets")
    if not isinstance(observations, list) or not isinstance(absences, list):
        raise DKObservationError("OBSERVATION_LISTS_REQUIRED")

    # Market family != offered contract. A family can appear as both main
    # O/U and single-sided alternates, or in several periods/phases.
    # A market-name-only dict would erase these distinct offerings.
    seen: dict[str, list[dict[str, Any]]] = {}
    seen_contracts: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in observations:
        if not isinstance(item, Mapping):
            raise DKObservationError("MARKET_OBSERVATION_NOT_OBJECT")
        market = _market(item.get("market"))
        tab = _required_text(item.get("source_tab"), "MARKET_SOURCE_TAB")
        if tab not in inspected_tabs:
            raise DKObservationError("MARKET_TAB_NOT_INSPECTED:" + market)
        shape = _dimension(item.get("offer_shape"), "OFFER_SHAPE")
        if shape not in OFFER_SHAPES:
            raise DKObservationError("OFFER_SHAPE_UNVERIFIED:" + market)
        period = _dimension(item.get("period"), "PERIOD")
        phase = _dimension(item.get("phase"), "PHASE")
        settlement = _dimension(item.get("settlement"), "SETTLEMENT")
        line_variant = (_dimension(item["line_variant"], "LINE_VARIANT")
                        if item.get("line_variant") is not None
                        else "UNSPECIFIED")
        if line_variant not in LINE_VARIANTS:
            raise DKObservationError("LINE_VARIANT_INVALID:" + market)
        # Supply period/settlement as observed, even if unknown; neither can
        # be inferred from a market name. No source-backed rule -> unverified.
        if phase not in {"PREGAME", "LIVE"}:
            raise DKObservationError("PHASE_INVALID:" + market)
        contract = {
            "availability": "OFFERED_ON_THIS_EVENT",
            "offer_shape": shape, "period": period, "phase": phase,
            "settlement": settlement, "line_variant": line_variant,
            "source_tab": tab, "source_tabs": [tab],
        }
        identity = (market,) + tuple(contract[dim] for dim in CONTRACT_DIMS)
        if identity in seen_contracts:
            # The SAME contract can appear in both Popular and a stat
            # tab on one DK board. This is corroboration, not an extra
            # contract. Reject duplicates from a single tab so a
            # malformed scraper cannot inflate observed coverage.
            recorded = seen_contracts[identity]
            if tab in recorded["source_tabs"]:
                raise DKObservationError("DUPLICATE_MARKET_OBSERVATION:" + market)
            recorded["source_tabs"].append(tab)
            continue
        seen_contracts[identity] = contract
        seen.setdefault(market, []).append(contract)

    absent: dict[str, list[dict[str, Any]]] = {}
    for item in absences:
        if not isinstance(item, Mapping):
            raise DKObservationError("ABSENCE_NOT_OBJECT")
        market = _market(item.get("market"))
        tab = _required_text(item.get("source_tab"), "ABSENCE_SOURCE_TAB")
        if tab not in inspected_tabs:
            raise DKObservationError("ABSENCE_TAB_NOT_INSPECTED:" + market)
        scope = {"source_tab": tab}
        for field in CONTRACT_DIMS:
            supplied = item.get(field)
            scope[field] = (_dimension(supplied, field.upper())
                            if supplied is not None else None)
        if scope["line_variant"] is not None and scope["line_variant"] not in LINE_VARIANTS:
            raise DKObservationError("ABSENCE_LINE_VARIANT_INVALID:" + market)
        if scope["phase"] is not None and scope["phase"] not in {"PREGAME", "LIVE"}:
            raise DKObservationError("ABSENCE_PHASE_INVALID:" + market)
        if scope["offer_shape"] is not None and scope["offer_shape"] not in OFFER_SHAPES:
            raise DKObservationError("ABSENCE_OFFER_SHAPE_INVALID:" + market)
        # A scoped absence may coexist with a different OFFERED period, shape,
        # phase, settlement or alternate-line contract. Overlapping claims are
        # contradictory. Unscoped absence conflicts with *all* offered rows.
        for offer in seen.get(market, []):
            if all(scope[field] is None or scope[field] == offer[field]
                   for field in CONTRACT_DIMS):
                raise DKObservationError("OFFERED_AND_ABSENT_CONFLICT:" + market)
        scopes = absent.setdefault(market, [])
        if any(all(existing[f] == scope[f] for f in ("source_tab",) + CONTRACT_DIMS)
               for existing in scopes):
            raise DKObservationError("DUPLICATE_ABSENCE:" + market)
        scopes.append(scope)

    if not isinstance(registry_markets, Sequence) or isinstance(registry_markets, (str, bytes)):
        raise DKObservationError("REGISTRY_NOT_MARKET_LIST")
    registry = [_market(k) for k in registry_markets]
    if len(set(registry)) != len(registry):
        raise DKObservationError("REGISTRY_DUPLICATE_MARKET")
    if engine_states is None:
        engine_states = {}
    if not isinstance(engine_states, Mapping):
        raise DKObservationError("ENGINE_STATES_NOT_OBJECT")
    normalized_engines = {_market(k): v for k, v in engine_states.items()}
    if any(v not in ENGINE_STATES for v in normalized_engines.values()):
        raise DKObservationError("ENGINE_STATE_INVALID")
    all_markets = sorted(set(registry) | set(seen) | set(absent))
    rows = []
    for market in all_markets:
        variants = seen.get(market, [])
        scopes = absent.get(market, [])
        if variants:
            availability = "OFFERED_ON_THIS_EVENT"
        elif scopes and any(all(scope[d] is None for d in CONTRACT_DIMS)
                            for scope in scopes):
            availability = "NOT_OFFERED_ON_THIS_EVENT"
        else:
            # Only a specific contract is disproved; other variants of this
            # family remain unverified. Never call the whole family absent.
            availability = "NOT_VERIFIED_ON_THIS_EVENT"
        family_engine_state = normalized_engines.get(market, "UNVERIFIED")
        registered = market in registry
        # PRICED_PATH on a *family* does not prove that main, alternate and
        # ladder contracts each have a matching period/settlement-aware engine.
        # A family-wide block (NO_ENGINE) safely applies to every variant;
        # a claimed positive path is ambiguous across multiple contracts.
        engine_ambiguous = len(variants) > 1 and family_engine_state == "PRICED_PATH"
        engine_state = "UNVERIFIED" if engine_ambiguous else family_engine_state
        engine_scope = ("FAMILY_PATH_NOT_ATTESTED_FOR_EACH_VARIANT"
                        if engine_ambiguous else "CALLER_SUPPLIED_FAMILY_STATE")
        rows.append({
            "market": market, "registered": registered,
            "registration_status": "REGISTERED" if registered else "NOT_REGISTERED",
            "availability": availability,
            # Exactly one offer may be projected into the legacy single
            # evidence field. Otherwise there is no unambiguous variant.
            "evidence": variants[0] if len(variants) == 1 else {
                "source_tab": scopes[0]["source_tab"] if scopes and not variants else None,
                "offer_shape": None, "period": None,
                "phase": None, "settlement": "UNVERIFIED",
                "line_variant": None,
            },
            "offer_variants": sorted(variants, key=lambda v: tuple(v[k] for k in CONTRACT_DIMS)),
            "offer_variant_count": len(variants),
            "explicit_absence_scopes": scopes,
            "family_engine_state": family_engine_state if registered else "NOT_REGISTERED",
            "engine_state": engine_state if registered else "NOT_REGISTERED",
            "engine_state_scope": engine_scope if registered else "NOT_REGISTERED",
            "engine_state_source": "CALLER_SUPPLIED_NOT_INDEPENDENTLY_ATTESTED",
            "can_derive_two_sided_no_vig": False,
            "model_validated": False,
            "deployment_eligible": False,
        })
    return {
        "schema": "DK_EVENT_COVERAGE_RECONCILIATION_V1",
        "sport": sport, "book": "draftkings",
        "event_id": event_id, "source_url": url,
        "observed_at_utc": timestamp.isoformat(),
        "required_tabs": required_tabs, "inspected_tabs": inspected_tabs,
        "catalog_inspection_complete": tabs_complete,
        "catalog_verified_globally": False,
        "observation_evidence_is_user_supplied": True,
        "market_count": len(rows),
        "registered_count": len(registry),
        "offered_contract_count": sum(map(len, seen.values())),
        "distinct_offered_family_count": len(seen),
        "unregistered_offered": sorted(k for k in seen if k not in registry),
        "catalog_inspection_scope": "ONLY_CALLER_DECLARED_REQUIRED_TABS",
        "rows": rows,
        "promotion_authority": False,
        "notes": [
            "Availability is per sport, game, and capture time; never globalized.",
            "Each offered family may include multiple distinct periods, phases, settlement and alternate-line variants.",
            "A scoped absence does not establish absence of the entire market family.",
            "Provider documentation cannot be inferred from DraftKings board observations.",
            "Ladders do not create a second side, a no-vig benchmark, or model probability.",
            "No pricing, eligibility or research promotion is decided by this report.",
        ],
    }
