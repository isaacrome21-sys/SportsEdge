"""Unit tests for sportsedge.mlb_savant_features. Zero network.

Uses the recorded real fixture tests/fixtures/savant/statcast_slice_20261005_20261008.csv
for parse/schema/aggregation tests, plus deterministic synthetic pitch rows for
the AVAILABLE-path math (the 4-day playoff fixture is too thin to clear the
sample gates — which is itself the fail-closed behavior under test).
"""
from __future__ import annotations

import csv
import math
from datetime import date, datetime, timezone

import pytest

from sportsedge import mlb_savant_features as sf
from sportsedge.mlb_savant_features import (
    SavantFeatureError,
    attach_prop_percentiles,
    batter_quality_features,
    exit_velo_trend,
    fit_xk_weights,
    parse_statcast_csv,
    per_pitch_event_rates,
    pitch_count_history,
    pitch_outcome_rates,
    pitcher_prop_projection,
    pitcher_quality_features,
    pitcher_strikeout_features,
    poisson_quantiles,
    project_pitch_count,
    savant_game_quality,
    savant_runs_adjustment,
    snapshot_from_csv_rows,
    team_batter_quality,
    xk_per_pitch,
)

FIXTURE = "tests/fixtures/savant/statcast_slice_20261005_20261008.csv"


def _fixture_rows():
    with open(FIXTURE, encoding="utf-8") as fh:
        return parse_statcast_csv(fh.read())


def _row(**kw):
    base = {
        "game_date": "2026-09-20", "game_pk": "900001", "batter": "111",
        "pitcher": "222", "events": "", "description": "ball",
        "inning_topbot": "Top", "pitch_number": "1",
        "estimated_woba_using_speedangle": "", "launch_speed": "",
        "launch_angle": "", "launch_speed_angle": "", "release_speed": "94.5",
        "zone": "5", "stand": "R", "p_throws": "R",
    }
    base.update(kw)
    return base


def _pa_rows(pitcher="222", batter="111", game="900001", date_s="2026-09-20",
             n_pa=30, xwoba=0.340, ev=91.0, desc_cycle=None, event="field_out"):
    """Deterministic synthetic PA-terminal pitch rows."""
    descs = desc_cycle or ["called_strike", "ball", "foul", "hit_into_play"]
    rows = []
    for i in range(n_pa):
        rows.append(_row(
            game_date=date_s, game_pk=game, batter=batter, pitcher=pitcher,
            events=event, description=descs[i % len(descs)],
            inning_topbot="Top" if i % 2 == 0 else "Bot",
            pitch_number=str(i + 1),
            estimated_woba_using_speedangle=str(xwoba),
            launch_speed=str(ev), launch_angle="12.0", launch_speed_angle="",
            zone="5"))
    return rows


# ---------------------------------------------------------------------------
# Parse / schema fail-closed
# ---------------------------------------------------------------------------

def test_parse_fixture_ok():
    rows = _fixture_rows()
    assert len(rows) == 2652
    assert sf.REQUIRED_COLUMNS.issubset(set(rows[0].keys()))


def test_parse_empty_fail_closed():
    with pytest.raises(SavantFeatureError, match="SAVANT_EMPTY_RESPONSE"):
        parse_statcast_csv("   \n")


def test_parse_schema_change_fail_closed():
    rows = _fixture_rows()
    fieldnames = [c for c in rows[0].keys() if c != "launch_speed"]
    buf = io_string(fieldnames, rows)
    with pytest.raises(SavantFeatureError, match="SAVANT_SCHEMA_UNEXPECTED"):
        parse_statcast_csv(buf)


def io_string(fieldnames, rows):
    import io as _io
    buf = _io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def test_parse_no_rows_fail_closed():
    with pytest.raises(SavantFeatureError, match="SAVANT_NO_ROWS"):
        parse_statcast_csv("game_date,batter\n")


def test_parse_truncated_response_fail_closed():    # The endpoint silently caps at 25,000 rows; an at-cap response must
    # never be mistaken for a complete window.
    import io as _io
    rows = _fixture_rows()
    buf = _io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    for i in range(sf.STATCAST_ROW_CAP):
        r = dict(rows[i % len(rows)])
        w.writerow(r)
    with pytest.raises(SavantFeatureError, match="SAVANT_RESPONSE_TRUNCATED"):
        parse_statcast_csv(buf.getvalue())


def test_parse_endpoint_error_column_fail_closed():
    # Savant returns failures as a CSV carrying an `error` column
    # (pattern confirmed via the pybaseball reference implementation).
    with pytest.raises(SavantFeatureError, match="SAVANT_ENDPOINT_ERROR"):
        parse_statcast_csv("error\nNo data found for this query\n")


# ---------------------------------------------------------------------------
# Aggregation + quality features
# ---------------------------------------------------------------------------

def test_snapshot_from_fixture():
    rows = _fixture_rows()
    snap = snapshot_from_csv_rows(
        rows, start=date(2026, 10, 5), end=date(2026, 10, 8))
    assert snap.raw_pitch_rows == 2652
    assert len(snap.batter_rows) > 50
    assert len(snap.pitcher_rows) > 30
    # xwoba_contact within plausible range for every row that has one
    for r in snap.batter_rows:
        v = r.get("xwoba_contact")
        if v is not None:
            assert 0.0 <= v <= 1.5


def test_batter_quality_available_synthetic():
    rows = _pa_rows(n_pa=30, xwoba=0.340, ev=91.0)
    snap = snapshot_from_csv_rows(rows, start=date(2026, 9, 1),
                                  end=date(2026, 9, 30))
    assert len(snap.batter_rows) == 1
    q = batter_quality_features(snap.batter_rows[0])
    assert q["status"] == "AVAILABLE"
    f = q["features"]
    assert f["pa"] == 30
    assert f["xwoba"] == pytest.approx(0.340)
    assert f["avg_exit_velocity"] == pytest.approx(91.0)
    assert f["hard_hit_rate"] == 0.0  # 91 < 95
    assert 0.0 <= f["k_rate"] <= 1.0


def test_batter_quality_small_sample_missing():
    rows = _pa_rows(n_pa=10)
    snap = snapshot_from_csv_rows(rows, start=date(2026, 9, 1),
                                  end=date(2026, 9, 30))
    q = batter_quality_features(snap.batter_rows[0])
    assert q["status"] == "MISSING"
    assert "SAVANT_BATTER_SAMPLE_TOO_SMALL" in q["reason"]


def test_pitcher_quality_available_synthetic():
    rows = _pa_rows(n_pa=120, xwoba=0.300, ev=88.0)
    snap = snapshot_from_csv_rows(rows, start=date(2026, 9, 1),
                                  end=date(2026, 9, 30))
    prow = next(r for r in snap.pitcher_rows if r["entity_id"] == "222")
    q = pitcher_quality_features(prow)
    assert q["status"] == "AVAILABLE"
    f = q["features"]
    assert f["pitches"] == 120
    assert f["xwoba_against"] == pytest.approx(0.300)
    assert f["hard_hit_rate_against"] == 0.0
    assert f["whiff_rate"] is None or 0.0 <= f["whiff_rate"] <= 1.0


def test_pitcher_quality_small_sample_missing():
    rows = _pa_rows(n_pa=40)
    snap = snapshot_from_csv_rows(rows, start=date(2026, 9, 1),
                                  end=date(2026, 9, 30))
    prow = next(r for r in snap.pitcher_rows if r["entity_id"] == "222")
    q = pitcher_quality_features(prow)
    assert q["status"] == "MISSING"
    assert "SAVANT_PITCHER_SAMPLE_TOO_SMALL" in q["reason"]


def test_exit_velo_trend_math():
    recent = {"status": "AVAILABLE",
              "features": {"avg_exit_velocity": 93.5, "batted_balls": 20}}
    season = {"status": "AVAILABLE",
              "features": {"avg_exit_velocity": 89.0, "batted_balls": 200}}
    t = exit_velo_trend(recent, season)
    assert t["status"] == "AVAILABLE"
    assert t["exit_velo_trend_mph"] == pytest.approx(4.5)


def test_exit_velo_trend_missing_input():
    t = exit_velo_trend({"status": "MISSING", "reason": "X"}, {"status": "AVAILABLE", "features": {}})
    assert t["status"] == "MISSING"
    assert "SAVANT_TREND_INPUT_MISSING" in t["reason"]


# ---------------------------------------------------------------------------
# xK% engine
# ---------------------------------------------------------------------------

def _xk_examples(n=16, weights=(0.25, 0.55, 0.10, 0.02)):
    """Synthetic examples from known weights (zero intercept).

    Feature columns vary independently (prime-period cycles) so the design
    is well-conditioned and the true weights are identifiable.
    """
    out = []
    for i in range(n):
        called = 0.10 + 0.05 * ((i * 1) % 5) / 4      # 0.10..0.15
        whiff = 0.06 + 0.08 * ((i * 2) % 7) / 6        # 0.06..0.14
        foul = 0.14 + 0.08 * ((i * 3) % 5) / 4        # 0.14..0.22
        inplay = 0.12 + 0.06 * ((i * 5) % 7) / 6       # 0.12..0.18
        y = (weights[0] * called + weights[1] * whiff
             + weights[2] * foul + weights[3] * inplay)
        out.append({"rates": {"called_strike": called, "whiff": whiff,
                              "foul": foul, "in_play": inplay},
                    "k_per_pitch": y, "pitches": 300})
    return out, weights


def test_fit_xk_weights_recovers_known_weights():
    examples, true_w = _xk_examples()
    fit = fit_xk_weights(examples)
    for k, tv in zip(("called_strike", "whiff", "foul", "in_play"), true_w):
        assert fit["weights"][k] == pytest.approx(tv, abs=0.03), k
    assert fit["method"] == "nnls_zero_intercept"
    assert all(v >= 0 for v in fit["weights"].values())
    assert fit["weighted_r2_zero_intercept"] > 0.99


def test_fit_xk_weights_too_few_examples():
    with pytest.raises(SavantFeatureError, match="SAVANT_XK_TOO_FEW_EXAMPLES"):
        fit_xk_weights(_xk_examples(n=5)[0])


def test_fit_xk_weights_rejects_negative_rates():
    ex, _ = _xk_examples(n=12)
    ex[0]["rates"]["whiff"] = -0.1
    with pytest.raises(SavantFeatureError, match="SAVANT_XK_RATES_INVALID"):
        fit_xk_weights(ex)


def test_xk_per_pitch_explicit_weights():
    rates = {"called_strike": 0.16, "whiff": 0.11, "foul": 0.19, "in_play": 0.16}
    weights = {"called_strike": 0.25, "whiff": 0.55, "foul": 0.10, "in_play": 0.02}
    out = xk_per_pitch(rates, weights)
    assert out["status"] == "AVAILABLE"
    assert out["xk_per_pitch"] == pytest.approx(
        0.25 * 0.16 + 0.55 * 0.11 + 0.10 * 0.19 + 0.02 * 0.16)


def test_xk_per_pitch_missing_artifact_is_missing_not_invented(monkeypatch):
    monkeypatch.setattr(sf, "WEIGHTS_ARTIFACT", "/nonexistent/xk.json")
    out = xk_per_pitch({"called_strike": 0.1, "whiff": 0.1,
                        "foul": 0.1, "in_play": 0.1})
    assert out["status"] == "MISSING"
    assert "SAVANT_XK_WEIGHTS_UNRECORDED" in out["reason"]


def test_xk_per_pitch_unvalidated_weights_refused(tmp_path, monkeypatch):
    import json
    p = tmp_path / "xk.json"
    p.write_text(json.dumps({"status": "VALIDATION_FAILED",
                             "weights": {"called_strike": 0.1, "whiff": 0.4,
                                         "foul": 0.0, "in_play": 0.0}}))
    monkeypatch.setattr(sf, "WEIGHTS_ARTIFACT", str(p))
    out = xk_per_pitch({"called_strike": 0.1, "whiff": 0.1,
                        "foul": 0.1, "in_play": 0.1})
    assert out["status"] == "MISSING"
    assert "SAVANT_XK_WEIGHTS_UNVALIDATED" in out["reason"]


def test_pitch_outcome_rates_buckets():
    rows = []
    descs = (["called_strike"] * 16 + ["swinging_strike"] * 11
             + ["foul"] * 19 + ["hit_into_play"] * 16 + ["ball"] * 38)
    assert len(descs) == 100
    for d in descs:
        rows.append(_row(pitcher="222", description=d))
    out = pitch_outcome_rates(rows, "222")
    assert out["status"] == "AVAILABLE"
    assert out["rates"]["called_strike"] == pytest.approx(0.16)
    assert out["rates"]["whiff"] == pytest.approx(0.11)
    assert out["rates"]["foul"] == pytest.approx(0.19)
    assert out["rates"]["in_play"] == pytest.approx(0.16)
    assert out["rates"]["other"] == pytest.approx(0.38)
    assert sum(out["rates"].values()) == pytest.approx(1.0)


def test_pitch_outcome_rates_small_sample():
    out = pitch_outcome_rates([_row(pitcher="222")], "222")
    assert out["status"] == "MISSING"
    assert "SAVANT_XK_SAMPLE_TOO_SMALL" in out["reason"]


def test_pitcher_strikeout_features_reports_both():
    rows = []
    # 100 pitches, 8 terminal strikeouts -> raw K/pitch = 0.08
    for i in range(100):
        if i < 8:
            rows.append(_row(pitcher="222", events="strikeout",
                             description="swinging_strike"))
        else:
            rows.append(_row(pitcher="222", events="", description="ball"))
    weights = {"called_strike": 0.25, "whiff": 0.55, "foul": 0.10,
               "in_play": 0.02}
    out = pitcher_strikeout_features(rows, "222", weights=weights)
    assert out["status"] == "AVAILABLE"
    assert out["raw_k_per_pitch"] == pytest.approx(0.08)
    assert out["xk_per_pitch"] == pytest.approx(
        0.25 * 0.0 + 0.55 * 0.08 + 0.10 * 0.0 + 0.02 * 0.0)


# ---------------------------------------------------------------------------
# Pitch-count-first projections + percentiles
# ---------------------------------------------------------------------------

def _starter_rows(pitcher="222", outings=(95, 102, 88), start_game=900001):
    rows = []
    for gi, n in enumerate(outings):
        gpk = str(start_game + gi)
        for i in range(n):
            # every 12th pitch ends a PA as a strikeout for determinism
            if i % 12 == 11:
                rows.append(_row(pitcher=pitcher, game_pk=gpk,
                                 events="strikeout",
                                 description="swinging_strike",
                                 game_date=f"2026-09-{10 + gi:02d}"))
            else:
                rows.append(_row(pitcher=pitcher, game_pk=gpk,
                                 events="", description="ball",
                                 game_date=f"2026-09-{10 + gi:02d}"))
    return rows


def test_pitch_count_first_projection():
    rows = _starter_rows()
    hist = pitch_count_history(rows, "222")
    assert hist["status"] == "AVAILABLE"
    assert len(hist["outings"]) == 3
    proj = project_pitch_count(hist)
    assert proj["status"] == "AVAILABLE"
    assert proj["expected_pitches"] == pytest.approx((95 + 102 + 88) / 3)
    # per-pitch K rate: 285 pitches; strikeouts = pitches with i%12==11
    rates = per_pitch_event_rates(rows, "222")
    assert rates["status"] == "AVAILABLE"
    k_actual = sum(1 for n in (95, 102, 88) for i in range(n) if i % 12 == 11)
    assert rates["k_per_pitch"] == pytest.approx(k_actual / 285)
    pp = pitcher_prop_projection(expected_pitches=proj["expected_pitches"],
                                 k_per_pitch=rates["k_per_pitch"],
                                 bb_per_pitch=rates["bb_per_pitch"],
                                 out_per_pitch=rates["out_per_pitch"],
                                 k_source="raw")
    assert pp["status"] == "AVAILABLE"
    assert pp["PITCHER_K"]["mean"] == pytest.approx(
        proj["expected_pitches"] * rates["k_per_pitch"], abs=1e-3)
    pct = pp["PITCHER_K"]["percentiles"]
    assert pct["p10"] <= pct["p50"] <= pct["p90"]
    assert set(pct) == {"p10", "p50", "p90"}


def test_pitch_count_too_few_starts():
    rows = _starter_rows(outings=(95, 102))
    hist = pitch_count_history(rows, "222")
    assert hist["status"] == "MISSING"
    assert "SAVANT_PITCH_COUNT_TOO_FEW_STARTS" in hist["reason"]


def test_poisson_quantiles_known_values():
    q = poisson_quantiles(5.0)
    assert q["p50"] == 5  # median of Poisson(5)
    assert q["p10"] < q["p50"] < q["p90"]
    z = poisson_quantiles(0.0)
    assert z == {"p10": 0, "p50": 0, "p90": 0}  # degenerate Poisson(0)
    with pytest.raises(SavantFeatureError, match="SAVANT_POISSON_LAMBDA_INVALID"):
        poisson_quantiles(-1.0)
    with pytest.raises(SavantFeatureError, match="SAVANT_POISSON_LAMBDA_INVALID"):
        poisson_quantiles(float("nan"))


def test_pitcher_prop_projection_xk_source():
    pp = pitcher_prop_projection(expected_pitches=95.0, xk_per_pitch=0.075,
                                 bb_per_pitch=0.03, out_per_pitch=0.20,
                                 k_source="xk")
    assert pp["status"] == "AVAILABLE"
    assert pp["k_source"] == "xk"
    assert pp["PITCHER_K"]["mean"] == pytest.approx(95.0 * 0.075)
    assert pp["PITCHER_BB"]["mean"] == pytest.approx(95.0 * 0.03)
    assert pp["PITCHER_OUTS"]["mean"] == pytest.approx(95.0 * 0.20)
    for m in ("PITCHER_K", "PITCHER_BB", "PITCHER_OUTS"):
        pct = pp[m]["percentiles"]
        assert pct["p10"] <= pct["p50"] <= pct["p90"]


def test_pitcher_prop_projection_bad_inputs_missing():
    assert pitcher_prop_projection(
        expected_pitches=-3, k_per_pitch=0.07)["status"] == "MISSING"
    assert pitcher_prop_projection(
        expected_pitches=95, k_per_pitch=1.5)["status"] == "MISSING"
    out = pitcher_prop_projection(expected_pitches=95, k_per_pitch=0.07,
                                  k_source="bogus")
    assert out["status"] == "MISSING"


def test_attach_prop_percentiles():
    pp = pitcher_prop_projection(expected_pitches=95.0, xk_per_pitch=0.075,
                                 k_source="xk")
    row = {"market": "PITCHER_K", "model_p": 0.4}
    out = attach_prop_percentiles(row, pp)
    assert out["percentiles"]["market"] == "PITCHER_K"
    assert out["percentiles"]["p10"] <= out["percentiles"]["p50"] <= out["percentiles"]["p90"]
    # no-op on missing projection: card output never breaks
    row2 = {"market": "PITCHER_K"}
    assert attach_prop_percentiles(row2, {"status": "MISSING"}) == row2
    assert attach_prop_percentiles(row2, None) == row2
    # wrong market: no block attached
    row3 = {"market": "PITCHER_ER"}
    assert "percentiles" not in attach_prop_percentiles(row3, pp)


# ---------------------------------------------------------------------------
# Team quality + runs adjustment
# ---------------------------------------------------------------------------

def test_team_batter_quality_topbot_mapping():
    rows = []
    # away team 10 bats in Top; home team 20 bats in Bot
    for i in range(30):
        rows.append(_row(batter="111", game_pk="900001", events="single",
                         inning_topbot="Top",
                         estimated_woba_using_speedangle="0.400"))
    for i in range(30):
        rows.append(_row(batter="112", game_pk="900001", events="single",
                         inning_topbot="Bot",
                         estimated_woba_using_speedangle="0.300"))
    out = team_batter_quality(rows, {"900001": (10, 20)}, min_pa=10)
    assert out["status"] == "AVAILABLE"
    assert out["teams"]["10"]["team_xwoba"] == pytest.approx(0.400)
    assert out["teams"]["20"]["team_xwoba"] == pytest.approx(0.300)


def test_team_batter_quality_lineup_filter():
    rows = []
    for i in range(30):
        rows.append(_row(batter="111", game_pk="900001", events="single",
                         inning_topbot="Top",
                         estimated_woba_using_speedangle="0.400"))
    for i in range(30):
        rows.append(_row(batter="999", game_pk="900001", events="single",
                         inning_topbot="Top",
                         estimated_woba_using_speedangle="0.100"))
    out = team_batter_quality(rows, {"900001": (10, 20)},
                              batter_ids=["111"], min_pa=10)
    assert out["teams"]["10"]["team_xwoba"] == pytest.approx(0.400)


def test_savant_runs_adjustment_math():
    adj = savant_runs_adjustment(team_xwoba=0.340, league_xwoba=0.320, pa=380,
                                 pitcher_xwoba_against=0.300,
                                 pitcher_batters_faced=220)
    assert adj["status"] == "AVAILABLE"
    assert adj["batting_runs_added"] == pytest.approx((0.020 / 1.21) * 380,
                                                      abs=1e-3)
    assert adj["pitching_runs_allowed_vs_avg"] == pytest.approx(
        (-0.020 / 1.21) * 220, abs=1e-3)
    bad = savant_runs_adjustment(team_xwoba=0.9, league_xwoba=0.32, pa=10)
    assert bad["status"] == "MISSING"


# ---------------------------------------------------------------------------
# Factor-pipeline entry point: fail-closed behavior
# ---------------------------------------------------------------------------

def _big_synthetic_snapshot():
    rows = []
    for b in range(9):
        rows += _pa_rows(pitcher="501", batter=f"11{b}", game="900001",
                         n_pa=30, xwoba=0.330 + 0.002 * b, ev=90.0)
    for b in range(9):
        rows += _pa_rows(pitcher="502", batter=f"22{b}", game="900002",
                         n_pa=30, xwoba=0.310, ev=89.0)
    # 120 pitches for each probable starter across 4 outings
    for pid, base in (("501", 910001), ("502", 920001)):
        for gi in range(4):
            for i in range(30):
                rows.append(_row(pitcher=pid, batter="999",
                                 game_pk=str(base + gi), events="field_out",
                                 description="hit_into_play",
                                 game_date=f"2026-09-{10 + gi:02d}",
                                 estimated_woba_using_speedangle="0.290",
                                 launch_speed="87.0"))
    # filler batters so the league-average gate (>=50 entities) clears
    for b in range(40):
        rows += _pa_rows(pitcher="503", batter=f"33{b}", game="900003",
                         n_pa=5, xwoba=0.320, ev=89.0)
    return snapshot_from_csv_rows(rows, start=date(2026, 9, 1),
                                  end=date(2026, 9, 30))


def test_savant_game_quality_available():
    snap = _big_synthetic_snapshot()
    out = savant_game_quality(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        home_team_id=10, away_team_id=20,
        home_pitcher_id="501", away_pitcher_id="502",
        home_batter_ids=[f"11{b}" for b in range(9)],
        away_batter_ids=[f"22{b}" for b in range(9)],
        snapshot=snap)
    assert out["status"] in ("AVAILABLE", "PARTIAL"), out
    assert out["teams"]["home"]["batter_quality"]["status"] == "AVAILABLE"
    assert out["teams"]["home"]["pitcher_quality"]["status"] == "AVAILABLE"
    assert out["teams"]["home"]["runs_adjustment"]["status"] == "AVAILABLE"
    audit = out["coverage_audit"]
    assert "savant_batter_xwoba:home" in audit["verified_used"]
    assert out["schema_version"] == sf.SCHEMA_VERSION


def test_savant_game_quality_no_snapshot_no_opener_missing():
    out = savant_game_quality(
        as_of=datetime(2026, 10, 1, tzinfo=timezone.utc),
        home_team_id=10, away_team_id=20,
        home_pitcher_id="501", away_pitcher_id="502")
    assert out["status"] == "MISSING"
    assert "SAVANT_NO_SNAPSHOT_AND_NO_OPENER" in out["reason"]


def test_savant_game_quality_outage_never_raises():
    def boom(req, timeout=60):
        raise TimeoutError("savant down")
    out = savant_game_quality(
        as_of=datetime(2026, 10, 1, tzinfo=timezone.utc),
        home_team_id=10, away_team_id=20,
        home_pitcher_id="501", away_pitcher_id="502",
        opener=boom)
    assert out["status"] == "MISSING"
    assert "SAVANT_FETCH_FAILED" in out["reason"]
    assert out["coverage_audit"]["missing"]


def test_savant_game_quality_unverified_pitcher_is_missing_lane():
    snap = _big_synthetic_snapshot()
    out = savant_game_quality(
        as_of=datetime(2026, 10, 1, tzinfo=timezone.utc),
        home_team_id=10, away_team_id=20,
        home_pitcher_id=None, away_pitcher_id="502",
        home_batter_ids=[f"11{b}" for b in range(9)],
        away_batter_ids=[f"22{b}" for b in range(9)],
        snapshot=snap)
    assert out["status"] == "PARTIAL"
    assert "SAVANT_PROBABLE_PITCHER_UNVERIFIED" in \
        out["teams"]["home"]["pitcher_quality"]["reason"]
    assert any("savant_pitcher_quality:home" in m
               for m in out["coverage_audit"]["missing"])


def test_savant_game_quality_requires_tz_aware_as_of():
    with pytest.raises(SavantFeatureError, match="SAVANT_AS_OF_TIMEZONE_REQUIRED"):
        savant_game_quality(as_of=datetime(2026, 10, 1),
                            home_team_id=10, away_team_id=20,
                            home_pitcher_id="501", away_pitcher_id="502")
