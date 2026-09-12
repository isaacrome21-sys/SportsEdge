#!/usr/bin/env python3
"""Build normalized CFB signal-quality rows from a timestamped capture bundle.

This adapter is intentionally provenance-first: it merges sportsbook market rows with
explicitly captured game context, computes freshness ages from timestamps, binds model
registry state, and never invents missing Model_P, injuries, weather, handles, or prices.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REGISTRY = Path("config/cfb_game_model_freeze.json")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _age_minutes(captured_at: str | None, as_of: datetime) -> float | None:
    captured = _parse_ts(captured_at)
    if captured is None:
        return None
    age = (as_of - captured).total_seconds() / 60.0
    if age < -1e-9:
        raise ValueError(f"capture timestamp is after as_of: {captured_at}")
    return round(max(0.0, age), 6)


def _context_index(capture: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    games = capture.get("games") or []
    if not isinstance(games, list):
        raise ValueError("games must be a list")
    out: dict[str, Mapping[str, Any]] = {}
    for game in games:
        if not isinstance(game, Mapping) or not game.get("game_id"):
            raise ValueError("every game context row needs game_id")
        game_id = str(game["game_id"])
        if game_id in out:
            raise ValueError(f"duplicate game_id context: {game_id}")
        out[game_id] = game
    return out


def _sources(*groups: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for source in group or []:
            if not isinstance(source, Mapping):
                raise ValueError("source provenance rows must be objects")
            item = dict(source)
            key = (
                str(item.get("family", "")).strip().lower(),
                str(item.get("kind", "")).strip().lower(),
                str(item.get("captured_at", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
    return rows


def build_rows(
    capture: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Normalize a capture bundle into evaluator-ready rows."""
    markets = capture.get("markets") or []
    if not isinstance(markets, list):
        raise ValueError("markets must be a list")

    if as_of is None:
        as_of = _parse_ts(capture.get("as_of"))
    if as_of is None:
        raise ValueError("capture needs timezone-aware as_of")
    if as_of.tzinfo is None:
        raise ValueError("as_of must include timezone")
    as_of = as_of.astimezone(timezone.utc)

    games = _context_index(capture)
    output: list[dict[str, Any]] = []
    seen_market_ids: set[str] = set()

    for raw in markets:
        if not isinstance(raw, Mapping):
            raise ValueError("market rows must be objects")
        for required in ("game_id", "market_id", "market_type", "selection", "sportsbook", "current_odds", "current_market_value", "captured_at"):
            if raw.get(required) is None:
                raise ValueError(f"market row missing {required}")

        market_id = str(raw["market_id"])
        if market_id in seen_market_ids:
            raise ValueError(f"duplicate market_id: {market_id}")
        seen_market_ids.add(market_id)

        game_id = str(raw["game_id"])
        ctx = games.get(game_id, {})
        row = deepcopy(dict(raw))

        row["model_registry_status"] = registry.get("status")
        row["promotion_authority"] = bool(registry.get("promotion_authority", False))
        row["model_p"] = raw.get("model_p") if row["model_registry_status"] == "FROZEN" and row["promotion_authority"] else None
        row["truth_gate_pass"] = bool(raw.get("truth_gate_pass")) if row["model_p"] is not None else False
        row["odds_age_minutes"] = _age_minutes(str(raw["captured_at"]), as_of)

        public = ctx.get("public") or {}
        if public:
            row["tickets_pct"] = public.get("tickets_pct")
            row["money_pct"] = public.get("money_pct")
            row["handles_required"] = bool(public.get("required", False))
            row["handles_age_minutes"] = _age_minutes(public.get("captured_at"), as_of)
        else:
            row.setdefault("handles_required", False)

        injury = ctx.get("injury") or {}
        row["injury_required"] = bool(injury.get("required", True))
        row["injury_age_minutes"] = _age_minutes(injury.get("captured_at"), as_of)
        row["required_starter_status_unknown"] = bool(injury.get("required_starter_status_unknown", False))

        weather = ctx.get("weather") or {}
        row["outdoor_game"] = bool(weather.get("outdoor_game", ctx.get("outdoor_game", False)))
        if row["outdoor_game"]:
            row["weather_available"] = bool(weather.get("available", False))
            row["weather_age_minutes"] = _age_minutes(weather.get("captured_at"), as_of)
        else:
            row["weather_available"] = weather.get("available")
            row["weather_age_minutes"] = _age_minutes(weather.get("captured_at"), as_of) if weather.get("captured_at") else None

        if "benchmarks" not in row:
            row["benchmarks"] = deepcopy(ctx.get("benchmarks") or [])
        row["sources"] = _sources(raw.get("sources"), public.get("sources"), injury.get("sources"), weather.get("sources"), ctx.get("sources"))

        if "underlying_candidate" not in row:
            row["underlying_candidate"] = bool(ctx.get("underlying_candidate", False))
        if "promo" not in row and ctx.get("promo") is not None:
            row["promo"] = deepcopy(ctx.get("promo"))

        row["adapter_as_of"] = as_of.isoformat().replace("+00:00", "Z")
        output.append(row)

    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--as-of", help="override bundle as_of with timezone-aware ISO timestamp")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    as_of = _parse_ts(args.as_of) if args.as_of else None
    rows = build_rows(_load(args.capture), _load(args.registry), as_of=as_of)
    payload = {"schema_version": "CFB_SIGNAL_INPUT_V1", "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
