from bs4 import BeautifulSoup

from scripts.audit_nfl_2025_prekick_inactive_articles import (
    _article_url,
    article_timestamps,
    parse_games,
)


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_article_url_only_admits_official_nfl_inactive_news():
    assert (
        _article_url(
            "https://www.nfl.com/news/week-1-monday-inactives-minnesota-vikings-at-chicago-bears"
        )
        == "https://amp.nfl.com/news/week-1-monday-inactives-minnesota-vikings-at-chicago-bears"
    )
    assert _article_url("/news/nfl-week-2-inactives-players-ruled-out") == (
        "https://amp.nfl.com/news/nfl-week-2-inactives-players-ruled-out"
    )
    assert _article_url("/news/week-1-preview") is None
    assert _article_url("https://example.com/news/week-1-inactives") is None


def test_single_game_published_before_kickoff_is_admitted():
    doc = soup(
        """
        <html><body>
        <h1>Vikings vs. Bears Week 1 inactives</h1>
        <p>Published: Sep 08, 2025 at 06:53 PM</p>
        <ul><li>WHEN: 8:15 p.m. ET | ESPN</li></ul>
        <h3>VIKINGS</h3>
        <ul><li>QB Max Brosmer</li><li>OT Christian Darrisaw</li></ul>
        <h3>BEARS</h3>
        <ul><li>QB Case Keenum</li><li>CB Jaylon Johnson</li></ul>
        <h2>Related Content</h2>
        </body></html>
        """
    )
    published, modified = article_timestamps(doc)
    week, games = parse_games(
        doc,
        published=published,
        modified=modified,
        source_url="https://amp.nfl.com/news/test",
    )
    assert week == 1
    assert len(games) == 1
    row = games[0]
    assert row["admissible"] is True
    assert row["reason"] == "ADMITTED_PREKICK_OFFICIAL_INACTIVE_LIST"
    assert row["lead_minutes"] == 82.0
    assert row["inactive_by_team"]["MIN"] == ["Max Brosmer", "Christian Darrisaw"]
    assert row["inactive_by_team"]["CHI"] == ["Case Keenum", "Jaylon Johnson"]


def test_final_update_timestamp_gates_each_game_independently():
    doc = soup(
        """
        <html><body>
        <h1>Week 2 Monday inactives: Bucs at Texans; Chargers at Raiders</h1>
        <p>Published: Sep 15, 2025 at 05:32 PM</p>
        <p>Updated: Sep 15, 2025 at 08:41 PM</p>

        <ul><li>WHEN: 7:00 p.m. ET | ESPN</li></ul>
        <h3>BUCCANEERS</h3><ul><li>WR Player One</li></ul>
        <h3>TEXANS</h3><ul><li>CB Player Two</li></ul>

        <ul><li>WHEN: 10:00 p.m. ET | ESPN</li></ul>
        <h3>CHARGERS</h3><ul><li>RB Player Three</li></ul>
        <h3>RAIDERS</h3><ul><li>LB Player Four</li></ul>
        <h2>Related Content</h2>
        </body></html>
        """
    )
    published, modified = article_timestamps(doc)
    _, games = parse_games(
        doc,
        published=published,
        modified=modified,
        source_url="https://amp.nfl.com/news/test",
    )
    assert len(games) == 2
    assert games[0]["admissible"] is False
    assert games[0]["reason"] == "ARTICLE_FINAL_TIMESTAMP_AFTER_KICKOFF"
    assert games[1]["admissible"] is True
    assert games[1]["lead_minutes"] == 79.0


def test_missing_one_team_inactive_list_fails_closed():
    doc = soup(
        """
        <html><body>
        <h1>Week 3 Thursday inactives</h1>
        <p>Published: Sep 18, 2025 at 06:30 PM</p>
        <ul><li>WHEN: 8:15 p.m. ET</li></ul>
        <h3>DOLPHINS</h3><ul><li>WR Player One</li></ul>
        <h3>BILLS</h3>
        <h2>Related Content</h2>
        </body></html>
        """
    )
    published, modified = article_timestamps(doc)
    _, games = parse_games(
        doc,
        published=published,
        modified=modified,
        source_url="https://amp.nfl.com/news/test",
    )
    assert games[0]["admissible"] is False
    assert games[0]["reason"] == "BOTH_TEAM_INACTIVE_LISTS_REQUIRED"


def test_jsonld_timestamp_preferred_and_timezone_aware():
    doc = soup(
        """
        <html><head>
        <script type="application/ld+json">
        {
          "@type": "NewsArticle",
          "datePublished": "2025-09-08T18:53:00-04:00",
          "dateModified": "2025-09-08T19:01:00-04:00"
        }
        </script>
        </head><body><h1>Week 1 inactives</h1></body></html>
        """
    )
    published, modified = article_timestamps(doc)
    assert published.isoformat() == "2025-09-08T18:53:00-04:00"
    assert modified is not None
    assert modified.isoformat() == "2025-09-08T19:01:00-04:00"
