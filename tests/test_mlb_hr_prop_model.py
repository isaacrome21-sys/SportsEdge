"""Unit tests for sportsedge.mlb_hr_prop_model. Zero network.

Synthetic deterministic pitch rows; the HR model math (platoon regression,
multiplicative lambda, Poisson P(>=1)) is verified exactly, and every
fail-closed path returns BLOCKED with an explicit HR_* reason.
"""
from __future__ import annotations

import math

import pytest

from sportsedge import mlb_hr_prop_model as hr
from sportsedge.mlb_hr_prop_model import (
    HRPropError,
    attach_prop_percentiles,
    batter_platoon_power,
    hr_prop_projection,
    league_platoon_hr_rates,
    load_component_park_hr,
    pitcher_hr_factor,
    regressed_platoon_hr_rate,
)


def _row(**kw):
    base = {
        "game_date": "2026-09-20", "game_pk": "900001", "batter": "111",
        "pitcher": "222", "events": "field_out", "description": "hit_into_play",
        "inning_topbot": "Top", "pitch_number": "1",
        "estimated_woba_using_speedangle": "0.320", "launch_speed": "89.0",
        "launch_angle": "12.0", "launch_speed_angle": "", "release_speed": "94.5",
        "zone": "5", "stand": "R", "p_throws": "R",
    }
    base.update(kw)
    return base


def _platoon_rows():
    """Batter 111 (RHB): 60 PA vs RHP (3 HR), 60 PA vs LHP (6 HR)."""
    rows = []
    for i in range(60):
        rows.append(_row(batter="111", p_throws="R", stand="R",
                         events="home_run" if i < 3 else "field_out",
                         launch_speed="104.0" if i < 3 else "89.0",
                         launch_speed_angle="6" if i < 3 else ""))
    for i in range(60):
        rows.append(_row(batter="111", p_throws="L", stand="R",
                         events="home_run" if i < 6 else "field_out",
                         launch_speed="104.0" if i < 6 else "89.0",
                         launch_speed_angle="6" if i < 6 else ""))
    # league filler: many PA so league matchup rates clear the 500-PA gate
    # (6 matchup cells; each needs >=500 PA)
    for b in range(48):
        for i in range(70):
            rows.append(_row(batter=f"9{b:02d}", p_throws="R" if i % 2 else "L",
                             stand="R" if b % 2 else "L",
                             events="home_run" if i % 37 == 0 else "field_out"))
    return rows


def _park_factors():
    return {"Test Park Home": 1.10, "Other Park": 0.90}


# ---------------------------------------------------------------------------
# Platoon splits
# ---------------------------------------------------------------------------

def test_batter_platoon_power_splits():
    rows = _platoon_rows()
    out = batter_platoon_power(rows, "111")
    assert out["status"] == "AVAILABLE"
    assert out["bats"] == "R"
    assert out["vs_R"]["pa"] == 60
    assert out["vs_R"]["hr"] == 3
    assert out["vs_R"]["hr_per_pa"] == pytest.approx(0.05)
    assert out["vs_L"]["pa"] == 60
    assert out["vs_L"]["hr"] == 6
    assert out["vs_L"]["hr_per_pa"] == pytest.approx(0.10)
    # power splits >> contact: barrel rate tracks the HR split
    assert out["vs_L"]["barrel_rate"] > out["vs_R"]["barrel_rate"]
    assert out["vs_L"]["avg_exit_velocity"] > out["vs_R"]["avg_exit_velocity"]


def test_batter_platoon_power_insufficient_history():
    rows = [_row(batter="111") for _ in range(10)]
    out = batter_platoon_power(rows, "111")
    assert out["status"] == "MISSING"
    assert "HR_BATTER_HISTORY_INSUFFICIENT" in out["reason"]


def test_league_platoon_hr_rates():
    rows = _platoon_rows()
    out = league_platoon_hr_rates(rows)
    assert out["status"] == "AVAILABLE"
    assert "RvR" in out["matchups"]
    assert "RvL" in out["matchups"]
    assert out["matchups"]["RvR"]["hr_per_pa"] > 0


def test_regressed_platoon_hr_rate_math():
    rows = _platoon_rows()
    platoon = batter_platoon_power(rows, "111")
    lg = league_platoon_hr_rates(rows)["matchups"]
    reg = regressed_platoon_hr_rate(platoon, "L", lg)
    assert reg["status"] == "AVAILABLE"
    assert reg["matchup"] == "RvL"
    assert reg["prior_pa"] == 2200  # Carty RHB prior
    lg_rate = lg["RvL"]["hr_per_pa"]
    expected = (6 + 2200 * lg_rate) / (60 + 2200)
    assert reg["regressed_hr_per_pa"] == pytest.approx(expected, abs=1e-6)
    # zero observations -> pure league rate (no invented signal)
    empty = {"status": "AVAILABLE", "bats": "R",
             "vs_L": {"pa": 0, "hr": 0}, "vs_R": {"pa": 0, "hr": 0}}
    reg0 = regressed_platoon_hr_rate(empty, "L", lg)
    assert reg0["regressed_hr_per_pa"] == pytest.approx(lg_rate, abs=1e-6)


def test_regressed_platoon_lhb_prior():
    platoon = {"status": "AVAILABLE", "bats": "L",
               "vs_R": {"pa": 40, "hr": 2}, "vs_L": {"pa": 10, "hr": 0}}
    lg = {"LvR": {"pa": 5000, "hr": 150, "hr_per_pa": 0.03}}
    reg = regressed_platoon_hr_rate(platoon, "R", lg)
    assert reg["prior_pa"] == 1000  # Carty LHB prior
    assert reg["regressed_hr_per_pa"] == pytest.approx(
        (2 + 1000 * 0.03) / (40 + 1000), abs=1e-6)


def test_regressed_platoon_missing_pitcher_hand_blocked():
    platoon = {"status": "AVAILABLE", "bats": "R",
               "vs_R": {"pa": 60, "hr": 3}}
    out = regressed_platoon_hr_rate(platoon, None, {})
    assert out["status"] == "BLOCKED"
    assert out["reason"] == "HR_PITCHER_HAND_UNVERIFIED"


# ---------------------------------------------------------------------------
# Pitcher HR factor
# ---------------------------------------------------------------------------

def test_pitcher_hr_factor_shrinkage():
    rows = []
    # 200 BF, 10 HR allowed -> raw HR/PA = 0.05; league 0.03 -> raw 1.667
    for i in range(200):
        rows.append(_row(pitcher="222",
                         events="home_run" if i < 10 else "field_out"))
    out = pitcher_hr_factor(rows, "222", 0.03)
    assert out["status"] == "AVAILABLE"
    assert out["raw_factor"] == pytest.approx(1.6667, abs=1e-3)
    # shrunk toward 1.0 with 300-BF prior
    assert out["factor"] == pytest.approx((200 * 1.6667 + 300) / 500, abs=1e-3)
    assert out["factor"] < out["raw_factor"]


def test_pitcher_hr_factor_small_sample_missing():
    rows = [_row(pitcher="222") for _ in range(50)]
    out = pitcher_hr_factor(rows, "222", 0.03)
    assert out["status"] == "MISSING"
    assert "HR_PITCHER_SAMPLE_TOO_SMALL" in out["reason"]


# ---------------------------------------------------------------------------
# Park factors (Phase 2 artifact by contract)
# ---------------------------------------------------------------------------

def test_load_component_park_hr_schema_pinned():
    payload = {"schema": "SPORTSEDGE_COMPONENT_PARK_FACTORS_V1",
               "teams": {"Test Park Home": {"HR": {"pf": 1.10, "raw": 1.2}}}}
    out = load_component_park_hr(payload)
    assert out == {"Test Park Home": 1.10}


def test_load_component_park_hr_wrong_schema():
    with pytest.raises(HRPropError, match="HR_PARK_FACTORS_SCHEMA_UNEXPECTED"):
        load_component_park_hr({"schema": "SOMETHING_ELSE", "teams": {}})


def test_load_component_park_hr_missing_file():
    with pytest.raises(HRPropError, match="HR_PARK_FACTORS_FILE_MISSING"):
        load_component_park_hr("/nonexistent/park_factors.json")


def test_load_real_phase2_artifact():
    import os
    path = "/home/hatch/workspace/sportsedge-freefactors/data/component_park_factors_2022_2024.json"
    if not os.path.exists(path):
        pytest.skip("Phase 2 artifact not present in this environment")
    out = load_component_park_hr(path)
    assert out["Colorado Rockies"] == pytest.approx(1.2273)
    assert out["San Francisco Giants"] == pytest.approx(0.8815)
    assert len(out) == 30


# ---------------------------------------------------------------------------
# Full projection
# ---------------------------------------------------------------------------

def _hr_rows():
    rows = _platoon_rows()
    # pitcher 222: 200 BF, 8 HR allowed
    for i in range(200):
        rows.append(_row(batter="555", pitcher="222", p_throws="R",
                         events="home_run" if i < 8 else "field_out"))
    return rows


def test_hr_prop_projection_math():
    rows = _hr_rows()
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand="R",
        home_team_name="Test Park Home", pitch_rows=rows,
        park_hr_factors=_park_factors(), pa_expected=4.2)
    assert out["status"] == "AVAILABLE", out
    lam = out["lambda_hr"]
    assert out["p_ge1_hr"] == pytest.approx(1 - math.exp(-lam), abs=1e-4)
    assert out["p_ge2_hr"] == pytest.approx(1 - math.exp(-lam) * (1 + lam), abs=1e-4)
    assert out["p_ge2_hr"] < out["p_ge1_hr"]
    pct = out["percentiles"]
    assert pct["p10"] <= pct["p50"] <= pct["p90"]
    # card-renderable block
    assert out["BATTER_HRS"]["mean"] == pytest.approx(lam, abs=1e-4)
    c = out["components"]
    assert c["park_hr_pf"] == pytest.approx(1.10)
    assert c["matchup"] == "RvR"
    assert c["pa_expected"] == 4.2
    assert out["coverage_audit"]["missing"] == []


def test_hr_prop_projection_lambda_composition():
    rows = _hr_rows()
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand="L",
        home_team_name="Test Park Home", pitch_rows=rows,
        park_hr_factors=_park_factors(), pa_expected=4.0)
    c = out["components"]
    expected_lam = (4.0 * c["batter_regressed_hr_per_pa"]
                    * c["pitcher_hr_factor"] * 1.10)
    assert out["lambda_hr"] == pytest.approx(expected_lam, abs=1e-3)


def test_hr_prop_missing_pitcher_hand_blocked():
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand=None,
        home_team_name="Test Park Home", pitch_rows=_hr_rows(),
        park_hr_factors=_park_factors())
    assert out["status"] == "BLOCKED"
    assert out["reason"] == "HR_PITCHER_HAND_UNVERIFIED"


def test_hr_prop_missing_park_blocked():
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand="R",
        home_team_name="Nonexistent Park", pitch_rows=_hr_rows(),
        park_hr_factors=_park_factors())
    assert out["status"] == "BLOCKED"
    assert "HR_PARK_FACTOR_MISSING" in out["reason"]


def test_hr_prop_no_park_factors_blocked():
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand="R",
        home_team_name="Test Park Home", pitch_rows=_hr_rows(),
        park_hr_factors=None)
    assert out["status"] == "BLOCKED"
    assert out["reason"] == "HR_PARK_FACTORS_NOT_SUPPLIED"


def test_hr_prop_unverified_lineup_blocked():
    out = hr_prop_projection(
        batter_id="000", batter_hand="R", pitcher_id="222", pitcher_hand="R",
        home_team_name="Test Park Home", pitch_rows=_hr_rows(),
        park_hr_factors=_park_factors())
    assert out["status"] == "BLOCKED"
    assert "HR_BATTER_HISTORY_INSUFFICIENT" in out["reason"]


def test_hr_prop_never_point_estimate_on_defaults():
    # Every required input missing -> BLOCKED, never a silent estimate.
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand="R",
        home_team_name="Test Park Home", pitch_rows=[],
        park_hr_factors=_park_factors())
    assert out["status"] == "BLOCKED"


def test_hr_percentiles_attach_to_card_row():
    rows = _hr_rows()
    out = hr_prop_projection(
        batter_id="111", batter_hand="R", pitcher_id="222", pitcher_hand="R",
        home_team_name="Test Park Home", pitch_rows=rows,
        park_hr_factors=_park_factors())
    row = {"market": "BATTER_HRS", "model_p": out["p_ge1_hr"]}
    enriched = attach_prop_percentiles(row, out)
    assert enriched["percentiles"]["market"] == "BATTER_HRS"
    assert enriched["percentiles"]["p10"] <= enriched["percentiles"]["p50"]
