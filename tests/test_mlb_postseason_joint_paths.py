"""Synthetic state-machine tests, not fitted parameters or validation evidence."""
from dataclasses import replace
import math
import random

import pytest

from sportsedge.dfs import mlb_joint_paths as joint
from sportsedge.research.mlb_joint_market_readout import read_joint_research_probability
from tests.test_dfs_mlb_joint_paths import _game, _profile, _row


def half(monkeypatch, events, *, rules="POSTSEASON", inning=9, away_score=0,
         offense="HOME", bullpen=False):
    game = replace(_game(), rules_mode=rules)
    script = iter(events)
    monkeypatch.setattr(joint.PlateAppearanceProfile, "sample", lambda self, rng: (next(script, "OUT"), 4))
    state = joint._GameState(away_score=away_score)
    starters = {
        "AWAY": joint._StarterState("AWY", "AWY-P", active=not bullpen),
        "HOME": joint._StarterState("HME", "HME-P", active=not bullpen),
    }
    hitters = {h.player_id: joint._HitterStats() for h in game.away.lineup + game.home.lineup}
    walkoff = joint._simulate_half_inning(
        game=game, game_state=state, starters=starters, hitters=hitters,
        offense_side=offense, inning=inning, rng=random.Random(2),
        walkoff_enabled=offense == "HOME" and inning >= 9,
    )
    return state, starters, hitters, walkoff


@pytest.mark.parametrize("rules,inning,runs", [
    ("REGULAR_SEASON", 10, 2), ("POSTSEASON", 10, 1), ("REGULAR_SEASON", 9, 1),
])
def test_extra_inning_runner_is_explicit(monkeypatch, rules, inning, runs):
    state, starters, _, _ = half(monkeypatch, ["HR"], rules=rules, inning=inning, offense="AWAY")
    assert state.away_score == runs
    assert starters["HOME"].earned_runs == 1  # placed runner is unearned


@pytest.mark.parametrize("hit", ["1B", "2B", "3B"])
def test_ordinary_walkoff_stops_at_winning_run_and_limits_hit_credit(monkeypatch, hit):
    state, starters, hitters, ended = half(monkeypatch, ["BB", "BB", "BB", hit])
    assert ended and state.home_score == 1
    assert sum(h.runs for h in hitters.values()) == 1
    assert sum(h.rbi for h in hitters.values()) == 1
    assert hitters["HME-H4"].singles == 1
    assert hitters["HME-H4"].doubles == hitters["HME-H4"].triples == 0
    assert starters["AWAY"].earned_runs == 1


def test_walkoff_home_run_counts_all_four(monkeypatch):
    state, _, hitters, ended = half(monkeypatch, ["BB", "BB", "BB", "HR"])
    assert ended and state.home_score == 4
    assert sum(h.runs for h in hitters.values()) == 4
    assert hitters["HME-H4"].rbi == 4
    assert hitters["HME-H4"].home_runs == 1


def test_nonwinning_homer_does_not_disable_later_walkoff_cap(monkeypatch):
    state, _, hitters, ended = half(monkeypatch, ["HR", "BB", "BB", "BB", "3B"], away_score=1)
    assert ended and state.home_score == 2
    assert hitters["HME-H5"].singles == 1
    assert hitters["HME-H5"].rbi == 1


def test_sacrifice_fly_on_third_out_cannot_score(monkeypatch):
    state, _, hitters, ended = half(monkeypatch, ["3B", "OUT", "OUT", "SAC_FLY"], away_score=10)
    assert not ended and state.home_score == 0
    assert sum(h.rbi for h in hitters.values()) == 0


def test_infinite_offense_fails_instead_of_hanging(monkeypatch):
    with pytest.raises(joint.MlbJointPathError, match="PA_LIMIT_UNRESOLVED"):
        half(monkeypatch, ["BB"] * 1001, offense="AWAY", bullpen=True)


def test_unresolved_ties_never_get_an_invented_winner(monkeypatch):
    monkeypatch.setattr(joint.PlateAppearanceProfile, "sample", lambda self, rng: ("OUT", 4))
    with pytest.raises(joint.MlbJointPathError, match="NOT_TERMINATED_BY_30_INNINGS"):
        joint.simulate_mlb_joint_paths(replace(_game(), rules_mode="POSTSEASON"), path_count=1, seed=2)


def test_missing_or_unknown_rules_rejected():
    with pytest.raises(joint.MlbJointPathError, match="RULES_MODE_REQUIRED"):
        replace(_game(), rules_mode="")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_input_probabilities_rejected(value):
    with pytest.raises(joint.MlbJointPathError, match="PROBABILITY_INVALID"):
        replace(_profile("synthetic"), outcome_probabilities={"OUT": value})


def test_rules_are_bound_to_path_identity():
    regular = joint.simulate_mlb_joint_paths(_game(), path_count=10, seed=7)
    postseason = joint.simulate_mlb_joint_paths(replace(_game(), rules_mode="POSTSEASON"), path_count=10, seed=7)
    assert regular.path_set_id != postseason.path_set_id


@pytest.fixture
def result():
    return joint.simulate_mlb_joint_paths(replace(_game(), rules_mode="POSTSEASON"), path_count=100, seed=47)


def test_final_scores_equal_player_runs_on_every_path(result):
    for i, final in enumerate(result.snapshot["game_samples"]):
        for side, prefix in (("away", "AWY"), ("home", "HME")):
            runs = sum(_row(result.snapshot, f"{prefix}-H{j}")["samples"][i]["runs"] for j in range(1, 10))
            assert runs == final[f"{side}_runs"]
        assert final["away_runs"] != final["home_runs"]


def test_all_game_readouts_share_paths_and_preserve_pushes(result):
    def read(market, side, line=None):
        return read_joint_research_probability(result, market=market, side=side, line=line)
    assert read("MONEYLINE", "HOME")["research_p"] + read("MONEYLINE", "AWAY")["research_p"] == pytest.approx(1)
    over, under = read("TOTALS", "OVER", 8), read("TOTALS", "UNDER", 8)
    assert over["research_p"] + under["research_p"] + over["push_p"] == pytest.approx(1)
    assert over["push_p"] == under["push_p"]
    home, away = read("RUN_LINE", "HOME", -1), read("RUN_LINE", "AWAY", 1)
    assert home["research_p"] + away["research_p"] + home["push_p"] == pytest.approx(1)
    assert home["path_set_id"] == over["path_set_id"] == result.path_set_id
    assert home["official_authority"] is False


@pytest.mark.parametrize("market", ["HITS", "TOTAL_BASES", "BATTER_K", "HITS_RUNS_RBIS"])
def test_hitter_props_use_same_samples_and_preserve_pushes(result, market):
    kwargs = dict(market=market, line=1, player_id="HME-H1")
    over = read_joint_research_probability(result, side="OVER", **kwargs)
    under = read_joint_research_probability(result, side="UNDER", **kwargs)
    assert over["research_p"] + under["research_p"] + over["push_p"] == pytest.approx(1)
    assert over["model_p_authority"] is False


@pytest.mark.parametrize("market", ["PITCHER_K", "PITCHER_OUTS", "PITCHER_HITS_ALLOWED", "PITCHER_ER"])
def test_pitcher_props_derive_from_starter_samples(result, market):
    readout = read_joint_research_probability(result, market=market, side="OVER", line=1.5, player_id="AWY-P")
    assert 0 <= readout["research_p"] <= 1
    assert readout["push_p"] == 0
    with pytest.raises(ValueError, match="COUNT_INVALID"):
        read_joint_research_probability(result, market=market, side="OVER", line=1.5, player_id="AWY-H1")


@pytest.mark.parametrize("market", ["STOLEN_BASES", "FIRST_HOME_RUN", "F5_TOTALS", "NRFI"])
def test_unsupported_market_does_not_become_a_zero_probability(result, market):
    with pytest.raises(ValueError, match="MARKET_UNSUPPORTED"):
        read_joint_research_probability(result, market=market, side="OVER", line=0.5, player_id="HME-H1")
