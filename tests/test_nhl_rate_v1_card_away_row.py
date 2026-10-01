from sportsedge import nhl_rate_v1_card as card


def test_simulate_matchup_builds_away_rate_from_away_team(monkeypatch):
    calls = []

    def fake_row(team, opp, *, home):
        calls.append((team, opp, home))
        return (1.0,)

    monkeypatch.setattr(card, "load_freeze", lambda: object())
    monkeypatch.setattr(card, "_row", fake_row)
    monkeypatch.setattr(card, "_lam", lambda _params, _features: 1.0)
    monkeypatch.setattr(card, "_poisson", lambda _rng, _mean: 0)

    result = card.simulate_matchup("Rangers", "Bruins", n=1, seed=7)

    assert result is not None
    assert calls == [
        ("BOS", "NYR", True),
        ("NYR", "BOS", False),
    ]
