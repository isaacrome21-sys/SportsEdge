#!/usr/bin/env python3
"""CFB market-consensus PAPER card.

This is deliberately not a predictive model. It compares DraftKings prices with a
cross-book no-vig consensus and emits research-only paper candidates when DK is
materially better than consensus. It creates no Model_P, Truth Gate, promotion,
eligibility, staking, evidence-clock, backfill, or OFFICIAL authority.

Market input can come from the configured odds provider or from a manually supplied
JSON board using the same event/bookmaker shape. If neither is available, the runner
still emits a durable zero-authority PAPER artifact with an explicit input blocker
instead of failing before the governance assertions can run.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
BOOKS = ("draftkings", "fanduel", "betmgm", "caesars")


def implied(a):
    a = float(a)
    return 100 / (100 + a) if a > 0 else (-a) / ((-a) + 100)


def fetch(key):
    q = urlencode(
        {
            "apiKey": key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "bookmakers": ",".join(BOOKS),
        }
    )
    with urlopen(Request(ODDS_URL + "?" + q), timeout=30) as r:
        return json.loads(r.read().decode())


def _decode_events(raw, source):
    try:
        events = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"CFB_PAPER_INVALID_{source}_JSON: {exc}") from exc
    if not isinstance(events, list):
        raise SystemExit(f"CFB_PAPER_INVALID_{source}_JSON: top level must be an array")
    return events


def load_events(key, input_json=None, inline_json=None):
    """Return (events, source, input_status) without inventing missing market data."""
    if input_json:
        path = Path(input_json)
        if not path.is_file():
            raise SystemExit(f"CFB_PAPER_INPUT_FILE_NOT_FOUND: {path}")
        return _decode_events(path.read_text(), "MANUAL_FILE"), "MANUAL_JSON_FILE", "READY"
    inline = (inline_json or "").strip()
    if inline:
        return _decode_events(inline, "MANUAL_INLINE"), "MANUAL_JSON_INLINE", "READY"
    if key:
        events = fetch(key)
        if not isinstance(events, list):
            raise SystemExit("CFB_PAPER_PROVIDER_RESPONSE_NOT_ARRAY")
        return events, "ODDS_PROVIDER", "READY"
    return [], "MARKET_INPUT_UNAVAILABLE", "BLOCKED_NO_MARKET_INPUT"


def pair_probs(outcomes):
    if len(outcomes) != 2:
        return None
    ps = [implied(x["price"]) for x in outcomes]
    s = sum(ps)
    if s <= 0:
        return None
    return {str(o["name"]): p / s for o, p in zip(outcomes, ps)}


def build_payload(events, min_edge, now, market_input_source, input_status):
    candidates = []
    for event in events:
        try:
            start = datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if start <= now:
            continue
        grouped = {}
        for bk in event.get("bookmakers", []):
            for market in bk.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                probs = pair_probs(market.get("outcomes", []))
                if probs:
                    grouped[bk.get("key")] = {
                        "outcomes": market["outcomes"],
                        "probs": probs,
                    }
        dk = grouped.get("draftkings")
        peers = [value for key, value in grouped.items() if key != "draftkings"]
        if not dk or len(peers) < 2:
            continue
        for outcome in dk["outcomes"]:
            name = str(outcome["name"])
            vals = [peer["probs"].get(name) for peer in peers if name in peer["probs"]]
            if len(vals) < 2:
                continue
            consensus = sum(vals) / len(vals)
            price = float(outcome["price"])
            raw = implied(price)
            decimal = 1 + (100 / abs(price) if price < 0 else price / 100)
            ev_per_dollar = consensus * (decimal - 1) - (1 - consensus)
            edge = consensus - raw
            if edge >= min_edge and ev_per_dollar > 0:
                candidates.append(
                    {
                        "game_id": str(event.get("id")),
                        "away_team": event.get("away_team"),
                        "home_team": event.get("home_team"),
                        "commence_time": event.get("commence_time"),
                        "market": "MONEYLINE",
                        "side": name,
                        "draftkings_odds": price,
                        "market_consensus_no_vig_p": consensus,
                        "draftkings_raw_implied_p": raw,
                        "market_consensus_edge": edge,
                        "market_consensus_ev_per_dollar": ev_per_dollar,
                        "peer_books_used": len(vals),
                        "status": "PAPER_MARKET_CONSENSUS_ONLY",
                        "model_p": None,
                        "truth_gate": False,
                        "official": False,
                    }
                )
    candidates.sort(key=lambda x: x["market_consensus_ev_per_dollar"], reverse=True)
    return {
        "schema": "CFB_PAPER_MARKET_CARD_V2",
        "generated_at_utc": now.isoformat(),
        "status": "PAPER_ONLY",
        "input_status": input_status,
        "market_input_source": market_input_source,
        "method": "CROSS_BOOK_NO_VIG_CONSENSUS_V1",
        "min_edge": min_edge,
        "candidates": candidates,
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "eligibility": False,
            "staking": False,
            "evidence_clock": False,
            "backfill": False,
            "official": False,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/cfb/cfb_paper_market_card.json")
    ap.add_argument("--min-edge", type=float, default=0.02)
    ap.add_argument(
        "--input-json",
        help="Optional manual market-board JSON file using the event/bookmaker shape",
    )
    args = ap.parse_args()

    key = (os.getenv("ODDS_API_KEY") or os.getenv("SPORTSEDGE_ODDS_API_KEY") or "").strip()
    inline_json = os.getenv("CFB_PAPER_BOARD_JSON", "")
    now = datetime.now(timezone.utc)
    events, source, input_status = load_events(key, args.input_json, inline_json)
    payload = build_payload(events, args.min_edge, now, source, input_status)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "input_status": input_status,
                "market_input_source": source,
                "candidate_count": len(payload["candidates"]),
                "output": str(out),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
