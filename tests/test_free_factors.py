"""Offline unit tests for sportsedge/free_factors.py.

No network. Every test injects values directly; fail-closed behavior is
asserted, not just the happy path. Research only.
"""
import importlib.util
import math
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Standalone load (no `sportsedge` package import): the harness worktree's
# `sportsedge` package must be importable separately (see
# test_adversarial_factors.py).
ff = _load("ff_factors_unit", WORKTREE / "sportsedge" / "free_factors.py")


def test_park_verified():
    pf, status, _ = ff.park_factor_for("Colorado Rockies", 2025)
    assert status == "PARK_FACTOR_VERIFIED"
    assert pf > 1.10  # Coors is a hitter's park


def test_park_stale_fail_closed():
    pf, status, _ = ff.park_factor_for("Colorado Rockies", 2026)
    assert pf is None and status == "PARK_FACTOR_STALE"


def test_park_team_moved_fail_closed():
    # Athletics left Oakland after 2024; Rays left Tropicana after 2024.
    for team in ("Athletics", "Tampa Bay Rays"):
        pf, status, _ = ff.park_factor_for(team, 2025)
        assert pf is None and status == "PARK_FACTOR_TEAM_PARK_CHANGED", team
    # ... but the old park still applies for 2024 games.
    pf, status, _ = ff.park_factor_for("Athletics", 2024)
    assert status == "PARK_FACTOR_VERIFIED"


def test_park_unknown_team():
    pf, status, _ = ff.park_factor_for("Springfield Isotopes", 2025)
    assert pf is None and status == "PARK_FACTOR_TEAM_UNKNOWN"


def test_park_scale_bounded():
    assert ff.park_runs_scale(1.10) == 1.0 + 0.5 * 0.10
    assert ff.park_runs_scale(1.1661) == 1.08  # clipped at the bound
    assert ff.park_runs_scale(2.0) == 1.08
    assert ff.park_runs_scale(0.5) == 0.92


def test_rest_adjustment():
    adj, status, _ = ff.rest_margin_adjustment(10, 6)
    assert status == "REST_VERIFIED_APPLIED"
    assert adj == 0.4
    adj, _, _ = ff.rest_margin_adjustment(21, 6)  # cap
    assert adj == 1.0
    adj, status, _ = ff.rest_margin_adjustment(None, 6)
    assert adj == 0.0 and status == "REST_UNVERIFIED"


def test_travel_adjustment():
    adj, status, _ = ff.travel_margin_adjustment(400, 0)
    assert adj == 0.0 and status == "TRAVEL_VERIFIED_APPLIED"  # under free miles
    adj, status, _ = ff.travel_margin_adjustment(2500, 3)
    assert status == "TRAVEL_VERIFIED_APPLIED"
    assert adj < 0  # burden on traveler
    adj, _, _ = ff.travel_margin_adjustment(8000, 8)  # total cap
    assert adj == -1.0
    adj, status, _ = ff.travel_margin_adjustment(None, 2)
    assert adj == 0.0 and status == "TRAVEL_UNVERIFIED"


def test_haversine_and_tz():
    # NYC -> LA ~ 2450 mi, 3 time zones.
    m = ff.haversine_miles(40.7, -74.0, 34.05, -118.25)
    assert 2300 < m < 2600, m
    assert ff.timezone_jumps(-74.0, -118.25) == 3


def test_weather_mlb_buckets():
    # Wind blowing out (Coors azimuth ~4 deg; wind FROM ~184 => out).
    adj, status, _ = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=16, wind_from_degrees=184,
        field_azimuth_degrees=4, precip_probability_pct=10)
    assert status == "WEATHER_THRESHOLDS_VERIFIED_APPLIED" and adj == 0.5
    # Wind blowing in.
    adj, status, _ = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=16, wind_from_degrees=4,
        field_azimuth_degrees=4, precip_probability_pct=10)
    assert adj == -0.5, adj
    # Calm.
    adj, status, _ = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=3, wind_from_degrees=184,
        field_azimuth_degrees=4, precip_probability_pct=10)
    assert status == "WEATHER_CALM_NO_EFFECT" and adj == 0.0
    # Missing azimuth -> fail closed (no speed-only fallback).
    adj, status, _ = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=25, wind_from_degrees=None,
        field_azimuth_degrees=None, precip_probability_pct=10)
    assert adj == 0.0 and status == "WEATHER_UNVERIFIED"
    # Indoor.
    adj, status, _ = ff.weather_total_adjustment(
        sport="MLB", wind_speed_mph=25, indoor=True)
    assert adj == 0.0 and status == "VERIFIED_INDOOR"


def test_weather_football_buckets():
    adj, status, _ = ff.weather_total_adjustment(sport="NFL", wind_speed_mph=22,
                                                precip_probability_pct=10)
    assert adj == -1.5 and status == "WEATHER_THRESHOLDS_VERIFIED_APPLIED"
    adj, _, _ = ff.weather_total_adjustment(sport="NFL", wind_speed_mph=16,
                                            precip_probability_pct=80)
    assert adj == -1.5, adj  # -0.75 wind + -0.75 precip
    adj, status, _ = ff.weather_total_adjustment(sport="NFL", wind_speed_mph=None)
    assert adj == 0.0 and status == "WEATHER_UNVERIFIED"


def test_key_number_push():
    p, status, _ = ff.key_number_push_probability("NFL", -3, 0.05)
    assert status == "KEY_NUMBER_PUSH_VERIFIED"
    emp = ff.KEY_MARGIN_FREQUENCIES["NFL"][3]
    assert abs(p - (0.5 * emp + 0.5 * 0.05)) < 1e-12
    # Non-integer line -> normal push kept.
    p, status, _ = ff.key_number_push_probability("NFL", -3.5, 0.05)
    assert p == 0.05 and status == "PUSH_AWARE_ONLY"


def test_apply_key_push_preserves_ratio():
    w, p, l = ff.apply_key_push(0.5, 0.05, 0.45, 0.15)
    assert abs((w + p + l) - 1.0) < 1e-9
    assert abs(w / l - 0.5 / 0.45) < 1e-9


def test_pitcher_adjustment():
    adj, status, _ = ff.pitcher_quality_adjustment(2.50, 30)
    assert status == "PITCHER_VERIFIED_APPLIED" and adj < 0  # good pitcher
    adj, status, _ = ff.pitcher_quality_adjustment(5.50, 30)
    assert adj > 0
    adj, status, _ = ff.pitcher_quality_adjustment(3.00, 2)
    assert adj == 0.0 and status == "PITCHER_HISTORY_INSUFFICIENT"


def test_bullpen_adjustment():
    adj, status, _ = ff.bullpen_workload_adjustment(185, 3)
    assert status == "BULLPEN_TAXED_APPLIED" and adj == 0.40
    adj, status, _ = ff.bullpen_workload_adjustment(140, 3)
    assert adj == 0.25
    adj, status, _ = ff.bullpen_workload_adjustment(90, 3)
    assert adj == 0.0 and status == "BULLPEN_OK"
    adj, status, _ = ff.bullpen_workload_adjustment(None, 0)
    assert adj == 0.0 and status == "BULLPEN_WORKLOAD_UNVERIFIED"


def test_rotation_adjustment():
    adj, status, _ = ff.rotation_rest_adjustment(3)
    assert status == "ROTATION_SHORT_REST_APPLIED" and adj == 0.50
    adj, status, _ = ff.rotation_rest_adjustment(5)
    assert adj == 0.0 and status == "ROTATION_REST_OK"
    adj, status, _ = ff.rotation_rest_adjustment(None)
    assert adj == 0.0 and status == "ROTATION_REST_UNVERIFIED"


def test_participation():
    adj, status, _ = ff.qb_out_adjustment("NFL", True, "Lamar Jackson")
    assert status == "QB_OUT_VERIFIED_APPLIED" and adj == -2.5
    adj, status, _ = ff.qb_out_adjustment("NFL", False)
    assert adj == 0.0 and status == "QB_STATUS_NOT_VERIFIED"
    assert ff.BACKUP_QUALITY_STATUS == "NOT_INVENTED"


def test_srs():
    games = [("A", "B", 10.0, 5.0), ("B", "C", 7.0, 5.0), ("A", "C", 14.0, 40.0)]
    srs = ff.srs_ratings(games)
    assert abs(sum(srs.values())) < 1e-6  # mean-centered
    assert srs["A"] > srs["B"] > srs["C"]
    margin, status = ff.srs_predicted_margin(srs, "A", "C", 1.5)
    assert status == "SRS_VERIFIED" and margin > 0
    margin, status = ff.srs_predicted_margin(srs, "A", "ZZZ", 1.5)
    assert margin is None and status == "SRS_TEAM_UNRATED"


def test_venue_hfa():
    delta, status, _ = ff.venue_hfa_delta([10.0] * 20, [-2.0] * 20, 1.5)
    assert status == "VENUE_HFA_VERIFIED" and delta > 0
    delta, status, _ = ff.venue_hfa_delta([3.0], [-3.0], 1.5)
    assert delta == 0.0 and status == "VENUE_HFA_UNVERIFIED"


def test_pace_and_turnovers():
    adj, status, _ = ff.pace_total_adjustment(68, 64, 62.0)
    assert status == "PACE_VERIFIED_APPLIED" and adj > 0
    adj, status, _ = ff.pace_total_adjustment(None, 64, 62.0)
    assert adj == 0.0 and status == "PACE_UNVERIFIED"
    adj, status, _ = ff.turnover_luck_adjustment(1.0)
    assert status == "TURNOVER_REGRESSED_APPLIED" and adj == -2.0  # capped
    adj, status, _ = ff.turnover_luck_adjustment(-0.5)
    assert adj == 1.4  # unlucky team gets points back


def test_fip():
    fip, n = ff.fip_from_gamelog([
        {"HR": 1, "BB": 2, "HBP": 0, "SO": 7, "IP": "6.0"},
        {"HR": 0, "BB": 1, "HBP": 1, "SO": 5, "IP": "5.2"},
    ])
    assert n == 2
    # (13*1 + 3*4 - 2*12)/11.667 + 3.10
    assert abs(fip - ((13 + 12 - 24) / (11 + 2 / 3) + 3.10)) < 1e-9
    adj, status, _ = ff.pitcher_fip_adjustment(3.0, 10)
    assert status == "PITCHER_FIP_VERIFIED_APPLIED" and adj < 0
    adj, status, _ = ff.pitcher_fip_adjustment(3.0, 2)
    assert adj == 0.0 and status == "PITCHER_FIP_HISTORY_INSUFFICIENT"


def test_epa_margin():
    margin, status = ff.epa_predicted_margin(0.08, -0.04, 1.5)
    assert status == "EPA_VERIFIED"
    assert abs(margin - (55.0 * 0.12 + 1.5)) < 1e-9
    margin, status = ff.epa_predicted_margin(None, -0.04)
    assert margin is None and status == "EPA_STRENGTH_UNVERIFIED"


def test_ingest_contract():
    e = ff.ingest_mlb_park("Colorado Rockies", 2025)
    assert e["kind"] == "scale" and e["target"] == "BOTH_MEANS"
    assert e["verified"] is True and 0.92 <= e["value"] <= 1.08
    e = ff.ingest_mlb_park("Colorado Rockies", 2026)
    assert e["kind"] == "none" and e["verified"] is False and e["value"] is None
    e = ff.ingest_rest("NFL", 10, 6)
    assert e["kind"] == "add" and e["target"] == "HOME_MARGIN" and e["verified"]
    e = ff.ingest_weather("NFL", None)
    assert e["verified"] is False and e["value"] == 0.0
    e = ff.ingest_participation("NFL", "home", True, "Lamar Jackson")
    assert e["target"] == "HOME_MEAN" and e["value"] == -2.5 and e["verified"]
    e = ff.umpire_entry()
    assert e["status"] == "NOT_WIRED" and e["kind"] == "none"
    # every registered entry point name resolves to a callable
    for name, sig in ff.INGEST_ENTRY_POINTS.items():
        fn = sig.split("(")[0]
        assert callable(getattr(ff, fn)), name


def test_wind_components_match_repo_math():
    # Same projection math as sportsedge.mlb_environment_derived
    # (reimplemented dependency-free here).
    out = ff.wind_out_component_mph(10.0, 184.0, 4.0)
    assert out > 9.9  # nearly straight out
    out = ff.wind_out_component_mph(10.0, 4.0, 4.0)
    assert out < -9.9  # nearly straight in
    out = ff.wind_out_component_mph(10.0, 94.0, 4.0)
    assert abs(out) < 0.1  # crosswind


def test_time_decay_weight():
    assert ff.time_decay_weight(0, 30.0) == 1.0
    assert abs(ff.time_decay_weight(30.0, 30.0) - 0.5) < 1e-12
    assert abs(ff.time_decay_weight(60.0, 30.0) - 0.25) < 1e-12
    # recent games weigh more
    assert ff.time_decay_weight(5, 30.0) > ff.time_decay_weight(50, 30.0)


def test_time_decay_negative_age_raises():
    try:
        ff.time_decay_weight(-1, 30.0)
    except ValueError as exc:
        assert "NEGATIVE_AGE" in str(exc)
    else:
        raise AssertionError("negative age must raise")


def test_decay_weighted_mean():
    m, status = ff.decay_weighted_mean([(10.0, 0.0), (0.0, 1000.0)], 30.0)
    assert status == "TIME_DECAY_VERIFIED"
    assert 9.0 < m <= 10.0  # recent game dominates
    m, status = ff.decay_weighted_mean([], 30.0)
    assert m is None and status == "TIME_DECAY_NO_GAMES"
    e = ff.ingest_time_decay([(5.0, 3.0)], "NFL")
    assert e["verified"] is True
    e = ff.ingest_time_decay([(5.0, 3.0)], "NHL")
    assert e["verified"] is False and e["status"] == "TIME_DECAY_NOT_APPLICABLE"


def test_weather_interaction_nfl():
    # wind x passing: pass-heavy matchup -> stronger suppression
    a1, s1, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=0.65, base_wind_adj=-1.5)
    a2, s2, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=0.45, base_wind_adj=-1.5)
    assert s1 == "WEATHER_INTERACTION_VERIFIED"
    assert a1 < a2 < 0  # more pass-heavy -> more negative
    # missing pass rate -> fail closed
    a, s, _ = ff.weather_interaction_adjustment(
        sport="NFL", base_wind_adj=-1.5)
    assert a == 0.0 and s == "WEATHER_INTERACTION_UNVERIFIED"
    # bad pass rate -> fail closed
    a, s, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=1.5, base_wind_adj=-1.5)
    assert a == 0.0 and s == "WEATHER_INTERACTION_UNVERIFIED"
    # indoor -> no effect
    a, s, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=0.6, base_wind_adj=-1.5, indoor=True)
    assert a == 0.0 and s == "VERIFIED_INDOOR"


def test_weather_interaction_mlb():
    # hot + humid + hitter park -> positive
    a, s, d = ff.weather_interaction_adjustment(
        sport="MLB", temp_f=90, humidity_pct=75, park_factor=1.16)
    assert s == "WEATHER_INTERACTION_VERIFIED"
    assert a > 0.4  # 0.025*20=0.5, x1.25=0.625, x1.16=0.725
    # cold -> negative
    a, s, _ = ff.weather_interaction_adjustment(sport="MLB", temp_f=50)
    assert s == "WEATHER_INTERACTION_VERIFIED" and a < 0
    # mild -> near zero
    a, s, _ = ff.weather_interaction_adjustment(sport="MLB", temp_f=70)
    assert abs(a) < 0.01
    # missing temp -> fail closed
    a, s, _ = ff.weather_interaction_adjustment(sport="MLB", humidity_pct=80)
    assert a == 0.0 and s == "WEATHER_INTERACTION_UNVERIFIED"
    # implausible temp -> fail closed
    a, s, _ = ff.weather_interaction_adjustment(sport="MLB", temp_f=200)
    assert a == 0.0 and s == "WEATHER_INTERACTION_UNVERIFIED"


def test_component_park_factors():
    # Rockies HR factor >1 (hitter park), Giants <1 (pitcher park)
    pf, status, _ = ff.component_park_factor_for("Colorado Rockies", 2024, "HR")
    assert status == "COMPONENT_PARK_VERIFIED" and pf > 1.1
    pf, status, _ = ff.component_park_factor_for("San Francisco Giants", 2024, "HR")
    assert status == "COMPONENT_PARK_VERIFIED" and pf < 1.0
    # Components differ (not aggregate)
    pf_hr, _, _ = ff.component_park_factor_for("Colorado Rockies", 2024, "HR")
    pf_k, _, _ = ff.component_park_factor_for("Colorado Rockies", 2024, "K")
    assert pf_hr != pf_k
    # Invalid component -> fail closed
    pf, status, _ = ff.component_park_factor_for("Colorado Rockies", 2024, "XX")
    assert pf is None and status == "COMPONENT_PARK_INVALID"
    # Moved team 2025 -> fail closed
    pf, status, _ = ff.component_park_factor_for("Athletics", 2025, "HR")
    assert pf is None and "PARK_CHANGED" in status


def test_regress_stat():
    # Full sample -> near observed; zero sample -> league avg
    v, s = ff.regress_stat(0.300, 1000, 0.250, 500)
    assert s == "REGRESSED_VERIFIED" and abs(v - 0.2833) < 0.001
    v, s = ff.regress_stat(0.300, 0, 0.250, 500)
    assert v == 0.250 and s == "REGRESSED_TO_LEAGUE_AVG"
    # Invalid -> fail closed
    v, s = ff.regress_stat(0.300, -10, 0.250, 500)
    assert v is None and s == "REGRESS_INPUT_INVALID"


def test_regress_platoon_split():
    # RHB regresses more (2200 PA) than LHB (1000 PA)
    v_r, _ = ff.regress_platoon_split(0.050, 500, "RHB", 0.010)
    v_l, _ = ff.regress_platoon_split(0.050, 500, "LHB", 0.010)
    # RHB: (0.05*500 + 0.01*2200)/2700 = 0.0174; LHB: (0.05*500+0.01*1000)/1500 = 0.0233
    assert abs(v_r - 0.0174) < 0.001
    assert abs(v_l - 0.0233) < 0.001
    assert v_r < v_l  # RHB regresses more toward league avg
    # Unknown hand -> fail closed
    v, s = ff.regress_platoon_split(0.050, 500, "X", 0.010)
    assert v is None and s == "PLATOON_HAND_UNKNOWN"


def test_ingest_component_park_and_platoon():
    e = ff.ingest_component_park("Colorado Rockies", 2024, "HR")
    assert e["verified"] is True and e["value"] > 1.1
    e = ff.ingest_platoon("RHB", 0.050, 500, 0.010)
    assert e["verified"] is True
