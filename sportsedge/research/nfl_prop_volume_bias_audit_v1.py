"""Descriptive NFL player-prop volume-bias audit; no betting authority.

Consumes already-frozen *pregame* model/quote pairs subsequently joined to
results. It never reprices a board, selects a bet, changes a projection, or
counts historical rows as forward-validation evidence. Receipts must be
independently checked before any conclusion about live performance.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isfinite
from statistics import mean
from typing import Any, Mapping, Sequence


AUDIT_ID = "NFL_PROP_VOLUME_BIAS_AUDIT_V1"
STATUS = "RESEARCH_DIAGNOSTIC_ONLY"
MAX_CAPTURE_AGE_SECONDS = 180


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}_INVALID")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if not isfinite(result) or result < 0:
        raise ValueError(f"{field}_INVALID")
    return result


def _time(value: Any, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field}_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def _identifier(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}_REQUIRED")
    return value.strip()


def audit_nfl_prop_volume_bias(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit only rows with honest pregame receipts and known final outcomes.

    One row per game/player/market. Model and quote capture clocks must both
    precede kickoff; the quote must be no older than 180 seconds when the
    model entry was recorded. A single game's many props remain one cluster.
    The audit has no access to, and cannot verify, external source receipts.
    """
    if not isinstance(rows, (tuple, list)):
        raise ValueError("ROWS_REQUIRED")

    seen: set[tuple[str, str, str]] = set()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized: list[dict[str, Any]] = []

    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("ROW_REQUIRED")
        event = _identifier(raw, "event_id")
        player = _identifier(raw, "player_id")
        market = _identifier(raw, "market").upper()
        if raw.get("sport") != "NFL":
            raise ValueError("SPORT_MUST_BE_NFL")
        key = (event, player, market)
        if key in seen:
            raise ValueError("DUPLICATE_PLAYER_GAME_MARKET")
        seen.add(key)

        # A receipt ID is recorded but never treated as independently verified.
        _identifier(raw, "model_snapshot_id")
        _identifier(raw, "quote_id")
        _identifier(raw, "result_receipt_id")
        if raw.get("result_status") != "FINAL":
            raise ValueError("FINAL_RESULT_REQUIRED")
        kickoff = _time(raw.get("event_start"), "EVENT_START")
        entry = _time(raw.get("entry_captured_at"), "ENTRY_CAPTURED_AT")
        quote = _time(raw.get("quote_captured_at"), "QUOTE_CAPTURED_AT")
        result_time = _time(raw.get("result_captured_at"), "RESULT_CAPTURED_AT")
        if not quote <= entry < kickoff:
            raise ValueError("NOT_PROSPECTIVE_PREGAME_PAIR")
        if (entry - quote).total_seconds() > MAX_CAPTURE_AGE_SECONDS:
            raise ValueError("QUOTE_STALE_AT_ENTRY")
        if result_time < kickoff:
            raise ValueError("RESULT_BEFORE_GAME_START")

        projected = _number(raw.get("projected_mean"), "PROJECTED_MEAN")
        line = _number(raw.get("line"), "MARKET_LINE")
        actual = _number(raw.get("actual"), "ACTUAL")
        side = "UNDER" if projected < line else "OVER" if projected > line else "TIE"
        if raw.get("published_side") is not None:
            stated = str(raw["published_side"]).strip().upper()
            if stated not in {"UNDER", "OVER", "NONE"}:
                raise ValueError("PUBLISHED_SIDE_INVALID")
        else:
            stated = "NONE"
        predicted_agrees = stated == "NONE" or stated == side
        row = {
            "event_id": event,
            "market": market,
            "side": side,
            "published_side_agrees": predicted_agrees,
            "model_minus_actual": projected - actual,
            "model_minus_market": projected - line,
            "under_realized": actual < line,
            "over_realized": actual > line,
        }
        normalized.append(row)
        groups[event].append(row)
        by_market[market].append(row)

    def _breakdown(items: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(r["side"] for r in items)
        directional = counts["UNDER"] + counts["OVER"]
        independent_games = len({r["event_id"] for r in items})
        return {
            "rows": len(items),
            "distinct_games": independent_games,
            "under": counts["UNDER"],
            "over": counts["OVER"],
            "tie": counts["TIE"],
            "under_share": counts["UNDER"] / directional if directional else None,
            "mean_model_minus_actual": mean(r["model_minus_actual"] for r in items) if items else None,
            "mean_model_minus_market": mean(r["model_minus_market"] for r in items) if items else None,
            "published_direction_mismatches": sum(not r["published_side_agrees"] for r in items),
            "one_direction_warning": (
                directional >= 20 and independent_games >= 5
                and max(counts["UNDER"], counts["OVER"]) / directional >= 0.8
            ),
        }

    game_clusters = {
        event: {"prop_rows": len(items), "under": sum(r["side"] == "UNDER" for r in items),
                "over": sum(r["side"] == "OVER" for r in items)}
        for event, items in sorted(groups.items())
    }
    return {
        "audit_id": AUDIT_ID,
        "status": STATUS,
        "overall": _breakdown(normalized),
        "by_market": {market: _breakdown(items) for market, items in sorted(by_market.items())},
        "game_clusters": game_clusters,
        "warning_criteria": "AT_LEAST_20_DIRECTIONAL_ROWS_5_GAMES_AND_80_PERCENT_ONE_DIRECTION",
        "source_receipts_reverified": False,
        "forward_validation_counted": False,
        "market_admission": "NOT_VERIFIED",
        "model_p_authority": False,
        "play_authority": False,
        "research_only": True,
    }
