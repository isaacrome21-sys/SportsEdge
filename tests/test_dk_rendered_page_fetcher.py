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


def _all(out):
    return out["rows"] + out["refused_rows"]


def test_missing_price_is_refusal_not_filled():
    out = _parse(_card(_btn("0HC1N300_3", pts="-3") + _btn("0HC1P300_1", pts="+3", odds="−110")))
    assert out["rows"] == []
    by = {r["outcome"]: r for r in out["refused_rows"]}
    assert by["AWAY Team"]["refusal"] == "PRICE_MISSING" and by["AWAY Team"]["price_american"] is None
    assert by["HOME Team"]["refusal"] == "PAIR_HAS_REFUSED_SIDE"


def test_unparseable_price_and_missing_point_are_refusals():
    out = _parse(_card(_btn("0HC1N300_3", pts="-3", odds="EVENS?") + _btn("0HC1P300_1", odds="+100")))
    by = {r["outcome"]: r for r in out["refused_rows"]}
    assert by["AWAY Team"]["refusal"] == "PRICE_UNPARSEABLE_OR_OUT_OF_RANGE" and by["AWAY Team"]["price_american"] is None
    assert by["HOME Team"]["refusal"] == "POINT_MISSING" and by["HOME Team"]["point"] is None
    assert out["rows"] == []


def test_even_price_text_parsed_only_when_explicit():
    rows = {r["outcome"]: r for r in _parse(_card(_btn("0ML1_3", odds="EVEN") + _btn("0ML1_1", odds="+100")))["rows"]}
    assert rows["AWAY Team"]["price_american"] == 100 and rows["HOME Team"]["price_american"] == 100


def test_unknown_market_code_refused():
    out = _parse(_card(_btn("0ZZ1_3", odds="+100") + _btn("0ZZ1_1", odds="+100")))
    assert out["rows"] == [] and out["card_refusals"] == [{"refusal": "UNKNOWN_MARKET_CODE", "card_index": 0}]


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


def test_fetch_passes_render_time_and_final_url(monkeypatch):
    calls = []
    def fake(url, **k):
        calls.append(url)
        return {"html": FIX.read_text(), "observed_at": T, "final_url": URL,
                "browser": {"path": "/usr/bin/google-chrome", "version": "1.0", "headless": False}}
    monkeypatch.setattr(f, "_render_with_browser", fake)
    out = f.fetch_rendered_board(URL)
    assert calls == [URL] and out["observed_at_utc"] == "2026-10-23T15:45:07Z"
    assert out["final_url"] == URL and out["browser"]["path"] == "/usr/bin/google-chrome"


@pytest.mark.skipif(os.environ.get("SPORTSEDGE_LIVE_FETCH") != "1", reason="live smoke only with SPORTSEDGE_LIVE_FETCH=1")
def test_live_smoke_nfl_game_lines():
    out = f.fetch_rendered_board(URL)
    assert out["source_uri"] == URL and len(out["page_html_sha256"]) == 64
    assert out["observed_at_utc"].endswith("Z") and out["final_url"]
    assert out["rows"], out["page_status"]


# ---- headed browser, stock user-agent (ruling 2026-10-23) ------------------
class _FakePage:
    def __init__(self, log, final_url=None):
        self.log = log
        self.url = final_url
    def goto(self, url, **k):
        self.log.append(("goto", url))
        self.url = self.url or url
    def wait_for_selector(self, *a, **k): pass
    def evaluate(self, *a, **k): self.log.append(("evaluate", a)); return "x"
    def content(self):
        self.log.append(("content", None))
        return "<html></html>"


class _FakeBrowser:
    version = "130.0.0.0"
    def __init__(self, log, final_url=None):
        self.log = log
        self.final_url = final_url
    def new_page(self, **k): self.log.append(("new_page", k)); return _FakePage(self.log, self.final_url)
    def new_context(self, **k): self.log.append(("new_context", k)); return self
    def close(self): self.log.append(("close", None))


class _FakePW:
    def __init__(self, log, final_url=None):
        self.log = log
        self.final_url = final_url
        self.chromium = self
    def launch(self, **k): self.log.append(("launch", k)); return _FakeBrowser(self.log, self.final_url)
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _install_fake_pw(monkeypatch, log, final_url=None):
    import sys, types
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _FakePW(log, final_url)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)


def test_browser_is_headed_and_never_sets_user_agent(monkeypatch):
    log = []
    _install_fake_pw(monkeypatch, log)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("SPORTSEDGE_BROWSER_PATH", raising=False)
    f._render_with_browser(URL)
    launch = [k for n, k in log if n == "launch"]
    assert launch and launch[0].get("headless") is False
    for name, kw in log:
        if name in ("new_page", "new_context", "launch"):
            assert "user_agent" not in kw and "userAgent" not in kw
            assert not any("user-agent" in str(a).lower() for a in kw.get("args", []))
    assert not any(n == "evaluate" for n, _ in log)
    assert ("goto", URL) in log


def test_headed_render_refused_without_display(monkeypatch):
    log = []
    _install_fake_pw(monkeypatch, log)
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(f.HeadedDisplayUnavailable):
        f._render_with_browser(URL)
    assert log == []


def test_module_source_never_touches_user_agent():
    src = Path(f.__file__).read_text().lower()
    for token in ("user_agent", "useragent", "user-agent", "headlesschrome"):
        assert token not in src


def test_playwright_only_in_research_requirements():
    root = Path(__file__).resolve().parents[1]
    research = (root / "requirements-research.txt").read_text().lower()
    assert any(l.strip().startswith("playwright") for l in research.splitlines())
    for main in ("requirements.txt", "requirements-test.txt"):
        p = root / main
        if p.exists():
            assert "playwright" not in p.read_text().lower()


# ---- auditor findings on 564edbb9 (one test per finding) -------------------
def test_finding1_team_from_market_pair_not_button_position():
    # Auditor repro: HC A -3, OU O 45, HC B +3, OU U 45, ML B +130 (5 buttons).
    html = _card(_btn("0HC7N300_3", pts="-3", odds="-110") + _btn("0OU7O4500_1", title="O", pts="45", odds="-110")
                 + _btn("0HC7P300_1", pts="+3", odds="-110") + _btn("0OU7U4500_3", title="U", pts="45", odds="-110")
                 + _btn("0ML7_1", odds="+130"))
    out = _parse(html)
    assert out["rows"] == [] and out["card_refusals"] == [{"refusal": "MARKET_NOT_TWO_SIDED", "card_index": 0}]
    # Same card with the ML pair completed: spreads must split A/B by the market's own pair.
    html2 = html.replace(_btn("0ML7_1", odds="+130"), _btn("0ML7_3", odds="-150") + _btn("0ML7_1", odds="+130"))
    rows = _parse(html2)["rows"]
    sp = {r["outcome"]: r["point"] for r in rows if r["market"] == "spreads"}
    assert sp == {"AWAY Team": -3.0, "HOME Team": 3.0}


@pytest.mark.parametrize("bad", [
    "https://sportsbook.draftkings.com/leagues/football/nfl?format=json",
    "https://sportsbook.draftkings.com/leagues/football/nfl.json",
    "https://sportsbook.draftkings.com/static/board.json",
    "https://sportsbook.draftkings.com/",
    "https://sportsbook.draftkings.com/event/x/1",
    "https://sportsbook.draftkings.com/leagues/../api/x",
])
def test_finding2_guard_allowlist_and_final_url(bad, monkeypatch):
    with pytest.raises(f.DkApiUrlRefused):
        f.assert_rendered_page_url(bad)
    log = []
    _install_fake_pw(monkeypatch, log, final_url="https://sportsbook-nash.draftkings.com/api/sportscontent/x")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("SPORTSEDGE_BROWSER_PATH", raising=False)
    with pytest.raises(f.DkApiUrlRefused):
        f._render_with_browser(URL)
    log2 = []
    _install_fake_pw(monkeypatch, log2)
    assert f._render_with_browser(URL)["final_url"] == URL


def _capture_module():
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_nfl_cap_for_test", root / "scripts" / "nfl_2026_line_capture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_finding3_adapter_runs_through_real_capture_consumer():
    cap = _capture_module()
    html = FIX.read_text().replace("</body>", _card(_btn("0HC9N300_3", pts="-3") + _btn("0HC9P300_1", pts="+3", odds="-110"))
                                   .replace("<html><body>", "").replace("</body></html>", "") + "</body>")
    out = _parse(html)
    assert all(r["status"] == "OK" for r in out["rows"])
    assert out["refused_rows"] and all(r["status"] == "REFUSED" for r in out["refused_rows"])
    events = f.to_capture_markets(out)["events"]
    assert {e["event_id"] for e in events} == {r["provider_event_id"] for r in out["rows"]}
    assert "999" not in {e["event_id"] for e in events}
    for e in events:
        s = cap.spread_row(e["markets"].get("spreads"), e["home_team"], e["away_team"])
        t = cap.total_row(e["markets"].get("totals"))
        assert s["status"] == "OK" and t["status"] == "OK"
        assert s["market_last_update"] is None and t["market_last_update"] is None
    pit = next(e for e in events if e["event_id"] == "34118009")
    s = cap.spread_row(pit["markets"]["spreads"], pit["home_team"], pit["away_team"])
    assert (s["away_point"], s["away_price"], s["home_point"], s["home_price"]) == (-3.0, -118, 3.0, -102)
    assert pit["home_team"] == "New Orleans Saints" and pit["away_team"] == "Pittsburgh Steelers"
    # a side refused for a missing line drops its price
    o2 = _parse(_card(_btn("0HC1N300_3", odds="-110") + _btn("0HC1P300_1", pts="+3", odds="-110")))
    miss = [r for r in o2["refused_rows"] if r["refusal"] == "POINT_MISSING"][0]
    assert miss["price_american"] is None and miss["point"] is None


@pytest.mark.parametrize("pts,odds,reason", [
    ("-3.25", "-110", "POINT_NOT_HALF_STEP"), ("-3.3", "-110", "POINT_NOT_HALF_STEP"),
    ("nan", "-110", "POINT_UNPARSEABLE"), ("inf", "-110", "POINT_UNPARSEABLE"), ("-1e3", "-110", "POINT_UNPARSEABLE"),
    ("-3", "-99", "PRICE_UNPARSEABLE_OR_OUT_OF_RANGE"), ("-3", "+99999", "PRICE_UNPARSEABLE_OR_OUT_OF_RANGE"),
    ("-3", "+050", "PRICE_UNPARSEABLE_OR_OUT_OF_RANGE"),
])
def test_finding4_line_step_and_price_range(pts, odds, reason):
    out = _parse(_card(_btn("0HC1N300_3", pts=pts, odds=odds) + _btn("0HC1P300_1", pts="+3", odds="-110")))
    away = next(r for r in out["refused_rows"] if r["outcome"] == "AWAY Team")
    assert away["refusal"] == reason and away["price_american"] is None
    assert out["rows"] == []


def test_finding5_observed_at_taken_right_after_snapshot(monkeypatch):
    log = []
    _install_fake_pw(monkeypatch, log)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("SPORTSEDGE_BROWSER_PATH", raising=False)
    def clock():
        log.append(("clock", None))
        return T
    r = f._render_with_browser(URL, clock=clock)
    names = [n for n, _ in log]
    assert names.index("clock") == names.index("content") + 1
    assert names.index("clock") < names.index("close")
    assert r["observed_at"] == T


def test_finding6_browser_binary_allowlist_and_recorded(monkeypatch):
    log = []
    _install_fake_pw(monkeypatch, log)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("SPORTSEDGE_BROWSER_PATH", "/tmp/not-chrome")
    with pytest.raises(f.BrowserBinaryRefused):
        f._render_with_browser(URL)
    assert log == []
    monkeypatch.setenv("SPORTSEDGE_BROWSER_PATH", "/usr/bin/google-chrome")
    r = f._render_with_browser(URL)
    launch = [k for n, k in log if n == "launch"][0]
    assert launch["executable_path"] == "/usr/bin/google-chrome"
    assert r["browser"]["path"] == "/usr/bin/google-chrome" and r["browser"]["version"] == "130.0.0.0"
    assert r["browser"]["headless"] is False


# ---- auditor findings on d77603eb -------------------------------------------
def _real_card_buttons():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(FIX.read_text(), "lxml")
    card = soup.select('[data-testid="market-mapping-template-210"]')[0]
    return card


def test_d776_high_swapped_button_order_refused_not_silently_swapped():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(FIX.read_text(), "lxml")
    card = soup.select('[data-testid="market-mapping-template-210"]')[0]
    btns = card.select('button[data-testid^="component-builder-market-button-"]')
    parent = btns[0].parent
    for b in btns:
        b.extract()
    # swap the two rows: home row buttons first, away row second
    for b in btns[3:] + btns[:3]:
        parent.append(b)
    out = _parse(str(soup))
    kept = [r for r in out["rows"] if r["provider_event_id"] == "34118009"]
    # team-sided markets are refused; totals map from their own O/U title + ID, so they stay correct
    assert {r["market"] for r in kept} <= {"totals"}
    assert {(r["outcome"], r["point"], r["price_american"]) for r in kept} <= {("Over", 44.5, -110), ("Under", 44.5, -110)}
    refused = [r for r in out["refused_rows"] if r["provider_event_id"] == "34118009"]
    assert refused and {r["refusal"] for r in refused} >= {"SIDE_SUFFIX_MISMATCH"}
    # untouched original maps PIT -3/-118 and NO +3/-102
    ok = {(r["market"], r["outcome"]): r for r in _parse(FIX.read_text())["rows"] if r["provider_event_id"] == "34118009"}
    assert ok[("spreads", "PIT Steelers")]["price_american"] == -118 and ok[("spreads", "NO Saints")]["price_american"] == -102


@pytest.mark.parametrize("code_a,pts_a,code_h,pts_h,reason", [
    ("0HC1N300_3", "+3", "0HC1P300_1", "-3", "LINE_ID_MISMATCH"),   # sign in ID contradicts parsed line
    ("0HC1N350_3", "-3", "0HC1P300_1", "+3", "LINE_ID_MISMATCH"),   # magnitude contradicts
    ("0HC1N300_2", "-3", "0HC1P300_1", "+3", "SIDE_SUFFIX_UNKNOWN"),
    ("0HC1N300_1", "-3", "0HC1P300_3", "+3", "SIDE_SUFFIX_MISMATCH"),
])
def test_d776_spread_id_sign_and_suffix_must_match(code_a, pts_a, code_h, pts_h, reason):
    out = _parse(_card(_btn(code_a, pts=pts_a, odds="-110") + _btn(code_h, pts=pts_h, odds="-110")))
    assert out["rows"] == []
    assert reason in {r["refusal"] for r in out["refused_rows"]}


def test_d776_total_id_side_and_line_must_match():
    out = _parse(_card(_btn("0OU1U4500_1", title="O", pts="45", odds="-110") + _btn("0OU1O4500_3", title="U", pts="45", odds="-110")))
    assert out["rows"] == [] and "TOTAL_SIDE_ID_MISMATCH" in {r["refusal"] for r in out["refused_rows"]}
    out = _parse(_card(_btn("0OU1O4450_1", title="O", pts="45", odds="-110") + _btn("0OU1U4450_3", title="U", pts="45", odds="-110")))
    assert out["rows"] == [] and "LINE_ID_MISMATCH" in {r["refusal"] for r in out["refused_rows"]}


@pytest.mark.parametrize("bad", [
    "https://sportsbook.draftkings.com/leagues/football/nfl;format=json",
    "https://sportsbook.draftkings.com/leagues/football/nfl?fmt=json",
    "https://sportsbook.draftkings.com/leagues/football/nfl?output=json",
    "https://sportsbook.draftkings.com/leagues/football/nfl?category=game-lines",
    "https://sportsbook.draftkings.com/leagues/football/nfl#format=json",
    "https://sportsbook.draftkings.com/leagues/football/nfl/format/json",
])
def test_d776_guard_refuses_any_query_and_format_like(bad):
    with pytest.raises(f.DkApiUrlRefused):
        f.assert_rendered_page_url(bad)


def test_d776_browser_symlink_resolved_before_allowlist(monkeypatch, tmp_path):
    log = []
    _install_fake_pw(monkeypatch, log)
    monkeypatch.setenv("DISPLAY", ":99")
    evil = tmp_path / "evil"
    evil.write_text("#!/bin/sh\n")
    import os as _os
    real_rp = _os.path.realpath
    monkeypatch.setattr(_os.path, "realpath", lambda p, *a, **k: str(evil) if p == "/usr/bin/google-chrome" else real_rp(p, *a, **k))
    monkeypatch.setenv("SPORTSEDGE_BROWSER_PATH", "/usr/bin/google-chrome")
    with pytest.raises(f.BrowserBinaryRefused):
        f._render_with_browser(URL)
    assert log == []


def test_d776_adapter_full_names_unmapped_refused_and_commence_none():
    cap = _capture_module()
    html = _card(_btn("0ML1_3", odds="+120") + _btn("0ML1_1", odds="-140"))
    res = f.to_capture_markets(_parse(html))
    assert res["events"] == []
    assert res["refused_events"] == [{"event_id": "999", "home_team_label": "HOME Team",
                                      "away_team_label": "AWAY Team", "refusal": "TEAM_NAME_UNMAPPED"}]
    res = f.to_capture_markets(_parse(FIX.read_text()))
    assert res["refused_events"] == [] and res["event_match_requirement"]
    for e in res["events"]:
        assert e["commence_time"] is None and e["commence_time_status"] == "NOT_ON_BOARD_CARD"
        assert e["event_match_requirement"] == res["event_match_requirement"]
        assert e["home_team"] in f.DK_BOARD_TEAM_FULL_NAMES.values()
        sp = cap.spread_row(e["markets"]["spreads"], e["home_team"], e["away_team"])
        assert sp["status"] == "OK"
    assert len(set(f.DK_BOARD_TEAM_FULL_NAMES.values())) == 32
