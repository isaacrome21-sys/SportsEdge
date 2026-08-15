from sportsedge.dfs_mlb import (
    DFSConfig,
    Lineup,
    PlayerProjection,
    generate_lineups,
    simulate_portfolio,
    validate_lineup,
)


def _pool():
    players = [
        PlayerProjection("p1", "Pitcher A", "AAA", "BBB", ("P",), 9500, 22.0, 7.0, 0.28, is_pitcher=True, game_id="g1"),
        PlayerProjection("p2", "Pitcher C", "CCC", "DDD", ("P",), 9000, 20.0, 6.5, 0.22, is_pitcher=True, game_id="g2"),
        PlayerProjection("p3", "Pitcher E", "EEE", "FFF", ("P",), 8200, 18.0, 6.0, 0.15, is_pitcher=True, game_id="g3"),
        PlayerProjection("c1", "Catcher", "AAA", "BBB", ("C",), 3900, 8.5, 5.0, 0.12, 5, False, "g1"),
        PlayerProjection("b1", "First Base", "CCC", "DDD", ("1B",), 4300, 9.5, 5.2, 0.18, 3, False, "g2"),
        PlayerProjection("b2", "Second Base", "AAA", "BBB", ("2B",), 4100, 9.0, 4.8, 0.14, 2, False, "g1"),
        PlayerProjection("b3", "Third Base", "CCC", "DDD", ("3B",), 4200, 9.2, 4.9, 0.16, 4, False, "g2"),
        PlayerProjection("ss1", "Shortstop", "EEE", "FFF", ("SS",), 4000, 8.8, 4.7, 0.10, 1, False, "g3"),
        PlayerProjection("of1", "Outfield 1", "AAA", "BBB", ("OF",), 5000, 11.2, 5.8, 0.25, 1, False, "g1"),
        PlayerProjection("of2", "Outfield 2", "CCC", "DDD", ("OF",), 4700, 10.5, 5.5, 0.20, 2, False, "g2"),
        PlayerProjection("of3", "Outfield 3", "EEE", "FFF", ("OF",), 4400, 9.8, 5.1, 0.13, 3, False, "g3"),
        PlayerProjection("of4", "Outfield 4", "GGG", "HHH", ("OF",), 3900, 8.4, 4.6, 0.08, 6, False, "g4"),
        PlayerProjection("of5", "Outfield 5", "III", "JJJ", ("OF",), 3600, 7.9, 4.4, 0.06, 7, False, "g5"),
    ]
    return players


def test_generate_lineups_are_legal_and_reproducible():
    cfg = DFSConfig(max_lineups=3, min_unique_players=1, max_player_exposure=1.0)
    first = generate_lineups(_pool(), cfg, seed=7)
    second = generate_lineups(_pool(), cfg, seed=7)

    assert first
    assert [[p.player_id for p in l.players] for l in first] == [[p.player_id for p in l.players] for l in second]
    for lineup in first:
        valid, errors = validate_lineup(lineup, cfg)
        assert valid, errors
        assert lineup.salary <= cfg.salary_cap


def test_validate_lineup_rejects_hitter_against_selected_pitcher():
    pitcher = PlayerProjection("p", "P", "AAA", "BBB", ("P",), 9000, 20, 6, is_pitcher=True)
    opp_hitter = PlayerProjection("h", "H", "BBB", "AAA", ("OF",), 4000, 9, 5)
    filler = [
        PlayerProjection(f"x{i}", f"X{i}", f"T{i}", "ZZZ", (slot if slot != "C/1B" else "1B",), 3000, 8, 4)
        for i, slot in enumerate(("P", "C/1B", "2B", "3B", "SS", "OF", "OF"), start=1)
    ]
    players = (pitcher, filler[0], filler[1], filler[2], filler[3], filler[4], opp_hitter, filler[5], filler[6])
    lineup = Lineup(players=players, slots=DFSConfig().slots, objective=0.0)
    valid, errors = validate_lineup(lineup, DFSConfig())
    assert not valid
    assert any(e.startswith("HITTER_VS_PITCHER") for e in errors)


def test_simulation_is_reproducible():
    cfg = DFSConfig(max_lineups=2, min_unique_players=1, max_player_exposure=1.0)
    lineups = generate_lineups(_pool(), cfg, seed=11)
    a = simulate_portfolio(lineups, n_sims=300, seed=99)
    b = simulate_portfolio(lineups, n_sims=300, seed=99)

    assert [(r.mean, r.p95, r.top_lineup_rate) for r in a] == [
        (r.mean, r.p95, r.top_lineup_rate) for r in b
    ]
