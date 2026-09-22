from sportsedge.opportunity_score import opportunity_score, probability_to_american

def test_fair_odds_come_from_model_probability():
    assert probability_to_american(.69) == -223

def test_longshot_score_is_not_win_probability():
    r=opportunity_score(model_p=.475, book_american_odds=150)
    assert r.fair_american_odds == 111
    assert r.ev_per_dollar > 0
    assert r.score != 48
    assert 0 <= r.score <= 100

def test_bad_price_scores_below_neutral():
    r=opportunity_score(model_p=.69, book_american_odds=-250)
    assert r.ev_per_dollar < 0
    assert r.score < 50

def test_quality_cannot_create_edge():
    full=opportunity_score(model_p=.50, book_american_odds=100)
    weak=opportunity_score(model_p=.50, book_american_odds=100, reliability=.2)
    assert full.score == weak.score == 50
