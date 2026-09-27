import pytest

from sportsedge.sports.cfb.source import (
    CFBGame,
    CFBSourceError,
    build_team_alias_index,
    parse_the_odds_api_quotes,
)


GAME = CFBGame(
    game_id="g1",
    season=2026,
    week=4,
    start_ts="2026-09-19T17:00:00+00:00",
    home_team="Home State",
    away_team="Away Tech",
    neutral_site=False,
)
ALIASES = build_team_alias_index(
    [
        {"school": "Home State", "abbreviation": "HOME"},
        {"school": "Away Tech", "abbreviation": "AWAY"},
    ]
)


def _payload(market_key, outcomes):
    return [
        {
            "id": "evt1",
            "home_team": "Home State",
            "away_team": "Away Tech",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": "2026-09-19T16:00:00Z",
                    "markets": [
                        {
                            "key": market_key,
                            "last_update": "2026-09-19T16:00:00Z",
                            "outcomes": outcomes,
                        }
                    ],
                }
            ],
        }
    ]


def _parse(market_key, outcomes):
    return parse_the_odds_api_quotes(
        _payload(market_key, outcomes),
        games=[GAME],
        alias_index=ALIASES,
    )


def test_valid_spread_pair_is_canonicalized_to_home_line():
    quotes = _parse(
        "spreads",
        [
            {"name": "Home State", "price": -110, "point": -7.5},
            {"name": "Away Tech", "price": -110, "point": 7.5},
        ],
    )

    assert [q.side for q in quotes] == ["HOME", "AWAY"]
    assert [q.line for q in quotes] == [-7.5, -7.5]


def test_spread_pair_mismatch_fails_closed():
    with pytest.raises(CFBSourceError, match=r"^CFB_SPREAD_PAIR_MISMATCH:"):
        _parse(
            "spreads",
            [
                {"name": "Home State", "price": -110, "point": -7.5},
                {"name": "Away Tech", "price": -110, "point": 6.5},
            ],
        )


def test_implausibly_large_spread_fails_closed():
    with pytest.raises(CFBSourceError, match=r"^CFB_SPREAD_LINE_OUT_OF_RANGE:"):
        _parse(
            "spreads",
            [
                {"name": "Home State", "price": -110, "point": -99.0},
                {"name": "Away Tech", "price": -110, "point": 99.0},
            ],
        )


def test_valid_total_pair_uses_one_canonical_line():
    quotes = _parse(
        "totals",
        [
            {"name": "Over", "price": -110, "point": 54.5},
            {"name": "Under", "price": -110, "point": 54.5},
        ],
    )

    assert [q.side for q in quotes] == ["OVER", "UNDER"]
    assert [q.line for q in quotes] == [54.5, 54.5]


def test_total_pair_mismatch_fails_closed():
    with pytest.raises(CFBSourceError, match=r"^CFB_TOTAL_PAIR_MISMATCH:"):
        _parse(
            "totals",
            [
                {"name": "Over", "price": -110, "point": 54.5},
                {"name": "Under", "price": -110, "point": 55.5},
            ],
        )


def test_implausible_total_fails_closed():
    with pytest.raises(CFBSourceError, match=r"^CFB_TOTAL_LINE_OUT_OF_RANGE:"):
        _parse(
            "totals",
            [
                {"name": "Over", "price": -110, "point": 999.0},
                {"name": "Under", "price": -110, "point": 999.0},
            ],
        )


def test_missing_opposite_spread_side_fails_closed():
    with pytest.raises(CFBSourceError, match=r"^CFB_AWAY_SPREAD_MISSING$"):
        _parse(
            "spreads",
            [{"name": "Home State", "price": -110, "point": -7.5}],
        )


def test_moneyline_behavior_is_unchanged():
    quotes = _parse(
        "h2h",
        [
            {"name": "Home State", "price": -150},
            {"name": "Away Tech", "price": 130},
        ],
    )

    assert [q.side for q in quotes] == ["HOME", "AWAY"]
    assert [q.line for q in quotes] == [0.0, 0.0]
