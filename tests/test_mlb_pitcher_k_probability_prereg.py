import copy
import json
from pathlib import Path

import pytest

from sportsedge.mlb_pitcher_k_probability_prereg import (
    PitcherKProbabilityPreregError,
    validate_pitcher_k_probability_prereg,
)


PATH = Path("config/research/mlb_pitcher_k_probability_prereg_v1.json")


def _load():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_checked_in_pitcher_k_probability_prereg_is_frozen_and_zero_authority():
    report = validate_pitcher_k_probability_prereg(_load())
    assert report["ready_for_training_only_fit"] is True
    assert report["training_seasons"] == [2023]
    assert report["validation_seasons"] == [2024]
    assert report["candidate_test_seasons"] == [2025]
    assert not any(report["authority"].values())


def test_market_features_cannot_be_added_to_fit():
    value = _load()
    value["features"] = list(value["features"]) + ["draftkings_price"]
    with pytest.raises(PitcherKProbabilityPreregError, match="feature set changed|market feature"):
        validate_pitcher_k_probability_prereg(value)


def test_candidate_test_season_cannot_be_reused_for_tuning():
    value = _load()
    value["data"]["training_seasons"] = [2023, 2025]
    with pytest.raises(PitcherKProbabilityPreregError, match="season split"):
        validate_pitcher_k_probability_prereg(value)


def test_prereg_cannot_grant_model_or_release_authority():
    value = _load()
    value["authority"]["model_p"] = True
    with pytest.raises(PitcherKProbabilityPreregError, match="cannot grant authority"):
        validate_pitcher_k_probability_prereg(value)


def test_historical_candidate_test_is_explicitly_not_broader_promotion_evidence():
    value = copy.deepcopy(_load())
    value["candidate_test_is_broader_promotion_evidence"] = True
    # Wrong nesting cannot weaken the actual frozen data-level declaration.
    validate_pitcher_k_probability_prereg(value)
    value = _load()
    value["data"]["candidate_test_is_broader_promotion_evidence"] = True
    with pytest.raises(PitcherKProbabilityPreregError, match="cannot create promotion authority"):
        validate_pitcher_k_probability_prereg(value)
