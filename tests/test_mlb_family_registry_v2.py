"""RED: PITCHER_PITCHES gets a versioned v2 registration that leaves the
frozen v1 catalog and the pinned PITCHER_WORKLOAD evidence set untouched."""
import hashlib
import json
from pathlib import Path

import pytest

from sportsedge import prop_evidence
from sportsedge.mlb_family_registry_v2 import (
    REGISTRY_V2,
    V1_CATALOG_SHA256,
    evidence_dependencies_v2,
    load_registry_v2,
    settle_pitcher_pitches,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v1_catalog_bytes_frozen():
    raw = (ROOT / "config/mlb_market_catalog.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V1_CATALOG_SHA256
    assert "PITCHER_PITCHES" not in json.loads(raw)["pitcher_markets"]


def test_v1_workload_set_unchanged():
    assert "PITCHER_PITCHES" not in prop_evidence.MARKET_EVIDENCE_DEPENDENCIES
    assert prop_evidence.MARKET_EVIDENCE_DEPENDENCIES["PITCHER_OUTS"] == frozenset(
        {prop_evidence.PITCHER_WORKLOAD})


def test_v2_is_superset_and_uses_new_group():
    v2 = evidence_dependencies_v2()
    for k, v in prop_evidence.MARKET_EVIDENCE_DEPENDENCIES.items():
        assert v2[k] == v
    assert v2["PITCHER_PITCHES"] == frozenset({"PITCHER_PITCH_COUNT_V2"})
    assert prop_evidence.PITCHER_WORKLOAD not in v2["PITCHER_PITCHES"]


def test_registration_is_research_only_and_non_promotable():
    fam = load_registry_v2()["families"]["PITCHER_PITCHES"]
    assert fam["status"] == "RESEARCH_ONLY"
    assert fam["promotable"] is False
    assert fam["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert fam["evidence"]["M29"]["verdict"] == "DOES_NOT_BEAT_BASELINE"
    assert fam["one_sided_no_vig"] == "UNAVAILABLE"
    assert fam["settlement_field"] == "numberOfPitches"


def test_registry_file_matches_module():
    on_disk = json.loads((ROOT / "config/mlb_family_registry_v2.json").read_text())
    assert on_disk == REGISTRY_V2


@pytest.mark.parametrize("stat,line,side,expect", [
    ({"numberOfPitches": 95}, 92.5, "OVER", "WIN"),
    ({"numberOfPitches": 90}, 92.5, "OVER", "LOSS"),
    ({"numberOfPitches": 92}, 92.0, "UNDER", "PUSH"),
    ({"numberOfPitches": 80}, 92.5, "UNDER", "WIN"),
])
def test_settlement_from_official_count(stat, line, side, expect):
    assert settle_pitcher_pitches(stat, line, side) == expect


@pytest.mark.parametrize("stat", [{}, {"numberOfPitches": None}, {"numberOfPitches": True},
                                  {"numberOfPitches": 90.5}, {"numberOfPitches": -1},
                                  {"pitchesThrown": 90}])
def test_settlement_refuses_missing_or_bad_count(stat):
    with pytest.raises(ValueError):
        settle_pitcher_pitches(stat, 92.5, "OVER")


def test_settlement_refuses_bad_side():
    with pytest.raises(ValueError):
        settle_pitcher_pitches({"numberOfPitches": 90}, 92.5, "YES")
