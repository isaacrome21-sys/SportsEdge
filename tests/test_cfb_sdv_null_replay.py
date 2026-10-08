import copy
import json

import pytest

from scripts.replay_cfb_sdv_null_control import (
    aggregate, checkpoint, memoized_calls, read_checkpoint, shuffled_rows, write_once,
)
from sportsedge.sports.cfb import sportsdataverse_candidate_model as model
from sportsedge.sports.cfb.sportsdataverse_bakeoff import evaluate_native_candidates
from tests.test_cfb_sportsdataverse_bakeoff import CFG, rows


def test_memoized_evaluator_is_exactly_equal_to_frozen_evaluator():
    data = rows()
    shuffled = shuffled_rows(data, 37)
    original = model.feature_vector
    expected = [evaluate_native_candidates(r, CFG) for r in (data, shuffled)]
    with memoized_calls(data, CFG):
        actual = [evaluate_native_candidates(r, CFG) for r in (data, shuffled)]
        assert actual == expected
    assert model.feature_vector is original


def test_feature_change_is_rejected_and_functions_restored():
    data = rows()
    original = model.feature_vector
    with pytest.raises(ValueError, match="FEATURES_CHANGED"):
        with memoized_calls(data, CFG):
            changed = copy.deepcopy(data[0])
            changed["home_metrics"]["off_ppa_rush"] += 1
            model.feature_vector(model.FAMILIES[0], changed, {})
    assert model.feature_vector is original


def test_shuffles_preserve_season_pairs_and_features():
    data = rows()
    out = shuffled_rows(data, 12)
    assert out == shuffled_rows(data, 12)
    for season in {r["season"] for r in data}:
        pairs = lambda rs: sorted((r["home_points"], r["away_points"]) for r in rs if r["season"] == season)
        assert pairs(data) == pairs(out)
    for a, b in zip(data, out):
        assert {k:v for k,v in a.items() if k not in ("home_points", "away_points")} == {k:v for k,v in b.items() if k not in ("home_points", "away_points")}


def test_checkpoint_rejects_tamper_and_changed_identity(tmp_path):
    path = tmp_path / "rep.json"
    payload = checkpoint(2, {"value": 7}, {"rows": "abc"})
    write_once(path, payload)
    write_once(path, payload)
    assert read_checkpoint(path, 2, {"rows": "abc"}) == {"value": 7}
    with pytest.raises(ValueError, match="IDENTITY"):
        read_checkpoint(path, 3, {"rows": "abc"})
    payload["result"]["value"] = 8
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="IDENTITY"):
        read_checkpoint(path, 2, {"rows": "abc"})


def test_partial_null_cannot_select_winner():
    with pytest.raises(ValueError, match="ALL_200"):
        aggregate({}, {0: {}}, {})


def test_exact_frozen_quantile_and_no_baseline_fallback():
    families = list(model.FAMILIES)
    observed = {"selected_family": families[1], "observed": {f: {"selection_metric": 10.0} for f in families}}
    results = {i: copy.deepcopy(observed) for i in range(200)}
    out = aggregate(observed, results, {"candidate_families_predeclared": families})
    assert out["selected_family"] is None
    assert out["selection_status"] == "NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"
    observed["observed"][families[1]]["selection_metric"] = 9.0
    out = aggregate(observed, results, {"candidate_families_predeclared": families})
    assert out["selected_family"] == families[1]
