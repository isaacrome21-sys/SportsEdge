"""Offline unit tests for MLB umpire assignment wiring (sportsedge/free_factors.py).

No network. Assignment extraction is tested with injected fixture dicts;
the fetch function is tested with a monkeypatched urlopen. Fail-closed
behavior is asserted, not just the happy path. Research only.
"""
import importlib.util
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


ff = _load("ff_umpire_unit", WORKTREE / "sportsedge" / "free_factors.py")


def _officials():
    return [
        {"officialType": "Home Plate",
         "official": {"id": 101, "fullName": "Manny Gonzalez"}},
        {"officialType": "First Base",
         "official": {"id": 102, "fullName": "James Jean"}},
        {"officialType": "Second Base",
         "official": {"id": 103, "fullName": "Scott Barry"}},
        {"officialType": "Third Base",
         "official": {"id": 104, "fullName": "Tom Hanahan"}},
    ]


def test_home_plate_extracted():
    a = ff.home_plate_assignment(777001, _officials())
    assert a is not None
    assert a["umpire_id"] == 101
    assert a["umpire_name"] == "Manny Gonzalez"
    assert a["game_pk"] == 777001
    assert a["source"] == ff.UMPIRE_ASSIGNMENT_SOURCE
    assert a["captured_at_utc"]  # timestamp recorded


def test_missing_home_plate_returns_none_no_crew_inference():
    # Crew rotation must NEVER be used to infer the home-plate umpire.
    others = [o for o in _officials() if o["officialType"] != "Home Plate"]
    assert len(others) == 3  # full crew minus home plate
    assert ff.home_plate_assignment(777001, others) is None


def test_empty_officials_returns_none():
    assert ff.home_plate_assignment(777001, []) is None
    assert ff.home_plate_assignment(777001, None) is None


def test_malformed_entries_skipped():
    officials = ["not-a-dict", {"officialType": "Home Plate"}]  # no official block
    assert ff.home_plate_assignment(777001, officials) is None


def test_home_plate_without_name_returns_none():
    officials = [{"officialType": "Home Plate", "official": {"id": 999}}]
    assert ff.home_plate_assignment(777001, officials) is None


def test_case_insensitive_official_type():
    officials = [{"officialType": "HOME PLATE",
                  "official": {"id": 101, "fullName": "Manny Gonzalez"}}]
    a = ff.home_plate_assignment(777001, officials)
    assert a is not None and a["umpire_name"] == "Manny Gonzalez"


def test_fetch_officials_by_game_parses_schedule(monkeypatch):
    import json

    payload = {"dates": [{"games": [
        {"gamePk": 777001, "officials": _officials()},
        {"gamePk": 777002, "officials": []},
    ]}]}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    import urllib.request as ureq
    monkeypatch.setattr(ureq, "urlopen", lambda req, timeout=None: FakeResp())
    by_game = ff.fetch_officials_by_game("2026-09-15")
    assert set(by_game) == {777001, 777002}
    assert len(by_game[777001]) == 4
    assert by_game[777002] == []


def test_fetch_officials_failure_raises(monkeypatch):
    import urllib.request as ureq

    def boom(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(ureq, "urlopen", boom)
    try:
        ff.fetch_officials_by_game("2026-09-15")
    except RuntimeError as exc:
        assert "UMPIRE_OFFICIALS_FETCH_FAILED" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on fetch failure")


def test_umpire_entry_pending_validation_no_pricing():
    e = ff.umpire_entry()
    assert e["status"] == "PENDING_VALIDATION"
    assert e["kind"] == "none"  # zero pricing effect
    assert e["verified"] is False
    assert e["value"] is None


def test_umpire_entry_with_assignment_names_umpire():
    a = ff.home_plate_assignment(777001, _officials())
    e = ff.umpire_entry(assignment=a)
    assert e["status"] == "PENDING_VALIDATION"
    assert e["kind"] == "none"  # still no pricing effect
    assert "Manny Gonzalez" in e["detail"]


def test_umpire_entry_unknown_assignment():
    e = ff.umpire_entry(assignment=None)
    assert e["status"] == "PENDING_VALIDATION"
    assert "UNKNOWN" in e["detail"]


def test_shrink_toward_league_average():
    # No observations -> league rate.
    assert ff.shrink_toward_league_average(0, 0.99, 0.50) == 0.50
    # Many observations -> observed rate dominates.
    v = ff.shrink_toward_league_average(10000, 0.60, 0.50)
    assert abs(v - 0.60) < 0.01
    # Few observations -> pulled strongly toward league rate.
    v = ff.shrink_toward_league_average(5, 0.90, 0.50, prior_weight=50.0)
    assert 0.50 < v < 0.60


def test_tendency_estimate_no_umpire_unknown():
    e = ff.umpire_tendency_estimate(None, [], 0.50)
    assert e["status"] == "PENDING_VALIDATION"
    assert e["kind"] == "none"
    assert "UNKNOWN" in e["detail"]


def test_tendency_estimate_structure_only_no_pricing():
    e = ff.umpire_tendency_estimate(101, [{"px": 0.1}] * 10, 0.50, era=2026)
    assert e["status"] == "PENDING_VALIDATION"
    assert e["kind"] == "none"
    assert e["verified"] is False


def test_tendency_estimate_flags_pre_abs_era():
    e = ff.umpire_tendency_estimate(101, [], 0.50, era=2024)
    assert "pre-ABS" in e["detail"]
    assert "harmonization" in e["detail"]


def test_factor_status_constant():
    assert ff.UMPIRE_FACTOR_STATUS == "PENDING_VALIDATION"
    assert ff.UMPIRE_ASSIGNMENT_SOURCE == "MLB_STATSAPI_OFFICIALS"
