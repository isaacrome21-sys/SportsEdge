"""Direct-provider coverage map for the frozen 38-market MLB replay surface.

The map is intentionally conservative: a canonical SportsEdge market is mapped only
when The Odds API documents a direct MLB market key with matching semantics. Nearby
or algebraically related markets are not treated as substitutes. In particular,
NRFI/YRFI are not synthesized from first-inning totals and custom combination props
are not reconstructed from component props.

This module grants no promotion, Model_P, floor, Truth Gate, staking, or OFFICIAL
authority. Provider coverage is evidence plumbing only.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

PROVIDER = "THE_ODDS_API"
PROVIDER_DOCS_AS_OF = "2026-09-16"
PROVIDER_MARKET_DOCS = "https://the-odds-api.com/sports-odds-data/betting-markets.html"

# Direct semantic matches documented by the provider.
PROVIDER_KEY_BY_MARKET: dict[str, str] = {
    "MONEYLINE": "h2h",
    "RUN_LINE": "spreads",
    "TOTALS": "totals",
    "TEAM_TOTALS": "team_totals",
    "HOME_RUNS": "batter_home_runs",
    "HITS": "batter_hits",
    "TOTAL_BASES": "batter_total_bases",
    "RBI": "batter_rbis",
    "RUNS": "batter_runs_scored",
    "HITS_RUNS_RBIS": "batter_hits_runs_rbis",
    "SINGLES": "batter_singles",
    "DOUBLES": "batter_doubles",
    "TRIPLES": "batter_triples",
    "BATTER_BB": "batter_walks",
    "BATTER_K": "batter_strikeouts",
    "STOLEN_BASES": "batter_stolen_bases",
    "PITCHER_K": "pitcher_strikeouts",
    "PITCHER_HITS_ALLOWED": "pitcher_hits_allowed",
    "PITCHER_BB": "pitcher_walks",
    "PITCHER_ER": "pitcher_earned_runs",
    "PITCHER_OUTS": "pitcher_outs",
    "PITCHER_RECORD_WIN": "pitcher_record_a_win",
    "FIRST_HOME_RUN": "batter_first_home_run",
    "F5_MONEYLINE": "h2h_1st_5_innings",
    "F5_RUN_LINE": "spreads_1st_5_innings",
    "F5_TOTALS": "totals_1st_5_innings",
}

# Canonical markets for which the provider does not document a direct equivalent.
# These are explicit terminal source-coverage dispositions, not permission to infer.
NO_DIRECT_PROVIDER_KEY: dict[str, str] = {
    "EXTRA_BASE_HITS": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "HITS_RUNS_STOLEN_BASES": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "RUNS_RBIS": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "HITS_STOLEN_BASES": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "HITS_WALKS_STOLEN_BASES": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "PITCHER_HITS_WALKS_ER": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "EITHER_PITCHER_HITS_ALLOWED": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "EITHER_PITCHER_BB": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "EITHER_PITCHER_ER": "NO_DOCUMENTED_DIRECT_PROVIDER_MARKET",
    "NRFI": "DIRECT_NRFI_MARKET_NOT_DOCUMENTED_DO_NOT_DERIVE_FROM_1ST_INNING_TOTAL",
    "YRFI": "DIRECT_YRFI_MARKET_NOT_DOCUMENTED_DO_NOT_DERIVE_FROM_1ST_INNING_TOTAL",
    "F5_TEAM_TOTALS": "DIRECT_F5_TEAM_TOTAL_MARKET_NOT_DOCUMENTED",
}

MARKET_BY_PROVIDER_KEY = {value: key for key, value in PROVIDER_KEY_BY_MARKET.items()}

TEAM_SIDE_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "F5_MONEYLINE", "F5_RUN_LINE"})
BINARY_ENTITY_MARKETS = frozenset({"PITCHER_RECORD_WIN", "FIRST_HOME_RUN"})
TEAM_TOTAL_MARKETS = frozenset({"TEAM_TOTALS", "F5_TEAM_TOTALS"})
F5_MARKETS = frozenset({"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"})


def flatten_market_catalog(catalog: Mapping[str, Any]) -> list[str]:
    """Return the canonical market list while rejecting duplicates/non-list fields."""
    markets: list[str] = []
    for key, raw in catalog.items():
        if key == "schema_version":
            continue
        if not isinstance(raw, list):
            raise ValueError(f"MLB_MARKET_CATALOG_LIST_REQUIRED:{key}")
        markets.extend(str(value).strip().upper() for value in raw)
    if any(not market for market in markets):
        raise ValueError("MLB_MARKET_CATALOG_EMPTY_MARKET")
    if len(markets) != len(set(markets)):
        raise ValueError("MLB_MARKET_CATALOG_DUPLICATE_MARKET")
    return markets


def validate_provider_coverage(catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Prove every canonical market has a direct-map or explicit no-direct disposition."""
    markets = flatten_market_catalog(catalog)
    market_set = set(markets)
    direct = set(PROVIDER_KEY_BY_MARKET)
    unavailable = set(NO_DIRECT_PROVIDER_KEY)
    overlap = direct & unavailable
    missing = market_set - direct - unavailable
    extra = (direct | unavailable) - market_set
    status = "COMPLETE" if not overlap and not missing and not extra else "INVALID"
    return {
        "schema_version": 1,
        "provider": PROVIDER,
        "provider_docs_as_of": PROVIDER_DOCS_AS_OF,
        "canonical_market_count": len(markets),
        "direct_market_count": len(direct & market_set),
        "no_direct_market_count": len(unavailable & market_set),
        "status": status,
        "missing_disposition": sorted(missing),
        "extra_disposition": sorted(extra),
        "overlap": sorted(overlap),
        "promotion_authority": False,
        "may_change_market_eligibility": False,
    }


def canonical_market_for_provider_key(provider_key: str) -> str | None:
    return MARKET_BY_PROVIDER_KEY.get(str(provider_key or "").strip())


def provider_key_for_market(market: str) -> str | None:
    return PROVIDER_KEY_BY_MARKET.get(str(market or "").strip().upper())


def provider_keys_for_markets(markets: Iterable[str]) -> list[str]:
    """Return unique direct provider keys in stable input order; unsupported are omitted."""
    out: list[str] = []
    seen: set[str] = set()
    for market in markets:
        key = provider_key_for_market(market)
        if key is not None and key not in seen:
            seen.add(key)
            out.append(key)
    return out
