"""Synthetic construction tests; no historical performance evidence."""
from copy import deepcopy
from dataclasses import replace

import pytest

from sportsedge.dfs.mlb_joint_paths import simulate_mlb_joint_paths
from sportsedge.research.mlb_joint_hr_hrr import read_joint_hr_hrr, validate_run_conservation
from sportsedge.research.mlb_joint_market_readout import read_joint_research_probability
from tests.test_dfs_mlb_joint_paths import _game

N, SEED = 300, 11


@pytest.fixture(scope="module")
def paths():
    game = _game()
    return game, simulate_mlb_joint_paths(game, path_count=N, seed=SEED)


def _pid(game):
    return game.away.lineup[2].player_id


def _mutate(result, fn):
    snap = deepcopy(result.snapshot)
    fn(snap)
    return replace(result, snapshot=snap)


def test_simulator_paths_conserve_runs(paths):
    game, result = paths
    assert len(validate_run_conservation(result, game=game, seed=SEED)) == 18


def test_marginals_match_existing_readout_and_joint_is_consistent(paths):
    game, result = paths
    pid = _pid(game)
    r = read_joint_hr_hrr(result, game=game, seed=SEED, player_id=pid, hrr_line=1.5)
    ref = read_joint_research_probability(result, market="HITS_RUNS_RBIS", side="OVER",
                                          line=1.5, player_id=pid)
    assert r["p_hrr_over"] == ref["research_p"]
    ref_hr = read_joint_research_probability(result, market="HOME_RUNS", side="OVER",
                                             line=0.5, player_id=pid)
    assert r["p_home_runs_at_least"] == ref_hr["research_p"]
    assert sum(r["joint_pmf_hr_hrr"].values()) == pytest.approx(1)
    assert r["p_hrr_over"] + r["p_hrr_under"] + r["p_hrr_push"] == pytest.approx(1)
    assert r["p_joint_hr_and_hrr_over"] <= min(r["p_home_runs_at_least"], r["p_hrr_over"])
    # A HR alone contributes H+R+RBI >= 3, so HR>=1 implies H+R+RBI > 2.5.
    r3 = read_joint_hr_hrr(result, game=game, seed=SEED, player_id=pid, hrr_line=2.5)
    assert r3["p_joint_hr_and_hrr_over"] == r3["p_home_runs_at_least"]
    for k in r["joint_pmf_hr_hrr"]:
        hr, hrr = map(int, k.split(","))
        assert hrr >= 3 * hr
    assert not r["production_ready"] and not r["promotion_authority"]


def test_deterministic(paths):
    game, result = paths
    a = read_joint_hr_hrr(result, game=game, seed=SEED, player_id=_pid(game), hrr_line=1.5)
    b = read_joint_hr_hrr(result, game=game, seed=SEED, player_id=_pid(game), hrr_line=1.5)
    assert a["readout_sha256"] == b["readout_sha256"]


def _first_hitter(snap, game):
    return next(p for p in snap["players"] if p["player_id"] == _pid(game))


@pytest.mark.parametrize("mutation,code", [
    (lambda s, g: s["game_samples"][0].update(away_runs=s["game_samples"][0]["away_runs"] + 1),
     "HRR_RUN_CONSERVATION_MISMATCH"),
    (lambda s, g: _first_hitter(s, g)["samples"][0].update(runs=_first_hitter(s, g)["samples"][0]["runs"] + 1),
     "HRR_RUN_CONSERVATION_MISMATCH"),
    (lambda s, g: _first_hitter(s, g)["samples"][0].update(rbi=99.0), "HRR_RBI_EXCEEDS_RUNS"),
    (lambda s, g: _first_hitter(s, g)["samples"][0].update(home_runs=1.0, runs=0.0, plate_appearances=20.0),
     "HRR_HOME_RUN_ACCOUNTING_MISMATCH"),
    (lambda s, g: _first_hitter(s, g)["samples"][0].update(runs=1.5), "HRR_COUNT_INVALID"),
    (lambda s, g: _first_hitter(s, g)["samples"][0].update(runs=True), "HRR_COUNT_INVALID"),
    (lambda s, g: _first_hitter(s, g)["samples"][0].update(rbi=float("nan")), "HRR_COUNT_INVALID"),
    (lambda s, g: _first_hitter(s, g)["samples"].pop(), "HRR_PLAYER_SAMPLES_MISSING"),
    (lambda s, g: s["players"].remove(_first_hitter(s, g)), "HRR_PLAYER_SET_INVALID"),
    (lambda s, g: s["players"].append(deepcopy(_first_hitter(s, g))), "HRR_PLAYER_DUPLICATE"),
    (lambda s, g: _first_hitter(s, g).update(team="ZZZ"), "HRR_PLAYER_IDENTITY_MISMATCH"),
    (lambda s, g: s.update(game_id="other"), "HRR_PATH_IDENTITY_MISMATCH"),
    (lambda s, g: s["game_samples"].pop(), "HRR_GAME_SAMPLES_MISSING"),
])
def test_refusals(paths, mutation, code):
    game, result = paths
    bad = _mutate(result, lambda s: mutation(s, game))
    with pytest.raises(ValueError, match=code):
        read_joint_hr_hrr(bad, game=game, seed=SEED, player_id=_pid(game), hrr_line=1.5)


@pytest.mark.parametrize("kw,code", [
    (dict(seed=SEED + 1), "HRR_PATH_IDENTITY_MISMATCH"),
    (dict(seed=True), "HRR_SEED_INVALID"),
    (dict(player_id="nobody"), "HRR_PLAYER_NOT_IN_LINEUP"),
    (dict(hrr_line=float("inf")), "HRR_LINE_INVALID"),
    (dict(hrr_line=-1), "HRR_LINE_INVALID"),
    (dict(hr_at_least=0), "HRR_HR_THRESHOLD_INVALID"),
    (dict(hr_at_least=True), "HRR_HR_THRESHOLD_INVALID"),
])
def test_argument_refusals(paths, kw, code):
    game, result = paths
    args = dict(game=game, seed=SEED, player_id=_pid(game), hrr_line=1.5)
    args.update(kw)
    with pytest.raises(ValueError, match=code):
        read_joint_hr_hrr(result, **args)


def test_starter_pitcher_is_not_a_hitter(paths):
    game, result = paths
    with pytest.raises(ValueError, match="HRR_PLAYER_NOT_IN_LINEUP"):
        read_joint_hr_hrr(result, game=game, seed=SEED,
                          player_id=game.away.starter_player_id, hrr_line=1.5)
