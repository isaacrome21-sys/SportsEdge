import random

from sportsedge.mlb_f5_walkforward import parse_schedule, run_walkforward


def _payload(n_days=60, seed=3, extra=None):
    rng = random.Random(seed)
    dates = []
    pk = 1
    for d in range(n_days):
        games = []
        for t in range(0, 8, 2):
            inn = [{"away": {"runs": rng.choice([0, 0, 0, 1, 2])}, "home": {"runs": rng.choice([0, 0, 1, 1, 3])}}
                   for _ in range(9)]
            games.append({"gamePk": pk, "gameType": "R", "officialDate": f"2024-{4 + d // 28:02d}-{d % 28 + 1:02d}",
                          "gameDate": f"2024-{4 + d // 28:02d}-{d % 28 + 1:02d}T{17 + t}:05:00Z", "status": {"codedGameState": "F"}, "linescore": {"innings": inn},
                          "teams": {"away": {"team": {"id": 100 + t}, "score": sum(i["away"]["runs"] for i in inn)},
                                    "home": {"team": {"id": 101 + t}, "score": sum(i["home"]["runs"] for i in inn)}}})
            pk += 1
        dates.append({"date": games[0]["officialDate"], "games": games})
    return {"dates": dates + (extra or [])}


def test_parse_dedupes_and_drops_non_final_or_short():
    p = _payload(3)
    g0 = dict(p["dates"][0]["games"][0])
    short = dict(g0, gamePk=999, linescore={"innings": g0["linescore"]["innings"][:4]})
    pend = dict(g0, gamePk=998, status={"codedGameState": "P"})
    p["dates"][0]["games"] += [g0, short, pend]
    assert len(parse_schedule([p])) == 12


def test_future_games_do_not_change_past_scores():
    games = parse_schedule([_payload(60)])
    cut = games[-1]["date"]
    base = run_walkforward([g for g in games if g["date"] < cut])
    tampered = [dict(g, away_runs=99, away_f5=20) if g["date"] >= cut else g for g in games]
    again = run_walkforward([g for g in tampered if g["date"] < cut])
    assert base == again
    full = run_walkforward(tampered)
    assert full["lines"]["0.5"]["n"] > base["lines"]["0.5"]["n"]


def test_same_slate_results_not_used_for_that_slate():
    games = parse_schedule([_payload(60)])
    last = games[-1]["date"]
    a = run_walkforward(games, start_date=last)
    b = run_walkforward([dict(g, away_f5=g["away_f5"]) if g["date"] != last else dict(g, away_runs=50) for g in games],
                        start_date=last)
    assert a["lines"]["1.5"]["brier_model"] == b["lines"]["1.5"]["brier_model"]
    assert a["market_baseline"] == "MISSING"


def test_previous_night_game_not_final_at_cutoff_is_excluded():
    from datetime import timedelta
    games = parse_schedule([_payload(40)])
    last = games[-1]["date"]
    cutoff = min(g["start"] for g in games if g["date"] == last)
    # shift one prior-day game to start 1h before the slate cutoff: started, not final
    victim = next(g for g in reversed(games) if g["date"] < last)
    moved = [dict(g, start=cutoff - timedelta(hours=1), away_runs=60, home_runs=60) if g is victim else g
             for g in games]
    base = [dict(g, away_runs=0, home_runs=0) if g is victim else g for g in games]
    base = [dict(g, start=cutoff - timedelta(hours=1)) if g["game_id"] == victim["game_id"] else g for g in base]
    a = run_walkforward(moved, start_date=last)
    b = run_walkforward(base, start_date=last)
    assert a["lines"]["1.5"] == b["lines"]["1.5"] and a["lines"]["1.5"]["n"] > 0


def test_zinb_preserves_mean_and_fit_recovers_inflation():
    import random as _r
    from sportsedge.mlb_f5_team_total_ladder import zinb_pmf
    from sportsedge.mlb_f5_walkforward import fit_f5_dispersion
    pmf = zinb_pmf(2.6, 2.5, 0.06)
    assert abs(sum(pmf) - 1) < 1e-9 and abs(sum(k * p for k, p in enumerate(pmf)) - 2.6) < 1e-3
    rng = _r.Random(1)
    true = zinb_pmf(2.5, 2.0, 0.10)
    rows = [(2.5, rng.choices(range(len(true)), true)[0]) for _ in range(3000)]
    fit = fit_f5_dispersion(rows)
    assert abs(fit["pi"] - 0.10) <= 0.06 and 1.0 <= fit["r_f5"] <= 4.0
