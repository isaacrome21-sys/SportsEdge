"""Fail-closed integrity checks for third-party DFS projection snapshots."""

from __future__ import annotations

import json

import pytest

from sportsedge.dfs.projections import ensure_projection_coverage, load_projection_snapshot
from sportsedge.dfs.types import DKPlayer, Projection


def player(player_id="42"):
    return DKPlayer(player_id, "Example Receiver", "DET", "GB", ("WR",), 5300)


def read(tmp_path, rows, players=None):
    file = tmp_path / "projection.json"
    file.write_text(json.dumps({"source": "EXTERNAL_RESEARCH", "players": rows}))
    return load_projection_snapshot(file, players or [player()], "NFL")


def test_valid_exact_id_and_ownership(tmp_path):
    projections = read(tmp_path, [{
        "player_id": "42", "mean": 15.2, "floor": 5.1, "ceiling": 24.9,
        "stddev": 5.2, "ownership": 0.117, "components": {"targets": 7.2},
    }])
    assert projections["42"].mean == 15.2
    assert projections["42"].ownership == 0.117


@pytest.mark.parametrize("bad,field", [
    (float("nan"), "mean"), (float("inf"), "mean"),
    ("nan", "mean"), (True, "mean"),
])
def test_nonfinite_or_boolean_mean_refused(tmp_path, bad, field):
    with pytest.raises(ValueError, match=f"DFS_PROJECTION_NUMBER_INVALID:42:{field}"):
        read(tmp_path, [{"player_id": "42", "mean": bad}])


@pytest.mark.parametrize("change,error", [
    ({"mean": -2.0}, "MEAN_NEGATIVE"),
    ({"stddev": float("nan")}, "NUMBER_INVALID"),
    ({"stddev": -1.2}, "STDDEV_NEGATIVE"),
    ({"floor": 18.0}, "QUANTILES_INVALID"),
    ({"ceiling": 9.0}, "QUANTILES_INVALID"),
    ({"ownership": 1.01}, "OWNERSHIP_OUT_OF_RANGE"),
    ({"ownership": float("inf")}, "NUMBER_INVALID"),
    ({"ownership": True}, "NUMBER_INVALID"),
    ({"components": {"targets": float("nan")}}, "NUMBER_INVALID"),
    ({"components": [1, 2]}, "COMPONENTS_INVALID"),
])
def test_malformed_external_projection_refused(tmp_path, change, error):
    with pytest.raises(ValueError, match=f"DFS_PROJECTION_{error}"):
        read(tmp_path, [{"player_id": "42", "mean": 15.0, **change}])


def test_duplicate_player_row_refused_instead_of_last_write_wins(tmp_path):
    with pytest.raises(ValueError, match="DFS_PROJECTION_DUPLICATE_PLAYER:42"):
        read(tmp_path, [
            {"player_id": "42", "mean": 15},
            {"name": "Example Receiver", "team": "DET", "mean": 25},
        ])


def test_name_lookup_works_with_single_pass_roster(tmp_path):
    file = tmp_path / "projection.json"
    file.write_text(json.dumps([{"name": "Example Receiver", "team": "DET", "mean": 12}]))
    projections = load_projection_snapshot(file, iter([player()]), "NFL")
    assert projections["42"].mean == 12


def test_ambiguous_team_name_requires_exact_dk_id(tmp_path):
    roster = [player("42"), player("99")]
    with pytest.raises(ValueError, match="DFS_PROJECTION_PLAYER_AMBIGUOUS"):
        read(tmp_path, [{"name": "Example Receiver", "team": "DET", "mean": 15}], roster)
    assert read(tmp_path, [{"player_id": "99", "mean": 16}], roster)["99"].mean == 16


def test_stats_path_with_nonfinite_component_is_refused(tmp_path):
    with pytest.raises(ValueError, match="DFS_PROJECTION_NUMBER_INVALID:42:mean"):
        read(tmp_path, [{"player_id": "42", "stats": {"rec_yards": float("nan")}}])


def test_stats_path_with_impossible_ownership_is_refused(tmp_path):
    with pytest.raises(ValueError, match="DFS_PROJECTION_OWNERSHIP_OUT_OF_RANGE:42"):
        read(tmp_path, [{"player_id": "42", "stats": {"receptions": 5, "ownership": 3.5}}])


def test_direct_projection_map_also_rejects_nonfinite_and_id_mismatch():
    with pytest.raises(ValueError, match="DFS_PROJECTION_NUMBER_INVALID:42:mean"):
        ensure_projection_coverage([player()], {"42": Projection("42", float("nan"), 25)},
                                   allow_dk_fppg_baseline=False)
    with pytest.raises(ValueError, match="DFS_PROJECTION_PLAYER_ID_MISMATCH"):
        ensure_projection_coverage([player()], {"42": Projection("99", 12, 20)},
                                   allow_dk_fppg_baseline=False)


@pytest.mark.parametrize("invalid", [float("inf"), float("nan"), True, -2.0])
def test_malformed_dk_fppg_fallback_is_not_admitted(invalid):
    p = DKPlayer("42", "Example Receiver", "DET", "GB", ("WR",), 5300,
                 dk_fppg=invalid)
    with pytest.raises(ValueError, match="DFS_(DK_FPPG_INVALID|PROJECTION_NUMBER_INVALID)"):
        ensure_projection_coverage([p], {}, allow_dk_fppg_baseline=True)
