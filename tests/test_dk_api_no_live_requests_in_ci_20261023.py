"""Auto-triggered CI jobs that import DraftKings-API modules must not reach a DraftKings
host. Grok ruling 2026-10-23 (t234u): these jobs only test against fixtures/mocks, so they
keep their triggers; this guard runs exactly the DK-importing test modules they run with
every socket, urllib and requests entry point patched to refuse any *draftkings* host.
"""
import importlib
import io
import socket
import sys
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# workflow -> DK-importing test modules it runs on push/pull_request/workflow_run/issues
GUARDED = {
    "market-maker-radar.yml": ["tests.test_capture_nfl_market_maker_radar"],
    "mlb-additional-odds-contract.yml": ["tests.test_mlb_quote_source_coverage"],
    "mlb-additional-pit-archive.yml": ["tests.test_mlb_quote_source_coverage"],
    "football-nfl-promotion-evidence.yml": [
        "tests.test_nfl_2026_direct_capture_wiring",
        "tests.test_nfl_card_game_info", "tests.test_nfl_direct_capture_source",
        "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2-nested-diagnostic.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2h-first-readout.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2i-first-readout.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2j-first-readout.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
}
# nfl-lines-issue.yml runs scripts/render_nfl_myspari_card.py, which reaches the DK dfs
# modules only through `sportsedge.dfs` package imports (ESPN public_json helper).
# football-nfl-promotion-evidence runs `unittest discover -p 'test_football*.py'`, which
# imports tests/test_football_all_props_finish.py (pytest-style; unittest collects 0 tests).
IMPORT_ONLY_SCRIPTS = {"nfl-lines-issue.yml": ["scripts.render_nfl_myspari_card"],
                       "football-nfl-promotion-evidence.yml": ["tests.test_football_all_props_finish"]}
MODULES = sorted({m for ms in GUARDED.values() for m in ms})


class DraftKingsBlocked(OSError):
    pass


def _is_dk(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    return isinstance(host, str) and "draftkings" in host.lower()


@pytest.fixture
def dk_block(monkeypatch):
    attempts = []

    def refuse(where, host):
        attempts.append((where, str(host)))
        raise DraftKingsBlocked(f"LIVE_DK_REQUEST_BLOCKED:{where}:{host}")

    real_gai, real_cc, real_connect = socket.getaddrinfo, socket.create_connection, socket.socket.connect

    def gai(host, *a, **k):
        if _is_dk(host):
            refuse("getaddrinfo", host)
        return real_gai(host, *a, **k)

    def cc(address, *a, **k):
        if _is_dk(address[0]):
            refuse("create_connection", address[0])
        return real_cc(address, *a, **k)

    def connect(self, address):
        if isinstance(address, tuple) and _is_dk(address[0]):
            refuse("socket.connect", address[0])
        return real_connect(self, address)

    real_urlopen = urllib.request.urlopen

    def urlopen(url, *a, **k):
        full = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        if _is_dk(urllib.parse.urlsplit(full).hostname):
            refuse("urlopen", full)
        return real_urlopen(url, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", gai)
    monkeypatch.setattr(socket, "create_connection", cc)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    try:
        import requests
        real_req = requests.sessions.Session.request

        def req(self, method, url, *a, **k):
            if _is_dk(urllib.parse.urlsplit(str(url)).hostname):
                refuse("requests", url)
            return real_req(self, method, url, *a, **k)
        monkeypatch.setattr(requests.sessions.Session, "request", req)
    except ImportError:
        pass
    monkeypatch.chdir(ROOT)
    monkeypatch.syspath_prepend(str(ROOT))
    return attempts


def test_guard_blocks_a_real_dk_fetch(dk_block):
    """Control: the module the live probes use is stopped before any connection."""
    from sportsedge import draftkings_game_market_source as g
    with pytest.raises(Exception):
        g.fetch_board("americanfootball_nfl")
    assert dk_block, "fetch_board was not intercepted"


def test_guard_blocks_low_level_socket(dk_block):
    with pytest.raises(DraftKingsBlocked):
        socket.create_connection(("sportsbook-nash.draftkings.com", 443), timeout=1)
    with pytest.raises(DraftKingsBlocked):
        socket.getaddrinfo("api.draftkings.com", 443)


@pytest.mark.parametrize("module", MODULES)
def test_ci_test_module_makes_no_live_dk_request(dk_block, module):
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    assert result.testsRun > 0
    assert dk_block == [], dk_block
    blocked = [str(e) for _, e in result.errors + result.failures if "LIVE_DK_REQUEST_BLOCKED" in e]
    assert blocked == []


@pytest.mark.parametrize("module", sorted({m for ms in IMPORT_ONLY_SCRIPTS.values() for m in ms}))
def test_import_only_script_makes_no_live_dk_request_on_import(dk_block, module):
    sys.modules.pop(module, None)
    importlib.import_module(module)
    assert dk_block == []


def test_guarded_list_matches_workflows():
    wf = ROOT / ".github" / "workflows"
    for name, mods in {**GUARDED, **IMPORT_ONLY_SCRIPTS}.items():
        text = (wf / name).read_text(encoding="utf-8")
        assert "draftkings" not in "".join(
            l for l in text.splitlines() if "curl" in l).lower(), name
        for m in mods:
            stem = m.split(".")[-1]
            assert stem in text or "test_nfl*.py" in text or "test_football*.py" in text, (name, m)
