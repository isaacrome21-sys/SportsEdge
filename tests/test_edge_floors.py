import pytest

from sportsedge.edge_floors import EdgeFloorError, require_frozen_edge_floor


def _cfg(record=None):
    floors = {} if record is None else {"MLB_MONEYLINE": record}
    return {"truth_gate": {"edge_floors": floors}}


def _frozen(value="0.02"):
    return {
        "status": "FROZEN",
        "value_probability_points": value,
        "method_version": "oos_edge_floor_v1",
        "evidence": {
            "evidence_sha256": "e" * 64,
            "derivation_code_sha256": "d" * 64,
            "oos_cutoff_utc": "2026-08-01T00:00:00Z",
        },
        "frozen": {"frozen_by_commit": "a" * 40},
    }


def test_missing_market_fails_closed():
    with pytest.raises(EdgeFloorError):
        require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg())


def test_unproven_market_fails_closed():
    with pytest.raises(EdgeFloorError):
        require_frozen_edge_floor(
            market="MLB_MONEYLINE",
            config=_cfg({"status": "UNPROVEN", "value_probability_points": None}),
        )


@pytest.mark.parametrize("value", [0, 0.0, "0", -0.01, "-0.02", None, "nan", "inf"])
def test_nonpositive_or_invalid_floor_is_rejected(value):
    with pytest.raises(EdgeFloorError):
        require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(_frozen(value)))


def test_frozen_floor_requires_evidence_hashes_and_cutoff():
    record = _frozen()
    del record["evidence"]["evidence_sha256"]
    with pytest.raises(EdgeFloorError):
        require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(record))


def test_valid_frozen_floor_resolves_positive_value():
    floor = require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(_frozen("0.021")))
    assert str(floor.value_probability_points) == "0.021"
