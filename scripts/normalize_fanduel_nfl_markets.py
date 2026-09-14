#!/usr/bin/env python3
"""Normalize direct FanDuel NFL full-game markets into SportsEdge HARD_MARKET rows.

V1 is deliberately narrow and fail-closed. It accepts one pregame FanDuel event
whose name is explicitly `AWAY @ HOME`, plus exactly one open full-game Moneyline,
Spread, and Total Points market. Other derivatives, winning-margin markets, props,
SGP legs, alternate lines, and live markets are excluded.

FanDuel's event-page payload does not expose a trustworthy quote-update timestamp,
so `captured_at` is the only quote-time provenance used here. This is Layer B
market context with zero Model_P, Truth Gate, promotion, staking, OFFICIAL,
registry, evidence-clock, or wager-placement authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

SOURCE_FAMILY_ID = "FANDUEL_DIRECT_SPORTSBOOK_V1"
CORE_ORDER = ("moneyline", "spread", "total")
MARKET_NAMES = {"moneyline": "h2h", "spread": "spreads", "total": "totals"}
PROVIDER_MARKETS = {
    "moneyline": ("Moneyline", "MONEY_LINE", "ODDS"),
    "spread": ("Spread", "MATCH_HANDICAP_(2-WAY)", "MOVING_HANDICAP"),
    "total": ("Total Points", "TOTAL_POINTS_(OVER/UNDER)", "MOVING_HANDICAP"),
}


class FanDuelNormalizationError(RuntimeError):
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


def _canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FanDuelNormalizationError(f"FANDUEL_{label}_NOT_NUMERIC")
    result = float(value)
    if not math.isfinite(result):
        raise FanDuelNormalizationError(f"FANDUEL_{label}_INVALID")
    return result


def american_to_implied(price: Any) -> float:
    value = _number(price, label="PRICE")
    if value == 0:
        raise FanDuelNormalizationError("FANDUEL_PRICE_INVALID")
    if value < 0:
        return (-value) / ((-value) + 100.0)
    return 100.0 / (value + 100.0)


def probability_to_american(probability: float) -> float:
    p = float(probability)
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise FanDuelNormalizationError("FANDUEL_PROBABILITY_INVALID")
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def _american_price(runner: Mapping[str, Any]) -> int:
    odds = runner.get("winRunnerOdds")
    if not isinstance(odds, Mapping):
        raise FanDuelNormalizationError("FANDUEL_RUNNER_ODDS_MISSING")
    display = odds.get("americanDisplayOdds")
    if not isinstance(display, Mapping):
        raise FanDuelNormalizationError("FANDUEL_AMERICAN_ODDS_MISSING")
    value = display.get("americanOddsInt")
    if value is None:
        value = display.get("americanOdds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FanDuelNormalizationError("FANDUEL_AMERICAN_ODDS_INVALID")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric == 0 or not numeric.is_integer():
        raise FanDuelNormalizationError("FANDUEL_AMERICAN_ODDS_INVALID")
    return int(numeric)


def _decimal_price(runner: Mapping[str, Any]) -> float | None:
    odds = runner.get("winRunnerOdds")
    if not isinstance(odds, Mapping):
        return None
    true_odds = odds.get("trueOdds")
    if not isinstance(true_odds, Mapping):
        return None
    decimal = true_odds.get("decimalOdds")
    if not isinstance(decimal, Mapping):
        return None
    value = decimal.get("decimalOdds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result > 1.0 else None


def _single_event(event_page: Mapping[str, Any], *, captured_at: str) -> dict[str, Any]:
    attachments = event_page.get("attachments")
    if not isinstance(attachments, Mapping):
        raise FanDuelNormalizationError("FANDUEL_ATTACHMENTS_MISSING")
    events = attachments.get("events")
    if not isinstance(events, Mapping) or len(events) != 1:
        raise FanDuelNormalizationError("FANDUEL_EVENT_IDENTITY_AMBIGUOUS")
    event = next(iter(events.values()))
    if not isinstance(event, Mapping):
        raise FanDuelNormalizationError("FANDUEL_EVENT_NOT_OBJECT")
    event_id = event.get("eventId")
    if event_id is None:
        raise FanDuelNormalizationError("FANDUEL_EVENT_ID_MISSING")
    if event.get("inPlay") is True:
        raise FanDuelNormalizationError("FANDUEL_EVENT_IN_PLAY")
    name = str(event.get("name") or "").strip()
    if name.count(" @ ") != 1:
        raise FanDuelNormalizationError("FANDUEL_EVENT_NAME_NOT_AWAY_AT_HOME")
    away_team, home_team = (part.strip() for part in name.split(" @ ", 1))
    if not away_team or not home_team or away_team == home_team:
        raise FanDuelNormalizationError("FANDUEL_EVENT_TEAMS_INVALID")
    start_time = str(event.get("openDate") or "").strip()
    if not start_time or not captured_at:
        raise FanDuelNormalizationError("FANDUEL_EVENT_TIME_MISSING")
    return {
        "event_id": int(event_id),
        "away_team": away_team,
        "home_team": home_team,
        "start_time": start_time,
        "name": name,
    }


def _markets(event_page: Mapping[str, Any], *, event_id: int) -> dict[str, Mapping[str, Any]]:
    attachments = event_page.get("attachments")
    assert isinstance(attachments, Mapping)
    value = attachments.get("markets")
    if not isinstance(value, Mapping):
        raise FanDuelNormalizationError("FANDUEL_MARKETS_NOT_OBJECT")

    core: dict[str, list[Mapping[str, Any]]] = {name: [] for name in CORE_ORDER}
    for market in value.values():
        if not isinstance(market, Mapping):
            raise FanDuelNormalizationError("FANDUEL_MARKET_ROW_NOT_OBJECT")
        if market.get("eventId") != event_id:
            continue
        if str(market.get("marketStatus") or "").upper() != "OPEN":
            continue
        if market.get("inPlay") is True:
            continue
        for key, (name, market_type, betting_type) in PROVIDER_MARKETS.items():
            if (
                str(market.get("marketName") or "") == name
                and str(market.get("marketType") or "") == market_type
                and str(market.get("bettingType") or "") == betting_type
            ):
                core[key].append(market)
                break

    missing = [name for name, rows in core.items() if not rows]
    duplicates = [name for name, rows in core.items() if len(rows) > 1]
    if missing:
        raise FanDuelNormalizationError("FANDUEL_CORE_MARKET_MISSING:" + ",".join(missing))
    if duplicates:
        raise FanDuelNormalizationError("FANDUEL_CORE_MARKET_DUPLICATE:" + ",".join(duplicates))
    return {name: core[name][0] for name in CORE_ORDER}


def _runners(market: Mapping[str, Any], *, market_key: str, event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = market.get("runners")
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(r, Mapping) for r in value):
        raise FanDuelNormalizationError(f"FANDUEL_{market_key.upper()}_PAIR_MISSING")
    by_name = {str(r.get("runnerName") or "").strip(): r for r in value}
    if len(by_name) != 2:
        raise FanDuelNormalizationError(f"FANDUEL_{market_key.upper()}_RUNNER_DUPLICATE")

    if market_key in {"moneyline", "spread"}:
        expected = {event["away_team"], event["home_team"]}
        if set(by_name) != expected:
            raise FanDuelNormalizationError(f"FANDUEL_{market_key.upper()}_TEAM_MISMATCH")
        return [by_name[event["home_team"]], by_name[event["away_team"]]]
    if set(by_name) != {"Over", "Under"}:
        raise FanDuelNormalizationError("FANDUEL_TOTAL_DESIGNATION_MISMATCH")
    return [by_name["Over"], by_name["Under"]]


def _points(market_key: str, runners: list[Mapping[str, Any]]) -> tuple[float | None, list[float | None]]:
    if market_key == "moneyline":
        if any(abs(_number(r.get("handicap", 0), label="MONEYLINE_HANDICAP")) > 1e-9 for r in runners):
            raise FanDuelNormalizationError("FANDUEL_MONEYLINE_HANDICAP_NONZERO")
        return None, [None, None]
    points = [_number(r.get("handicap"), label=f"{market_key.upper()}_POINT") for r in runners]
    if market_key == "spread":
        if not math.isclose(points[0], -points[1], abs_tol=1e-9):
            raise FanDuelNormalizationError("FANDUEL_SPREAD_CONTRACT_MISMATCH")
        return points[0], points
    if not math.isclose(points[0], points[1], abs_tol=1e-9):
        raise FanDuelNormalizationError("FANDUEL_TOTAL_CONTRACT_MISMATCH")
    return points[0], points


def _normalize_market(
    market_key: str,
    market: Mapping[str, Any],
    *,
    event: Mapping[str, Any],
    captured_at: str,
    raw_sha256: str,
) -> list[dict[str, Any]]:
    runners = _runners(market, market_key=market_key, event=event)
    contract_line, points = _points(market_key, runners)
    american = [_american_price(r) for r in runners]
    implied = [american_to_implied(p) for p in american]
    overround = sum(implied)
    if not math.isfinite(overround) or overround <= 0:
        raise FanDuelNormalizationError("FANDUEL_OVERROUND_INVALID")
    fair = [p / overround for p in implied]

    market_id = str(market.get("marketId") or "").strip()
    if not market_id:
        raise FanDuelNormalizationError("FANDUEL_MARKET_ID_MISSING")

    if market_key in {"moneyline", "spread"}:
        designations = ("home", "away")
    else:
        designations = ("over", "under")

    rows: list[dict[str, Any]] = []
    for idx, designation in enumerate(designations):
        runner = runners[idx]
        outcome_name = str(runner.get("runnerName") or "").strip()
        selection_id = runner.get("selectionId")
        if selection_id is None:
            raise FanDuelNormalizationError("FANDUEL_SELECTION_ID_MISSING")
        identity = {
            "book": "fanduel",
            "event_id": int(event["event_id"]),
            "market": MARKET_NAMES[market_key],
            "designation": designation,
            "point": points[idx],
            "market_id": market_id,
            "selection_id": selection_id,
            "captured_at": captured_at,
        }
        rows.append(
            {
                "quote_id": _canonical_hash(identity),
                "source_family_id": SOURCE_FAMILY_ID,
                "book": "fanduel",
                "sport": "NFL",
                "league": "NFL",
                "event_id": f"fanduel:{int(event['event_id'])}",
                "provider_event_id": int(event["event_id"]),
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "start_time": event["start_time"],
                "market": MARKET_NAMES[market_key],
                "market_name_provider": market.get("marketName"),
                "market_type_provider": market.get("marketType"),
                "betting_type_provider": market.get("bettingType"),
                "designation": designation,
                "outcome_name": outcome_name,
                "point": points[idx],
                "contract_line": contract_line,
                "american_price": american[idx],
                "decimal_price_provider": _decimal_price(runner),
                "implied_probability": implied[idx],
                "no_vig_probability": fair[idx],
                "no_vig_fair_american": probability_to_american(fair[idx]),
                "market_overround": overround,
                "provider_market_id": market_id,
                "provider_selection_id": selection_id,
                "captured_at": captured_at,
                "book_last_update": None,
                "timestamp_source": "CAPTURED_AT",
                "provider_quote_timestamp_available": False,
                "period": 0,
                "is_alternate": False,
                "status": "open",
                "raw_sha256": raw_sha256,
                "authority": _authority(),
            }
        )
    return rows


def normalize(*, event_page: Any, captured_at: str, raw_sha256: str) -> dict[str, Any]:
    if not isinstance(event_page, Mapping):
        raise FanDuelNormalizationError("FANDUEL_EVENT_PAGE_NOT_OBJECT")
    if not captured_at or not raw_sha256:
        raise FanDuelNormalizationError("FANDUEL_PROVENANCE_MISSING")

    event = _single_event(event_page, captured_at=captured_at)
    markets = _markets(event_page, event_id=int(event["event_id"]))
    quotes: list[dict[str, Any]] = []
    for market_key in CORE_ORDER:
        quotes.extend(
            _normalize_market(
                market_key,
                markets[market_key],
                event=event,
                captured_at=captured_at,
                raw_sha256=raw_sha256,
            )
        )

    return {
        "contract": "FANDUEL_NFL_PRIMARY_MARKET_NORMALIZER_V1",
        "state": "NORMALIZED",
        "source_family_id": SOURCE_FAMILY_ID,
        "scope": {
            "sport": "NFL",
            "period": 0,
            "status": "open",
            "primary_only": True,
            "markets": ["h2h", "spreads", "totals"],
        },
        "event": event,
        "captured_at": captured_at,
        "raw_sha256": raw_sha256,
        "quote_count": len(quotes),
        "quotes": quotes,
        "authority": _authority(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", required=True, help="FanDuel probe status.json")
    parser.add_argument("--event-page", required=True, help="Raw event-page JSON")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    event_path = Path(args.event_page)
    raw = event_path.read_bytes()
    event_page = json.loads(raw.decode("utf-8"))
    captured = status.get("captures", {}).get("event_page", {})
    expected_sha = str(captured.get("raw_sha256") or "")
    actual_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha != actual_sha:
        raise FanDuelNormalizationError("FANDUEL_RAW_SHA_MISMATCH")

    result = normalize(
        event_page=event_page,
        captured_at=str(status.get("captured_at") or ""),
        raw_sha256=actual_sha,
    )
    selected = status.get("selected_event") or {}
    if selected.get("event_id") != result["event"]["event_id"]:
        raise FanDuelNormalizationError("FANDUEL_SELECTED_EVENT_ID_MISMATCH")

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "quote_count": result["quote_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
