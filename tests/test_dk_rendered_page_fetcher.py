"""Offline tests for the DraftKings rendered-page fetcher (SCREEN / NOT_VALIDATED).

The fixture is a real excerpt of the rendered NFL board DOM captured
2026-10-23T15:45:07Z with class/style/img attributes stripped, plus synthetic
edge-case cards built inline below (clearly synthetic, used only for refusals).
"""
from __future__ import annotations

import hashlib
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sportsedge import dk_rendered_page_fetcher as f

FIX = Path(__file__).parent / "fixtures" / "dk_rendered" / "nfl_board_excerpt_20261023.html"
T = datetime(2026, 10, 23, 15, 45, 7, 654321, tzinfo=timezone.utc)
URL = "https://sportsbook.draftkings.com/leagues/football/nfl"


def _parse(html: str):
    return f.parse_rendered_board(html, page_url=URL, observed_at=T)


# ---- URL guard -------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues/88808",
    "https://sportsbook.draftkings.com/api/odds/v1/x",
    "https://sportsbook.draftkings.com/sites/US-SB/api/v5/eventgroups/88808",
    "https://api.draftkings.com/lineups/v1",
    "https://sportsbook-us-nj.draftkings.com/leagues/football/nfl",
    "http://sportsbook.draftkings.com/leagues/football/nfl",
    "https://sportsbook.draftkings.com.evil.example/leagues/football/nfl",
    "https://sportsbook.draftkings.com/leagues/football/nfl?x=/api/",
    "https://SPORTSBOOK.draftkings.com/%61pi/v1",
    "https://sportsbook.draftkings.com/sportscontent/dkusnj/v1",
    "https://user@sportsbook.draftkings.com/leagues/football/nfl",
    "https://sportsbook.draftkings.com:8443/leagues/football/nfl",
])
def test_guard_refuses_api_and_non_page_urls(bad):
    with pytest.raises(f.DkApiUrlRefused):
        f.assert_rendered_page_url(bad)


def test_guard_allows_public_league_page():
    assert f.assert_rendered_page_url(URL) == URL


def test_fetch_refuses_api_url_before_any_browser(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("browser must not launch")
    monkeypatch.setattr(f, "_render_with_browser", boom)
    with pytest.raises(f.DkApiUrlRefused):
        f.fetch_rendered_board("https://sportsbook-nash.draftkings.com/api/sportscontent/x")


def test_module_source_has_no_api_root():
    src = Path(f.__file__).read_text()
    assert "draftkings_game_market_source" not in src
    for forbidden in ("urlopen", "import requests", "httpx", "DK_ROOT"):
        assert forbidden not in src


# ---- parser ----------------------------------------------------------------
def test_parser_real_excerpt_schema_and_values():
    html = FIX.read_text()
    out = _parse(html)
    assert out["page_html_sha256"] == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert out["observed_at_utc"] == "2026-10-23T15:45:07Z"
    assert out["source_uri"] == URL
    assert out["source_class"] == "DRAFTKINGS_RENDERED_PAGE_V1"
    assert out["status_label"] == "SCREEN" and out["play_allowed"] is False
    rows = out["rows"]
    pit = [r for r in rows if r["provider_event_id"] == "34118009"]
    assert len(pit) == 6
    key = {(r["market"], r["outcome"]): r for r in pit}
    assert key[("spreads", "PIT Steelers")]["point"] == -3.0
    assert key[("spreads", "PIT Steelers")]["price_american"] == -118
    assert key[("spreads", "NO Saints")]["point"] == 3.0
    assert key[("spreads", "NO Saints")]["price_american"] == -102
    assert key[("totals", "Over")]["point"] == 44.5
    assert key[("totals", "Under")]["price_american"] == -110
    assert key[("h2h", "PIT Steelers")]["price_american"] == -175
    assert key[("h2h", "NO Saints")]["price_american"] == 145
    for r in pit:
        assert r["away_team"] == "PIT Steelers" and r["home_team"] == "NO Saints"
        assert r["status"] == "OK"
        assert r["observed_at_utc"] == "2026-10-23T15:45:07Z"
        assert r["source_uri"] == URL
        assert r["commence_time"] is None and r["commence_time_status"] == "NOT_ON_BOARD_CARD"
        assert r["book_last_update"] is None
        for k in ("provider", "sportsbook", "sport_key", "provider_event_id", "home_team",
                  "away_team", "market", "outcome", "point", "price_american", "selection"):
            assert k in r
    assert len(rows) % 6 == 0 or any(r["status"] != "OK" for r in rows)


def _card(buttons: str) -> str:
    teams = ('<a data-testid="lp-nav-link" href="/event/a-%40-b/999"><span>AWAY Team</span></a>'
             '<a data-testid="lp-nav-link" href="/event/a-%40-b/999"><span>HOME Team</span></a>')
    return f'<html><body><div data-testid="market-mapping-template-210">{teams}{buttons}</div></body></html>'


def _btn(code, title="", pts="", odds=None):
    t = f'<span data-testid="button-title-market-board">{title}</span>' if title else ""
    p = f'<span data-testid="button-points-market-board">{pts}</span>' if pts else ""
    o = f'<span data-testid="button-odds-market-board">{odds}</span>' if odds is not None else ""
    return f'<button data-testid="component-builder-market-button-999-{code}">{t}{p}{o}</button>'


def test_missing_price_is_refusal_not_filled():
    html = _card(_btn("0HC1N300_3", pts="-3") + _btn("0HC1P300_1", pts="+3", odds="−110"))
    rows = _parse(html)["rows"]
    away = [r for r in rows if r["outcome"] == "AWAY Team"][0]
    assert away["status"] == "REFUSED" and away["refusal"] == "PRICE_MISSING"
    assert away["price_american"] is None
    home = [r for r in rows if r["outcome"] == "HOME Team"][0]
    assert home["status"] == "OK" and home["price_american"] == -110


def test_unparseable_price_and_missing_point_are_refusals():
    html = _card(_btn("0HC1N300_3", pts="-3", odds="EVENS?") + _btn("0HC1P300_1", odds="+100"))
    rows = {r["outcome"]: r for r in _parse(html)["rows"]}
    assert rows["AWAY Team"]["refusal"] == "PRICE_UNPARSEABLE" and rows["AWAY Team"]["price_american"] is None
    assert rows["HOME Team"]["refusal"] == "POINT_MISSING" and rows["HOME Team"]["point"] is None


def test_even_price_text_parsed_only_when_explicit():
    html = _card(_btn("0ML1_3", odds="EVEN") + _btn("0ML1_1", odds="+100"))
    rows = {r["outcome"]: r for r in _parse(html)["rows"]}
    assert rows["AWAY Team"]["price_american"] == 100 and rows["HOME Team"]["price_american"] == 100


def test_unknown_market_code_refused():
    rows = _parse(_card(_btn("0ZZ1_3", odds="+100") + _btn("0ZZ1_1", odds="+100")))["rows"]
    assert rows and all(r["status"] == "REFUSED" and r["refusal"] == "UNKNOWN_MARKET_CODE" for r in rows)


def test_card_without_two_teams_refused():
    html = '<html><body><div data-testid="market-mapping-template-210">' + _btn("0ML1_3", odds="+100") + "</div></body></html>"
    out = _parse(html)
    assert out["rows"] == [] and out["card_refusals"] == [{"refusal": "TEAMS_NOT_FOUND", "card_index": 0}]


def test_empty_page_is_refusal():
    out = _parse("<html><body>blocked</body></html>")
    assert out["rows"] == [] and out["page_status"] == "REFUSED_NO_MARKET_CARDS"


def test_observed_at_required_and_tz_aware():
    with pytest.raises(ValueError):
        f.parse_rendered_board("<html></html>", page_url=URL, observed_at=None)
    with pytest.raises(ValueError):
        f.parse_rendered_board("<html></html>", page_url=URL, observed_at=datetime(2026, 1, 1))


def test_parser_offline_no_network(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    assert _parse(FIX.read_text())["rows"]


def test_fetch_uses_real_clock_after_render(monkeypatch):
    calls = []
    monkeypatch.setattr(f, "_render_with_browser", lambda url, **k: calls.append(url) or FIX.read_text())
    monkeypatch.setattr(f, "_utcnow", lambda: T)
    out = f.fetch_rendered_board(URL)
    assert calls == [URL] and out["observed_at_utc"] == "2026-10-23T15:45:07Z"


@pytest.mark.skipif(os.environ.get("SPORTSEDGE_LIVE_FETCH") != "1", reason="live smoke only with SPORTSEDGE_LIVE_FETCH=1")
def test_live_smoke_nfl_game_lines():
    out = f.fetch_rendered_board(URL)
    assert out["source_uri"] == URL and len(out["page_html_sha256"]) == 64
    assert out["observed_at_utc"].endswith("Z")
    assert out["rows"], out["page_status"]
