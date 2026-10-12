"""Umpire + weather refinement tests (X-account review items 1-2, Bucket A).

Item 1 (umpscorecards.com): pins the probe finding -- the frontend data path
is Patreon-gated, so there is NO keyless stable umpire feed and the factor
stays NOT_WIRED/MISSING. If the site ever opens a keyless path, this fixture
and test must be revisited.
Item 2 (MySportsWeather calibration): recorded-fixture unit tests for the
declared weather interaction terms (MLB temp/humidity x park, NFL wind x
pass rate) plus fail-closed paths. Harness OOS validation runs separately
via scripts/validate_free_factors.py (weather | weather_interaction).

No network. Research only.
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
HARNESS = Path("/home/hatch/workspace/sportsedge-backtest")


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


ff = _load("uw_ff", WORKTREE / "sportsedge" / "free_factors.py")
sys.path.insert(0, str(HARNESS))
# The validation script needs the harness importable; point the factor
# worktree at this branch so stacked code is what gets tested, and point the
# harness dir at the real harness (the script otherwise uses cwd).
import os
os.environ.setdefault("SPORTSEDGE_FACTOR_WORKTREE", str(WORKTREE))
os.environ.setdefault("SPORTSEDGE_BACKTEST_DIR", str(HARNESS))
vs = _load("uw_vs", WORKTREE / "scripts" / "validate_free_factors.py")


# ---------------------------------------------------------------------------
# ERA5 hour-matching: naive UTC times vs aware kickoff (bug fix 2026-10-11)
# ---------------------------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402


def test_era5_best_hour_index_naive_times():
    # ERA5 returns naive ISO times for timezone=UTC; kickoff is aware.
    # The old code raised TypeError (naive - aware); must not.
    ko = datetime(2025, 6, 23, 23, 45, tzinfo=timezone.utc)
    times = ["2025-06-23T22:00", "2025-06-24T00:00", "2025-06-23T20:00"]
    assert vs._era5_best_hour_index(times, ko) == 1  # 00:00 is 15 min away


def test_era5_best_hour_index_aware_z_times():
    ko = datetime(2025, 6, 23, 23, 45, tzinfo=timezone.utc)
    times = ["2025-06-23T22:00:00Z", "2025-06-24T00:00:00Z"]
    assert vs._era5_best_hour_index(times, ko) == 1


def test_era5_best_hour_index_fail_closed():
    ko = datetime(2025, 6, 23, 23, 45, tzinfo=timezone.utc)
    assert vs._era5_best_hour_index([], ko) is None
    assert vs._era5_best_hour_index(None, ko) is None
    # All timestamps > 90 min away -> None (no silent nearest-day match).
    assert vs._era5_best_hour_index(["2025-06-20T12:00"], ko) is None
    # Garbage entries skipped, not fatal.
    assert vs._era5_best_hour_index(["garbage", "2025-06-24T00:00"], ko) == 1


# ---------------------------------------------------------------------------
# Item 1: umpscorecards probe -> no keyless stable path -> NOT_WIRED, stop
# ---------------------------------------------------------------------------

def test_umpscorecards_probe_fixture_documents_gate():
    fixture = json.loads(
        (WORKTREE / "tests" / "fixtures"
         / "umpscorecards_probe_20261011.json").read_text(encoding="utf-8"))
    assert fixture["gated"] is True
    probe = next(p for p in fixture["probes"]
                 if p["path"] == "/data/umpires/__data.json")
    payload = json.dumps(probe["payload"])
    for marker in fixture["gate_markers"]:
        assert marker in payload, f"expected gate marker {marker!r} in payload"
    assert fixture["total_requests"] <= 6, "probe must stay light (no hammering)"
    assert fixture["decision"].startswith("NOT_WIRED")


def test_umpire_registry_stays_not_wired():
    reg = ff.FACTOR_REGISTRY["mlb_umpire"]
    assert reg["wired"] is False
    assert reg["validation"] == "NOT_WIRED"
    zone = ff.FACTOR_REGISTRY["umpire_zone"]
    assert zone["wired"] is False
    assert zone["validation"] == "NOT_WIRED"
    assert ff.umpire_entry()["kind"] == "none"
    assert ff.umpire_entry()["verified"] is False


# ---------------------------------------------------------------------------
# Item 2: MLB temp/humidity x park interaction (declared, harness-gated)
# ---------------------------------------------------------------------------

def _mlb_interaction(temp_f, humidity_pct, park_factor):
    return ff.weather_interaction_adjustment(
        sport="MLB", temp_f=temp_f, humidity_pct=humidity_pct,
        park_factor=park_factor)


def test_mlb_temp_heat_hitter_park():
    # Recorded fixture: 95F, 75% RH, Coors-like 1.161 park.
    # Hand derivation: 0.025*(95-70)=0.625 -> x1.25 (humid heat)=0.78125
    # -> x1.161 (park)=0.90703... -> capped +/-1.0.
    adj, status, _ = _mlb_interaction(95.0, 75.0, 1.161)
    assert status == "WEATHER_INTERACTION_VERIFIED"
    expected = min(1.0, 0.625 * 1.25 * 1.161)
    assert math.isclose(adj, expected, rel_tol=1e-9)


def test_mlb_temp_cold_pitcher_park():
    # 50F, dry, pitcher park 0.917.
    # 0.025*(50-70)=-0.50 -> x0.917=-0.4585.
    adj, status, _ = _mlb_interaction(50.0, 30.0, 0.917)
    assert status == "WEATHER_INTERACTION_VERIFIED"
    assert math.isclose(adj, -0.50 * 0.917, rel_tol=1e-9)


def test_mlb_temp_mild_neutral_no_amplification():
    # 72F, 40% RH, no park factor verified -> plain temp effect only.
    adj, status, _ = _mlb_interaction(72.0, 40.0, None)
    assert status == "WEATHER_INTERACTION_VERIFIED"
    assert math.isclose(adj, 0.025 * 2.0, rel_tol=1e-9)


def test_mlb_temp_interaction_fail_closed():
    # Missing temp -> no interaction, never a silent zero with a verified
    # status.
    adj, status, _ = _mlb_interaction(None, 75.0, 1.161)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"
    # Implausible temp -> fail closed.
    adj, status, _ = _mlb_interaction(200.0, 75.0, 1.161)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"
    # Indoor verified -> no effect.
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="MLB", temp_f=95.0, humidity_pct=75.0, indoor=True)
    assert adj == 0.0 and status == "VERIFIED_INDOOR"
    # ingest entry point stays audit-only on failure.
    entry = ff.ingest_weather_interaction("MLB", temp_f=None)
    assert entry["kind"] == "none" and entry["verified"] is False


def test_weather_thresholds_wind_only_without_precip():
    # ERA5 archive has no precipitation_probability (verified all-nulls
    # 2026-10-11); the harness passes precip=None and the declared
    # thresholds must degrade to the wind leg only, not fail or invent.
    # Busch Stadium azimuth 62: wind 15mph from 198 (SSW) -> out-component
    # = 15*cos(198 - (62+180)) = 15*cos(-44deg) = +10.79 -> blowing OUT.
    adj, status, detail = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=15.0, wind_from_degrees=198.0,
        field_azimuth_degrees=62.0, precip_probability_pct=None)
    assert status == "WEATHER_THRESHOLDS_VERIFIED_APPLIED"
    # in-component: 15*cos(radians(198-242)) = 15*cos(-44deg) = +10.79
    # -> wind out >= 8 moderate -> +0.25
    assert adj == ff.MLB_WIND_OUT_MODERATE_ADJ
    assert "precip" not in detail


def test_weather_thresholds_calm_is_zero_not_unverified():
    adj, status, _ = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=3.0, wind_from_degrees=198.0,
        field_azimuth_degrees=62.0, precip_probability_pct=None)
    assert status == "WEATHER_CALM_NO_EFFECT"
    assert adj == 0.0


def test_mlb_temp_extreme_capped():
    # 120F extreme heat -> 0.025*50=1.25 capped at 0.75 before humidity/park.
    adj, status, _ = _mlb_interaction(120.0, 90.0, 1.3)
    assert status == "WEATHER_INTERACTION_VERIFIED"
    assert adj <= 1.0


# ---------------------------------------------------------------------------
# Item 2: NFL wind x pass rate interaction (declared, harness-gated)
# ---------------------------------------------------------------------------

def test_nfl_wind_x_passing_scales_with_pass_rate():
    # League-average ~0.59 -> scale 1.09; base wind adj -1.5 -> -1.635.
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=0.59, base_wind_adj=-1.5)
    assert status == "WEATHER_INTERACTION_VERIFIED"
    assert math.isclose(adj, -1.5 * 1.09, rel_tol=1e-9)
    # Run-heavy matchup scales less: 0.45 -> 0.95.
    adj2, _, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=0.45, base_wind_adj=-1.5)
    assert math.isclose(adj2, -1.5 * 0.95, rel_tol=1e-9)
    assert abs(adj2) < abs(adj)


def test_nfl_wind_x_passing_fail_closed():
    # Unverified pass rate -> interaction NOT applied, never silently scaled.
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=None, base_wind_adj=-1.5)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"
    # Out-of-range pass rate -> fail closed.
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=1.5, base_wind_adj=-1.5)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"
    # Non-numeric pass rate -> fail closed.
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate="high", base_wind_adj=-1.5)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"


def test_weather_interaction_registry_documented():
    reg = ff.FACTOR_REGISTRY["weather_interactions"]
    # CONDITIONAL_PASS on the legacy gate (2026-10-11): wired with labels,
    # per the standing precedent (rest/keynums).
    assert reg["wired"] is True
    assert reg["validation"] == "CONDITIONAL_PASS"
    assert "harness" in reg["validation_note"].lower() or \
        "2026-10-11" in reg["validation_note"]
    entry = ff.ingest_weather_interaction("MLB", temp_f=95.0,
                                         humidity_pct=75.0)
    assert entry["factor"] == "weather_interactions"
    assert entry["verified"] is True
    assert entry["kind"] == "add"
    assert entry["target"] == "TOTAL"  # matches the harness application


def test_weather_interaction_wiring_gates():
    # MLB temp/humidity leg: validated -> prices (labeled).
    e = ff.ingest_weather_interaction("MLB", temp_f=95.0, humidity_pct=75.0,
                                      park_factor=1.161)
    assert e["verified"] is True and e["kind"] == "add"
    # The xpark multiplier leg was fail-closed off in the harness run ->
    # forced off here until separately validated (detail shows no park leg).
    assert "park" not in e["detail"]
    # NFL wind x pass-rate: NOT_RUN -> audit-only, never prices.
    e = ff.ingest_weather_interaction("NFL", pass_rate=0.59,
                                     base_wind_adj=-1.5)
    assert e["verified"] is False and e["kind"] == "none"
    assert e["value"] == 0.0
    # Declared wind/precip thresholds: FAILED the harness gate -> audit-only.
    e = ff.ingest_weather("MLB", 15.0, wind_from_degrees=198.0,
                         field_azimuth_degrees=62.0)
    assert e["verified"] is False and e["kind"] == "none"
    assert e["value"] == 0.0
    assert "NOT_WIRED" in e["detail"]
