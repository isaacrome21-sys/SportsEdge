"""Guard one-time CFB live book comparison: freshness, policy, and no staking."""
from unittest.mock import patch
from datetime import datetime, timezone

from scripts.run_cfb_paper_market import BOOKS, build_payload

NOW = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)


def event(home="Alabama", away="Georgia", updated="2026-10-10T02:59:00Z"):
    def book(key, away_odds, home_odds):
        return {"key": key, "last_update": updated, "markets": [
            {"key": "h2h", "last_update": updated,
             "outcomes": [
                 {"name": away, "price": away_odds},
                 {"name": home, "price": home_odds},
             ]}
        ]}
    return {
        "id": "game", "home_team": home, "away_team": away,
        "commence_time": "2026-10-10T23:30:00Z",
        "bookmakers": [
            book("draftkings", 150, -170),
            book("fanduel", -110, -110),
            book("betmgm", -110, -110),
        ],
    }


def test_provider_only_accepts_fresh_independent_quoted_markets():
    ok = build_payload([event()], .02, NOW, "ODDS_PROVIDER", "READY")
    assert len(ok["candidates"]) == 1
    assert ok["candidates"][0]["market_consensus_ev_per_dollar"] > 0
    assert ok["candidates"][0]["official"] is False
    assert ok["candidates"][0]["model_p"] is None
    assert not any(ok["authority"].values())

    late = event()
    late["bookmakers"][1]["last_update"] = "2026-10-10T02:00:00Z"
    late["bookmakers"][1]["markets"][0]["last_update"] = "2026-10-10T02:00:00Z"
    blocked = build_payload([late], .02, NOW, "ODDS_PROVIDER", "READY")
    assert blocked["candidates"] == []

    absent = event()
    for book in absent["bookmakers"]:
        book.pop("last_update")
        book["markets"][0].pop("last_update")
    assert build_payload([absent], .02, NOW, "ODDS_PROVIDER", "READY")["candidates"] == []


def test_illinois_schools_and_price_cap():
    il = build_payload([event(home="Northwestern Wildcats")], .02, NOW,
                       "ODDS_PROVIDER", "READY")
    assert il["candidates"] == []
    for row in build_payload([event()], .02, NOW, "ODDS_PROVIDER", "READY")["candidates"]:
        assert row["draftkings_odds"] >= -165


def test_expected_bookmaker_keys_are_provider_supported():
    assert "draftkings" in BOOKS
    assert "pinnacle" in BOOKS
    assert "betonlineag" in BOOKS
    assert "caesars" not in BOOKS

def test_failed_provider_does_not_fabricate_paper_edges():
    from scripts.run_cfb_paper_market import load_events
    with patch("scripts.run_cfb_paper_market.fetch", side_effect=TimeoutError("fake")):
        rows, source, status = load_events("fake-test-key")
    assert rows == []
    assert source == "ODDS_PROVIDER_UNAVAILABLE"
    assert status == "BLOCKED_PROVIDER_UNAVAILABLE"


def test_workflow_binds_supported_key_alias_and_surfaces_blocked_input():
    from pathlib import Path
    workflow = Path('.github/workflows/cfb-paper-market-card.yml').read_text()
    assert 'SPORTSEDGE_ODDS_API_KEY: ${{ secrets.SPORTSEDGE_ODDS_API_KEY }}' in workflow
    assert "if p['input_status'] != 'READY':" in workflow
    assert 'CFB_SCAN_BLOCKED:' in workflow
    assert 'if: always()' in workflow


def test_coverage_distinguishes_blocked_scan_and_rejected_selections():
    blocked = build_payload([], .02, NOW, 'MARKET_INPUT_UNAVAILABLE', 'BLOCKED_NO_MARKET_INPUT')
    assert blocked['coverage']['scan_completed'] is False
    assert blocked['coverage']['events_received'] == 0
    good = build_payload([event()], .02, NOW, 'ODDS_PROVIDER', 'READY')
    assert good['coverage']['games_with_usable_draftkings'] == 1
    assert good['coverage']['draftkings_selections'] == 2
    assert good['coverage']['candidate_count'] == 1
    assert good['coverage']['straight_price_cap'] == 1
    stale = build_payload([event(updated='2026-10-09T01:00:00Z')], .02, NOW, 'ODDS_PROVIDER', 'READY')
    assert stale['coverage']['no_usable_draftkings_market'] == 1
