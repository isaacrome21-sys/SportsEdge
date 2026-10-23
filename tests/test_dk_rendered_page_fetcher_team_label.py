"""Team label vs sub-label (MLB pitcher) and live scoreboard cards. SCREEN / NOT_VALIDATED."""
from datetime import datetime, timezone

from sportsedge.dk_rendered_page_fetcher import parse_rendered_board

URL = "https://sportsbook.draftkings.com/leagues/baseball/mlb"
OBS = datetime(2026, 10, 23, 20, 40, 36, tzinfo=timezone.utc)


def _team(name, sub="", score=""):
    s = f'<span class="cb-market__label-sub-label">{sub}</span>' if sub else ""
    sc = f'<span class="cb-market__scoreboard-team-score">{score}</span>' if score else ""
    return ('<a data-testid="lp-nav-link" href="/event/a-%40-b/999"><div>'
            f'<span class="cb-market__label-inner cb-market__label-inner--parlay">{name}</span>{s}</div>{sc}</a>')


def _ml():
    return ('<button data-testid="component-builder-market-button-999-0ML1_3">'
            '<span data-testid="button-odds-market-board">+159</span></button>'
            '<button data-testid="component-builder-market-button-999-0ML1_1">'
            '<span data-testid="button-odds-market-board">−193</span></button>')


def _page(t1, t2):
    return f'<html><body><div data-testid="market-mapping-template-210">{t1}{t2}{_ml()}</div></body></html>'


def test_team_name_not_pitcher_sub_label():
    out = parse_rendered_board(_page(_team("TB Rays", sub="Nick Martinez"), _team("MIL Brewers", sub="Jacob Misiorowski")),
                               page_url=URL, observed_at=OBS, sport_key="baseball_mlb")
    assert {r["away_team"] for r in out["rows"]} == {"TB Rays"}
    assert {r["home_team"] for r in out["rows"]} == {"MIL Brewers"}
    assert {r["outcome"] for r in out["rows"]} == {"TB Rays", "MIL Brewers"}


def test_live_scoreboard_card_refused_whole():
    out = parse_rendered_board(_page(_team("CHI Bulls", score="17"), _team("MIL Bucks", score="32")),
                               page_url=URL, observed_at=OBS, sport_key="basketball_nba")
    assert out["rows"] == []
    assert any(c["refusal"] == "LIVE_IN_PROGRESS_CARD" for c in out["card_refusals"])
    assert all("17" not in (r.get("outcome") or "") for r in out["refused_rows"])
