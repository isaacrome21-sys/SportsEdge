#!/usr/bin/env python3
"""Normalize direct Pinnacle NFL game markets into SportsEdge HARD_MARKET rows.

V1 is deliberately narrow and fail-closed. It accepts only the primary, open,
period-0 moneyline, spread, and total for one structurally verified NFL matchup.
Alternate lines, team totals, derivative periods, props, specials, and live markets
are excluded. Two-sided no-vig probabilities are calculated only for exact paired
contracts.

This is Layer B market context. It has zero Model_P, Truth Gate, promotion,
staking, OFFICIAL, registry, evidence-clock, or wager-placement authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

SOURCE_FAMILY_ID = "PINNACLE_DIRECT_ARCADIA_V1"
CORE_TYPES = ("moneyline", "spread", "total")
MARKET_NAMES = {"moneyline": "h2h", "spread": "spreads", "total": "totals"}
EXPECTED_DESIGNATIONS = {
    "moneyline": ("home", "away"),
    "spread": ("home", "away"),
    "total": ("over", "under"),
}


class PinnacleNormalizationError(RuntimeError):
    pass


def _authority() -> dict[str, bool]:
    return {
        "model_p_input": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "production_registry_authority": False,
        "evidence_clock_authority": False,
        "wager_placement_authority": False,
    }


def american_to_implied(price: Any) -> float:
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise PinnacleNormalizationError("PINNACLE_PRICE_NOT_NUMERIC")
    value = float(price)
    if not math.isfinite(value) or value == 0:
        raise PinnacleNormalizationError("PINNACLE_PRICE_INVALID")
    if value < 0:
        return (-value) / ((-value) + 100.0)
    return 100.0 / (value + 100.0)


def probability_to_american(probability: float) -> float:
    p = float(probability)
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise PinnacleNormalizationError("PINNACLE_PROBABILITY_INVALID")
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PinnacleNormalizationError(f"PINNACLE_{label}_NOT_NUMERIC")
    result = float(value)
    if not math.isfinite(result):
        raise PinnacleNormalizationError(f"PINNACLE_{label}_INVALID")
    return result


def _canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _market_contract(market_type: str, prices: Sequence[Mapping[str, Any]]) -> tuple[float | None, dict[str, float | None]]:
    if market_type == "moneyline":
        return None, {"home": None, "away": None}
    if market_type == "spread":
        home = _number(prices[0].get("points"), label="SPREAD_POINT")
        away = _number(prices[1].get("points"), label="SPREAD_POINT")
        if not math.isclose(home, -away, abs_tol=1e-9):
            raise PinnacleNormalizationError("PINNACLE_SPREAD_CONTRACT_MISMATCH")
        return home, {"home": home, "away": away}
    if market_type == "total":
        over = _number(prices[0].get("points"), label="TOTAL_POINT")
        under = _number(prices[1].get("points"), label="TOTAL_POINT")
        if not math.isclose(over, under, abs_tol=1e-9):
            raise PinnacleNormalizationError("PINNACLE_TOTAL_CONTRACT_MISMATCH")
        return over, {"over": over, "under": under}
    raise PinnacleNormalizationError("PINNACLE_MARKET_TYPE_UNSUPPORTED")


def _normalize_one_market(
    market: Mapping[str, Any],
    *,
    matchup: Mapping[str, Any],
    captured_at: str,
    raw_sha256: str,
) -> list[dict[str, Any]]:
    market_type = str(market.get("type") or "").lower()
    expected = EXPECTED_DESIGNATIONS[market_type]
    prices_value = market.get("prices")
    if not isinstance(prices_value, list) or len(prices_value) != 2:
        raise PinnacleNormalizationError(f"PINNACLE_{market_type.upper()}_PAIR_MISSING")
    if not all(isinstance(item, Mapping) for item in prices_value):
        raise PinnacleNormalizationError("PINNACLE_PRICE_ROW_NOT_OBJECT")

    by_designation = {str(item.get("designation") or "").lower(): item for item in prices_value}
    if set(by_designation) != set(expected):
        raise PinnacleNormalizationError(f"PINNACLE_{market_type.upper()}_DESIGNATION_MISMATCH")
    prices = [by_designation[name] for name in expected]
    contract_line, side_points = _market_contract(market_type, prices)

    implied = [american_to_implied(item.get("price")) for item in prices]
    overround = sum(implied)
    if not math.isfinite(overround) or overround <= 0:
        raise PinnacleNormalizationError("PINNACLE_OVERROUND_INVALID")
    fair = [p / overround for p in implied]

    home_team = str(matchup.get("home_team") or "").strip()
    away_team = str(matchup.get("away_team") or "").strip()
    matchup_id = matchup.get("matchup_id")
    if not home_team or not away_team or matchup_id is None:
        raise PinnacleNormalizationError("PINNACLE_MATCHUP_IDENTITY_MISSING")

    provider_key = str(market.get("key") or "").strip()
    if not provider_key:
        raise PinnacleNormalizationError("PINNACLE_MARKET_KEY_MISSING")
    version = market.get("version")
    if version is None:
        raise PinnacleNormalizationError("PINNACLE_MARKET_VERSION_MISSING")

    rows: list[dict[str, Any]] = []
    for idx, designation in enumerate(expected):
        item = prices[idx]
        outcome_name = (
            home_team if designation == "home" else
            away_team if designation == "away" else
            designation
        )
        identity = {
            "book": "pinnacle",
            "matchup_id": int(matchup_id),
            "market": MARKET_NAMES[market_type],
            "designation": designation,
            "point": side_points[designation],
            "provider_key": provider_key,
            "provider_version": version,
            "captured_at": captured_at,
        }
        rows.append(
            {
                "quote_id": _canonical_hash(identity),
                "source_family_id": SOURCE_FAMILY_ID,
                "book": "pinnacle",
                "sport": "NFL",
                "league": "NFL",
                "event_id": f"pinnacle:{int(matchup_id)}",
                "matchup_id": int(matchup_id),
                "home_team": home_team,
                "away_team": away_team,
                "start_time": matchup.get("start_time"),
                "market": MARKET_NAMES[market_type],
                "market_type_provider": market_type,
                "designation": designation,
                "outcome_name": outcome_name,
                "point": side_points[designation],
                "contract_line": contract_line,
                "american_price": item.get("price"),
                "implied_probability": implied[idx],
                "no_vig_probability": fair[idx],
                "no_vig_fair_american": probability_to_american(fair[idx]),
                "market_overround": overround,
                "provider_key": provider_key,
                "provider_version": version,
                "provider_cutoff_at": market.get("cutoffAt"),
                "captured_at": captured_at,
                "timestamp_source": "CAPTURED_AT",
                "provider_cutoff_is_quote_timestamp": False,
                "period": 0,
                "is_alternate": False,
                "status": "open",
                "limits": market.get("limits") if isinstance(market.get("limits"), list) else [],
                "raw_sha256": raw_sha256,
                "authority": _authority(),
            }
        )
    return rows


def normalize(
    *,
    matchup: Mapping[str, Any],
    markets: Any,
    captured_at: str,
    raw_sha256: str,
) -> dict[str, Any]:
    if not isinstance(markets, list):
        raise PinnacleNormalizationError("PINNACLE_MARKETS_NOT_LIST")
    if not captured_at or not raw_sha256:
        raise PinnacleNormalizationError("PINNACLE_PROVENANCE_MISSING")

    core: dict[str, list[Mapping[str, Any]]] = {name: [] for name in CORE_TYPES}
    skipped = {"alternate": 0, "derivative_period": 0, "unsupported_type": 0, "not_open": 0, "wrong_matchup": 0}
    target_matchup_id = matchup.get("matchup_id")

    for row in markets:
        if not isinstance(row, Mapping):
            raise PinnacleNormalizationError("PINNACLE_MARKET_ROW_NOT_OBJECT")
        if row.get("matchupId") != target_matchup_id:
            skipped["wrong_matchup"] += 1
            continue
        if str(row.get("status") or "").lower() != "open":
            skipped["not_open"] += 1
            continue
        if row.get("period") != 0:
            skipped["derivative_period"] += 1
            continue
        if row.get("isAlternate") is True:
            skipped["alternate"] += 1
            continue
        market_type = str(row.get("type") or "").lower()
        if market_type not in core:
            skipped["unsupported_type"] += 1
            continue
        core[market_type].append(row)

    missing = [name for name, rows in core.items() if not rows]
    duplicates = [name for name, rows in core.items() if len(rows) > 1]
    if missing:
        raise PinnacleNormalizationError("PINNACLE_CORE_MARKET_MISSING:" + ",".join(missing))
    if duplicates:
        raise PinnacleNormalizationError("PINNACLE_CORE_MARKET_DUPLICATE:" + ",".join(duplicates))

    quotes: list[dict[str, Any]] = []
    for market_type in CORE_TYPES:
        quotes.extend(
            _normalize_one_market(
                core[market_type][0],
                matchup=matchup,
                captured_at=captured_at,
                raw_sha256=raw_sha256,
            )
        )

    return {
        "contract": "PINNACLE_NFL_PRIMARY_MARKET_NORMALIZER_V1",
        "state": "NORMALIZED",
        "source_family_id": SOURCE_FAMILY_ID,
        "scope": {
            "sport": "NFL",
            "period": 0,
            "status": "open",
            "primary_only": True,
            "markets": ["h2h", "spreads", "totals"],
        },
        "matchup": dict(matchup),
        "captured_at": captured_at,
        "raw_sha256": raw_sha256,
        "quote_count": len(quotes),
        "quotes": quotes,
        "skipped": skipped,
        "authority": _authority(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", required=True, help="Probe status.json")
    parser.add_argument("--markets", required=True, help="Raw straight-markets JSON")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    markets_path = Path(args.markets)
    raw = markets_path.read_bytes()
    markets = json.loads(raw.decode("utf-8"))
    captured = status.get("captures", {}).get("straight_markets", {})
    expected_sha = str(captured.get("raw_sha256") or "")
    actual_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha != actual_sha:
        raise PinnacleNormalizationError("PINNACLE_RAW_SHA_MISMATCH")

    result = normalize(
        matchup=status.get("selected_matchup") or {},
        markets=markets,
        captured_at=str(status.get("captured_at") or ""),
        raw_sha256=actual_sha,
    )
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "quote_count": result["quote_count"], "skipped": result["skipped"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
