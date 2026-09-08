"""Fail-closed MLB market binding at the normalized quote/orchestration boundary.

This module binds model probability identity to sportsbook offer identity.  It must
not manufacture sportsbook/event/team/player identities in the model layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping


class BindingError(ValueError):
    pass


THRESHOLD_DOMAINS = frozenset({"NONE", "RUNS", "COUNT", "BINARY", "MARGIN"})
NO_THRESHOLD_MARKETS = frozenset({"MONEYLINE", "F5_MONEYLINE", "NRFI", "YRFI", "PITCHER_RECORD_WIN", "FIRST_HOME_RUN"})
RUN_THRESHOLD_MARKETS = frozenset({"TOTALS", "TEAM_TOTALS", "F5_TOTALS", "F5_TEAM_TOTALS"})
MARGIN_THRESHOLD_MARKETS = frozenset({"RUN_LINE", "F5_RUN_LINE"})
TEAM_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TEAM_TOTALS", "F5_MONEYLINE", "F5_RUN_LINE", "F5_TEAM_TOTALS"})
MULTI_PITCHER_PREFIX = "EITHER_PITCHER_"


@dataclass(frozen=True)
class MarketBindingSpec:
    market: str
    threshold_domain: str

    def __post_init__(self) -> None:
        market = str(self.market).strip().upper()
        domain = str(self.threshold_domain).strip().upper()
        if not market or domain not in THRESHOLD_DOMAINS:
            raise BindingError("BINDING_SPEC_INVALID")
        if market in NO_THRESHOLD_MARKETS and domain != "NONE":
            raise BindingError("THRESHOLD_DOMAIN_CONTRADICTION")
        if market in RUN_THRESHOLD_MARKETS and domain != "RUNS":
            raise BindingError("THRESHOLD_DOMAIN_CONTRADICTION")
        if market in MARGIN_THRESHOLD_MARKETS and domain != "MARGIN":
            raise BindingError("THRESHOLD_DOMAIN_CONTRADICTION")
        if market.startswith(MULTI_PITCHER_PREFIX) and domain != "COUNT":
            raise BindingError("THRESHOLD_DOMAIN_CONTRADICTION")
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "threshold_domain", domain)


def binding_spec_for_market(market: str) -> MarketBindingSpec:
    """Explicit domain declaration. Unknown markets never inherit/infer a domain."""
    m = str(market).strip().upper()
    explicit = {
        "MONEYLINE": "NONE", "RUN_LINE": "MARGIN", "TOTALS": "RUNS", "TEAM_TOTALS": "RUNS",
        "NRFI": "NONE", "YRFI": "NONE", "F5_MONEYLINE": "NONE", "F5_RUN_LINE": "MARGIN",
        "F5_TOTALS": "RUNS", "F5_TEAM_TOTALS": "RUNS", "PITCHER_RECORD_WIN": "NONE",
        "FIRST_HOME_RUN": "NONE",
    }
    if m in explicit:
        return MarketBindingSpec(m, explicit[m])
    # Prop markets must be explicitly count-domain by their registered canonical family.
    from .hitter_joint_engine import HITTER_MARKETS
    from .pitcher_joint_engine import PITCHER_MARKETS
    if m in HITTER_MARKETS or m in PITCHER_MARKETS:
        return MarketBindingSpec(m, "COUNT")
    raise BindingError("BINDING_SPEC_MISSING_EXPLICIT_THRESHOLD_DOMAIN")


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None or not str(value).strip():
        raise BindingError(f"BINDING_IDENTITY_MISSING:{key}")
    return str(value).strip()


def _aware(row: Mapping[str, Any], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BindingError(f"BINDING_TIMESTAMP_INVALID:{key}")
    return value


def _number(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool):
        raise BindingError(f"BINDING_NUMERIC_INVALID:{key}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise BindingError(f"BINDING_NUMERIC_INVALID:{key}") from exc
    if not isfinite(out):
        raise BindingError(f"BINDING_NUMERIC_INVALID:{key}")
    return out


def validate_quote_binding_identity(quote: Mapping[str, Any]) -> None:
    """Validate only identities that originate at acquisition/normalization."""
    for key in ("game_id", "market", "entity_id", "side", "period", "book_key", "raw_market_name"):
        _text(quote, key)
    _aware(quote, "retrieved_at")
    odds = _number(quote, "american_odds")
    if odds == 0 or -100 < odds < 100 or odds != int(odds):
        raise BindingError("BINDING_PRICE_INVALID")
    spec = binding_spec_for_market(_text(quote, "market"))
    if spec.threshold_domain != "NONE":
        _number(quote, "line")
    # Event-instance identity is required independently of game_id.  Do not synthesize it.
    event_id = quote.get("event_id")
    game_number = quote.get("game_number")
    if (event_id is None or not str(event_id).strip()) and game_number is None:
        raise BindingError("BINDING_EVENT_INSTANCE_MISSING")
    if game_number is not None:
        if isinstance(game_number, bool):
            raise BindingError("BINDING_GAME_NUMBER_INVALID")
        try:
            gn = int(game_number)
        except (TypeError, ValueError) as exc:
            raise BindingError("BINDING_GAME_NUMBER_INVALID") from exc
        if gn <= 0 or float(game_number) != gn:
            raise BindingError("BINDING_GAME_NUMBER_INVALID")
    if _text(quote, "market") in TEAM_MARKETS:
        _text(quote, "team_id")
    if _text(quote, "market").startswith(MULTI_PITCHER_PREFIX):
        ids = quote.get("pitcher_ids")
        if not isinstance(ids, (list, tuple)) or len(ids) != 2 or len({str(x).strip() for x in ids if str(x).strip()}) != 2:
            raise BindingError("BINDING_TWO_PITCHER_IDS_REQUIRED")
    if _text(quote, "market") == "FIRST_HOME_RUN" and _text(quote, "side") in {"YES", "PLAYER"}:
        _text(quote, "player_id")


def validate_probability_binding(probability: Mapping[str, Any], quote: Mapping[str, Any]) -> None:
    """Bind engine readout identity to the already-normalized executable quote."""
    validate_quote_binding_identity(quote)
    market = _text(quote, "market")
    spec = binding_spec_for_market(market)
    if _text(probability, "probability_market_id").upper() != market.upper():
        raise BindingError("BINDING_MARKET_MISMATCH")
    if _text(probability, "game_id") != _text(quote, "game_id"):
        raise BindingError("BINDING_GAME_MISMATCH")
    if _text(probability, "entity_id") != _text(quote, "entity_id"):
        raise BindingError("BINDING_ENTITY_MISMATCH")
    if _text(probability, "side").upper() != _text(quote, "side").upper():
        raise BindingError("BINDING_SIDE_MISMATCH")
    if _text(probability, "period").upper() != _text(quote, "period").upper():
        raise BindingError("BINDING_PERIOD_MISMATCH")
    if market in TEAM_MARKETS:
        if _text(probability, "probability_team_id") != _text(quote, "team_id"):
            raise BindingError("BINDING_TEAM_MISMATCH")
    if spec.threshold_domain != "NONE":
        threshold = _number(probability, "probability_threshold")
        line = _number(quote, "line")
        if market in MARGIN_THRESHOLD_MARKETS:
            if abs(threshold) != abs(line):
                raise BindingError("BINDING_THRESHOLD_MISMATCH")
        elif threshold != line:
            raise BindingError("BINDING_THRESHOLD_MISMATCH")
    source_market = _text(probability, "probability_source_market")
    if source_market.upper() != market.upper():
        raise BindingError("BINDING_SOURCE_MARKET_MISMATCH")
