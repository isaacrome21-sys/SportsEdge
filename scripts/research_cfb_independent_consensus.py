#!/usr/bin/env python3
"""Independent multi-book CFB side/total price comparison, research ONLY.

Reference quotes are supplied externally with capture timestamps; no scraping,
sportsbook receipt verification, learned book weights, or betting authority.
Never use DraftKings (the target) to derive its own fair price. Exact contract,
pregame and contemporaneous timestamps are mandatory. No postgame backfill.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

SCHEMA = "CFB_INDEPENDENT_CONSENSUS_RESEARCH_V1"
MAX_AGE_SECONDS = 900
MIN_REFERENCE_BOOKS = 2
MIN_ADVANTAGE_PP = 0.02
MAX_REFERENCE_DISAGREEMENT = 0.12
TARGET_BOOKS = {"draftkings", "dk", "draft kings"}
EXCLUDED_ILLINOIS_TEAMS = (
    "illinois", "northwestern", "northern illinois", "western illinois",
    "eastern illinois", "southern illinois", "illinois state",
)
OPPOSITES = {"MONEYLINE": {"HOME", "AWAY"},
             "SPREAD": {"HOME", "AWAY"},
             "TOTAL": {"OVER", "UNDER"}}


def _time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("offset required")
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("CONSENSUS_TIME_INVALID") from exc


def _num(value):
    if isinstance(value, bool):
        raise ValueError("CONSENSUS_NUMERIC_INVALID")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CONSENSUS_NUMERIC_INVALID") from exc
    if not isfinite(x):
        raise ValueError("CONSENSUS_NUMERIC_INVALID")
    return x


def _odds(value):
    x = _num(value)
    if x == 0 or -100 < x < 100:
        raise ValueError("CONSENSUS_AMERICAN_ODDS_INVALID")
    return x


def implied(american):
    n = _odds(american)
    return -n / (100 - n) if n < 0 else 100 / (100 + n)


def payout(american):
    n = _odds(american)
    return 100 / -n if n < 0 else n / 100


def _contract(q):
    market, side = str(q.get("market") or "").upper(), str(q.get("side") or "").upper()
    if market not in OPPOSITES or side not in OPPOSITES[market]:
        raise ValueError("CONSENSUS_MARKET_OR_SIDE_INVALID")
    gid = str(q.get("game_id") or "").strip()
    if not gid:
        raise ValueError("CONSENSUS_GAME_ID_REQUIRED")
    if market == "MONEYLINE":
        if q.get("line") is not None:
            raise ValueError("CONSENSUS_MONEYLINE_MUST_NOT_HAVE_LINE")
        key = (gid, market, None)
    else:
        line = _num(q.get("line"))
        if market == "SPREAD":
            # Opposite spreads represent the same event using the HOME handicap.
            line = line if side == "HOME" else -line
        key = (gid, market, round(line, 3))
    return key, side


def _illinois(matchup):
    import re
    name = str(matchup or "").lower()
    return any(re.search(r"\b" + re.escape(t) + r"\b", name) for t in EXCLUDED_ILLINOIS_TEAMS)


def _book_pairs(book):
    grouped = defaultdict(dict)
    rows = book.get("quotes")
    if not isinstance(rows, list):
        raise ValueError("CONSENSUS_BOOK_QUOTES_REQUIRED")
    for q in rows:
        key, side = _contract(q)
        if side in grouped[key]:
            raise ValueError("CONSENSUS_DUPLICATE_BOOK_SIDE")
        grouped[key][side] = implied(q["american_odds"])
    pairs = {}
    for key, d in grouped.items():
        if set(d) != OPPOSITES[key[1]]:
            continue
        total = sum(d.values())
        if not 0.90 <= total <= 1.25:
            continue
        pairs[key] = {s: v / total for s, v in d.items()}
    return pairs


def evaluate(card, references, *, max_age_seconds=MAX_AGE_SECONDS):
    if card.get("schema") != "CFB_SDV_CARD_V2":
        raise ValueError("CONSENSUS_CARD_SCHEMA_INVALID")
    asof = _time(card.get("scored_at_utc"))
    books = references.get("books")
    if not isinstance(books, list):
        raise ValueError("CONSENSUS_REFERENCE_BOOKS_REQUIRED")
    independent = defaultdict(list)
    seen_books = set()
    for book in books:
        ident = str(book.get("book") or "").strip().lower()
        if not ident or ident in TARGET_BOOKS:
            raise ValueError("CONSENSUS_TARGET_OR_UNNAMED_REFERENCE_FORBIDDEN")
        if ident in seen_books:
            raise ValueError("CONSENSUS_DUPLICATE_BOOK")
        seen_books.add(ident)
        captured = _time(book.get("captured_at_utc"))
        if not 0 <= (asof - captured).total_seconds() <= max_age_seconds:
            # Later quotes are NOT contemporaneous decision quotes.
            continue
        for key, probabilities in _book_pairs(book).items():
            for side, prob in probabilities.items():
                independent[(key, side)].append((ident, prob))
    output = []
    for row in card.get("results") or []:
        if row.get("market") not in OPPOSITES:
            continue
        key, side = _contract(row)
        offered = _odds(row["american_odds"])
        refs = independent.get((key, side), [])
        result = {
            "game_id": key[0], "matchup": row.get("matchup"),
            "market": key[1], "side": side, "line": row.get("line"),
            "target_book": "DRAFTKINGS_UNVERIFIED_PHONE_BOARD",
            "offered_american_odds": offered,
            "paired_reference_books": len(refs),
            "consensus_p": None, "fair_american_odds": None,
            "quoted_break_even_p": round(implied(offered), 6),
            "consensus_expected_roi": None,
            "pricing_role": "INDEPENDENT_MARKET_ESTIMATE_NOT_MODEL_P",
            "positive_ev_proven": False, "bets_enabled": False,
            "staking_authority": False, "status": "NO_PAIRED_REFERENCE",
        }
        kickoff = row.get("start_ts")
        if not kickoff or asof >= _time(kickoff):
            result["status"] = "NOT_PREGAME"
        elif _illinois(row.get("matchup")):
            result["status"] = "ILLINOIS_COLLEGE_EXCLUDED"
        elif offered < -165:
            result["status"] = "PRICE_CAP_MINUS_165"
        elif len(refs) < MIN_REFERENCE_BOOKS:
            result["status"] = "INSUFFICIENT_INDEPENDENT_BOOKS"
        else:
            ps = [x[1] for x in refs]
            if max(ps) - min(ps) > MAX_REFERENCE_DISAGREEMENT:
                result["status"] = "REFERENCE_DISAGREEMENT"
            else:
                p = sum(ps) / len(ps)
                fair_odds = -100 * p / (1 - p) if p >= 0.5 else 100 * (1 - p) / p
                roi = p * payout(offered) - (1 - p)
                result.update({
                    "consensus_p": round(p, 6),
                    "fair_american_odds": round(fair_odds, 1),
                    "consensus_expected_roi": round(roi, 6),
                    "independent_books": sorted(x[0] for x in refs),
                    "status": ("SHADOW_PRICE_DISLOCATION" if
                               p - implied(offered) >= MIN_ADVANTAGE_PP and roi > 0
                               else "NO_RESEARCH_PRICE_EDGE"),
                })
        output.append(result)
    return {
        "schema": SCHEMA, "sport": "CFB", "captured_card_at": asof.isoformat(),
        "reference_weight_method": "EQUAL_BOOK_RESEARCH_NOT_FITTED",
        "source": "MANUALLY_SUPPLIED_REFERENCES_UNATTESTED",
        "positive_ev_proven": False, "bets_enabled": False,
        "staking_authority": False, "model_probability_modified": False,
        "results": output,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card", required=True, type=Path)
    ap.add_argument("--reference-books", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ns = ap.parse_args(argv)
    result = evaluate(json.loads(ns.card.read_text()),
                      json.loads(ns.reference_books.read_text()))
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("CFB_INDEPENDENT_CONSENSUS rows=%s shadow_dislocations=%s no_staking=1" %
          (len(result["results"]),
           sum(x["status"] == "SHADOW_PRICE_DISLOCATION" for x in result["results"])))


if __name__ == "__main__":
    main()
