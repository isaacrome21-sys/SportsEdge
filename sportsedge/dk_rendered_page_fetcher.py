"""DraftKings RENDERED-PAGE line fetcher. Source class DRAFTKINGS_RENDERED_PAGE_V1.

SCREEN / NOT_VALIDATED. play_allowed is always False. Research-only: this module
reads public sportsbook pages and never places, stages or submits anything.

Contract
--------
* Only public ``https://sportsbook.draftkings.com`` page URLs may be navigated
  to. Any DK API host or API-shaped path is refused by
  ``assert_rendered_page_url`` before a browser is launched. This module never
  calls a DK API endpoint itself; it renders the page in a headed browser on the box display and
  parses the resulting DOM. (Requests the page's own scripts make while
  rendering are the page's behaviour, not calls made by SportsEdge.)
* ``observed_at_utc`` is the real wall-clock time read immediately after the
  DOM snapshot is taken, truncated to whole seconds. It is never inferred.
* ``page_html_sha256`` is the sha256 of the exact UTF-8 HTML snapshot parsed.
* Missing or unparseable prices/points are explicit refusals; nothing is
  filled in. The board card carries no kickoff time, so ``commence_time`` is
  None with ``commence_time_status`` = NOT_ON_BOARD_CARD. ``book_last_update``
  is None (the page carries no provider quote timestamp).
* Not wired into any workflow and has no schedule.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

SOURCE_CLASS = "DRAFTKINGS_RENDERED_PAGE_V1"
PROVIDER = "DRAFTKINGS_RENDERED_PAGE"
SPORTSBOOK = "draftkings"
ALLOWED_HOST = "sportsbook.draftkings.com"
_API_PATH_TOKENS = ("api", "sportscontent", "eventgroups", "graphql", "odds/v", "v1", "v2", "v3", "v4", "v5")
_MARKETS = {"HC": "spreads", "OU": "totals", "ML": "h2h"}
_BTN = re.compile(r"component-builder-market-button-(\d+)-0([A-Z]{2})")


class DkApiUrlRefused(ValueError):
    """Raised for any URL that is not a public rendered sportsbook page."""


def assert_rendered_page_url(url: str) -> str:
    parts = urlsplit(str(url))
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise DkApiUrlRefused("SCHEME_NOT_HTTPS")
    if host != ALLOWED_HOST or parts.username or parts.password or parts.port not in (None, 443):
        raise DkApiUrlRefused("HOST_NOT_RENDERED_SPORTSBOOK_PAGE")
    full = unquote(unquote(parts.path + "?" + parts.query)).lower()
    segs = [s for s in re.split(r"[/?&=]", full) if s]
    if any(tok in segs for tok in _API_PATH_TOKENS) or "/api" in full or "sportscontent" in full:
        raise DkApiUrlRefused("API_PATH")
    return url


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _price(text: str | None) -> tuple[int | None, str | None]:
    if text is None or not text.strip():
        return None, "PRICE_MISSING"
    t = text.strip().replace("\u2212", "-").replace("\u2013", "-")
    if t.upper() == "EVEN":
        return 100, None
    if re.fullmatch(r"[+-]\d{3,5}", t):
        v = int(t)
        if abs(v) >= 100:
            return v, None
    return None, "PRICE_UNPARSEABLE"


def _point(text: str | None) -> tuple[float | None, str | None]:
    if text is None or not text.strip():
        return None, "POINT_MISSING"
    t = text.strip().replace("\u2212", "-").replace("\u00bd", ".5")
    if t.lower() in {"pk", "pick", "pick'em"}:
        return 0.0, None
    try:
        return float(t), None
    except ValueError:
        return None, "POINT_UNPARSEABLE"


def parse_rendered_board(html: str, *, page_url: str, observed_at: datetime | None,
                         sport_key: str = "americanfootball_nfl") -> dict[str, Any]:
    import hashlib
    from bs4 import BeautifulSoup

    if observed_at is None or observed_at.tzinfo is None:
        raise ValueError("observed_at must be a real tz-aware fetch time")
    obs = _iso_z(observed_at)
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select('[data-testid="market-mapping-template-210"]')
    rows: list[dict[str, Any]] = []
    card_refusals: list[dict[str, Any]] = []
    for ci, card in enumerate(cards):
        teams: list[str] = []
        for a in card.select('a[data-testid="lp-nav-link"]'):
            sp = a.find_all("span")
            name = sp[-1].get_text(strip=True) if sp else ""
            if name and (not teams or teams[-1] != name):
                teams.append(name)
        buttons = card.select('button[data-testid^="component-builder-market-button-"]')
        if not teams and not buttons:
            continue  # layout wrapper with no market content
        if len(teams) != 2:
            card_refusals.append({"refusal": "TEAMS_NOT_FOUND", "card_index": ci})
            continue
        away, home = teams
        n = len(buttons)
        for bi, b in enumerate(buttons):
            m = _BTN.match(b.get("data-testid", ""))
            event_id = m.group(1) if m else None
            market = _MARKETS.get(m.group(2)) if m else None
            title = b.select_one('[data-testid="button-title-market-board"]')
            pts = b.select_one('[data-testid="button-points-market-board"]')
            odds = b.select_one('[data-testid="button-odds-market-board"]')
            title_t = title.get_text(strip=True) if title else ""
            side_team = away if bi < n / 2 else home
            if market == "totals":
                outcome = {"O": "Over", "U": "Under"}.get(title_t.upper())
            else:
                outcome = side_team
            row: dict[str, Any] = {
                "provider": PROVIDER, "sportsbook": SPORTSBOOK, "sport_key": sport_key,
                "source_class": SOURCE_CLASS, "provider_event_id": event_id,
                "home_team": home, "away_team": away, "commence_time": None,
                "commence_time_status": "NOT_ON_BOARD_CARD", "market": market,
                "outcome": outcome, "selection": outcome, "point": None, "price_american": None,
                "source_uri": page_url, "observed_at_utc": obs, "book_last_update": None,
                "status": "OK", "refusal": None,
            }
            refusal = None
            if market is None:
                refusal = "UNKNOWN_MARKET_CODE"
            elif outcome is None:
                refusal = "OUTCOME_UNRESOLVED"
            else:
                price, refusal = _price(odds.get_text() if odds else None)
                row["price_american"] = price
                if market != "h2h":
                    point, prefusal = _point(pts.get_text() if pts else None)
                    row["point"] = point
                    refusal = refusal or prefusal
            if refusal:
                row["status"], row["refusal"] = "REFUSED", refusal
                if refusal.startswith("PRICE"):
                    row["price_american"] = None
            rows.append(row)
    return {
        "source_class": SOURCE_CLASS, "provider": PROVIDER, "sportsbook": SPORTSBOOK,
        "sport_key": sport_key, "source_uri": page_url, "observed_at_utc": obs,
        "page_html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "status_label": "SCREEN", "validation": "NOT_VALIDATED", "play_allowed": False,
        "page_status": "OK" if cards else "REFUSED_NO_MARKET_CARDS",
        "rows": rows, "card_refusals": card_refusals,
    }


class HeadedDisplayUnavailable(RuntimeError):
    """No X display: headed rendering is impossible, and headless is not used."""


def _render_with_browser(url: str, *, timeout_ms: int = 60000, settle_ms: int = 30000,
                         executable_path: str | None = None) -> str:
    """Render in a normal HEADED Chrome on $DISPLAY with the browser's stock identity.

    Ruling 2026-10-23: the fetcher never sets or overrides the browser's
    identity string and never runs headless to work around DK's handling of
    headless browsers. If headed rendering shows no odds, the result is a
    REFUSED_NO_MARKET_CARDS page, not a workaround.
    """
    import os

    if not os.environ.get("DISPLAY"):
        raise HeadedDisplayUnavailable("DISPLAY_NOT_SET")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        kw: dict[str, Any] = {"headless": False}
        executable_path = executable_path or os.environ.get("SPORTSEDGE_BROWSER_PATH")
        if executable_path:
            kw["executable_path"] = executable_path
        browser = p.chromium.launch(**kw)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_selector('[data-testid="button-odds-market-board"]', timeout=settle_ms)
            except Exception:
                pass  # parse whatever rendered; an empty board becomes a refusal
            return page.content()
        finally:
            browser.close()


def fetch_rendered_board(url: str, *, sport_key: str = "americanfootball_nfl", **render_kw: Any) -> dict[str, Any]:
    assert_rendered_page_url(url)
    html = _render_with_browser(url, **render_kw)
    observed = _utcnow()  # real time, read right after the DOM snapshot
    return parse_rendered_board(html, page_url=url, observed_at=observed, sport_key=sport_key)
