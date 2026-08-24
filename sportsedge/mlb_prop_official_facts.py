"""Adapt proven MLB settlement-semantics facts into prop-specific realized outcomes.

This module consumes the hash-bound facts artifact produced by the settlement probe.
It does not fetch live data and it does not decide sportsbook settlement. The output
is only the official realized count for the requested game/player/market.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SUPPORTED = {
    "PITCHER_OUTS": ("pitchers", "outs"),
    "PITCHER_ER": ("pitchers", "earned_runs"),
    "RBI": ("batters", "rbi"),
}


class OfficialPropFactError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise OfficialPropFactError(f"{name} must be a non-negative integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise OfficialPropFactError(f"{name} must be a non-negative integer") from exc
    if out < 0 or float(out) != float(value):
        raise OfficialPropFactError(f"{name} must be a non-negative integer")
    return out


def prop_fact_from_settlement_report(
    report: Mapping[str, Any],
    *,
    market: str,
    game_id: str,
    entity_id: str,
) -> dict[str, Any]:
    """Return a canonical FINAL_OFFICIAL fact row or fail closed."""
    market_key = str(market or "").strip().upper()
    if market_key not in SUPPORTED:
        raise OfficialPropFactError(f"unsupported market {market_key!r}")
    game_key = str(game_id or "").strip()
    entity_key = str(entity_id or "").strip()
    if not game_key or not entity_key:
        raise OfficialPropFactError("game_id and entity_id required")
    if str(report.get("state") or "") != "SETTLEMENT_SEMANTICS_PASS":
        raise OfficialPropFactError("settlement semantics report is not PASS")

    facts = report.get("facts")
    if not isinstance(facts, Mapping):
        raise OfficialPropFactError("facts object required")
    expected_hash = str(report.get("facts_sha256") or "").strip().lower()
    if len(expected_hash) != 64 or _sha256(facts) != expected_hash:
        raise OfficialPropFactError("facts_sha256 mismatch")
    report_game = str(facts.get("game_pk") or report.get("game_pk") or "").strip()
    if report_game != game_key:
        raise OfficialPropFactError("game_id does not match settlement facts")
    if str(facts.get("status") or "") != "Final":
        raise OfficialPropFactError("official game fact is not Final")

    collection_name, value_name = SUPPORTED[market_key]
    collection = facts.get(collection_name)
    if not isinstance(collection, list):
        raise OfficialPropFactError(f"{collection_name} facts missing")
    match = None
    for row in collection:
        if isinstance(row, Mapping) and str(row.get("player_id") or "").strip() == entity_key:
            if match is not None:
                raise OfficialPropFactError("duplicate player fact")
            match = row
    if match is None:
        raise OfficialPropFactError("player fact not found")

    return {
        "market": market_key,
        "game_id": game_key,
        "entity_id": entity_key,
        "realized_count": _nonnegative_int(match.get(value_name), value_name),
        "fact_state": "FINAL_OFFICIAL",
        "facts_sha256": expected_hash,
        "facts_source": str(report.get("source") or facts.get("source") or "").strip(),
    }
