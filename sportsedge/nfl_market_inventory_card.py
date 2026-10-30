"""NFL issue-card inventory: every catalog market, with honest quote/model status.

Presentation only.  A quoted side is not a paired/fresh quote, model probability,
validated edge, or betting authorization.  This module never constructs prices.
"""
from __future__ import annotations

from collections import Counter
from html import escape
from typing import Mapping

from sportsedge.canonical_coverage import MARKET_RESOLUTIONS, PRICED_PATH


def _md(value: object) -> str:
    """Keep external market names from changing the Markdown table shape."""
    return escape(str(value or ""), quote=False).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def _valid_american(value: object) -> bool:
    return (type(value) is int and (value <= -100 or value >= 100))


def quote_side_counts(full_board: Mapping | None) -> Counter[str]:
    """Count actual exact-price quote SIDES, not placeholders or inferred pairs."""
    out: Counter[str] = Counter()
    rows = (full_board or {}).get("rows") or []
    if not isinstance(rows, (tuple, list)):
        return out
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not row.get("game_id") or row.get("reason") == "NO_QUOTE_OR_ENGINE_ROW":
            continue
        if not _valid_american(row.get("american_odds")):
            continue
        market = str(row.get("market") or "").strip().lower()
        if market:
            out[market] += 1
    return out


def market_inventory_section(full_board: Mapping | None) -> str:
    """Surface every NFL family; never imply prices for blocked or missing rows."""
    catalog = {
        name: resolution
        for (sport, name), resolution in MARKET_RESOLUTIONS.items()
        if sport == "NFL"
    }
    counts = quote_side_counts(full_board)
    research = sum(resolution["state"] == PRICED_PATH for resolution in catalog.values())
    blocked = len(catalog) - research
    quoted = sum(market in catalog for market in counts)
    unknown = sorted(set(counts) - set(catalog))
    lines = [
        "",
        "### NFL all-market coverage — PAPER ONLY",
        f"- Catalog: **{len(catalog)} market types** · **{research} research routes**"
        f" · **{blocked} blocked model routes**.",
        f"- Captured here: **{quoted} catalog families**, **{sum(counts.values())} exact-price quote sides**"
        " (not necessarily paired, fresh, or eligible).",
        "- **No NFL family is verified for wagering.** A quote without a permitted model"
        " remains track-only; no missing price or opposite side is invented.",
        "- This census covers the repository's NFL catalog. DraftKings may offer more;"
        " unobserved/off-catalog menus require separate source capture.",
        "",
        f"<details><summary>Every catalog market ({len(catalog)}) — quote and engine status</summary>",
        "",
        "| Market | Quoted sides | Model route | Actual card status |",
        "| --- | ---: | --- | --- |",
    ]
    for market, resolution in sorted(catalog.items()):
        n = counts.get(market, 0)
        route = ("RESEARCH_UNVALIDATED" if resolution["state"] == PRICED_PATH
                 else f"BLOCKED:{resolution['blocker']}")
        status = ("NO_QUOTE" if not n else
                  "QUOTED_RESEARCH_ONLY" if resolution["state"] == PRICED_PATH else
                  f"QUOTED_MODEL_BLOCKED:{resolution['blocker']}")
        lines.append(f"| {_md(market)} | {n} | {_md(route)} | {_md(status)} |")
    for market in unknown:
        lines.append(f"| {_md(market)} | {counts[market]} | UNMAPPED | QUOTED_NO_CATALOG_MODEL |")
    lines += ["", "</details>", ""]
    if unknown:
        lines.append(f"- **Unmapped captured market types ({len(unknown)}):** "
                     + ", ".join(_md(m) for m in unknown) + ". No model price.")
    return "\n".join(lines) + "\n"
