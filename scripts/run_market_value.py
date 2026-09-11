#!/usr/bin/env python3
"""Evaluate one manual/captured market through TOP_DOWN_MARKET_VALUE_V1."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Mapping

from sportsedge.market_value import (
    PriceQuote,
    ReferencePair,
    evaluate_market,
    load_policy,
    record_close,
)


def _quote(raw: Mapping[str, object]) -> PriceQuote:
    return PriceQuote(
        book=str(raw["book"]),
        market_key=str(raw["market_key"]),
        selection=str(raw["selection"]),
        american_odds=int(raw["american_odds"]),
        captured_at=str(raw["captured_at"]),
        source=str(raw["source"]),
    )


def _reference_pair(raw: Mapping[str, object]) -> ReferencePair:
    prices = raw.get("prices")
    if not isinstance(prices, Mapping) or len(prices) != 2:
        raise ValueError("each reference requires exactly two prices")
    base = {
        "book": raw["book"],
        "market_key": raw["market_key"],
        "captured_at": raw["captured_at"],
        "source": raw["source"],
    }
    quotes = [
        _quote({**base, "selection": selection, "american_odds": odds})
        for selection, odds in prices.items()
    ]
    return ReferencePair(quotes[0], quotes[1])


def run(payload: Mapping[str, object]) -> dict[str, object]:
    policy = load_policy()
    raw_references = payload.get("references")
    raw_executions = payload.get("executions")
    if not isinstance(raw_references, list) or not raw_references:
        raise ValueError("references must be a non-empty list")
    if not isinstance(raw_executions, list) or not raw_executions:
        raise ValueError("executions must be a non-empty list")

    references = [_reference_pair(item) for item in raw_references]
    executions = [_quote(item) for item in raw_executions]
    reference_mode = str(payload.get("reference_mode", "PINNACLE_ONLY_V1"))
    independent = payload.get("independent_model_selection")

    decision = evaluate_market(
        references,
        executions,
        reference_mode=reference_mode,
        policy=policy,
        independent_model_selection=(
            None if independent is None else str(independent)
        ),
    )
    result: dict[str, object] = {
        "decision": asdict(decision),
        "closing_snapshot": None,
    }

    raw_close = payload.get("closing_references")
    if raw_close is not None:
        if not isinstance(raw_close, list) or not raw_close:
            raise ValueError("closing_references must be a non-empty list when supplied")
        if decision.decision != "PAPER_BET":
            raise ValueError("closing_references supplied for a non-PAPER_BET decision")
        close = record_close(
            decision,
            [_reference_pair(item) for item in raw_close],
            policy=policy,
        )
        result["closing_snapshot"] = asdict(close)

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    args = parser.parse_args()

    with args.input_json.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("input root must be an object")

    print(json.dumps(run(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
