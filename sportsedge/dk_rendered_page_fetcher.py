"""DraftKings RENDERED-PAGE line fetcher. Source class DRAFTKINGS_RENDERED_PAGE_V1.

SCREEN / NOT_VALIDATED. play_allowed is always False. Research-only: this module
reads public sportsbook pages and never places, stages or submits anything.

Contract
--------
* Only explicitly allowlisted public page paths on
  ``https://sportsbook.draftkings.com`` may be navigated to. DK API hosts,
  API-shaped paths, ``format=`` queries and ``.json`` paths are refused before
  a browser launches, and the browser's final URL is re-checked after load and
  recorded as ``final_url``. This module never calls a DK API endpoint itself;
  requests the page's own scripts make while rendering are the page's behaviour.
* The browser is a normal HEADED Chrome on $DISPLAY with its stock identity;
  the browser identity string is never set or overridden. Only known Chrome binary paths are
  allowed; the path and browser version are recorded with each fetch.
* ``observed_at_utc`` is the real wall-clock time read immediately after the
  DOM snapshot (``page.content()``), truncated to whole seconds.
* ``page_html_sha256`` is the sha256 of the exact UTF-8 HTML snapshot parsed.
* Team assignment comes from each market's own pair: every market on a game
  card must have exactly two buttons (same DK market id). The DOM position in
  the pair (first = away row), the button-ID side suffix (_3 = away, _1 = home;
  totals Over = _1, Under = _3) and, for spreads/totals, the ID-encoded line
  (N300 = -3, P300 = +3, O4450 = 44.5) must all agree with the parsed button;
  any mismatch or unknown suffix is refused (SIDE_SUFFIX_MISMATCH,
  SIDE_SUFFIX_UNKNOWN, LINE_ID_MISMATCH, TOTAL_SIDE_ID_MISMATCH). A card where
  any market lacks exactly two sides is refused whole.
* Page URLs carry no query string, fragment or ``;`` path parameters.
* The browser path is resolved with realpath before the allowlist check.
* Lines must be finite multiples of 0.5; prices must be integer American odds
  with 100 <= |price| <= 50000. Anything else is an explicit refusal. A row
  refused for its line carries no price. Nothing is filled in.
* ``rows`` holds only OK, two-sided pairs; refused sides are in
  ``refused_rows``. Team names come from the ``cb-market__label-inner`` span
  when present (never the pitcher sub-label); a card showing a live score is
  refused whole (LIVE_IN_PROGRESS_CARD). The board card carries no kickoff time, so
  ``commence_time`` is None (``NOT_ON_BOARD_CARD``); ``book_last_update`` is None.
* ``to_capture_markets`` adapts rows to the market shape consumed by
  ``scripts/nfl_2026_line_capture.py`` ``spread_row`` / ``total_row``.
* Not wired into any workflow and has no schedule.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

SOURCE_CLASS = "DRAFTKINGS_RENDERED_PAGE_V1"
PROVIDER = "DRAFTKINGS_RENDERED_PAGE"
SPORTSBOOK = "draftkings"
ALLOWED_HOST = "sportsbook.draftkings.com"
ALLOWED_PATH_PREFIXES = ("/leagues/",)
ALLOWED_BROWSER_PATHS = ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/opt/google/chrome/chrome")
# Symlinks are resolved first; the resolved file must be one of these real Chrome files.
ALLOWED_BROWSER_REALPATHS = ("/opt/google/chrome/google-chrome", "/opt/google/chrome/chrome")
DEFAULT_BROWSER_PATH = "/usr/bin/google-chrome"
_API_PATH_TOKENS = ("api", "sportscontent", "eventgroups", "graphql", "v1", "v2", "v3", "v4", "v5")
_MARKETS = {"HC": "spreads", "OU": "totals", "ML": "h2h"}
_BTN = re.compile(r"component-builder-market-button-(\d+)-0([A-Z]{2})(\d+)(?:([NPOU])(\d+))?_(\d+)$")
# Button-ID side suffix: _3 = away (first team row), _1 = home. Totals: Over = _1, Under = _3.
_SIDE_SUFFIX = {"away": "3", "home": "1", "Over": "1", "Under": "3"}
MAX_ABS_PRICE = 50000
MAX_ABS_POINT = 200.0


class DkApiUrlRefused(ValueError):
    """Raised for any URL that is not an allowlisted public rendered page."""


class HeadedDisplayUnavailable(RuntimeError):
    """No X display: headed rendering is impossible, and headless is not used."""


class BrowserBinaryRefused(RuntimeError):
    """Browser binary is not a known Chrome path."""


def assert_rendered_page_url(url: str) -> str:
    parts = urlsplit(str(url))
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise DkApiUrlRefused("SCHEME_NOT_HTTPS")
    if host != ALLOWED_HOST or parts.username or parts.password or parts.port not in (None, 443):
        raise DkApiUrlRefused("HOST_NOT_RENDERED_SPORTSBOOK_PAGE")
    path = unquote(unquote(parts.path)).lower()
    query = unquote(unquote(parts.query)).lower()
    full = path + "?" + query
    segs = [s for s in re.split(r"[/?&=]", full) if s]
    if any(t in segs for t in _API_PATH_TOKENS) or "/api" in full or "sportscontent" in full:
        raise DkApiUrlRefused("API_PATH")
    if parts.query or parts.fragment or "?" in str(url) or "#" in str(url):
        raise DkApiUrlRefused("QUERY_OR_FRAGMENT_NOT_ALLOWED")
    if ".json" in full or ";" in path or "format" in path or "fmt" in path:
        raise DkApiUrlRefused("DATA_FORMAT_REQUEST")
    if not any(path.startswith(p) for p in ALLOWED_PATH_PREFIXES) or ".." in path:
        raise DkApiUrlRefused("PATH_NOT_ALLOWLISTED")
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
        if 100 <= abs(v) <= MAX_ABS_PRICE:
            return v, None
    return None, "PRICE_UNPARSEABLE_OR_OUT_OF_RANGE"


def _point(text: str | None) -> tuple[float | None, str | None]:
    if text is None or not text.strip():
        return None, "POINT_MISSING"
    t = text.strip().replace("\u2212", "-").replace("\u00bd", ".5")
    if t.lower() in {"pk", "pick", "pick'em"}:
        return 0.0, None
    if not re.fullmatch(r"[+-]?\d{1,3}(\.\d+)?", t):
        return None, "POINT_UNPARSEABLE"
    v = float(t)
    if not math.isfinite(v) or abs(v) > MAX_ABS_POINT or (v * 2) != int(v * 2):
        return None, "POINT_NOT_HALF_STEP"
    return v, None


def _id_consistency(m, market: str, outcome: str, position_side: str, point: float | None) -> str | None:
    """The DOM position, the button-ID side suffix and the ID-encoded line must all agree."""
    suffix, letter, digits = m.group(6), m.group(4), m.group(5)
    if suffix not in ("1", "3"):
        return "SIDE_SUFFIX_UNKNOWN"
    if market == "totals":
        if suffix != _SIDE_SUFFIX[outcome] or letter != outcome[0]:
            return "TOTAL_SIDE_ID_MISMATCH"
        if digits is None or point is None or int(digits) != round(point * 100):
            return "LINE_ID_MISMATCH"
        return None
    if suffix != _SIDE_SUFFIX[position_side]:
        return "SIDE_SUFFIX_MISMATCH"
    if market == "spreads":
        if letter not in ("N", "P") or digits is None or point is None:
            return "LINE_ID_MISMATCH"
        if int(digits) != round(abs(point) * 100) or (point != 0 and (letter == "N") != (point < 0)):
            return "LINE_ID_MISMATCH"
    elif letter is not None:
        return "LINE_ID_MISMATCH"
    return None


def _teams(card) -> list[str]:
    teams: list[str] = []
    for a in card.select('a[data-testid="lp-nav-link"]'):
        inner = a.select_one("span.cb-market__label-inner")
        if inner is not None:
            # The team label; sub-labels (MLB probable pitcher) and scores are other spans.
            name = inner.get_text(strip=True)
        else:
            sp = a.find_all("span")
            name = sp[-1].get_text(strip=True) if sp else ""
        if name and (not teams or teams[-1] != name):
            teams.append(name)
    return teams


def parse_rendered_board(html: str, *, page_url: str, observed_at: datetime | None,
                         sport_key: str = "americanfootball_nfl", final_url: str | None = None,
                         browser: dict[str, Any] | None = None) -> dict[str, Any]:
    import hashlib
    from bs4 import BeautifulSoup

    if observed_at is None or observed_at.tzinfo is None:
        raise ValueError("observed_at must be a real tz-aware fetch time")
    obs = _iso_z(observed_at)
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select('[data-testid="market-mapping-template-210"]')
    rows: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    card_refusals: list[dict[str, Any]] = []
    for ci, card in enumerate(cards):
        teams = _teams(card)
        buttons = card.select('button[data-testid^="component-builder-market-button-"]')
        if not teams and not buttons:
            continue  # layout wrapper with no market content
        if len(teams) != 2:
            card_refusals.append({"refusal": "TEAMS_NOT_FOUND", "card_index": ci})
            continue
        if card.select_one(".cb-market__scoreboard-team-score") is not None:
            # In-play card: live prices are not pregame screen inputs.
            card_refusals.append({"refusal": "LIVE_IN_PROGRESS_CARD", "card_index": ci})
            continue
        away, home = teams
        pairs: dict[tuple[str, str, str], list] = {}
        bad = None
        for b in buttons:
            m = _BTN.match(b.get("data-testid", ""))
            if not m or m.group(2) not in _MARKETS:
                bad = "UNKNOWN_MARKET_CODE"
                break
            pairs.setdefault((m.group(1), _MARKETS[m.group(2)], m.group(3)), []).append((b, m))
        if bad is None and any(len(v) != 2 for v in pairs.values()):
            bad = "MARKET_NOT_TWO_SIDED"
        if bad is None and len({k[1] for k in pairs}) != len(pairs):
            bad = "DUPLICATE_MARKET"
        if bad:
            card_refusals.append({"refusal": bad, "card_index": ci})
            continue
        for (event_id, market, _mid), pair in pairs.items():
            sides = []
            for idx, (b, m) in enumerate(pair):
                title = b.select_one('[data-testid="button-title-market-board"]')
                pts = b.select_one('[data-testid="button-points-market-board"]')
                odds = b.select_one('[data-testid="button-odds-market-board"]')
                if market == "totals":
                    outcome = {"O": "Over", "U": "Under"}.get((title.get_text(strip=True) if title else "").upper())
                else:
                    outcome = away if idx == 0 else home
                row: dict[str, Any] = {
                    "provider": PROVIDER, "sportsbook": SPORTSBOOK, "sport_key": sport_key,
                    "source_class": SOURCE_CLASS, "provider_event_id": event_id,
                    "home_team": home, "away_team": away, "commence_time": None,
                    "commence_time_status": "NOT_ON_BOARD_CARD", "market": market,
                    "outcome": outcome, "selection": outcome, "point": None, "price_american": None,
                    "source_uri": page_url, "final_url": final_url, "observed_at_utc": obs,
                    "book_last_update": None, "status": "OK", "refusal": None,
                }
                refusal = None
                if outcome is None:
                    refusal = "OUTCOME_UNRESOLVED"
                else:
                    if market != "h2h":
                        row["point"], refusal = _point(pts.get_text() if pts else None)
                    if refusal is None:
                        row["price_american"], refusal = _price(odds.get_text() if odds else None)
                if refusal is None:
                    refusal = _id_consistency(m, market, outcome, "away" if idx == 0 else "home", row["point"])
                if refusal:
                    row.update(status="REFUSED", refusal=refusal, price_american=None,
                               point=row["point"] if refusal.startswith("PRICE") else None)
                sides.append(row)
            pair_refusal = None
            if any(s["status"] != "OK" for s in sides):
                pair_refusal = "PAIR_HAS_REFUSED_SIDE"
            elif market == "totals" and ({s["outcome"] for s in sides} != {"Over", "Under"} or sides[0]["point"] != sides[1]["point"]):
                pair_refusal = "TOTAL_PAIR_INCONSISTENT"
            elif market == "spreads" and sides[0]["point"] != -sides[1]["point"]:
                pair_refusal = "SPREAD_PAIR_INCONSISTENT"
            if pair_refusal:
                for s in sides:
                    if s["status"] == "OK":
                        s.update(status="REFUSED", refusal=pair_refusal)
                refused.extend(sides)
            else:
                rows.extend(sides)
    return {
        "source_class": SOURCE_CLASS, "provider": PROVIDER, "sportsbook": SPORTSBOOK,
        "sport_key": sport_key, "source_uri": page_url, "final_url": final_url,
        "observed_at_utc": obs, "browser": browser,
        "page_html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "status_label": "SCREEN", "validation": "NOT_VALIDATED", "play_allowed": False,
        "page_status": "OK" if cards else "REFUSED_NO_MARKET_CARDS",
        "rows": rows, "refused_rows": refused, "card_refusals": card_refusals,
    }


DK_BOARD_TEAM_FULL_NAMES = {
    "ARI Cardinals": "Arizona Cardinals", "ATL Falcons": "Atlanta Falcons", "BAL Ravens": "Baltimore Ravens",
    "BUF Bills": "Buffalo Bills", "CAR Panthers": "Carolina Panthers", "CHI Bears": "Chicago Bears",
    "CIN Bengals": "Cincinnati Bengals", "CLE Browns": "Cleveland Browns", "DAL Cowboys": "Dallas Cowboys",
    "DEN Broncos": "Denver Broncos", "DET Lions": "Detroit Lions", "GB Packers": "Green Bay Packers",
    "HOU Texans": "Houston Texans", "IND Colts": "Indianapolis Colts", "JAX Jaguars": "Jacksonville Jaguars",
    "KC Chiefs": "Kansas City Chiefs", "LA Chargers": "Los Angeles Chargers", "LA Rams": "Los Angeles Rams",
    "LV Raiders": "Las Vegas Raiders", "MIA Dolphins": "Miami Dolphins", "MIN Vikings": "Minnesota Vikings",
    "NE Patriots": "New England Patriots", "NO Saints": "New Orleans Saints", "NY Giants": "New York Giants",
    "NY Jets": "New York Jets", "PHI Eagles": "Philadelphia Eagles", "PIT Steelers": "Pittsburgh Steelers",
    "SEA Seahawks": "Seattle Seahawks", "SF 49ers": "San Francisco 49ers", "TB Buccaneers": "Tampa Bay Buccaneers",
    "TEN Titans": "Tennessee Titans", "WAS Commanders": "Washington Commanders",
}
EVENT_MATCH_REQUIREMENT = (
    "commence_time is NOT on the DK board card and is carried as None. Before any capture use, each "
    "event must be matched one-to-one to the official schedule by (home_team, away_team) full names; "
    "an unmatched or ambiguous event is refused. No time is inferred.")


def to_capture_markets(output: dict[str, Any]) -> dict[str, Any]:
    """Adapt OK rows to the market shape read by nfl_2026_line_capture spread_row/total_row.

    Team labels are mapped to full names via DK_BOARD_TEAM_FULL_NAMES (the names spread_row is
    called with); an event with an unmapped label is refused, never guessed. ``commence_time`` is
    None and ``event_match_requirement`` states the schedule-matching rule. ``last_update`` is None
    (no provider quote time on the page). Refused rows are never passed on.
    Returns {"events": [...], "refused_events": [...], "event_match_requirement": str}.
    """
    events: dict[str, dict[str, Any]] = {}
    refused: dict[str, dict[str, Any]] = {}
    for r in output["rows"]:
        if r.get("status") != "OK":
            continue
        eid = r["provider_event_id"]
        home = DK_BOARD_TEAM_FULL_NAMES.get(r["home_team"])
        away = DK_BOARD_TEAM_FULL_NAMES.get(r["away_team"])
        if home is None or away is None:
            refused[eid] = {"event_id": eid, "home_team_label": r["home_team"], "away_team_label": r["away_team"],
                            "refusal": "TEAM_NAME_UNMAPPED"}
            continue
        full = {r["home_team"]: home, r["away_team"]: away}
        ev = events.setdefault(eid, {
            "event_id": eid, "home_team": home, "away_team": away,
            "home_team_label": r["home_team"], "away_team_label": r["away_team"],
            "commence_time": None, "commence_time_status": "NOT_ON_BOARD_CARD",
            "event_match_requirement": EVENT_MATCH_REQUIREMENT,
            "observed_at_utc": r["observed_at_utc"], "source_class": SOURCE_CLASS, "markets": {}})
        mk = ev["markets"].setdefault(r["market"], {"key": r["market"], "last_update": None, "outcomes": []})
        out = {"name": full.get(r["outcome"], r["outcome"]), "price": r["price_american"]}
        if r["point"] is not None:
            out["point"] = r["point"]
        mk["outcomes"].append(out)
    return {"events": list(events.values()), "refused_events": list(refused.values()),
            "event_match_requirement": EVENT_MATCH_REQUIREMENT}


def _browser_path(explicit: str | None) -> str:
    path = explicit or os.environ.get("SPORTSEDGE_BROWSER_PATH") or DEFAULT_BROWSER_PATH
    if path not in ALLOWED_BROWSER_PATHS:
        raise BrowserBinaryRefused("BROWSER_PATH_NOT_ALLOWLISTED")
    if os.path.realpath(path) not in ALLOWED_BROWSER_REALPATHS:
        raise BrowserBinaryRefused("BROWSER_REALPATH_NOT_ALLOWLISTED")
    return path


def _render_with_browser(url: str, *, timeout_ms: int = 60000, settle_ms: int = 30000,
                         executable_path: str | None = None,
                         clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Render in a normal HEADED Chrome on $DISPLAY with the browser's stock identity."""
    clock = clock or _utcnow
    if not os.environ.get("DISPLAY"):
        raise HeadedDisplayUnavailable("DISPLAY_NOT_SET")
    path = _browser_path(executable_path)
    real = os.path.realpath(path)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, executable_path=path)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_selector('[data-testid="button-odds-market-board"]', timeout=settle_ms)
            except Exception:
                pass  # parse whatever rendered; an empty board becomes a refusal
            html = page.content()
            observed = clock()  # immediately after the DOM snapshot
            final_url = page.url
            version = browser.version
        finally:
            browser.close()
    try:
        assert_rendered_page_url(final_url)
    except DkApiUrlRefused as exc:
        raise DkApiUrlRefused("FINAL_URL_" + str(exc)) from None
    return {"html": html, "observed_at": observed, "final_url": final_url,
            "browser": {"path": path, "realpath": real, "version": version, "headless": False}}


def fetch_rendered_board(url: str, *, sport_key: str = "americanfootball_nfl", **render_kw: Any) -> dict[str, Any]:
    assert_rendered_page_url(url)
    r = _render_with_browser(url, **render_kw)
    return parse_rendered_board(r["html"], page_url=url, observed_at=r["observed_at"], sport_key=sport_key,
                                final_url=r["final_url"], browser=r["browser"])
