from sportsedge.sports.nba.ratings_model import NBARatings, NBARatingsParams, replay


def test_prediction_uses_only_prior_games():
    games = [
        {"season": 1, "date": 1, "home": "A", "away": "B", "home_pts": 120, "away_pts": 100},
        {"season": 1, "date": 2, "home": "A", "away": "B", "home_pts": 90, "away_pts": 130},
    ]
    seen = []
    replay(games, NBARatingsParams(), on_pre=lambda g, r: seen.append(r.margin_total(g["home"], g["away"])))
    # first game: only home-court advantage
    assert abs(seen[0][0] - 3.0) < 1e-9
    assert abs(seen[0][1] - 200.0) < 1e-9
    # second game reflects the A win, not the later B blowout
    assert seen[1][0] > seen[0][0]


def test_season_carry_shrinks_ratings():
    r = NBARatings(NBARatingsParams(carry=0.5))
    r.start_season(1)
    r.update("A", "B", 130, 90)
    before = r.margin_total("A", "B")[0] - r.hca
    r.start_season(2)
    after = r.margin_total("A", "B")[0] - r.hca
    assert abs(after - 0.5 * before) < 1e-9


def test_neutral_site_has_no_hca():
    r = NBARatings()
    assert r.margin_total("A", "B", neutral=True)[0] == 0.0
