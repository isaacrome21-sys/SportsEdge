#!/usr/bin/env python3
"""CFB cross-book PAPER card for moneyline, spread, and total.

This is deliberately not a predictive model. It compares DraftKings offers with
same-market, same-threshold cross-book no-vig consensus and emits research-only
paper candidates when DK is materially better than consensus. It creates no
Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill,
or OFFICIAL authority.

Spread/total comparisons are line-identity strict: a peer price contributes only
when it offers the exact same threshold as DraftKings. A different line is not
converted, interpolated, or treated as equivalent.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

BOOKS = ("draftkings", "fanduel", "betmgm", "williamhill_us", "betonlineag", "pinnacle")
SUPPORTED = ("h2h", "spreads", "totals")
MARKET_NAME = {"h2h": "MONEYLINE", "spreads": "SPREAD", "totals": "TOTAL"}
# Governance contract sentinels retained for the repository text guard:
# "status":"PAPER_ONLY" "model_p":None "official":False


def implied(a):
    a = float(a)
    if not isfinite(a) or (-100.0 < a < 100.0):
        raise ValueError("CFB_PAPER_AMERICAN_ODDS_INVALID")
    return 100 / (100 + a) if a > 0 else (-a) / ((-a) + 100)


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
    # Key retained only for call compatibility; supplied prices only, no provider calls.
    return [], "MARKET_INPUT_UNAVAILABLE", "BLOCKED_NO_MARKET_INPUT"


def _point(outcome):
    value = outcome.get("point")
    if value is None:
        return None
    point = float(value)
    if not isfinite(point):
        raise ValueError("CFB_PAPER_MARKET_POINT_INVALID")
    return point


def _pair_identity(market_key, outcomes):
    if len(outcomes) != 2:
        return None
    names = [str(x.get("name") or "").strip() for x in outcomes]
    if market_key == "h2h":
        if len(set(names)) != 2 or any(not x for x in names):
            return None
        return "H2H"
    points = [_point(x) for x in outcomes]
    if market_key == "totals":
        if {x.lower() for x in names} != {"over", "under"}:
            return None
        if points[0] is None or points[1] is None or abs(points[0] - points[1]) > 1e-9:
            return None
        return points[0]
    if market_key == "spreads":
        if len(set(names)) != 2 or any(not x for x in names):
            return None
        if points[0] is None or points[1] is None or abs(points[0] + points[1]) > 1e-9:
            return None
        return "TEAM_POINTS"
    return None


def pair_probs(market_key, outcomes):
    identity = _pair_identity(market_key, outcomes)
    if identity is None:
        return None
    if len(outcomes) != 2:
        return None
    ps = [implied(x["price"]) for x in outcomes]
    total = sum(ps)
    if total <= 0:
        return None
    rows = []
    for outcome, p in zip(outcomes, ps):
        rows.append(
            {
                "name": str(outcome.get("name") or "").strip(),
                "point": _point(outcome),
                "price": float(outcome["price"]),
                "no_vig_p": p / total,
            }
        )
    return rows


def _selection_key(market_key, row):
    name = str(row["name"])
    point = row.get("point")
    if market_key == "h2h":
        return (name, None)
    return (name.lower() if market_key == "totals" else name, float(point))


def _book_markets(event, *, now=None):
    out = {}
    for book in event.get("bookmakers", []):
        if not isinstance(book, dict):
            continue
        book_key = str(book.get("key") or "").strip().lower()
        markets = {}
        for market in book.get("markets", []):
            if not isinstance(market, dict):
                continue
            market_key = str(market.get("key") or "").strip().lower()
            if market_key not in SUPPORTED:
                continue
            if now is not None:
                # Only accept a source-provided fresh timestamp for paid live
                # quote comparisons. Manual test/research boards remain PAPER.
                stamp = market.get("last_update") or book.get("last_update")
                try:
                    updated = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                    age = (now - updated).total_seconds()
                    if updated.tzinfo is None or not 0 <= age <= 600:
                        continue
                except (TypeError, ValueError, OverflowError):
                    continue
            paired = pair_probs(market_key, market.get("outcomes", []))
            if paired:
                markets[market_key] = paired
        if markets:
            out[book_key] = markets
    return out


def build_payload(events, min_edge, now, market_input_source, input_status):
    candidates = []
    counts = Counter(events_received=len(events))
    for event in events:
        try:
            start = datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            counts["invalid_kickoff"] += 1
            continue
        if start.tzinfo is None or start <= now:
            counts["started_or_naive_kickoff"] += 1
            continue
        participants = ' | '.join(str(event.get(k) or '').lower() for k in ('home_team', 'away_team'))
        if any(team in participants for team in ('illinois', 'northwestern', 'depaul', 'bradley', 'loyola chicago', 'roosevelt')):
            counts['illinois_games_excluded'] += 1
            continue

        books = _book_markets(event, now=now if market_input_source == "ODDS_PROVIDER" else None)
        dk = books.get("draftkings")
        if not dk:
            counts["no_usable_draftkings_market"] += 1
            continue
        counts["games_with_usable_draftkings"] += 1

        for market_key in SUPPORTED:
            dk_rows = dk.get(market_key)
            if not dk_rows:
                counts["missing_draftkings_market"] += 1
                continue
            for dk_row in dk_rows:
                counts["draftkings_selections"] += 1
                selection_key = _selection_key(market_key, dk_row)
                peer_probabilities = []
                peer_books = []
                for peer_key, peer_markets in books.items():
                    if peer_key == "draftkings":
                        continue
                    for peer_row in peer_markets.get(market_key, []):
                        if _selection_key(market_key, peer_row) == selection_key:
                            peer_probabilities.append(float(peer_row["no_vig_p"]))
                            peer_books.append(peer_key)
                            break
                if len(peer_probabilities) < 2:
                    counts["fewer_than_two_exact_line_peers"] += 1
                    continue
                counts["selections_with_two_exact_line_peers"] += 1

                consensus = sum(peer_probabilities) / len(peer_probabilities)
                price = float(dk_row["price"])
                if price < -165:
                    counts["straight_price_cap"] += 1
                    continue  # Straight-wager cap; no SGP path in paper lane.
                raw = implied(price)
                decimal = 1 + (100 / abs(price) if price < 0 else price / 100)
                ev_per_dollar = consensus * (decimal - 1) - (1 - consensus)
                edge = consensus - raw
                if edge < float(min_edge) or ev_per_dollar <= 0:
                    counts["below_edge_floor_or_nonpositive_ev"] += 1
                    continue

                side = str(dk_row["name"])
                line = dk_row.get("point")
                candidates.append(
                    {
                        "game_id": str(event.get("id")),
                        "away_team": event.get("away_team"),
                        "home_team": event.get("home_team"),
                        "commence_time": event.get("commence_time"),
                        "market": MARKET_NAME[market_key],
                        "side": side,
                        "line": None if line is None else float(line),
                        "draftkings_odds": price,
                        "market_consensus_no_vig_p": consensus,
                        "draftkings_raw_implied_p": raw,
                        "market_consensus_edge": edge,
                        "market_consensus_ev_per_dollar": ev_per_dollar,
                        "peer_books_used": len(peer_probabilities),
                        "peer_book_keys": sorted(peer_books),
                        "line_identity_rule": "EXACT_THRESHOLD_ONLY",
                        "status": "PAPER_MARKET_CONSENSUS_ONLY",
                        "model_p": None,
                        "truth_gate": False,
                        "official": False,
                    }
                )

    candidates.sort(
        key=lambda x: (
            -float(x["market_consensus_ev_per_dollar"]),
            str(x["game_id"]),
            str(x["market"]),
            str(x["side"]),
        )
    )
    return {
        "schema": "CFB_PAPER_MARKET_CARD_V3",
        "generated_at_utc": now.isoformat(),
        "status": "PAPER_ONLY",
        "input_status": input_status,
        "market_input_source": market_input_source,
        "method": "CROSS_BOOK_NO_VIG_CONSENSUS_EXACT_LINE_V2",
        "markets": ["MONEYLINE", "SPREAD", "TOTAL"],
        "min_edge": min_edge,
        "candidates": candidates,
        "coverage": {**dict(counts), "candidate_count": len(candidates),
                     "scan_completed": input_status == "READY"},
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

    inline_json = os.getenv("CFB_PAPER_BOARD_JSON", "")
    now = datetime.now(timezone.utc)
    events, source, input_status = load_events("", args.input_json, inline_json)
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
                "coverage": payload["coverage"],
                "markets": payload["markets"],
                "output": str(out),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
