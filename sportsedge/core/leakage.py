"""Fail-closed temporal leakage checks shared by football feature builders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        if not isinstance(value, str) or not value:
            raise ValueError("INVALID_TIMESTAMP")
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return out.astimezone(timezone.utc)


def assert_feature_asof_before_game(rows: Iterable[Mapping[str, Any]]) -> None:
    """Reject any row whose feature cut is not strictly prior to kickoff."""

    for index, row in enumerate(rows):
        feature_ts = _parse_ts(row.get("feature_asof_ts"))
        game_ts = _parse_ts(row.get("game_start_ts"))
        if feature_ts >= game_ts:
            game_id = row.get("game_id", f"row_{index}")
            raise ValueError(f"FEATURE_TIME_LEAK:{game_id}")


def assert_source_pit_integrity(rows: Iterable[Mapping[str, Any]]) -> None:
    """Reject source-level look-ahead and unverifiable timestamp envelopes.

    Promotion-grade rows must prove when the source observation was available, when it
    was incorporated into the feature cut, and when it was ingested. ``max_latency_seconds``
    is a source-contract bound, not a grace period for post-kick data.
    """

    for index, row in enumerate(rows):
        game_id = str(row.get("game_id") or f"row_{index}")
        source_ts = _parse_ts(row.get("source_asof_ts"))
        feature_ts = _parse_ts(row.get("feature_asof_ts"))
        ingested_ts = _parse_ts(row.get("ingested_ts"))
        game_ts = _parse_ts(row.get("game_start_ts"))
        source_id = str(row.get("source_id") or "").strip()
        source_version = str(row.get("source_version") or "").strip()
        provenance_id = str(row.get("provenance_id") or "").strip()
        if not source_id or not source_version or not provenance_id:
            raise ValueError(f"SOURCE_PROVENANCE_REQUIRED:{game_id}")
        latency_raw = row.get("max_latency_seconds")
        if isinstance(latency_raw, bool):
            raise ValueError(f"SOURCE_LATENCY_INVALID:{game_id}")
        try:
            max_latency = int(latency_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SOURCE_LATENCY_INVALID:{game_id}") from exc
        if max_latency < 0:
            raise ValueError(f"SOURCE_LATENCY_INVALID:{game_id}")
        if source_ts > feature_ts:
            raise ValueError(f"SOURCE_AFTER_FEATURE_CUT:{game_id}")
        if feature_ts >= game_ts:
            raise ValueError(f"FEATURE_TIME_LEAK:{game_id}")
        if source_ts >= game_ts:
            raise ValueError(f"SOURCE_TIME_LEAK:{game_id}")
        latency = (ingested_ts - source_ts).total_seconds()
        if latency < 0:
            raise ValueError(f"SOURCE_INGESTION_CLOCK_INVALID:{game_id}")
        if latency > max_latency:
            raise ValueError(f"SOURCE_LATENCY_EXCEEDED:{game_id}")


def assert_no_market_fields(value: Any, *, banned_tokens: Iterable[str] = ()) -> None:
    """Generic recursive market-field leakage assertion for predictive payloads.

    Sport adapters may supply additional tokens. This catches common aliases that can
    otherwise bypass exact-key allow/deny lists.
    """

    tokens = {
        "spread", "total_line", "spread_line", "moneyline", "american_odds",
        "decimal_odds", "implied_probability", "implied_prob", "novig_prob",
        "no_vig_prob", "closing_line", "closing_price", "opening_line",
        "opening_price", "sportsbook", "book", "public_ticket", "public_money",
        "handle_pct", "ticket_pct", "consensus_line", "sharp_line",
    }
    tokens.update(str(x).strip().lower() for x in banned_tokens)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                name = str(key).strip().lower()
                if name in tokens or any(
                    fragment in name
                    for fragment in (
                        "implied_prob", "no_vig", "novig", "public_split",
                        "ticket_pct", "handle_pct", "sportsbook", "closing_odds",
                        "opening_odds",
                    )
                ):
                    raise ValueError(f"MARKET_FEATURE_LEAK:{path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for i, child in enumerate(node):
                walk(child, f"{path}[{i}]")

    walk(value, "root")
