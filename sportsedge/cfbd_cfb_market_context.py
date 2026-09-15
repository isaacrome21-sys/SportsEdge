"""CFBD CFB market context with explicit non-freshness semantics.

CFBD's live lines payload identifies a provider/book but does not provide a
source-native quote observation timestamp. Fetch time is therefore retained as
transport provenance only and can never satisfy a TTL, closing-line, promotion,
or OFFICIAL evidence contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CFBD_LINES_ENDPOINT = "https://api.collegefootballdata.com/lines"
DEFAULT_CONTRACT = Path("config/market_provider_contract_v1.json")
SCHEMA_VERSION = "SPORTSEDGE_CFBD_CFB_MARKET_CONTEXT_V1"
LANE = "CFB_MARKET_CONTEXT"


class CFBDMarketContextError(ValueError):
    pass


@dataclass(frozen=True)
class CFBDMarketContextSnapshot:
    rows: tuple[dict[str, Any], ...]
    rejected: tuple[dict[str, Any], ...]
    fetched_at_utc: str
    payload_sha256: str
    disposition: str


def _aware(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    elif isinstance(value, str) and value.strip():
        try:
            out = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise CFBDMarketContextError("FETCH_TIME_INVALID") from exc
    else:
        raise CFBDMarketContextError("FETCH_TIME_REQUIRED")
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBDMarketContextError("FETCH_TIME_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _num(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _american(value: Any) -> int | None:
    out = _num(value)
    if out is None or int(out) != out or out == 0:
        return None
    return int(out)


def _provider_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("name") or value.get("displayName") or "").strip()
    return str(value or "").strip()


def _load_cfbd_rule(path: str | Path = DEFAULT_CONTRACT) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "MARKET_PROVIDER_CONTRACT_V1":
        raise CFBDMarketContextError("PROVIDER_CONTRACT_SCHEMA_MISMATCH")
    rules = {str(row.get("provider")): row for row in payload.get("rules") or []}
    rule = rules.get("CFBD_LINES")
    if not isinstance(rule, Mapping):
        raise CFBDMarketContextError("CFBD_PROVIDER_RULE_MISSING")
    freshness = rule.get("freshness") or {}
    if freshness.get("source_native_timestamp_available") is not False:
        raise CFBDMarketContextError("CFBD_SOURCE_NATIVE_TIMESTAMP_MUST_BE_UNAVAILABLE")
    if freshness.get("fetch_timestamp_is_quote_observation") is not False:
        raise CFBDMarketContextError("CFBD_FETCH_TIME_MUST_NOT_BE_QUOTE_OBSERVATION")
    if freshness.get("ttl_eligible") is not False or freshness.get("ttl_seconds") is not None:
        raise CFBDMarketContextError("CFBD_TTL_MUST_BE_DISABLED")
    if rule.get("context_only") is not True:
        raise CFBDMarketContextError("CFBD_CONTEXT_ONLY_REQUIRED")
    for key in (
        "closing_benchmark_eligible",
        "exact_book_contract_eligible",
        "model_p_eligible",
        "truth_gate_eligible",
        "promotion_authority",
        "staking_authority",
        "official_authority",
    ):
        if rule.get(key) is not False:
            raise CFBDMarketContextError(f"CFBD_ZERO_AUTHORITY_REQUIRED:{key}")
    return rule


def _allowlisted_books(rule: Mapping[str, Any]) -> dict[str, str]:
    identity = rule.get("book_identity") or {}
    raw = identity.get("named_book_allowlist") or []
    books = {_norm(name): str(name) for name in raw if str(name).strip()}
    if not books:
        raise CFBDMarketContextError("CFBD_NAMED_BOOK_ALLOWLIST_EMPTY")
    return books


def _is_consensus(name: str) -> bool:
    return "consensus" in _norm(name)


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def _market_values(line: Mapping[str, Any]) -> dict[str, Any]:
    home_ml = _american(line.get("homeMoneyline", line.get("moneylineHome")))
    away_ml = _american(line.get("awayMoneyline", line.get("moneylineAway")))
    markets: dict[str, Any] = {}
    if home_ml is not None and away_ml is not None:
        markets["moneyline"] = {"home": home_ml, "away": away_ml, "paired": True}
    spread = _num(line.get("spread"))
    if spread is not None:
        markets["spread"] = {"source_spread": spread}
    total = _num(line.get("overUnder"))
    if total is not None:
        markets["total"] = {"over_under": total}
    return markets


def _slate_disposition(
    payload: list[Any],
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> str:
    if accepted:
        return "AVAILABLE"
    if not payload:
        return "VALID_NO_BET_SLATE"
    if any(row.get("reason") in {"CFBD_LINES_EMPTY", "CFBD_LINES_MISSING"} for row in rejected):
        return "BLOCKED_NO_ODDS"
    return "NO_ELIGIBLE_QUOTES"


def build_cfbd_cfb_market_context(
    payload: Any,
    *,
    fetched_at: datetime | str,
    contract_path: str | Path = DEFAULT_CONTRACT,
) -> CFBDMarketContextSnapshot:
    """Parse CFBD lines into context-only observations.

    The returned rows intentionally contain no `source_updated_at` or equivalent.
    `fetched_at_utc` says only when SportsEdge retrieved the payload.

    A source-attested empty top-level slate is a valid zero-bet slate. If CFBD
    returns scheduled game objects but their line collection is empty or absent,
    the snapshot is blocked for missing odds rather than treated as a successful
    zero-row market snapshot.
    """
    fetched = _aware(fetched_at)
    if not isinstance(payload, list):
        raise CFBDMarketContextError("CFBD_LINES_PAYLOAD_NOT_LIST")
    rule = _load_cfbd_rule(contract_path)
    allowlist = _allowlisted_books(rule)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for game in payload:
        if not isinstance(game, Mapping):
            rejected.append({"reason": "CFBD_GAME_NOT_OBJECT"})
            continue
        game_id = str(game.get("id") or game.get("gameId") or "").strip()
        line_rows = game.get("lines")
        if isinstance(line_rows, list):
            if not line_rows:
                rejected.append({"game_id": game_id or None, "reason": "CFBD_LINES_EMPTY"})
                continue
            candidates = line_rows
        elif "provider" in game or "linesProviderId" in game:
            candidates = [game]
        else:
            rejected.append({"game_id": game_id or None, "reason": "CFBD_LINES_MISSING"})
            continue

        for line in candidates:
            if not isinstance(line, Mapping):
                rejected.append({"game_id": game_id or None, "reason": "CFBD_LINE_NOT_OBJECT"})
                continue
            provider = _provider_name(line.get("provider"))
            if not provider:
                rejected.append({"game_id": game_id or None, "reason": "CFBD_PROVIDER_MISSING"})
                continue
            if _is_consensus(provider):
                rejected.append({"game_id": game_id or None, "sportsbook": provider, "reason": "CFBD_CONSENSUS_PROVIDER_INELIGIBLE"})
                continue
            canonical = allowlist.get(_norm(provider))
            if canonical is None:
                rejected.append({"game_id": game_id or None, "sportsbook": provider, "reason": "CFBD_PROVIDER_NOT_ALLOWLISTED"})
                continue
            markets = _market_values(line)
            if not markets:
                rejected.append({"game_id": game_id or None, "sportsbook": provider, "reason": "CFBD_SUPPORTED_MARKETS_MISSING"})
                continue
            accepted.append({
                "schema_version": SCHEMA_VERSION,
                "lane": LANE,
                "sport": "CFB",
                "game_id": game_id or None,
                "season": game.get("season"),
                "week": game.get("week"),
                "season_type": game.get("seasonType") or game.get("season_type"),
                "home_team": game.get("homeTeam") or game.get("home_team"),
                "away_team": game.get("awayTeam") or game.get("away_team"),
                "quote_provider": "CFBD_LINES",
                "sportsbook": canonical,
                "source_provider_name": provider,
                "markets": markets,
                "fetched_at_utc": fetched.isoformat(),
                "source_native_observed_at": None,
                "provider_timestamp_semantics": "FETCH_TIME_PROVENANCE_ONLY_NO_SOURCE_NATIVE_QUOTE_TIME",
                "fetched_at_is_quote_observation": False,
                "ttl_eligible": False,
                "freshness_eligible": False,
                "closing_benchmark_eligible": False,
                "opening_benchmark_eligible": False,
                "exact_book_contract_eligible": False,
                "market_context_only": True,
                "model_p_eligible": False,
                "truth_gate_eligible": False,
                "promotion_authority": False,
                "staking_authority": False,
                "official_authority": False,
            })

    return CFBDMarketContextSnapshot(
        rows=tuple(accepted),
        rejected=tuple(rejected),
        fetched_at_utc=fetched.isoformat(),
        payload_sha256=_payload_hash(payload),
        disposition=_slate_disposition(payload, accepted, rejected),
    )


def fetch_cfbd_cfb_market_context(
    *,
    year: int,
    week: int,
    season_type: str = "regular",
    api_key: str | None = None,
    opener: Callable = urlopen,
    now: datetime | None = None,
    contract_path: str | Path = DEFAULT_CONTRACT,
) -> CFBDMarketContextSnapshot:
    key = str(api_key or os.environ.get("CFBD_API_KEY") or "").strip()
    if not key:
        raise CFBDMarketContextError("CFBD_API_KEY_REQUIRED")
    fetched = _aware(now or datetime.now(timezone.utc))
    query = urlencode({"year": int(year), "week": int(week), "seasonType": str(season_type)})
    request = Request(
        f"{CFBD_LINES_ENDPOINT}?{query}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "SportsEdge-CFBD-context/1",
        },
    )
    try:
        with opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CFBDMarketContextError(f"CFBD_FETCH_FAILED:{type(exc).__name__}") from exc
    return build_cfbd_cfb_market_context(payload, fetched_at=fetched, contract_path=contract_path)


__all__ = [
    "CFBD_LINES_ENDPOINT",
    "CFBDMarketContextError",
    "CFBDMarketContextSnapshot",
    "SCHEMA_VERSION",
    "build_cfbd_cfb_market_context",
    "fetch_cfbd_cfb_market_context",
]
