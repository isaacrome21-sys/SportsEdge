#!/usr/bin/env python3
"""Import a saved VegasInsider public HTML odds table; never calls an API.

Page retrieval is not a sportsbook quote timestamp. Output remains manual
research input requiring a current DraftKings check before using any price.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKETS = {"spread": "spreads", "total": "totals", "moneyline": "h2h"}


def number(value):
    text = str(value).strip().lower().replace("−", "-").replace("½", ".5")
    if text in {"even", "ev", "evs"}:
        return 100.0
    if text in {"pk", "pick", "pick'em"}:
        return 0.0
    return float(text)


def parse_page(html, *, captured_at, source_url):
    stamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("CFB_PUBLIC_CAPTURE_TIMEZONE_REQUIRED")
    soup = BeautifulSoup(html, "html.parser")
    events = {}
    for body in soup.select("table.odds-table tbody"):
        found = re.match(r"odds-table-(spread|total|moneyline)--", body.get("id", ""))
        if not found:
            continue
        kind = found[1]
        books, kickoff, pending = [], None, []
        for row in body.select("tr"):
            clock = row.select_one('[data-format="date"][data-value]')
            if clock:
                if pending:
                    raise ValueError("CFB_PUBLIC_INCOMPLETE_GAME_PAIR")
                kickoff = clock["data-value"]
                books = []
                for head in row.select("th.book-logo"):
                    icon = head.select_one("img[alt]")
                    books.append(icon["alt"].lower() if icon else head.get_text(strip=True).lower())
                continue
            team = row.select_one(".team-name")
            if team is None:
                continue
            if not kickoff or not books:
                raise ValueError("CFB_PUBLIC_HEADER_REQUIRED")
            cells = row.select("td.game-odds")
            pending.append((team.get_text(" ", strip=True), cells))
            if len(pending) < 2:
                continue
            (away, away_cells), (home, home_cells) = pending
            pending = []
            if away == home:
                raise ValueError("CFB_PUBLIC_IDENTICAL_TEAMS")
            key = (kickoff, away, home)
            event = events.setdefault(key, {
                "id": "public-" + hashlib.sha256("|".join(key).encode()).hexdigest()[:16],
                "away_team": away, "home_team": home, "commence_time": kickoff,
                "bookmakers": [], "source_url": source_url,
                "page_captured_at": captured_at, "book_quote_receipt_verified": False,
            })
            for i, book in enumerate(books):
                if book in {"open", "consensus", ""}:
                    continue
                if i >= len(away_cells) or i >= len(home_cells):
                    raise ValueError("CFB_PUBLIC_BOOK_COLUMN_MISSING")
                outcomes = []
                for name, cell in ((away, away_cells[i]), (home, home_cells[i])):
                    val, price = cell.select_one(".data-value"), cell.select_one(".data-odds")
                    try:
                        if kind == "moneyline":
                            node = cell.select_one(".data-moneyline") or price or val
                            odds = number(node.get_text(strip=True)) if node else None
                            point = None
                        else:
                            raw = val.get_text(strip=True) if val else ""
                            if kind == "total":
                                if not raw or raw[0].lower() not in {"o", "u"}:
                                    break
                                name = "Over" if raw[0].lower() == "o" else "Under"
                                raw = raw[1:]
                            point = number(raw)
                            odds = number(price.get_text(strip=True)) if price else None
                        if odds is None or abs(odds) < 100:
                            break
                    except ValueError:
                        break
                    out = {"name": name, "price": odds}
                    if point is not None:
                        out["point"] = point
                    outcomes.append(out)
                if len(outcomes) != 2:
                    continue
                entry = next((b for b in event["bookmakers"] if b["key"] == book), None)
                if entry is None:
                    entry = {"key": book, "markets": []}
                    event["bookmakers"].append(entry)
                if any(m["key"] == MARKETS[kind] for m in entry["markets"]):
                    raise ValueError("CFB_PUBLIC_DUPLICATE_BOOK_MARKET")
                entry["markets"].append({"key": MARKETS[kind], "outcomes": outcomes})
        if pending:
            raise ValueError("CFB_PUBLIC_INCOMPLETE_GAME_PAIR")
    if not events:
        raise ValueError("CFB_PUBLIC_NO_ODDS_TABLE_GAMES")
    return list(events.values())


def attach_user_draftkings(events, board):
    """Use only supplied DK prices; public DK columns are never target offers."""
    from scripts.run_cfb_sdv_card_v2 import _n, expand_compact
    output, missing = [], []
    for supplied in board:
        identities = {_n(supplied.get("away", "")), _n(supplied.get("home", ""))}
        matches = [e for e in events if {_n(e["away_team"]), _n(e["home_team"])} == identities]
        if len(matches) != 1:
            missing.append({"away": supplied.get("away"), "home": supplied.get("home"),
                            "reason": "NO_UNIQUE_PUBLIC_GAME"})
            continue
        event = copy.deepcopy(matches[0])
        if supplied.get("start_ts") and (
            datetime.fromisoformat(supplied["start_ts"].replace("Z", "+00:00")) !=
            datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        ):
            missing.append({"away": supplied.get("away"), "home": supplied.get("home"),
                            "reason": "PUBLIC_KICKOFF_MISMATCH"})
            continue
        names = {_n(event[k]): event[k] for k in ("away_team", "home_team")}
        markets = {}
        for quote in expand_compact(supplied)["quotes"]:
            market = {"MONEYLINE": "h2h", "SPREAD": "spreads", "TOTAL": "totals"}[quote["market"]]
            name = (quote["side"].title() if market == "totals" else
                    names[_n(supplied["home" if quote["side"] == "HOME" else "away"])])
            outcome = {"name": name, "price": quote["american_odds"]}
            if quote.get("line") is not None:
                outcome["point"] = quote["line"]
            markets.setdefault(market, []).append(outcome)
        event["bookmakers"] = [b for b in event["bookmakers"] if b["key"] != "draftkings"]
        event["bookmakers"].append({"key": "draftkings", "markets": [
            {"key": key, "outcomes": outcomes} for key, outcomes in markets.items()]})
        event["target_price_source"] = "USER_SUPPLIED_DRAFTKINGS_BOARD"
        event["target_quote_captured_at"] = supplied.get("quote_captured_at")
        output.append(event)
    return output, missing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", type=Path, required=True)
    p.add_argument("--captured-at", required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dk-board", type=Path, required=True,
                   help="User supplied compact DK board; public DK prices are discarded")
    a = p.parse_args()
    blob = a.html.read_bytes()
    events = parse_page(blob.decode(), captured_at=a.captured_at, source_url=a.source_url)
    for event in events:
        event["source_html_sha256"] = hashlib.sha256(blob).hexdigest()
    imported = len(events)
    events, missing = attach_user_draftkings(events, json.loads(a.dk_board.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(events, indent=2) + "\n")
    print(json.dumps({"public_games_imported": imported, "supplied_dk_games_matched": len(events),
                      "unmatched_dk_games": missing, "sportsbook_api_used": False,
                      "book_quote_receipt_verified": False}))


if __name__ == "__main__":
    main()
