"""NFL fair-price check: DraftKings price vs a no-vig market price.

Fair value is not a SportsEdge model. It comes from the market:
  1. Pinnacle at the exact same line, de-vigged (two-way, multiplicative), or
  2. if Pinnacle has no matching line, the median de-vigged price of at least
     MIN_CONSENSUS_BOOKS other books at the exact same line.
If neither exists the side is skipped. A fair price is never interpolated
across different lines and never built from one soft book.

EV is measured against the current no-vig price, not the closing line. It is a
price comparison, not a backtest-proven bet.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median
from typing import Any, Iterable, Mapping

from sportsedge.nfl_team_aliases import NFL_TEAMS

TARGET_BOOK = "draftkings"
SHARP_BOOK = "pinnacle"
# <=10 bookmakers count as one region on The Odds API, so 3 markets cost 3 credits.
BOOKMAKERS = (
    "draftkings", "pinnacle", "fanduel", "betmgm", "williamhill_us",
    "betrivers", "lowvig", "betonlineag", "bovada", "espnbet",
)
MARKETS = ("h2h", "spreads", "totals")
MIN_CONSENSUS_BOOKS = 3
EV_FLAG = 0.01
# A DK price this far above fair is usually stale or a typo, not free money.
STALE_EV = 0.05

_FULL_TO_ABBR = {names[0]: abbr for abbr, names in NFL_TEAMS.items()}


def team_abbr(full_name: str) -> str:
    return _FULL_TO_ABBR.get(str(full_name), str(full_name))


def american_to_decimal(price: float) -> float:
    p = float(price)
    if not isfinite(p) or -100.0 < p < 100.0:
        raise ValueError("AMERICAN_PRICE_INVALID")
    return 1.0 + (p / 100.0 if p > 0 else 100.0 / -p)


def prob_to_american(p: float) -> int:
    if not 0.0 < p < 1.0:
        raise ValueError("PROBABILITY_OUT_OF_RANGE")
    if p >= 0.5:
        return -int(round(100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def devig_two_way(price_a: float, price_b: float) -> tuple[float, float]:
    ia, ib = 1.0 / american_to_decimal(price_a), 1.0 / american_to_decimal(price_b)
    s = ia + ib
    return ia / s, ib / s


def _two_way(book: Mapping[str, Any], market_key: str) -> dict[tuple[str, float | None], float] | None:
    """{(outcome_name, point): price} for a two-outcome market, else None."""
    for market in book.get("markets") or []:
        if market.get("key") != market_key:
            continue
        outcomes = market.get("outcomes") or []
        if len(outcomes) != 2:
            return None
        out: dict[tuple[str, float | None], float] = {}
        for o in outcomes:
            try:
                point = None if o.get("point") is None else float(o["point"])
                price = float(o["price"])
                if (point is not None and not isfinite(point)) or not price.is_integer():
                    return None
                american_to_decimal(price)  # reject malformed provider prices
                out[(str(o["name"]), point)] = price
            except (KeyError, TypeError, ValueError):
                return None
        if len(out) != 2:
            return None
        names = [name for name, _point in out]
        points = [point for _name, point in out]
        if market_key == "h2h":
            if len(set(names)) != 2 or any(point is not None for point in points):
                return None
        elif market_key == "spreads":
            if (len(set(names)) != 2 or any(point is None for point in points)
                    or abs(points[0] + points[1]) > 1e-8):
                return None
        elif market_key == "totals":
            if ({name.casefold() for name in names} != {"over", "under"}
                    or any(point is None for point in points)
                    or abs(points[0] - points[1]) > 1e-8):
                return None
        else:
            return None
        return out
    return None


def _fair_for(sides: dict, book: Mapping[str, Any], market_key: str) -> dict | None:
    """De-vigged probabilities for the same two (name, point) sides in another book."""
    other = _two_way(book, market_key)
    if other is None or set(other) != set(sides):
        return None
    (ka, kb) = list(sides)
    pa, pb = devig_two_way(other[ka], other[kb])
    return {ka: pa, kb: pb}


def price_event(event: Mapping[str, Any]) -> list[dict]:
    books = {str(b.get("key")): b for b in event.get("bookmakers") or []}
    dk = books.get(TARGET_BOOK)
    if dk is None:
        return []
    rows: list[dict] = []
    for market_key in MARKETS:
        sides = _two_way(dk, market_key)
        if sides is None:
            continue
        if market_key in ("h2h", "spreads"):
            expected_teams = {str(event.get("home_team")), str(event.get("away_team"))}
            if {name for name, _point in sides} != expected_teams:
                continue
        fair = None
        source = ""
        if SHARP_BOOK in books:
            fair = _fair_for(sides, books[SHARP_BOOK], market_key)
            source = "Pinnacle no-vig" if fair else ""
        if fair is None:
            per_book = [
                f for key, b in books.items()
                if key not in (TARGET_BOOK, SHARP_BOOK)
                for f in [_fair_for(sides, b, market_key)] if f
            ]
            if len(per_book) >= MIN_CONSENSUS_BOOKS:
                fair = {k: median(f[k] for f in per_book) for k in sides}
                source = f"{len(per_book)}-book no-vig median"
        for (name, point), price in sides.items():
            row = {
                "market": market_key,
                "side": name,
                "point": point,
                "dk_price": int(price),
                "fair_p": None,
                "fair_price": None,
                "ev": None,
                "source": source or "no matching line elsewhere",
            }
            if fair is not None:
                p = fair[(name, point)]
                row["fair_p"] = p
                row["fair_price"] = prob_to_american(p)
                row["ev"] = p * american_to_decimal(price) - 1.0
            rows.append(row)
    return rows


def upcoming(events: Iterable[Mapping[str, Any]], now: datetime, days: int = 7) -> list[Mapping[str, Any]]:
    out = []
    for e in events:
        try:
            t = datetime.fromisoformat(str(e["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if now < t <= now + timedelta(days=days):
            out.append(e)
    return sorted(out, key=lambda e: str(e["commence_time"]))


def _fmt_price(p: int | None) -> str:
    return "—" if p is None else (f"+{p}" if p > 0 else str(p))


def _label(row: Mapping[str, Any], home: str, away: str) -> str:
    m, side, pt = row["market"], row["side"], row["point"]
    if m == "totals":
        return f"{side} {pt:g}"
    team = team_abbr(side)
    if m == "spreads":
        return f"{team} {pt:+g}"
    return f"{team} ML"


def render_card(events: list[Mapping[str, Any]], *, fetched_at: datetime) -> str:
    lines = [
        "**NFL fair-price check** (DraftKings vs no-vig market)",
        "",
        f"Prices pulled {fetched_at.strftime('%a %b %d %H:%M')} UTC. Fair = Pinnacle no-vig at the same line, "
        f"else the median no-vig of {MIN_CONSENSUS_BOOKS}+ other books at the same line. "
        f"✅ = DK pays at least {EV_FLAG:.0%} more than fair. This compares prices right now; it is not tracked "
        "against the closing line yet, so it is not a proven bet. Re-check the DK price before betting.",
        "",
    ]
    flagged: list[str] = []
    body: list[str] = []
    clv_log: list[dict] = []
    for e in events:
        home, away = str(e.get("home_team")), str(e.get("away_team"))
        rows = price_event(e)
        if not rows:
            continue
        t = datetime.fromisoformat(str(e["commence_time"]).replace("Z", "+00:00"))
        body.append(f"### {team_abbr(away)} @ {team_abbr(home)} · {t.strftime('%a %H:%M')} UTC")
        for r in rows:
            label = _label(r, home, away)
            if r["ev"] is None:
                body.append(f"- {label} @ {_fmt_price(r['dk_price'])} · fair: {r['source']}")
                continue
            stale = r["ev"] >= STALE_EV
            mark = "⚠️" if stale else ("✅" if r["ev"] >= EV_FLAG else ("·" if r["ev"] >= 0 else "❌"))
            text = (f"{label} @ {_fmt_price(r['dk_price'])} · fair {_fmt_price(r['fair_price'])} "
                    f"({r['source']}) · EV {r['ev'] * 100:+.1f}%")
            if stale:
                text += " · verify: DK is far off every other price (stale or typo?)"
            body.append(f"- {mark} {text}")
            if r["ev"] >= EV_FLAG:
                flagged.append(f"- {mark} {team_abbr(away)} @ {team_abbr(home)}: {text}")
                clv_log.append({
                    "event_id": e.get("id"), "commence": e.get("commence_time"),
                    "home": team_abbr(home), "away": team_abbr(away),
                    "market": r["market"], "side": r["side"], "point": r["point"],
                    "dk_price": r["dk_price"], "fair_p": round(r["fair_p"], 4),
                    "ev": round(r["ev"], 4), "source": r["source"], "stale": stale,
                    "flagged_at": fetched_at.isoformat(),
                })
        body.append("")
    if not body:
        lines.append("No upcoming NFL games with DraftKings prices were returned.")
        return "\n".join(lines) + "\n"
    lines.append(f"**DK prices at least {EV_FLAG:.0%} above fair ({len(flagged)}):**")
    lines.extend(flagged or ["- None right now."])
    lines.append("")
    lines.append("<details><summary>Every DK side vs fair</summary>")
    lines.append("")
    lines.extend(body)
    lines.append("</details>")
    # Machine-readable record of every flag, graded later against the closing line (CLV).
    lines.append("")
    lines.append("<!-- sportsedge-clv-log " + json.dumps(clv_log, separators=(",", ":")) + " -->")
    return "\n".join(lines) + "\n"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
