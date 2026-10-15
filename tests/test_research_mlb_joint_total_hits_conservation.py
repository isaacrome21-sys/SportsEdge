"""Conservation battery for the aligned-path Total Hits construction.

Independent regression evidence against the research candidate in
``sportsedge/research/mlb_joint_total_hits.py`` (PR #2334). The endogenous
joint simulator records, on every path, pitcher witnesses for the opposing
team's hits: ``opponent_team_hits`` and its decomposition
``hits_allowed + bullpen_hits_allowed``. The candidate reader identity-checks
the pitcher rows but never reads their samples, so batter totals are never
cross-checked against those witnesses. These tests assert the candidate
REFUSES (a named ``TOTAL_HITS_*`` ValueError) whenever the witnesses
contradict the batter sums, and that it accepts evidence that is consistent.

Positive controls (simulator self-conservation, the unmutated snapshot, the
correlated fixture with consistent witnesses, and the player-set refusals the
candidate already performs) prove the battery is green when the evidence is
sound; they are not weakened to manufacture the conservation failures.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from sportsedge.dfs.mlb_joint_paths import simulate_mlb_joint_paths
from sportsedge.research.mlb_joint_total_hits import read_joint_total_hits
from tests.test_dfs_mlb_joint_paths import _game

HIT_FIELDS = ("singles", "doubles", "triples", "home_runs")


@pytest.fixture(scope="module")
def paths():
    game = _game()
    return game, simulate_mlb_joint_paths(game, path_count=24, seed=71)


def _rows(result):
    return {r["player_id"]: r for r in result.snapshot["players"]}


def _team_hits(result, game, team):
    """Per-path summed batter hits for one team, from hitter rows only."""
    rows = _rows(result)
    ids = [h.player_id for t in (game.away, game.home) if t.team == team
           for h in t.lineup]
    return [sum(sum(rows[pid]["samples"][i][k] for k in HIT_FIELDS)
                for pid in ids)
            for i in range(result.path_count)]


def _read(result, game, **kwargs):
    args = dict(game=game, seed=71, market="GAME_TOTAL_HITS", side="OVER",
                line=14.5)
    args.update(kwargs)
    return read_joint_total_hits(result, **args)


def _mutated(paths, mutate):
    game, result = paths
    snapshot = deepcopy(result.snapshot)
    mutate(game, snapshot)
    return game, replace(result, snapshot=snapshot)


def _row(snapshot, player_id):
    return next(r for r in snapshot["players"] if r["player_id"] == player_id)


def _assert_refuses(paths, **kwargs):
    """The candidate must fail closed with a named TOTAL_HITS_* refusal.

    If it returns a readout instead, that readout IS the failure evidence:
    a distribution silently priced from contradictory evidence.
    """
    game, result = paths
    try:
        readout = _read(result, game, **kwargs)
    except ValueError as exc:
        assert "TOTAL_HITS" in str(exc), (
            f"refusal is not a named TOTAL_HITS_* failure: {exc!r}")
        return str(exc)
    raise AssertionError(
        "expected a named TOTAL_HITS_* refusal, but the candidate silently "
        f"priced a distribution: research_p={readout['research_p']}, "
        f"push_p={readout['push_p']}, count_pmf={readout['count_pmf']}, "
        f"readout_sha256={readout['readout_sha256']}")


# ---------------------------------------------------------------------------
# Positive controls: the battery is green when the evidence is consistent.
# ---------------------------------------------------------------------------

def test_simulated_paths_conserve_hits_end_to_end(paths):
    """Scaffolding control: the simulator's witnesses agree with batter sums.

    For every path, each starter's opponent_team_hits equals the opposing
    lineup's summed batter hits, and hits_allowed + bullpen_hits_allowed
    decomposes that same total. This proves the witness data the candidate
    ignores is present and coherent in the unmutated snapshot.
    """
    game, result = paths
    rows = _rows(result)
    for team_input, opp in ((game.away, game.home), (game.home, game.away)):
        opp_hits = [float(v) for v in _team_hits(result, game, opp.team)]
        witness = rows[team_input.starter_player_id]["samples"]
        assert [s["opponent_team_hits"] for s in witness] == opp_hits
        assert [s["hits_allowed"] + s["bullpen_hits_allowed"]
                for s in witness] == opp_hits


def test_unmutated_snapshot_is_accepted(paths):
    game, result = paths
    readout = _read(result, game)
    assert readout["validation_status"] == "UNVALIDATED_RESEARCH"
    assert readout["path_count"] == 24


def test_correlated_fixture_with_consistent_witnesses_is_accepted(paths):
    """Perfect-correlation fixture (as in the candidate's own suite), but with
    pitcher witnesses made consistent with the hitter outcomes: must pass."""
    def mutate(game, snapshot):
        for row in snapshot["players"]:
            samples = row["samples"]
            if "plate_appearances" not in samples[0]:
                continue
            for i, sample in enumerate(samples):
                sample.update(singles=i % 2, doubles=0, triples=0,
                              home_runs=0, plate_appearances=1)
        # Each opposing lineup now produces 9 hits on odd paths, 0 on even.
        # Split the witness 5 (starter) + 4 (bullpen) so the decomposition
        # is exercised as well as the total.
        for team_input in (game.away, game.home):
            for i, s in enumerate(_row(snapshot,
                                        team_input.starter_player_id)["samples"]):
                s["opponent_team_hits"] = float(9 * (i % 2))
                s["hits_allowed"] = float(5 * (i % 2))
                s["bullpen_hits_allowed"] = float(4 * (i % 2))

    game, result = _mutated(paths, mutate)
    rows = _rows(result)
    for team_input, opp in ((game.away, game.home), (game.home, game.away)):
        opp_hits = [float(v) for v in _team_hits(result, game, opp.team)]
        witness = rows[team_input.starter_player_id]["samples"]
        assert [s["opponent_team_hits"] for s in witness] == opp_hits
        assert [s["hits_allowed"] + s["bullpen_hits_allowed"]
                for s in witness] == opp_hits
    readout = _read(result, game, line=9)
    assert readout["count_pmf"] == {"0": .5, "18": .5}
    assert readout["research_p"] == .5


# ---------------------------------------------------------------------------
# Item 1: batter-pitcher conservation — opponent_team_hits witness.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("starter,path_index,delta", [
    ("HME-P", 0, 1),    # AWAY batters scored 5 on path 0; witness claims 6
    ("AWY-P", 7, 2),    # HME batters scored 6 on path 7; witness claims 8
    ("HME-P", 23, -1),  # AWAY batters scored 10 on path 23; witness claims 9
])
def test_opponent_team_hits_contradiction_must_refuse(paths, starter,
                                                      path_index, delta):
    def mutate(game, snapshot):
        _row(snapshot, starter)["samples"][path_index][
            "opponent_team_hits"] += delta

    _assert_refuses(_mutated(paths, mutate))


def test_team_market_witness_contradiction_must_refuse(paths):
    """Same contradiction, read through the TEAM_TOTAL_HITS market."""
    def mutate(game, snapshot):
        _row(snapshot, "HME-P")["samples"][0]["opponent_team_hits"] += 1

    game, result = _mutated(paths, mutate)
    _assert_refuses((game, result), market="TEAM_TOTAL_HITS",
                    team=game.away.team)


# ---------------------------------------------------------------------------
# Item 2: pitcher decomposition — hits_allowed + bullpen_hits_allowed.
# ---------------------------------------------------------------------------

def test_hits_allowed_decomposition_contradiction_must_refuse(paths):
    """opponent_team_hits left intact; the decomposition no longer sums."""
    def mutate(game, snapshot):
        _row(snapshot, "AWY-P")["samples"][3]["hits_allowed"] += 1

    _assert_refuses(_mutated(paths, mutate))


def test_bullpen_decomposition_contradiction_must_refuse(paths):
    def mutate(game, snapshot):
        _row(snapshot, "HME-P")["samples"][5]["bullpen_hits_allowed"] += 1

    _assert_refuses(_mutated(paths, mutate))


# ---------------------------------------------------------------------------
# Item 3: adversarial batter mutation with pitcher evidence unchanged.
# ---------------------------------------------------------------------------

def test_batter_hit_added_without_witness_update_must_refuse(paths):
    """AWY-H1 on path 0 has 1 hit in 4 PA; a second single keeps hits <= PA,
    passes every per-hitter check the candidate performs, and contradicts
    the unchanged pitcher witness (HME-P still records 5 AWAY hits)."""
    def mutate(game, snapshot):
        _row(snapshot, "AWY-H1")["samples"][0]["singles"] += 1

    _assert_refuses(_mutated(paths, mutate))


def test_batter_hit_removed_without_witness_update_must_refuse(paths):
    """AWY-H1 has a single on path 4; removing it leaves the witness
    claiming one more AWAY hit than the batters now record."""
    def mutate(game, snapshot):
        _row(snapshot, "AWY-H1")["samples"][4]["singles"] -= 1

    _assert_refuses(_mutated(paths, mutate))


# ---------------------------------------------------------------------------
# Item 4: path alignment — swaps, missing/extended samples, row counts.
# ---------------------------------------------------------------------------

def test_swapped_path_indices_in_one_hitter_row_must_refuse(paths):
    """AWY-H1 recorded 1 hit on path 0 and 0 on path 1. Swapping the two
    samples inside that row alone desynchronises the paths: the per-path
    team totals change while every pitcher witness stays put."""
    def mutate(game, snapshot):
        samples = _row(snapshot, "AWY-H1")["samples"]
        samples[0], samples[1] = samples[1], samples[0]

    _assert_refuses(_mutated(paths, mutate))


def test_pitcher_samples_truncated_must_refuse(paths):
    """A pitcher row with path_count - 1 samples is missing evidence."""
    def mutate(game, snapshot):
        _row(snapshot, "HME-P")["samples"].pop()

    _assert_refuses(_mutated(paths, mutate))


def test_pitcher_samples_extended_must_refuse(paths):
    """A pitcher row with path_count + 1 samples is inconsistent evidence."""
    def mutate(game, snapshot):
        samples = _row(snapshot, "AWY-P")["samples"]
        samples.append(deepcopy(samples[0]))

    _assert_refuses(_mutated(paths, mutate))


def test_missing_pitcher_row_refuses_by_name(paths):
    """Already-correct behaviour, kept as a control: dropping a pitcher row
    breaks the exact player set and the candidate refuses today."""
    def mutate(game, snapshot):
        snapshot["players"] = [r for r in snapshot["players"]
                                if r["player_id"] != "AWY-P"]

    name = _assert_refuses(_mutated(paths, mutate))
    assert name == "TOTAL_HITS_PLAYER_SET_INVALID"


def test_duplicate_pitcher_row_refuses_by_name(paths):
    """Already-correct behaviour, kept as a control."""
    def mutate(game, snapshot):
        snapshot["players"].append(deepcopy(_row(snapshot, "HME-P")))

    name = _assert_refuses(_mutated(paths, mutate))
    assert name == "TOTAL_HITS_PLAYER_SET_INVALID"
