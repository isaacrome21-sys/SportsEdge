#!/usr/bin/env python3
"""Budgeted OddsPapi v4 sportsbook snapshots with conservative paired OU research.

Live calls are explicit and preflighted against /v4/account. The output stores
the complete upstream fixture object for later verified market-ID mapping.
Only numeric-line OVER/UNDER pairs are interpreted; no guessed market names,
Model_P, PLAY authorization, backfill, or sportsbook web-page scraping.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.oddspapi.io/v4"
MAX_AGE_SECONDS = 180
DEFAULT_RESERVE = 25
PAIR_LABEL = re.compile(r"^([+-]?(?:\d+(?:\.\d+)?|\.\d+))/(over|under)$", re.I)
FIXTURE_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
BOOK_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class IntakeRefusal(ValueError):
    """Expected fail-closed provider, quote, or quota refusal."""


def utc_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def american(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value))
    except (ValueError, TypeError):
        return None
    if str(value).strip().startswith("+"):
        if str(value).strip() != "+" + str(number):
            return None
    elif str(value).strip() != str(number):
        return None
    return number if abs(number) >= 100 else None


def _source_stamp(player, asof):
    # The earlier trustworthy source update governs; a fetch-time timestamp
    # is NOT a substitute for either provider price-change timestamp.
    stamps = [utc_time(player.get("changedAt"))]
    if player.get("bookmakerChangedAt") is not None:
        stamps.append(utc_time(player.get("bookmakerChangedAt")))
    if any(x is None for x in stamps):
        return None
    oldest = min(stamps)
    age = (asof - oldest).total_seconds()
    return oldest if 0 <= age <= MAX_AGE_SECONDS else None


def _american_fair(over, under):
    def imp(price):
        return -price / (100 - price) if price < 0 else 100 / (100 + price)
    po, pu = imp(over), imp(under)
    if po + pu <= 0:
        raise IntakeRefusal("INVALID_MARKET_PROBABILITY")
    return {"over": round(po / (po + pu), 8), "under": round(pu / (po + pu), 8)}


def normalize_fixture(raw, fixture_id, *, asof):
    """Expose only exact paired numeric OVER/UNDER outcomes, with raw IDs.

    Unknown odds families and incompatible line formats remain in raw payload.
    Never infer an absent opposite, merge independent players, or normalize
    an opaque market ID into a named player stat without an admitted catalog.
    """
    if not isinstance(raw, dict) or raw.get("fixtureId") != fixture_id:
        raise IntakeRefusal("FIXTURE_ID_MISMATCH")
    start = utc_time(raw.get("startTime"))
    if start is None or start <= asof or raw.get("statusId") != 0:
        raise IntakeRefusal("NOT_PROSPECTIVE_PREGAME_FIXTURE")
    if raw.get("hasOdds") is not True:
        return {"fixture_id": fixture_id, "status": "NO_ODDS",
                "pairs": [], "books_seen": [], "model_p": None,
                "play_eligible": False}
    all_books = raw.get("bookmakerOdds")
    if not isinstance(all_books, dict):
        raise IntakeRefusal("BOOKMAKER_DATA_MISSING")
    pairs = []
    for book, book_data in sorted(all_books.items()):
        if not isinstance(book_data, dict) or book_data.get("suspended") is True:
            continue
        if book_data.get("bookmakerIsActive") is not True:
            continue
        markets = book_data.get("markets")
        if not isinstance(markets, dict):
            continue
        for market_id, market_data in sorted(markets.items()):
            if not isinstance(market_data, dict) or market_data.get("marketActive") is not True:
                continue
            outcomes = market_data.get("outcomes")
            if not isinstance(outcomes, dict):
                continue
            groups = {}
            for outcome_id, outcome in outcomes.items():
                if not isinstance(outcome, dict) or not isinstance(outcome.get("players"), dict):
                    continue
                for player_id, player in outcome["players"].items():
                    if not isinstance(player, dict) or player.get("active") is not True:
                        continue
                    match = PAIR_LABEL.fullmatch(str(player.get("bookmakerOutcomeId") or "").strip())
                    if match is None:
                        continue
                    try:
                        line = Decimal(match.group(1))
                    except InvalidOperation:
                        continue
                    if not line.is_finite():
                        continue
                    price = american(player.get("priceAmerican"))
                    stamp = _source_stamp(player, asof)
                    if price is None or stamp is None:
                        continue
                    name = player.get("playerName")
                    if name is not None and (not isinstance(name, str) or not name.strip()):
                        continue
                    group_key = (str(market_id), str(player_id), name, str(line.normalize()))
                    side = match.group(2).lower()
                    group = groups.setdefault(group_key, {"over": [], "under": []})
                    group[side].append({
                        "price": price, "source_changed_at": stamp.isoformat(),
                        "outcome_id": str(outcome_id),
                        "bookmaker_outcome_id": player["bookmakerOutcomeId"],
                        "main_line": player.get("mainLine") is True,
                    })
            for (raw_market, raw_player, name, line), sides in sorted(
                    groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][3])):
                # Ambiguous duplicate outcomes are not resolved by guesswork.
                if len(sides["over"]) != 1 or len(sides["under"]) != 1:
                    continue
                over, under = sides["over"][0], sides["under"][0]
                pairs.append({
                    "fixture_id": fixture_id, "book": book, "market_id": raw_market,
                    "player_id": raw_player, "player_name": name, "line": line,
                    "over": over, "under": under,
                    "no_vig_market_reference": _american_fair(over["price"], under["price"]),
                    "quote_origin": "ODDSPAPI_V4_SOURCE_CHANGED_AT",
                    "model_p": None, "play_eligible": False,
                })
    return {
        "fixture_id": fixture_id, "status": "PAIRS_FOUND" if pairs else "RAW_ONLY_NO_SAFE_PAIRS",
        "sport_id": raw.get("sportId"), "start_time": start.isoformat(),
        "participant1": raw.get("participant1Name"),
        "participant2": raw.get("participant2Name"),
        "books_seen": sorted(all_books),
        "pairs": pairs, "model_p": None, "play_eligible": False,
        "unmapped_market_ids_are_not_model_priced": True,
    }


def account_remaining(account):
    if not isinstance(account, dict):
        raise IntakeRefusal("ACCOUNT_RESPONSE_INVALID")
    active_id = account.get("current_subscription_id")
    subs = account.get("subscriptions")
    if not isinstance(subs, list):
        raise IntakeRefusal("ACCOUNT_SUBSCRIPTIONS_MISSING")
    eligible = [s for s in subs if isinstance(s, dict) and
                s.get("is_active") is True and s.get("subscription_id") == active_id]
    if len(eligible) != 1:
        raise IntakeRefusal("ACTIVE_SUBSCRIPTION_NOT_UNIQUE")
    s = eligible[0]
    limit, count = s.get("request_limit"), s.get("request_count")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (limit, count)):
        raise IntakeRefusal("QUOTA_COUNT_INVALID")
    if not 0 <= count <= limit:
        raise IntakeRefusal("QUOTA_COUNT_OUT_OF_RANGE")
    return limit - count


def safe_request(endpoint, params, key, *, opener=urlopen):
    """No URLs, response payloads or account secrets in errors/log output."""
    query = urlencode(dict(params, apiKey=key))
    req = Request(API + endpoint + "?" + query,
                  headers={"Accept": "application/json",
                           "User-Agent": "SportsEdge-OddsPapi-Intake/1"})
    try:
        with opener(req, timeout=20) as res:
            blob = res.read(15_000_001)
            if len(blob) > 15_000_000:
                raise IntakeRefusal("RESPONSE_TOO_LARGE")
        return json.loads(blob)
    except HTTPError as exc:
        raise IntakeRefusal("PROVIDER_HTTP_" + str(exc.code)) from None
    except (URLError, OSError, TimeoutError):
        raise IntakeRefusal("PROVIDER_UNAVAILABLE") from None
    except (ValueError, UnicodeDecodeError):
        raise IntakeRefusal("PROVIDER_RESPONSE_INVALID") from None


def validate_selection(fixtures, books):
    if not fixtures or len(fixtures) != len(set(fixtures)) or any(
            not FIXTURE_ID.fullmatch(x) for x in fixtures):
        raise IntakeRefusal("FIXTURE_IDS_INVALID")
    if not 1 <= len(books) <= 3 or len(books) != len(set(books)) or any(
            not BOOK_SLUG.fullmatch(x) for x in books):
        raise IntakeRefusal("BOOKMAKERS_INVALID")


def collect(fixtures, books, *, max_billable=0, reserve=DEFAULT_RESERVE,
            out_dir=None, key=None, request=safe_request, clock=None):
    """Explicit per-run budget, independent free quota check BEFORE EACH call."""
    validate_selection(fixtures, books)
    if isinstance(max_billable, bool) or not isinstance(max_billable, int) or max_billable < 0:
        raise IntakeRefusal("BILLABLE_LIMIT_INVALID")
    if not isinstance(reserve, int) or reserve < DEFAULT_RESERVE:
        raise IntakeRefusal("MINIMUM_RESERVE_REQUIRED")
    if max_billable == 0:
        return {"status": "DRY_RUN_NO_BILLABLE_CALLS",
                "planned_fixture_ids": list(fixtures),
                "books": list(books), "cost": 0}
    if not key:
        raise IntakeRefusal("ODDSPAPI_KEY_MISSING")
    if max_billable < len(fixtures):
        raise IntakeRefusal("BILLABLE_LIMIT_BELOW_FIXTURE_COUNT")
    if out_dir is None:
        raise IntakeRefusal("OUTPUT_DIR_REQUIRED")
    out_dir = Path(out_dir)
    now = clock or (lambda: datetime.now(timezone.utc))
    results = []
    for fixture_id in fixtures:
        account = request("/account", {}, key)
        if account_remaining(account) <= reserve:
            raise IntakeRefusal("QUOTA_RESERVE_WOULD_BE_BREACHED")
        asof = now()
        # Book slugs are explicit, bounded, and not fetched from arbitrary HTML.
        raw = request("/odds", {"fixtureId": fixture_id,
                                "bookmakers": ",".join(books), "verbosity": 3}, key)
        normalized = normalize_fixture(raw, fixture_id, asof=now())
        safe_name = fixture_id + ".json"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / safe_name).write_text(json.dumps({
            "source": "ODDSPAPI_V4", "asof_utc": now().isoformat(),
            "fixture_id": fixture_id, "normalized": normalized,
            "raw_unmapped_provider_response": raw, "model_p": None,
            "play_eligible": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results.append({"fixture_id": fixture_id, "status": normalized["status"],
                        "pairs": len(normalized["pairs"]), "file": str(out_dir / safe_name)})
    return {"status": "RESEARCH_CAPTURED", "calls": len(results),
            "books": list(books), "fixtures": results,
            "model_p": None, "play_eligible": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-id", action="append", required=True)
    parser.add_argument("--bookmakers", default="draftkings,pinnacle,fanduel")
    parser.add_argument("--max-billable", type=int, default=0,
                        help="Default 0: dry run, NEVER spend a credit implicitly.")
    parser.add_argument("--reserve", type=int, default=DEFAULT_RESERVE)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/oddspapi_live"))
    args = parser.parse_args()
    try:
        payload = collect(args.fixture_id, args.bookmakers.split(","),
                          max_billable=args.max_billable, reserve=args.reserve,
                          out_dir=args.out_dir, key=os.environ.get("SPORTSEDGE_ODDSPAPI_KEY"))
    except IntakeRefusal as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
