import pytest

from scripts.run_nba_lines_issue import fetch_results, parse_events
from sportsedge.sports.nba.lines_card import (
    NBALinesError, parse_lines, price_game, ratings_from_results, render, team_abbr,
)

BODY = """Celtics @ Knicks
ML +130 -155
Spread +3.5 -110 -110
Total 224.5 -108 -112

GS Warriors @ LA Lakers
Spread -2 -110 -110
"""


def _results():
    out = []
    for i in range(40):
        out.append({"season": 2026, "date": 20251101 + i, "home": "NYK", "away": "BOS", "home_pts": 115, "away_pts": 105})
        out.append({"season": 2026, "date": 20251101 + i, "home": "LAL", "away": "GSW", "home_pts": 110, "away_pts": 112})
    return out


def test_parse_and_aliases():
    games = parse_lines(BODY)
    assert [(g.away, g.home) for g in games] == [("BOS", "NYK"), ("GSW", "LAL")]
    assert games[0].markets[1].line == 3.5 and games[0].markets[2].p2 == -112
    assert team_abbr("Philadelphia 76ers") == "PHI" and team_abbr("POR Trail Blazers") == "POR"


@pytest.mark.parametrize("bad", ["ML +130", "Celtics @ Knicks\nML +130", "Celtics @ Knicks\nSpread +3.5 -110", "Foo @ Bar\nML +100 -120"])
def test_fail_closed(bad):
    with pytest.raises(NBALinesError):
        parse_lines(bad)


def test_prices_are_leans_not_bets_and_probabilities_sum():
    games = parse_lines(BODY)
    r = ratings_from_results(_results())
    m, t, rows = price_game(games[0], r)
    assert m > 0  # Knicks rated better at home
    for i in range(0, len(rows), 2):
        assert abs(rows[i].model_p + rows[i + 1].model_p - 1) < 1e-9
        assert abs(rows[i].novig_p + rows[i + 1].novig_p - 1) < 1e-9
    assert all(x.label in ("LEAN", "PASS") for x in rows)
    card = render(games, r, observed="now", results_note="test")
    assert "Validated markets: NONE" in card and "| BET |" not in card


def test_parse_events_and_fetch_chunks():
    ev = {"events": [
        {"id": "1", "date": "2025-11-02T00:00Z", "season": {"year": 2026, "type": 2},
         "competitions": [{"status": {"type": {"completed": True}}, "competitors": [
             {"homeAway": "home", "score": "110", "team": {"abbreviation": "NY"}},
             {"homeAway": "away", "score": "100", "team": {"abbreviation": "BOS"}}]}]},
        {"id": "2", "date": "2025-10-05T00:00Z", "season": {"year": 2026, "type": 1},
         "competitions": [{"status": {"type": {"completed": True}}, "competitors": []}]},
    ]}
    rows = parse_events(ev)
    assert rows == [{"id": "1", "season": 2026, "date": 20251102, "home": "NYK", "away": "BOS",
                     "home_pts": 110.0, "away_pts": 100.0, "neutral": False}]
    from datetime import date
    urls = []
    games, errors = fetch_results(date(2026, 10, 20), fetch=lambda u: (urls.append(u), ev)[1])
    assert len(games) == 1 and not errors
    assert "dates=20251001-20251031" in urls[0] and "20261019" in urls[-1]


def test_free_text_notes_are_ignored_but_typos_fail_closed():
    body = "Smoke test only. Synthetic quotes.\n" + BODY + "\nNotes: do not count as forward evidence.\n"
    assert [(g.away, g.home) for g in parse_lines(body)] == [("BOS", "NYK"), ("GSW", "LAL")]
    with pytest.raises(NBALinesError):
        parse_lines("Celtics @ Knicks\nSprad +3.5 -110 -110")


def test_fetch_falls_back_to_per_day_after_http_400():
    from datetime import date
    from scripts.run_nba_lines_issue import FetchError

    day_ev = lambda d: {"events": [
        {"id": d, "date": f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00Z", "season": {"year": 2026, "type": 2},
         "competitions": [{"status": {"type": {"completed": True}}, "competitors": [
             {"homeAway": "home", "score": "110", "team": {"abbreviation": "NY"}},
             {"homeAway": "away", "score": "100", "team": {"abbreviation": "BOS"}}]}]}]}
    urls = []

    def fetch(u):
        urls.append(u)
        q = u.split("dates=")[1].split("&")[0]
        if "-" in q:
            raise FetchError("ESPN_FETCH_FAILED:HTTP 400", client=True)
        return day_ev(q)

    games, errors = fetch_results(date(2026, 10, 10), fetch=fetch)
    assert not errors
    day_urls = [u for u in urls if "-" not in u.split("dates=")[1]]
    days = {u.split("dates=")[1] for u in day_urls}
    assert "20251001" in days and "20261009" in days and "20261010" not in days
    assert not any(d[4:6] in ("07", "08", "09") and d[:4] == "2026" for d in days)
    assert len(games) == len(days) == len(day_urls)
    assert sum("-" in u.split("dates=")[1] for u in urls) == 1  # one range attempt, then per-day


def test_fetch_server_errors_skip_month_without_fallback():
    from datetime import date
    from scripts.run_nba_lines_issue import FetchError

    def fetch(u):
        raise FetchError("ESPN_FETCH_FAILED:URLError:timeout")

    games, errors = fetch_results(date(2026, 10, 10), fetch=fetch)
    assert games == [] and len(errors) == 13
