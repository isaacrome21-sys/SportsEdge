from sportsedge.nfl_run_it import run_it


def _q(**kwargs):
    base = {
        "game_id": "2026-W3-KC-NYJ",
        "home": "KC",
        "away": "NYJ",
        "book": "dk",
    }
    base.update(kwargs)
    return base


def test_empty_slate_is_valid_when_quotes_missing():
    card = run_it([], [])
    assert card.picks == ()
    assert card.empty_reason == "Nothing looks strong enough."
    assert "Nothing looks strong enough." in card.render()


def test_empty_when_edge_below_floor():
    quotes = [
        _q(market="spread", selection="KC", line=-3.0, price_american=-110),
        _q(market="spread", selection="NYJ", line=3.0, price_american=-110),
    ]
    models = [
        _q(market="spread", selection="KC", line=-3.0, model_p=0.52, why="tiny lean"),
    ]
    card = run_it(quotes, models, edge_floor=0.02)
    assert card.picks == ()
    assert card.omitted == 2


def test_ranks_by_ev_at_posted_price_not_score():
    quotes = [
        _q(market="spread", selection="KC", line=-3.0, price_american=-105),
        _q(market="spread", selection="NYJ", line=3.0, price_american=-115),
        _q(market="total", selection="OVER", line=47.5, price_american=-108),
        _q(market="total", selection="UNDER", line=47.5, price_american=-112),
        _q(game_id="2026-W3-DET-CHI", home="CHI", away="DET", market="moneyline", selection="DET", price_american=150),
        _q(game_id="2026-W3-DET-CHI", home="CHI", away="DET", market="moneyline", selection="CHI", price_american=-170),
    ]
    models = [
        _q(market="spread", selection="KC", line=-3.0, model_p=0.57, why="Key-number mass + rest"),
        _q(market="total", selection="OVER", line=47.5, model_p=0.56, why="Pace, wind-neutral"),
        {
            "game_id": "2026-W3-DET-CHI",
            "home": "CHI",
            "away": "DET",
            "market": "moneyline",
            "selection": "DET",
            "line": None,
            "model_p": 0.48,
            "why": "QB gap vs inflated favorite",
        },
    ]
    card = run_it(quotes, models, edge_floor=0.015)
    assert len(card.picks) >= 1
    evs = [p.ev_per_dollar for p in card.picks]
    assert evs == sorted(evs, reverse=True)
    assert all(p.price_american in {-105, -108, 150, -110, -115, -112, -170} for p in card.picks)
    assert all(p.score >= 0 and p.score <= 100 for p in card.picks)
    text = card.render()
    assert text.startswith("NFL — RUN IT")
    assert "edge" in text


def test_binds_posted_line_from_simulation():
    quotes = [
        _q(market="spread", selection="KC", line=-3.0, price_american=-110),
        _q(market="spread", selection="NYJ", line=3.0, price_american=-110),
    ]
    rows = [{"home_score": 27, "away_score": 17} for _ in range(80)] + [
        {"home_score": 20, "away_score": 24} for _ in range(20)
    ]
    card = run_it(quotes, [], simulations={"2026-W3-KC-NYJ": rows}, edge_floor=0.02)
    assert len(card.picks) == 1
    pick = card.picks[0]
    assert pick.selection == "KC"
    assert pick.line == -3.0
    assert pick.model_p == 0.8
    assert pick.paired is True


def test_does_not_emit_official_label():
    quotes = [
        _q(market="moneyline", selection="KC", price_american=-150),
        _q(market="moneyline", selection="NYJ", price_american=130),
    ]
    models = [_q(market="moneyline", selection="KC", model_p=0.70, why="talent gap")]
    card = run_it(quotes, models, edge_floor=0.01)
    blob = card.render() + str(card.to_dict())
    assert "OFFICIAL" not in blob
    assert "SPORTSEDGE OFFICIAL" not in blob
