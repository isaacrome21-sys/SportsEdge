"""t197 (#2319/#2354): DK "Anytime TD 1+" board rows reach the real nflverse
anytime-TD lane instead of dying as MARKET_NOT_SUPPORTED_BY_NFL_EMPIRICAL,
so the card names the real blocker (governance NO_ENGINE).
Team totals stay NO_ENGINE; nothing is guessed (no team is inferred).

RED before the fix: PLAYER_ANYTIME_TD was not an ANYTIME_TD alias.
"""
from artifacts import run_it_full
from sportsedge.phone_display import build_phone_card


def td(**extra):
    row = {"sport": "NFL", "away": "Seattle Seahawks", "home": "Denver Broncos",
           "kickoff": "2026-10-15T19:15:00-05:00", "book": "draftkings",
           "market": "PLAYER_ANYTIME_TD", "side": "OVER", "odds": 100, "line": 0.5,
           "player_name": "Jaxon Smith-Njigba"}
    row.update(extra)
    return row


def _run(lines):
    return run_it_full.run_full({"lines": lines}, auto_context=False, getter=lambda u: None)


def test_player_anytime_td_routes_to_td_engine_and_names_real_blocker():
    row = _run([td()])["evaluated_rows"][0]
    assert row["reason"] != "MARKET_NOT_SUPPORTED_BY_NFL_EMPIRICAL"
    assert row["market"] == "ANYTIME_TD"
    # The nflverse estimator exists but is not governance-admitted for
    # NFL player props: the honest blocker is the governance NO_ENGINE,
    # which is kept (no research annex for NO_ENGINE).
    assert row["reason"].startswith("NO_ENGINE: GOVERNANCE_NO_ENGINE")
    assert "research_estimate" not in row


def test_milestone_side_mapping_is_exact():
    line = td(); run_it_full._anytime_td_milestone_side(line)
    assert line["side"] == "YES"
    line = td(side="UNDER"); run_it_full._anytime_td_milestone_side(line)
    assert line["side"] == "NO"
    line = td(line=1.5); run_it_full._anytime_td_milestone_side(line)
    assert line["side"] == "OVER"  # 2+ TDs is not anytime TD; engine refuses


def test_nfl_team_total_stays_no_engine():
    row = _run([{"sport": "NFL", "away": "Seattle Seahawks", "home": "Denver Broncos",
                 "kickoff": "2026-10-15T19:15:00-05:00", "book": "draftkings",
                 "market": "TEAM_TOTAL", "side": "OVER", "odds": -105, "line": 21.5,
                 "team": "AWAY"}])["evaluated_rows"][0]
    assert row["reason"].startswith("NO_ENGINE")
    card = {"evaluated_rows": [dict(row, input_index=0)], "summary": {"rows": 1}, "min_ev": 0.02}
    assert build_phone_card(card)["selections"][0]["status"] == "BLOCKED"
