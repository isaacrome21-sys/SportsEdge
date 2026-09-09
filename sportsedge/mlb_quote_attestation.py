"""Acquisition-origin integrity binding for MLB sportsbook quotes.

The sportsbook/provider identity in this module is created only at the provider
normalization boundary. Canonical MLB identity remains an independent StatsAPI
binding. A The Odds API event id is never rewritten to an MLB ``gamePk`` and an
MLB ``game_number`` is never represented as provider-origin data.

The SHA-256 is an integrity binding, not a cryptographic statement that the
provider is authentic. Authenticity comes from the acquisition path that created
this object (real provider response + independent MLB schedule binding).
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from math import isfinite
from typing import Any, Mapping
import unicodedata


class QuoteAttestationError(ValueError):
    pass


SOURCE_PROVIDER = "THE_ODDS_API"
SOURCE_IDENTITY_VERSION = "the_odds_api_mlb_source_identity_v1"
QUOTE_HASH_ALGORITHM = "SHA256"
QUOTE_HASH_SCHEMA_VERSION = "mlb_acquisition_quote_v1"


def _norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None:
        raise QuoteAttestationError(f"ACQUISITION_IDENTITY_MISSING:{key}")
    text = str(value).strip()
    if not text:
        raise QuoteAttestationError(f"ACQUISITION_IDENTITY_MISSING:{key}")
    return text


def _timestamp_text(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise QuoteAttestationError("ACQUISITION_QUOTE_TIMESTAMP_NAIVE")
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        raise QuoteAttestationError("ACQUISITION_QUOTE_TIMESTAMP_MISSING")
    return text


def _finite_number(value: Any, field: str) -> int | float:
    if isinstance(value, bool):
        raise QuoteAttestationError(f"ACQUISITION_QUOTE_{field.upper()}_INVALID")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QuoteAttestationError(f"ACQUISITION_QUOTE_{field.upper()}_INVALID") from exc
    if not isfinite(number):
        raise QuoteAttestationError(f"ACQUISITION_QUOTE_{field.upper()}_INVALID")
    return int(number) if number.is_integer() else number


def _team_id(game: Any, side: str) -> Any:
    primary = f"{side}_id"
    live = f"{side}_team_id"
    value = getattr(game, primary, None)
    return value if value is not None else getattr(game, live, None)


def _team_name(game: Any, side: str) -> str:
    return str(getattr(game, f"{side}_name", "") or "").strip()


def _canonical_payload(quote: Mapping[str, Any]) -> dict[str, Any]:
    line = quote.get("line")
    return {
        "source_provider": _required_text(quote, "source_provider"),
        "source_event_id": _required_text(quote, "source_event_id"),
        "source_home_team_name": _required_text(quote, "source_home_team_name"),
        "source_away_team_name": _required_text(quote, "source_away_team_name"),
        "source_identity_version": _required_text(quote, "source_identity_version"),
        "canonical_game_id": _required_text(quote, "canonical_game_id"),
        "canonical_game_number": quote.get("canonical_game_number"),
        "canonical_home_team_id": _required_text(quote, "canonical_home_team_id"),
        "canonical_away_team_id": _required_text(quote, "canonical_away_team_id"),
        "game_id": _required_text(quote, "game_id"),
        "book_key": _required_text(quote, "book_key"),
        "sportsbook": str(quote.get("sportsbook") or "").strip(),
        "retrieved_at": _timestamp_text(quote.get("retrieved_at")),
        "market": _required_text(quote, "market").upper(),
        "raw_market_name": _required_text(quote, "raw_market_name"),
        "entity_id": _required_text(quote, "entity_id"),
        "side": _required_text(quote, "side").upper(),
        "line": None if line is None else _finite_number(line, "line"),
        "american_odds": _finite_number(quote.get("american_odds"), "american_odds"),
        "is_alternate": quote.get("is_alternate"),
        "offer_id": str(quote.get("offer_id") or "").strip(),
        "selection": str(quote.get("selection") or "").strip(),
    }


def acquisition_quote_sha256(quote: Mapping[str, Any]) -> str:
    payload = _canonical_payload(quote)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def stamp_the_odds_api_quote(quote: Mapping[str, Any], *, provider_event: Mapping[str, Any], game: Any) -> dict[str, Any]:
    """Stamp source identity while the raw provider event is still in hand."""
    if not isinstance(provider_event, Mapping):
        raise QuoteAttestationError("ACQUISITION_PROVIDER_EVENT_MALFORMED")
    source_event_id = _required_text(provider_event, "id")
    source_home = _required_text(provider_event, "home_team")
    source_away = _required_text(provider_event, "away_team")
    game_home = _team_name(game, "home")
    game_away = _team_name(game, "away")
    if not game_home or not game_away:
        raise QuoteAttestationError("CANONICAL_GAME_TEAM_IDENTITY_MISSING")
    if _norm_name(source_home) != _norm_name(game_home) or _norm_name(source_away) != _norm_name(game_away):
        raise QuoteAttestationError("ACQUISITION_PROVIDER_TEAM_BINDING_MISMATCH")

    game_pk = getattr(game, "game_pk", None)
    home_id = _team_id(game, "home")
    away_id = _team_id(game, "away")
    if game_pk is None or home_id is None or away_id is None:
        raise QuoteAttestationError("CANONICAL_GAME_IDENTITY_MISSING")

    out = dict(quote)
    out.update(
        source_provider=SOURCE_PROVIDER,
        source_event_id=source_event_id,
        source_home_team_name=source_home,
        source_away_team_name=source_away,
        source_identity_version=SOURCE_IDENTITY_VERSION,
        canonical_game_id=str(game_pk),
        canonical_game_number=getattr(game, "game_number", None),
        canonical_home_team_id=str(home_id),
        canonical_away_team_id=str(away_id),
        quote_hash_algorithm=QUOTE_HASH_ALGORITHM,
        quote_hash_schema_version=QUOTE_HASH_SCHEMA_VERSION,
    )
    if str(out.get("game_id") or "") != str(game_pk):
        raise QuoteAttestationError("ACQUISITION_CANONICAL_GAME_BINDING_MISMATCH")
    out["acquisition_quote_sha256"] = acquisition_quote_sha256(out)
    return out


def validate_acquisition_quote(quote: Mapping[str, Any], *, game: Any) -> None:
    """Validate exact source/hash binding before feature or model execution.

    LiveGame does not retain provider-facing team names, so the downstream check
    binds the already-hashed source names to the independent canonical game/team
    IDs. When names are available (GameSnapshot), they are checked again too.
    """
    if _required_text(quote, "source_provider") != SOURCE_PROVIDER:
        raise QuoteAttestationError("ACQUISITION_PROVIDER_UNSUPPORTED")
    if _required_text(quote, "source_identity_version") != SOURCE_IDENTITY_VERSION:
        raise QuoteAttestationError("ACQUISITION_SOURCE_IDENTITY_VERSION_MISMATCH")
    if _required_text(quote, "quote_hash_algorithm") != QUOTE_HASH_ALGORITHM:
        raise QuoteAttestationError("ACQUISITION_QUOTE_HASH_ALGORITHM_MISMATCH")
    if _required_text(quote, "quote_hash_schema_version") != QUOTE_HASH_SCHEMA_VERSION:
        raise QuoteAttestationError("ACQUISITION_QUOTE_HASH_SCHEMA_MISMATCH")

    game_pk = str(getattr(game, "game_pk", "") or "")
    home_raw = _team_id(game, "home")
    away_raw = _team_id(game, "away")
    if not game_pk or home_raw is None or away_raw is None:
        raise QuoteAttestationError("CANONICAL_GAME_IDENTITY_MISSING")
    home_id = str(home_raw)
    away_id = str(away_raw)
    if _required_text(quote, "canonical_game_id") != game_pk or _required_text(quote, "game_id") != game_pk:
        raise QuoteAttestationError("ACQUISITION_CANONICAL_GAME_BINDING_MISMATCH")
    if _required_text(quote, "canonical_home_team_id") != home_id or _required_text(quote, "canonical_away_team_id") != away_id:
        raise QuoteAttestationError("ACQUISITION_CANONICAL_TEAM_BINDING_MISMATCH")

    official_number = getattr(game, "game_number", None)
    attested_number = quote.get("canonical_game_number")
    if official_number is not None and attested_number != official_number:
        raise QuoteAttestationError("ACQUISITION_CANONICAL_GAME_NUMBER_MISMATCH")

    game_home = _team_name(game, "home")
    game_away = _team_name(game, "away")
    if game_home and _norm_name(_required_text(quote, "source_home_team_name")) != _norm_name(game_home):
        raise QuoteAttestationError("ACQUISITION_SOURCE_HOME_TEAM_MISMATCH")
    if game_away and _norm_name(_required_text(quote, "source_away_team_name")) != _norm_name(game_away):
        raise QuoteAttestationError("ACQUISITION_SOURCE_AWAY_TEAM_MISMATCH")

    attested = _required_text(quote, "acquisition_quote_sha256").lower()
    if len(attested) != 64 or any(ch not in "0123456789abcdef" for ch in attested):
        raise QuoteAttestationError("ACQUISITION_QUOTE_HASH_MALFORMED")
    expected = acquisition_quote_sha256(quote)
    if attested != expected:
        raise QuoteAttestationError("ACQUISITION_QUOTE_HASH_MISMATCH")
