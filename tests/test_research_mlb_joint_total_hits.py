"""Synthetic construction tests; no historical performance evidence."""
from copy import deepcopy
from dataclasses import replace

import pytest

from sportsedge.dfs.mlb_joint_paths import simulate_mlb_joint_paths
from sportsedge.research.mlb_joint_total_hits import read_joint_total_hits
from tests.test_dfs_mlb_joint_paths import _game


@pytest.fixture
def paths():
    game = _game()
    return game, simulate_mlb_joint_paths(game, path_count=24, seed=71)


def read(paths, **kwargs):
    game, result = paths
    args = dict(game=game, seed=71, market="GAME_TOTAL_HITS", side="OVER", line=14.5)
    args.update(kwargs)
    return read_joint_total_hits(result, **args)


def test_exact_pathwise_sum_and_complement(paths):
    game, result = paths
    rows = result.snapshot["players"]
    hitter_ids = {h.player_id for t in (game.away, game.home) for h in t.lineup}
    values = [sum(sum(r["samples"][i][k] for k in ("singles", "doubles", "triples", "home_runs"))
                  for r in rows if r["player_id"] in hitter_ids) for i in range(24)]
    for line in (0, 7.5, 14, 14.5, 100):
        over, under = read(paths, line=line), read(paths, line=line, side="UNDER")
        assert over["research_p"] == sum(v > line for v in values) / 24
        assert over["push_p"] == sum(v == line for v in values) / 24
        assert over["research_p"] + under["research_p"] + over["push_p"] == pytest.approx(1)
        assert sum(over["count_pmf"].values()) == pytest.approx(1)
        assert not over["production_ready"] and not over["model_p_authority"]


def test_team_means_sum_to_game_and_ladders_monotone(paths):
    game, _ = paths
    def mean(r):
        return sum(int(k) * p for k, p in r["count_pmf"].items())
    a = read(paths, market="TEAM_TOTAL_HITS", team=game.away.team)
    h = read(paths, market="TEAM_TOTAL_HITS", team=game.home.team)
    assert mean(a) + mean(h) == pytest.approx(mean(read(paths)))
    probs = [read(paths, line=x + .5)["research_p"] for x in range(30)]
    assert probs == sorted(probs, reverse=True)


def test_dependence_is_preserved_not_convolved(paths):
    game, result = paths
    snapshot = deepcopy(result.snapshot)
    # Perfect positive dependence: all hitters hit on the same 12 paths.
    for row in snapshot["players"]:
        if "plate_appearances" not in row["samples"][0]:
            continue
        for i, sample in enumerate(row["samples"]):
            sample.update(singles=i % 2, doubles=0, triples=0, home_runs=0, plate_appearances=1)
    r = read((game, replace(result, snapshot=snapshot)), line=9)
    assert r["count_pmf"] == {"0": .5, "18": .5}
    assert r["research_p"] == .5 and r["push_p"] == 0


@pytest.mark.parametrize("bad", [True, None, -1, float("inf"), float("nan"), "14.5"])
def test_bad_line(paths, bad):
    with pytest.raises(ValueError, match="SIDE_OR_LINE"):
        read(paths, line=bad)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "team", "path", "length", "negative", "fraction", "bool", "pa"])
def test_damaged_hitter_evidence_refuses(paths, kind):
    game, result = paths
    s = deepcopy(result.snapshot)
    row = s["players"][0]
    if kind == "missing": s["players"].pop(0)
    elif kind == "duplicate": s["players"].append(deepcopy(row))
    elif kind == "team": row["team"] = "OTHER"
    elif kind == "path": row["path_set_id"] = "OTHER"
    elif kind == "length": row["samples"].pop()
    else:
        row["samples"][0]["singles"] = {"negative": -1, "fraction": .5, "bool": True, "pa": 999}[kind]
    with pytest.raises(ValueError, match="TOTAL_HITS"):
        read((game, replace(result, snapshot=s)))


@pytest.mark.parametrize("overrides", [dict(seed=72), dict(team="AWY"), dict(market="TEAM_TOTAL_HITS"), dict(side="YES"), dict(market="TOTALS")])
def test_identity_and_selection_refuse(paths, overrides):
    with pytest.raises(ValueError, match="TOTAL_HITS"):
        read(paths, **overrides)


def test_deterministic_and_inputs_unchanged(paths):
    before = deepcopy(paths[1].snapshot)
    assert read(paths) == read(paths)
    assert paths[1].snapshot == before
