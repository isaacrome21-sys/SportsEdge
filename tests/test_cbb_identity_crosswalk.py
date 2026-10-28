"""Offline guards for the CBB team identity crosswalk packet.

These tests never touch the network and never read the data pulls.
They pin the crosswalk's invariants: a complete 365-team Torvik spine,
PR #2871's override table carried verbatim, total surface accounting
per source (resolved + unresolved = total, no surface in both), every
override and binding target present in the registry, the Illinois
capture exclusion flagged on exactly the downstream denylist schools,
the minted canonical ids limited to the declared set, and the fixture
proofs agreeing across all four sources. A final test exercises the
verifier's tripwire: a surface from a future pull that the artifact
neither resolves nor lists as unresolved is reported as unmapped.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_identity_crosswalk_20261028"
ART = json.loads((PACKET / "crosswalk.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "CROSSWALK_RECORD.md").read_text(encoding="utf-8")

# PR #2871's NORMALIZATION_OVERRIDES, pinned verbatim. An edit to the
# crosswalk that changes or drops one of these pairs must fail here
# until this test is amended in the same governed act.
PR2871_OVERRIDES = {
    "Albany": "albany-ny", "American University": "american",
    "BYU": "brigham-young", "Central Connecticut": "central-connecticut-state",
    "Cleveland St.": "cleveland-state", "Detroit": "detroit-mercy",
    "ETSU": "east-tennessee-state", "Fort Wayne": "ipfw",
    "Fort Wayne Mastodons": "ipfw", "LIU": "long-island-university",
    "LIU-Brooklyn": "long-island-university",
    "LIU-Brooklyn Blackbirds": "long-island-university",
    "LSU": "louisiana-state", "Nebraska Omaha": "nebraska-omaha",
    "Ole Miss": "mississippi", "Oregon St.": "oregon-state",
    "Penn": "pennsylvania", "Pitt": "pittsburgh",
    "Saint Mary's": "saint-marys-ca", "San Diego St.": "san-diego-state",
    "SIU-Edwardsville": "southern-illinois-edwardsville",
    "SMU": "southern-methodist", "Southern Miss": "southern-mississippi",
    "St. Joseph's": "saint-josephs", "St. Peter's": "saint-peters",
    "Texas St.": "texas-state", "UAlbany": "albany-ny",
    "UConn": "connecticut", "UIC": "illinois-chicago",
    "UMass": "massachusetts", "UMass-Lowell": "massachusetts-lowell",
    "UMBC": "maryland-baltimore-county", "UMKC": "missouri-kansas-city",
    "UNC": "north-carolina", "UNLV": "nevada-las-vegas",
    "USC": "southern-california", "USC Upstate": "south-carolina-upstate",
    "UCSB": "california-santa-barbara", "UT-Martin": "tennessee-martin",
    "VCU": "virginia-commonwealth", "Youngstown St.": "youngstown-state",
}
ILLINOIS_SLUGS = {
    "bradley", "chicago-state", "depaul", "eastern-illinois", "illinois",
    "illinois-chicago", "illinois-state", "loyola-il", "northern-illinois",
    "northwestern", "southern-illinois",
    "southern-illinois-edwardsville", "western-illinois",
}
ILLINOIS_ESPN_IDS = {
    "71", "77", "79", "82", "305", "356", "2130", "2197", "2287",
    "2350", "2459", "2565", "2710",
}
MINTED = {"Mercyhurst": "mercyhurst", "West Georgia": "west-georgia",
          "Le Moyne": "le-moyne", "New Haven": "new-haven",
          "West Florida": "west-florida"}
HISTORICAL_ONLY = {"hartford", "saint-francis-pa", "savannah-state",
                   "st-francis-ny"}


def _registry():
    return {t["canonical_id"]: t for t in ART["teams"]}


def test_artifact_is_identity_only():
    assert ART["artifact"] == "CBB_TEAM_IDENTITY_CROSSWALK_V1"
    assert ART["design_only"] is True
    assert ART["validation_credit"] is False
    assert ART["forward_clock_credit"] is False
    assert ART["play_eligible"] is False
    assert ART["sport"] == "CBB"


def test_spine_is_complete_and_unique():
    teams = ART["teams"]
    spine = [t for t in teams if t["spine_member"]]
    assert len(spine) == 365
    assert len({t["canonical_id"] for t in teams}) == len(teams) == 369
    assert all(t["torvik_name"] for t in spine)
    assert {t["canonical_id"] for t in teams if t["historical_only"]} == \
        HISTORICAL_ONLY
    # Every spine team carries an ESPN id: the Nov 1 pre-check joins on it.
    assert all(t["espn_id"] for t in spine)


def test_pr2871_overrides_carried_verbatim():
    assert len(PR2871_OVERRIDES) == 41
    for surface, slug in PR2871_OVERRIDES.items():
        entry = ART["overrides"][surface]
        assert entry["canonical"] == slug
        assert entry["origin"] == "PR2871"


def test_every_override_target_exists():
    registry = _registry()
    for entry in ART["overrides"].values():
        assert entry["canonical"] in registry
        assert entry["justification"]


def test_surface_accounting_is_total():
    registry = _registry()
    for source, cov in ART["coverage"].items():
        if source == "espn_team_ids":
            continue
        resolved = ART["source_surfaces"][source]
        unresolved = ART["unresolved"][source]
        assert len(resolved) + len(unresolved) == cov["surfaces_total"]
        assert cov["resolved"] == len(resolved)
        assert cov["unresolved"] == len(unresolved)
        assert not ({u["surface"] for u in unresolved} & set(resolved))
        for entry in resolved.values():
            assert entry["canonical"] in registry


def test_illinois_exclusion_flags():
    flagged = {t["canonical_id"] for t in ART["teams"]
               if t["capture_excluded_illinois"]}
    assert flagged == ILLINOIS_SLUGS
    for t in ART["teams"]:
        if t["capture_excluded_illinois"]:
            assert t["espn_id"] in ILLINOIS_ESPN_IDS
    assert set(ART["illinois_exclusion"]["flagged_canonicals"]) == flagged


def test_minted_ids_are_exactly_the_declared_set():
    assert ART["minted_canonical_ids"] == MINTED
    registry = _registry()
    for slug in MINTED.values():
        assert registry[slug]["canonical_id_origin"] == \
            "MINTED_NO_CBR_SLUG_IN_PINNED_SCOPE"
        assert registry[slug]["cbr_slug"] is None
        assert registry[slug]["spine_member"] is True


def test_ambiguous_surface_never_resolves_by_name():
    for source in ART["source_surfaces"].values():
        assert "Miami" not in source
    reasons = {u["surface"]: u["reason"]
               for u in ART["unresolved"]["espn_location"]}
    assert reasons["Miami"] == "AMBIGUOUS_SURFACE_NAME_ONLY_JOIN_FORBIDDEN"
    # Miami (FL) is still fully bound by id and display name.
    assert ART["id_bindings"]["espn_team_id"]["2390"]["canonical"] == "miami-fl"


def test_fixture_proofs_agree_across_sources():
    proofs = ART["fixture_proofs"]
    championships = [p for p in proofs if "canonical_pair" in p]
    assert len(championships) == 3
    for p in championships:
        assert p["all_sources_agree"] is True
        assert p["hoopr"]["scores"] == p["cbr_scores"]
        espn_scores = {c["canonical"]: c["score"]
                       for c in p["espn"]["competitors"]}
        assert espn_scores == p["cbr_scores"]
    forward = [p for p in proofs if "canonical_pair" not in p]
    assert len(forward) == 1
    rome = forward[0]
    assert rome["espn_event_id"] == "401920982"
    assert rome["forward_path_proven"] is True
    assert {c["canonical"] for c in rome["competitors"]} == \
        {"notre-dame", "villanova"}


def test_unmapped_surface_tripwire():
    spec = importlib.util.spec_from_file_location(
        "verify_crosswalk", PACKET / "verify_crosswalk.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.unmapped_surfaces(ART, "torvik", ["Duke", "Kansas"]) == []
    assert module.unmapped_surfaces(
        ART, "torvik", ["Duke", "Zzyzx State"]) == ["Zzyzx State"]
    # An unresolved-but-listed surface is accounted, not unmapped.
    assert module.unmapped_surfaces(ART, "espn_location", ["Miami"]) == []
    assert module.unmapped_surfaces(
        ART, "hoopr_location", ["Duke", "Zzyzx State"]) == ["Zzyzx State"]


def test_record_states_the_governing_limits():
    assert "NOT a source admission" in RECORD
    assert "Illinois" in RECORD and "exclusion applies downstream" in RECORD
    assert "UNRESOLVED" in RECORD
    assert "no fuzzy" in RECORD.lower() or "No fuzzy" in RECORD
