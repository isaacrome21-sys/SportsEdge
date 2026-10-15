import math

import pytest

from sportsedge.research.mlb_joint_team_runs import (
    MODE_SHARED_PACE_NB, JointTeamRunsError, build_joint_team_runs, ladder, marginal_means, read_market,
)
from sportsedge.shared_game_engine import build_shared_game_engine_session
from sportsedge.v7_distribution import (
    V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN, V8_INDEPENDENT_TEAM_DISPERSION_R,
    calibrated_full_game_means, simulate_game_distribution,
)

A, H = 4.3, 4.7


@pytest.fixture(scope="module")
def ind():
    return build_joint_team_runs(away_mean_runs=A, home_mean_runs=H)


@pytest.fixture(scope="module")
def shared():
    return build_joint_team_runs(away_mean_runs=A, home_mean_runs=H, mode=MODE_SHARED_PACE_NB, shared_pace_r=20.0)


def _sum_where(d, pred):
    return sum(p for k, p in d["joint_score_pmf"].items() if pred(*map(int, k.split(","))))


@pytest.mark.parametrize("name", ["ind", "shared"])
def test_normalized_no_ties_research_flags(name, request):
    d = request.getfixturevalue(name)
    assert abs(sum(d["joint_score_pmf"].values()) - 1.0) < 1e-9
    assert all(a != h for a, h in (map(int, k.split(",")) for k in d["joint_score_pmf"]))
    assert d["research_only"] is True and d["eligible"] is False


def test_marginal_means_preserved(ind, shared):
    # Regulation means are preserved exactly; extras add ~0.1 run on average.
    for d in (ind, shared):
        a, h = marginal_means(d)
        assert A < a < A + 0.25 and H < h < H + 0.25
    assert abs(marginal_means(ind)[0] - marginal_means(shared)[0]) < 0.01


@pytest.mark.parametrize("name", ["ind", "shared"])
def test_moneyline_sums_to_one_without_push(name, request):
    d = request.getfixturevalue(name)
    h = read_market(d, market="MONEYLINE", side="HOME")
    a = read_market(d, market="MONEYLINE", side="AWAY")
    assert h["push_probability"] == 0.0 and abs(h["probability"] + a["probability"] - 1) < 1e-9


@pytest.mark.parametrize("line", [7.0, 8.0, 9.0])
def test_totals_integer_push_equals_point_mass(ind, line):
    o = read_market(ind, market="TOTALS", side="OVER", line=line)
    u = read_market(ind, market="TOTALS", side="UNDER", line=line)
    point = _sum_where(ind, lambda a, h: a + h == line)
    assert point > 0.05
    assert abs(o["push_probability"] - point) < 1e-12
    assert abs(o["probability"] + u["probability"] + point - 1) < 1e-9


def test_half_lines_have_zero_push(ind):
    for m, s, kw in (("TOTALS", "OVER", {}), ("RUN_LINE", "HOME", {}), ("TEAM_TOTALS", "OVER", {"team_side": "HOME"})):
        assert read_market(ind, market=m, side=s, line=-1.5 if m == "RUN_LINE" else 4.5, **kw)["push_probability"] == 0.0


def test_run_line_integer_push_and_complement(ind):
    hm1 = read_market(ind, market="RUN_LINE", side="HOME", line=-1.0)
    ap1 = read_market(ind, market="RUN_LINE", side="AWAY", line=1.0)
    assert abs(hm1["push_probability"] - _sum_where(ind, lambda a, h: h - a == 1)) < 1e-12
    assert abs(hm1["probability"] + ap1["probability"] + hm1["push_probability"] - 1) < 1e-9
    # +-1.5 complement
    h = read_market(ind, market="RUN_LINE", side="HOME", line=-1.5)["probability"]
    a = read_market(ind, market="RUN_LINE", side="AWAY", line=1.5)["probability"]
    assert abs(h + a - 1) < 1e-9


def test_alternate_ladders_monotone(ind, shared):
    lines = [x / 2 for x in range(5, 31)]
    for d in (ind, shared):
        over = [r["probability"] for r in ladder(d, market="TOTALS", side="OVER", lines=lines)]
        assert all(x >= y for x, y in zip(over, over[1:])) and over[0] > over[-1]
        tt = [r["probability"] for r in ladder(d, market="TEAM_TOTALS", side="UNDER", lines=[x / 2 for x in range(1, 20)], team_side="AWAY")]
        assert all(x <= y for x, y in zip(tt, tt[1:]))
        rl = [r["probability"] for r in ladder(d, market="RUN_LINE", side="HOME", lines=[-4.5, -3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5])]
        assert all(x <= y for x, y in zip(rl, rl[1:]))


def test_team_totals_coherent_with_game_pmf(ind):
    for line in (3.5, 4.0, 5.5):
        o = read_market(ind, market="TEAM_TOTALS", side="OVER", line=line, team_side="HOME")
        assert abs(o["probability"] - _sum_where(ind, lambda a, h: h > line)) < 1e-12


def test_shared_pace_induces_positive_correlation(ind, shared):
    def cov(d):
        ma, mh = marginal_means(d)
        return sum(
            p * (int(k.split(",")[0]) - ma) * (int(k.split(",")[1]) - mh) for k, p in d["joint_score_pmf"].items())
    assert cov(shared) > cov(ind) + 0.3


def test_agrees_with_production_mc_simulator(ind):
    mc = simulate_game_distribution(away_mean_runs=A, home_mean_runs=H, total_line=8.5, simulations=200000, seed=11,
                                    shared_game_sigma=0.0, team_sigma=0.0, team_dispersion_r=V8_INDEPENDENT_TEAM_DISPERSION_R,
                                    extra_half_inning_mean=V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN)
    tol = 4 * math.sqrt(0.25 / 200000)
    assert abs(mc.home_win_probability - read_market(ind, market="MONEYLINE", side="HOME")["probability"]) < tol
    assert abs(mc.over_probability - read_market(ind, market="TOTALS", side="OVER", line=8.5)["probability"]) < tol
    assert abs(mc.home_minus_1_5_probability - read_market(ind, market="RUN_LINE", side="HOME", line=-1.5)["probability"]) < tol
    assert abs(mc.regulation_tie_probability - ind["regulation_tie_probability"]) < tol


def test_agrees_with_existing_team_total_engine():
    engine = build_shared_game_engine_session()
    sa, sh = calibrated_full_game_means(4.1, 4.9)
    d = build_joint_team_runs(away_mean_runs=sa, home_mean_runs=sh)
    tol = 4 * math.sqrt(0.25 / 100000)
    for team_side, line in (("HOME", 4.5), ("AWAY", 3.5), ("HOME", 5.0)):
        prod = engine({"market": "TEAM_TOTALS", "game_id": "g1", "away_mean_runs": 4.1, "home_mean_runs": 4.9,
                       "line": line, "side": "OVER", "team_side": team_side, "feature_source_hash": "x"})
        mine = read_market(d, market="TEAM_TOTALS", side="OVER", line=line, team_side=team_side)
        assert abs(prod["model_p"] - mine["probability"]) < tol
        assert abs(prod["push_p"] - mine["push_probability"]) < tol


@pytest.mark.parametrize("kw,reason", [
    ({"away_mean_runs": "4"}, "NOT_NUMERIC"), ({"away_mean_runs": True}, "NOT_NUMERIC"),
    ({"away_mean_runs": float("nan")}, "FINITE"), ({"away_mean_runs": -1.0}, "FINITE"),
    ({"away_mean_runs": 40.0}, "OUT_OF_RANGE"), ({"mode": "X"}, "MODE"),
    ({"mode": MODE_SHARED_PACE_NB}, "SHARED_PACE_R_REQUIRED"), ({"shared_pace_r": 5.0}, "ONLY_FOR_SHARED"),
    ({"team_dispersion_r": None}, "NOT_NUMERIC"),
])
def test_fail_closed_inputs(kw, reason):
    args = {"away_mean_runs": A, "home_mean_runs": H, **kw}
    with pytest.raises(JointTeamRunsError, match=reason):
        build_joint_team_runs(**args)


def test_not_registered_in_live_engine_registry():
    from sportsedge import engine_registry
    import inspect
    assert "mlb_joint_team_runs" not in inspect.getsource(engine_registry)
