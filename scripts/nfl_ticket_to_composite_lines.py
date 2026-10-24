#!/usr/bin/env python3
"""Convert an automatic NFL DK ticket (scripts/collect_auto_dk_four_sports.py
nfl_ticket_<date>.json) into the composite RUN IT intake ({"lines": [...]}).

Ruling 8 (Oct 17 2026): composite live acceptance on the next real
multi-game slate. Conversion only: every price, line and timestamp is copied
verbatim. Each row's quote_captured_at is the market's own provider
observation stamp (its quote_timestamp_source is carried through); nothing
is re-dated, inferred or invented. Both sides of every two-sided market are
emitted together so the existing pairing contract can bind them; a market
missing either price is refused, never half-emitted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class TicketRefusal(ValueError):
    pass


def _sides(m: dict) -> list[tuple[str, str, object, object]]:
    kind = m.get("market")
    a, h, line = m.get("away_or_over_price"), m.get("home_or_under_price"), m.get("line")
    if a is None or h is None:
        raise TicketRefusal(f"TICKET_MARKET_NOT_TWO_SIDED:{kind}")
    if kind == "moneyline":
        return [("ML", "AWAY", a, None), ("ML", "HOME", h, None)]
    if kind == "spread":
        if line is None:
            raise TicketRefusal("TICKET_SPREAD_LINE_MISSING")
        return [("SPREAD", "AWAY", a, float(line)), ("SPREAD", "HOME", h, -float(line))]
    if kind == "total":
        if line is None:
            raise TicketRefusal("TICKET_TOTAL_LINE_MISSING")
        return [("TOTAL", "OVER", a, float(line)), ("TOTAL", "UNDER", h, float(line))]
    raise TicketRefusal(f"TICKET_MARKET_UNSUPPORTED:{kind}")


def convert(ticket: dict) -> dict:
    if ticket.get("sport") != "NFL":
        raise TicketRefusal("TICKET_SPORT_NOT_NFL")
    lines = []
    for g in ticket.get("games") or []:
        for m in g.get("markets") or []:
            stamp = m.get("quote_retrieved_at")
            if not stamp:
                raise TicketRefusal("TICKET_QUOTE_STAMP_MISSING")
            for market, side, odds, line in _sides(m):
                row = {"sport": "NFL", "away": g["away"], "home": g["home"],
                       "kickoff": g["commence_time"], "book": "draftkings",
                       "quote_captured_at": stamp,
                       "quote_timestamp_source": m.get("quote_timestamp_source"),
                       "market": market, "side": side, "odds": odds}
                if line is not None:
                    row["line"] = line
                lines.append(row)
    if not lines:
        raise TicketRefusal("TICKET_EMPTY")
    return {"lines": lines}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticket", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        out = convert(json.loads(a.ticket.read_text()))
    except TicketRefusal as exc:
        print(f"REFUSED {exc}", file=sys.stderr)
        return 3
    a.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"converted {len(out['lines'])} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
