#!/usr/bin/env python3
"""Capture a full Saturday FBS DK public-splits board as research-only input.

The source is a jurisdiction-combined PUBLIC web table, NOT an independently
verified executable DraftKings quote or a predictive sports model. Never backfill
a price after kickoff; use only the scraped pregame board with its capture receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SCHEMA = "CFB_SATURDAY_FBS_DK_PUBLIC_CAPTURE_V1"
GAME_DATE = "2026-10-10"
BASE = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/"
REQUEST_PARAMS = {"tb_edate": "n30days", "tb_eg": "87637"}
EXPECTED_MATCHUPS = (
    ("Tulane", "Army"), ("North Carolina", "Pittsburgh"),
    ("Arizona", "West Virginia"), ("Wake Forest", "NC State"),
    ("Indiana", "Nebraska"), ("UCF", "Oklahoma State"),
    ("Texas A&M", "Missouri"), ("Sacramento State", "Bowling Green"),
    ("Ball State", "Northwestern"), ("South Carolina", "Florida"),
    ("Old Dominion", "Appalachian State"), ("Rice", "East Carolina"),
    ("Miami OH", "UMass"), ("Illinois", "Michigan State"),
    ("Buffalo", "Toledo"), ("Central Michigan", "Ohio"),
    ("Eastern Michigan", "Akron"), ("Kent State", "Western Michigan"),
    ("Duke", "Georgia Tech"), ("Oklahoma", "Texas"),
    ("Ole Miss", "Vanderbilt"), ("Charlotte", "North Texas"),
    ("Houston", "Kansas State"), ("Virginia Tech", "California"),
    ("UCLA", "Oregon"), ("Tulsa", "Navy"),
    ("Stanford", "Notre Dame"), ("UConn", "Temple"),
    ("Maryland", "Ohio State"), ("Tennessee", "Arkansas"),
    ("San Diego State", "Oregon State"), ("Coastal Carolina", "Marshall"),
    ("LSU", "Kentucky"), ("UAB", "Memphis"),
    ("Nevada", "UTEP"), ("North Dakota State", "UNLV"),
    ("James Madison", "Georgia Southern"), ("USC", "Penn State"),
    ("Syracuse", "Virginia"), ("Louisiana", "Louisiana Tech"),
    ("Georgia", "Alabama"), ("Air Force", "Northern Illinois"),
    ("Minnesota", "Purdue"), ("Kansas", "Utah"),
    ("Hawaii", "Arizona State"), ("Boise State", "Fresno State"),
)
ILLINOIS_MATCHUPS = {("Ball State", "Northwestern"), ("Illinois", "Michigan State"),
                    ("Air Force", "Northern Illinois")}
NATIVE_FCS_GAPS = {("Sacramento State", "Bowling Green"),
                   ("North Dakota State", "UNLV")}
_GAME = re.compile(r"^\s*([^@]{2,70})\s+@\s+([^@]{2,70})\s*$")
_GAME_DATE = re.compile(r"^10/10,\s+(\d{1,2}:\d{2}[AP]M)$", re.I)
_SPREAD = re.compile(r"^(.+?)\s+([+-]\d+(?:\.\d+)?)$")
_TOTAL = re.compile(r"^(Over|Under)\s+(\d+(?:\.\d+)?)$", re.I)
_ODDS = re.compile(r"^[+-]\d{3,6}$")


def _clean(s):
    return str(s).replace("\u2212", "-").replace("\u2013", "-").strip()


def _name(s):
    n = re.sub(r"[^a-z0-9]+", " ", _clean(s).lower()).strip()
    return {"central florida": "ucf", "miami ohio": "miami oh",
            "miami oh": "miami oh", "connecticut": "uconn",
            "ul lafayette": "louisiana", "louisiana lafayette": "louisiana"}.get(n, n)


def _odds(s):
    s = _clean(s)
    if not _ODDS.fullmatch(s):
        return None
    n = int(s)
    return n if abs(n) >= 100 and abs(n) <= 100000 else None


def _game_time(s):
    match = _GAME_DATE.fullmatch(_clean(s))
    if not match:
        return None
    from datetime import datetime
    dt = datetime.strptime("2026-10-10 " + match.group(1).upper(), "%Y-%m-%d %I:%M%p")
    return dt.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat()


def _quote_pairs(section, *, spread=False, away="", home=""):
    found = {}
    for i in range(len(section) - 1):
        item, price = section[i], _odds(section[i + 1])
        if price is None:
            continue
        m = _SPREAD.fullmatch(item) if spread else _TOTAL.fullmatch(item)
        if not m:
            continue
        if spread:
            team, line = _name(m.group(1)), float(m.group(2))
            side = "AWAY" if team == _name(away) else "HOME" if team == _name(home) else None
        else:
            side, line = m.group(1).upper(), float(m.group(2))
        if side is None or side in found:
            continue
        found[side] = (line, price)
    sides = {"AWAY", "HOME"} if spread else {"OVER", "UNDER"}
    if set(found) != sides:
        return None
    if spread:
        if abs(found["AWAY"][0] + found["HOME"][0]) > 0.001:
            return None
        return [found["AWAY"][0], found["AWAY"][1], found["HOME"][1]]
    if abs(found["OVER"][0] - found["UNDER"][0]) > 0.001:
        return None
    return [found["OVER"][0], found["OVER"][1], found["UNDER"][1]]


def parse_public_html(html: str, *, page: int):
    """Extract exact opposing prices from a rendered PUBLIC text table.

    No guessed counterpart price and no synthesized match/line. Ignore duplicate
    nonmatchup text and any game without an October 10, 2026 kickoff.
    """
    if not isinstance(html, str) or "Betting Splits" not in html:
        raise ValueError("CFB_DK_TABLE_MISSING")
    t = [_clean(x) for x in BeautifulSoup(html, "html.parser").stripped_strings]
    result = []
    for i, token in enumerate(t):
        m = _GAME.fullmatch(token)
        if not m or i + 1 >= len(t):
            continue
        start = _game_time(t[i + 1])
        if not start:
            continue
        away, home = m.group(1).strip(), m.group(2).strip()
        nxt = next((j for j in range(i + 2, len(t) - 1)
                    if _GAME.fullmatch(t[j]) and _game_time(t[j + 1])), len(t))
        area = t[i + 2:nxt]
        # Sections must have valid sportsbook full-game labels in order.
        spread_ix = next((k for k, v in enumerate(area) if v == "Spread"), None)
        total_ix = next((k for k, v in enumerate(area) if v == "Total"), None)
        spread = (_quote_pairs(area[spread_ix + 1:total_ix], spread=True, away=away, home=home)
                  if spread_ix is not None and total_ix is not None and spread_ix < total_ix
                  else None)
        total = _quote_pairs(area[total_ix + 1:], spread=False) if total_ix is not None else None
        result.append({"away": away, "home": home, "start_ts": start,
                       "spread": spread, "total": total, "source_page": page})
    return result


def compile_full_slate(pages, *, captured_at_utc=None, min_eligible_paired=30):
    """Full game inventory; only complete, exact sportsbook pairs enter scoring."""
    if len(EXPECTED_MATCHUPS) != 46 or len(set(EXPECTED_MATCHUPS)) != 46:
        raise ValueError("CFB_SCHEDULE_INVENTORY_INVALID")
    captured = captured_at_utc or datetime.now(timezone.utc).isoformat()
    capture_dt = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
    if capture_dt.tzinfo is None or capture_dt.utcoffset() is None:
        raise ValueError("CFB_PUBLIC_CAPTURE_TIMESTAMP_REQUIRED")
    capture_dt = capture_dt.astimezone(timezone.utc)
    observed = {}
    for page, html in sorted(pages.items()):
        for row in parse_public_html(html, page=page):
            key = (_name(row["away"]), _name(row["home"]))
            if key not in {(_name(a), _name(h)) for a, h in EXPECTED_MATCHUPS}:
                continue
            if key in observed:
                original = observed[key]
                if (original["spread"], original["total"]) != (row["spread"], row["total"]):
                    # Pagination can shift while prices update. An ambiguous
                    # snapshot is not safe to advertise as a contemporaneous quote.
                    original["spread"], original["total"] = None, None
                    original["ambiguous_pagination"] = True
            else:
                observed[key] = row
    board, inventory = [], []
    for away, home in EXPECTED_MATCHUPS:
        key = (_name(away), _name(home))
        row = observed.get(key)
        reason = ("ILLINOIS_COLLEGE_EXCLUDED" if (away, home) in ILLINOIS_MATCHUPS else
                  "FCS_NATIVE_MODEL_SNAPSHOT_UNAVAILABLE" if (away, home) in NATIVE_FCS_GAPS else
                  "MISSING_PUBLIC_DK_MATCHUP" if row is None else
                  "CONFLICTING_PUBLIC_PAGE_QUOTES" if row.get("ambiguous_pagination") else
                  "KICKED_OFF_NO_RETROSPECTIVE_PRICE" if datetime.fromisoformat(row["start_ts"]) <= capture_dt else
                  "MISSING_PAIRED_SPREAD_OR_TOTAL" if not row.get("spread") or not row.get("total") else
                  "PREGAME_UNVERIFIED_PUBLIC_QUOTES")
        item = {"away": away, "home": home, "status": reason,
                "start_ts": row.get("start_ts") if row else None}
        inventory.append(item)
        if reason != "PREGAME_UNVERIFIED_PUBLIC_QUOTES":
            continue
        board.append({
            "away": away, "home": home,
            "spread": row["spread"], "total": row["total"],
            "start_ts": row["start_ts"],
            "public_quote_source": BASE,
            "source_page": row["source_page"],
            "quote_capture_at_utc": captured,
            "sportsbook_price_receipt_verified": False,
            "price_executable_for_illinois_account_verified": False,
            "research_only": True,
        })
    if len(board) < min_eligible_paired:
        raise ValueError("CFB_DK_PUBLIC_BOARD_INSUFFICIENT_PAIRED_COVERAGE:%d" % len(board))
    return {"schema": SCHEMA, "slate_date": GAME_DATE,
            "captured_at_utc": captured, "scheduled_fbs_games": 46,
            "illinois_exclusions": 3, "fcs_native_gap_exclusions": 2,
            "scorable_games_with_both_pairs": len(board),
            "source": "DRAFTKINGS_NETWORK_PUBLIC_AGGREGATE_SPLITS",
            "unverified_individual_quote_timestamps": True,
            "verified_executable_prices": False, "positive_ev_proven": False,
            "board": board, "inventory": inventory}


def capture(*, session=None):
    s = session if session is not None else requests.Session()
    pages, receipts = {}, []
    for page in range(1, 6):
        params = {**REQUEST_PARAMS, "tb_page": page}
        res = s.get(BASE, params=params, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SportsEdgeResearch/1.0)"
        }, timeout=20)
        res.raise_for_status()
        pages[page] = res.text
        receipts.append({"page": page, "url": res.url,
                         "body_sha256": hashlib.sha256(res.content).hexdigest(),
                         "captured_at_utc": datetime.now(timezone.utc).isoformat()})
    obj = compile_full_slate(pages)
    obj["source_pages"] = receipts
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board-output", required=True, type=Path)
    ap.add_argument("--audit-output", required=True, type=Path)
    ns = ap.parse_args()
    obj = capture()
    for path, item in ((ns.board_output, obj["board"]),
                       (ns.audit_output, {k: v for k, v in obj.items() if k != "board"})):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CFB_FULL_FBS_PUBLIC_BOARD scheduled=%d illinois_excluded=%d fcs_gap=%d paired_games=%d" %
          (obj["scheduled_fbs_games"], obj["illinois_exclusions"],
           obj["fcs_native_gap_exclusions"], obj["scorable_games_with_both_pairs"]))


if __name__ == "__main__":
    main()
