"""Family tests for NHL_ATTEMPT2_V1 (sportsedge/nhl_attempt2.py).

Hermetic: every fixture is synthetic and every expected value is
hand-computed. The proofs that matter, per the design and the MoneyPuck
admission record: strictly-prior filtering (a game is never a feature
for itself), the xG vintage ban enforced as a refusal, the OT/SO mass
added exactly once, and the frozen-constants path refusing while the
design's freeze-owed values are unpinned.
"""
import math

import pytest

from sportsedge import nhl_attempt2 as A
from sportsedge import nhl_attempt2_constants as C


def trow(team, opp, season, date, xgf, xga, gf=0.0, ga=0.0):
    return A.TeamGameRow(team=team, opponent=opp, season=season,
                         gamedate=date, home_or_away="HOME",
                         xgoals_for=xgf, xgoals_against=xga,
                         goals_for=gf, goals_against=ga)


def grow(pid, team, season, date, xg_faced, ga, name="G"):
    return A.GoalieGameRow(player_id=pid, name=name, team=team,
                           season=season, gamedate=date,
                           xgoals_faced=xg_faced, goals_allowed=ga,
                           icetime_seconds=3600.0)


def params(**over):
    base = dict(half_life_games=10.0, shrinkage_prior_games=5.0,
                goalie_shrinkage_games=2.0, treatment=None)
    base.update(over)
    return A.Params(**base)


# ---------------------------------------------------------------------------
# Strictly-prior (admission section 2.2)
# ---------------------------------------------------------------------------

def test_strictly_prior_invariance():
    rows = [trow("AAA", "BBB", 2026, 20261010, 3.0, 2.0),
            trow("AAA", "CCC", 2026, 20261012, 3.5, 2.5),
            trow("BBB", "AAA", 2026, 20261010, 2.0, 3.0),
            trow("CCC", "AAA", 2026, 20261012, 2.5, 3.5)]
    p = params()
    book1 = A.build_rate_book(rows, 20261015, p)
    poisoned = rows + [trow("AAA", "BBB", 2026, 20261015, 99.0, 0.0),
                       trow("AAA", "BBB", 2026, 20261020, 99.0, 0.0),
                       trow("BBB", "AAA", 2026, 20261015, 0.0, 99.0)]
    book2 = A.build_rate_book(poisoned, 20261015, p)
    assert book2.rates == book1.rates
    assert book2.league_rate == book1.league_rate
    assert book2.rows_used == book1.rows_used == 4


def test_strictly_prior_known_answer_weights():
    # half-life 1 game: two prior games weight [0.5, 1.0] oldest->newest.
    rows = [trow("AAA", "BBB", 2026, 20261010, 2.0, 3.0),
            trow("AAA", "BBB", 2026, 20261012, 4.0, 3.0)]
    p = params(half_life_games=1.0, shrinkage_prior_games=0.0)
    book = A.build_rate_book(rows, 20261015, p)
    assert book.rates["AAA"].off_rate == pytest.approx((0.5 * 2 + 1.0 * 4) / 1.5)
    assert book.rates["AAA"].def_rate == pytest.approx(3.0)
    assert book.rates["AAA"].games == 2


def test_shrinkage_toward_league_known_answer():
    rows = [trow("AAA", "BBB", 2026, 20261010, 4.0, 2.0),
            trow("BBB", "AAA", 2026, 20261010, 2.0, 4.0)]
    p = params(shrinkage_prior_games=2.0)
    book = A.build_rate_book(rows, 20261015, p)
    assert book.league_off == pytest.approx(3.0)
    # (1 * 4.0 + 2 * 3.0) / (1 + 2) = 10/3
    assert book.rates["AAA"].off_rate == pytest.approx(10.0 / 3.0)


def test_no_prior_rows_is_lookahead_refusal():
    rows = [trow("AAA", "BBB", 2026, 20261020, 3.0, 3.0)]
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.build_rate_book(rows, 20261015, params())
    assert ei.value.code == "LOOKAHEAD_RISK"


# ---------------------------------------------------------------------------
# xG vintage enforcement (admission section 4.1)
# ---------------------------------------------------------------------------

def mixed_rows():
    return [trow("AAA", "BBB", 2025, 20251010, 9.0, 9.0),
            trow("AAA", "BBB", 2026, 20261010, 3.0, 2.0),
            trow("BBB", "AAA", 2026, 20261010, 2.0, 3.0)]


def test_vintage_pooling_refused_without_treatment():
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.build_rate_book(mixed_rows(), 20261015, params(treatment=None))
    assert ei.value.code == "XG_VINTAGE_POOLING_REFUSED"


def test_vintage_undeclared_treatment_refused():
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.build_rate_book(mixed_rows(), 20261015,
                          params(treatment="POOL_ANYWAY"))
    assert ei.value.code == "XG_VINTAGE_TREATMENT_UNDECLARED"


def test_vintage_declared_treatment_excludes_and_counts():
    p = params(treatment=C.DECLARED_CROSS_VINTAGE_TREATMENT,
               shrinkage_prior_games=0.0)
    book = A.build_rate_book(mixed_rows(), 20261015, p)
    assert book.vintage_excluded_rows == 1
    assert book.rates["AAA"].games == 1
    assert book.rates["AAA"].off_rate == pytest.approx(3.0)


def test_vintage_single_season_needs_no_treatment():
    rows = [r for r in mixed_rows() if r.season == 2026]
    book = A.build_rate_book(rows, 20261015, params(treatment=None))
    assert book.vintage_excluded_rows == 0
    assert book.rows_used == 2


def test_vintage_enforced_on_goalie_pool_too():
    grows = [grow("1", "AAA", 2025, 20251010, 3.0, 2.0),
             grow("1", "AAA", 2026, 20261010, 3.0, 2.0)]
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.goalie_adjustment(grows, "AAA", 20261015, params(treatment=None))
    assert ei.value.code == "XG_VINTAGE_POOLING_REFUSED"


# ---------------------------------------------------------------------------
# Goaltender adjustment (design section 1)
# ---------------------------------------------------------------------------

def test_goalie_confirmed_starter_known_answer():
    grows = [grow("1", "AAA", 2026, 20261010, 3.0, 2.0),
             grow("1", "AAA", 2026, 20261012, 4.0, 2.0),
             grow("2", "AAA", 2026, 20261011, 9.0, 0.0)]
    adj = A.goalie_adjustment(grows, "AAA", 20261015,
                              params(goalie_shrinkage_games=2.0),
                              starter_player_id="1")
    # per-game delta ((3-2)+(4-2))/2 = 1.5; shrunk 1.5 * 2/(2+2) = 0.75
    assert adj.delta_per_game == pytest.approx(0.75)
    assert adj.confirmed is True and adj.degraded is False
    assert adj.games == 2


def test_goalie_blend_weighted_and_degraded():
    grows = [grow("1", "AAA", 2026, 20261010, 3.0, 2.0),
             grow("1", "AAA", 2026, 20261012, 4.0, 2.0),
             grow("2", "AAA", 2026, 20261011, 2.0, 3.0)]
    adj = A.goalie_adjustment(grows, "AAA", 20261015,
                              params(goalie_shrinkage_games=1.0))
    # pooled per-game ((1)+(2)+(-1))/3 = 2/3; shrunk (2/3) * 3/(3+1) = 0.5
    assert adj.delta_per_game == pytest.approx(0.5)
    assert adj.confirmed is False and adj.degraded is True
    assert adj.goalies_considered == 2


def test_goalie_starter_without_priors_refused():
    grows = [grow("1", "AAA", 2026, 20261010, 3.0, 2.0)]
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.goalie_adjustment(grows, "AAA", 20261015, params(),
                            starter_player_id="99")
    assert ei.value.code == "GOALIE_STARTER_NO_PRIOR"


# ---------------------------------------------------------------------------
# Distributions and the OT/SO layer (design section 2)
# ---------------------------------------------------------------------------

def test_goal_pmf_poisson_exact_and_sums():
    pmf = A.goal_pmf(3.0, 1.0)
    assert sum(pmf) == pytest.approx(1.0, abs=1e-12)
    for k in range(9):
        expect = math.exp(-3.0) * 3.0 ** k / math.factorial(k)
        assert pmf[k] == pytest.approx(expect, abs=1e-9)


def test_goal_pmf_negative_binomial_dispersion():
    pmf = A.goal_pmf(3.0, 1.5)
    assert sum(pmf) == pytest.approx(1.0, abs=1e-12)
    mean = sum(k * p for k, p in enumerate(pmf))
    var = sum((k - mean) ** 2 * p for k, p in enumerate(pmf))
    assert mean == pytest.approx(3.0, rel=0.01)
    assert var == pytest.approx(1.5 * 3.0, rel=0.05)
    assert var > sum((k - 3.0) ** 2 * p
                     for k, p in enumerate(A.goal_pmf(3.0, 1.0)))


def test_simulation_layer_added_exactly_once():
    sim = A.simulate(3.0, 2.8, 1.0, ot_home_win_share=0.6,
                     ot_decision_share=0.7)
    assert sim.p_home_reg_win + sim.p_reg_tie + sim.p_away_reg_win \
        == pytest.approx(1.0, abs=1e-9)
    assert sim.p_home_ml + sim.p_away_ml == pytest.approx(1.0, abs=1e-9)
    assert sim.p_home_ml - sim.p_home_reg_win \
        == pytest.approx(sim.p_reg_tie * 0.6, abs=1e-9)
    assert sim.p_away_ml - sim.p_away_reg_win \
        == pytest.approx(sim.p_reg_tie * 0.4, abs=1e-9)
    assert sum(sim.reg_total_pmf) == pytest.approx(1.0, abs=1e-9)
    assert sum(sim.final_total_pmf) == pytest.approx(1.0, abs=1e-9)
    e_reg = sum(k * p for k, p in enumerate(sim.reg_total_pmf))
    e_fin = sum(k * p for k, p in enumerate(sim.final_total_pmf))
    # the OT goal enters exactly once, only via tied games decided in OT
    assert e_fin - e_reg == pytest.approx(sim.p_reg_tie * 0.7, abs=1e-9)
    assert sim.p_home_puck_line_minus15 + sim.p_away_puck_line_plus15 \
        == pytest.approx(1.0, abs=1e-12)
    assert 0.0 < sim.p_home_puck_line_minus15 <= sim.p_home_reg_win


def test_simulation_totals_lines():
    sim = A.simulate(3.1, 2.9, 1.0, 0.5, 0.5)
    over, under, push = sim.totals(5.5)
    assert push == 0.0
    assert over + under == pytest.approx(1.0, abs=1e-9)
    over6, under6, push6 = sim.totals(6.0)
    assert over6 + under6 + push6 == pytest.approx(1.0, abs=1e-9)
    assert push6 == pytest.approx(sim.final_total_pmf[6])
    r_over, r_under, _ = sim.totals(5.5, regulation_only=True)
    assert r_over + r_under == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Frozen path + end-to-end pricing
# ---------------------------------------------------------------------------

def test_frozen_constants_path_refuses_at_build():
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.params_from_constants()
    assert ei.value.code == "NHL_ATTEMPT2_NOT_FROZEN"
    assert "HALF_LIFE_GAMES" in ei.value.detail["missing"]


def league_rows():
    rows = []
    for d, (xgf, xga) in zip((20261010, 20261012, 20261014),
                             ((3.2, 2.6), (2.8, 3.1), (3.4, 2.9))):
        rows.append(trow("AAA", "BBB", 2026, d, xgf, xga))
        rows.append(trow("BBB", "AAA", 2026, d, xga, xgf))
    return rows


def league_goalies():
    return [grow("1", "AAA", 2026, 20261010, 3.0, 2.0),
            grow("1", "AAA", 2026, 20261012, 3.2, 3.0),
            grow("2", "BBB", 2026, 20261010, 2.8, 3.0),
            grow("2", "BBB", 2026, 20261012, 3.1, 2.0)]


def test_price_game_end_to_end_build_stage():
    price = A.price_game(league_rows(), league_goalies(), "AAA", "BBB",
                         20261016, params())
    sim = price.sim
    assert price.counted is False and price.frozen is False
    assert price.validation_credit is False and price.play_eligible is False
    assert price.degraded is True          # starters unconfirmed -> blend
    assert price.rows_used == 6
    assert price.mu_home > C.MIN_MEAN and price.mu_away > C.MIN_MEAN
    assert sim.p_home_ml + sim.p_away_ml == pytest.approx(1.0, abs=1e-9)
    over, under, _ = sim.totals(5.5)
    assert over + under == pytest.approx(1.0, abs=1e-9)


def test_price_game_no_prior_team_refused():
    with pytest.raises(A.Attempt2Refusal) as ei:
        A.price_game(league_rows(), league_goalies(), "AAA", "ZZZ",
                     20261016, params())
    assert ei.value.code == "NO_PRIOR_GAMES"


def test_loader_filters_situation_and_parses():
    dicts = [
        {"playerTeam": "AAA", "opposingTeam": "BBB", "season": "2026",
         "gameDate": "20261010", "home_or_away": "HOME", "situation": "all",
         "xGoalsFor": "3.0", "xGoalsAgainst": "2.0", "goalsFor": "3",
         "goalsAgainst": "2", "playoffGame": "0"},
        {"playerTeam": "AAA", "opposingTeam": "BBB", "season": "2026",
         "gameDate": "20261010", "home_or_away": "HOME",
         "situation": "5on5", "xGoalsFor": "2.0", "xGoalsAgainst": "1.0",
         "goalsFor": "2", "goalsAgainst": "1", "playoffGame": "0"},
    ]
    rows = A.team_rows_from_dicts(dicts)
    assert len(rows) == 1
    assert rows[0].xgoals_for == 3.0 and rows[0].vintage == "rebuilt_2026_27"
