"""Adversarial tests (Isaac: "try to break it, fix it, improve, refine").

Red-teams every factor with stale / missing / contradictory inputs and
asserts fail-closed reason codes fire -- never silent defaults. Also
red-teams the harness gate itself with a spurious in-sample-fitted factor
and asserts the gate rejects it out-of-sample.

No network. Research only.
"""
import hashlib
import importlib.util
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
HARNESS = Path("/home/hatch/workspace/sportsedge-backtest")


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load free_factors standalone (no package import: the harness worktree's
# `sportsedge` package must win for `sportsedge.backtest` below).
ff = _load("adv_ff", WORKTREE / "sportsedge" / "free_factors.py")
sys.path.insert(0, str(HARNESS))


# ---------------------------------------------------------------------------
# Part 1: stale / missing / contradictory inputs -> fail closed
# ---------------------------------------------------------------------------

def test_stale_park_table():
    # Table covers 2022-2024 (MAX_SEASON 2025). A 2027 game must not price.
    pf, status, _ = ff.park_factor_for("Boston Red Sox", 2027)
    assert pf is None and status == "PARK_FACTOR_STALE"
    e = ff.ingest_mlb_park("Boston Red Sox", 2027)
    assert e["verified"] is False and e["value"] is None


def test_contradictory_park_season():
    pf, status, _ = ff.park_factor_for("Boston Red Sox", "next year")
    assert pf is None and status == "PARK_FACTOR_SEASON_UNVERIFIED"
    pf, status, _ = ff.park_factor_for("", 2025)
    assert pf is None and status == "PARK_FACTOR_TEAM_UNVERIFIED"


def test_contradictory_rest():
    # Negative rest days (played in the future) is contradictory data ->
    # fail closed (fixed 2026-10-11: was silently clamped before).
    adj, status, detail = ff.rest_margin_adjustment(-3, 6)
    assert adj == 0.0 and status == "REST_UNVERIFIED"
    assert "contradictory" in detail
    # NaN / infinite must fail closed.
    adj, status, _ = ff.rest_margin_adjustment(float("nan"), 6)
    assert adj == 0.0 and status == "REST_UNVERIFIED"
    adj, status, _ = ff.rest_margin_adjustment(float("inf"), 6)
    assert adj == 0.0 and status == "REST_UNVERIFIED"


def test_contradictory_travel():
    adj, status, _ = ff.travel_margin_adjustment(-100, 2)
    assert adj == 0.0 and status == "TRAVEL_UNVERIFIED"
    adj, status, _ = ff.travel_margin_adjustment(1500, -2)
    assert adj == 0.0 and status == "TRAVEL_UNVERIFIED"
    adj, status, _ = ff.travel_margin_adjustment(1500, 2, traveler="SOMEWHERE")
    assert adj == 0.0 and status == "TRAVEL_UNVERIFIED"


def test_contradictory_weather():
    adj, status, _ = ff.weather_total_adjustment(sport="NFL", wind_speed_mph=-5)
    assert adj == 0.0 and status == "WEATHER_UNVERIFIED"
    adj, status, _ = ff.weather_total_adjustment(sport="NFL", wind_speed_mph=20,
                                                precip_probability_pct=150)
    assert adj == 0.0 and status == "WEATHER_UNVERIFIED"
    adj, status, _ = ff.weather_total_adjustment(sport="NHL", wind_speed_mph=20)
    assert adj == 0.0 and status == "WEATHER_NOT_APPLICABLE"


def test_contradictory_key_numbers():
    # NaN line: fail closed to the normal push (was a crash before red-team).
    p, status, _ = ff.key_number_push_probability("NFL", float("nan"), 0.05)
    assert p == 0.05 and status == "KEY_NUMBER_PUSH_INVALID"
    p, status, _ = ff.key_number_push_probability("NFL", None, 0.05)
    assert p == 0.05 and status == "KEY_NUMBER_NOT_APPLICABLE"
    p, status, _ = ff.key_number_push_probability("NFL", 100, 0.05)
    assert p == 0.05  # beyond table support


def test_contradictory_pitcher():
    adj, status, _ = ff.pitcher_quality_adjustment(-1.0, 30)
    assert adj == 0.0 and status == "PITCHER_HISTORY_INSUFFICIENT"
    adj, status, _ = ff.pitcher_quality_adjustment(float("nan"), 30)
    assert adj == 0.0 and status == "PITCHER_HISTORY_INSUFFICIENT"


def test_ingest_never_silent():
    # Every ingest entry point with garbage inputs must return verified=False
    # and a null/zero value -- never a silent pricing default.
    cases = [
        ff.ingest_mlb_park("", "bogus"),
        ff.ingest_rest("NFL", None, None),
        ff.ingest_travel("NFL", "AWAY", None, None),
        ff.ingest_weather("NFL", float("nan")),
        ff.ingest_key_numbers("NFL", "SPREAD", float("nan"), 0.5, 0.05, 0.45),
        ff.ingest_mlb_pitcher("home", "", None, 0),
        ff.ingest_mlb_bullpen("away", None, 0),
        ff.ingest_mlb_rotation("home", None),
        ff.ingest_participation("NFL", "home", False),
        ff.ingest_srs_margin({}, "A", "B", 1.5),
        ff.ingest_venue_hfa([], [], 1.5),
        ff.ingest_pace(None, None, None),
        ff.ingest_turnovers(None, "home"),
        ff.ingest_mlb_pitcher_fip("home", "", None, 0),
        ff.ingest_epa_margin(None, None),
    ]
    for e in cases:
        assert e["verified"] is False, e["factor"]
        assert e["value"] in (None, 0.0, (0.0, 0.0, 0.0)) or e["kind"] == "none", e["factor"]
        assert e["status"] and e["detail"], e["factor"]


# ---------------------------------------------------------------------------
# Part 2: red-team the harness gate with a spurious in-sample factor
# ---------------------------------------------------------------------------
# A noise factor with its coefficient FIT IN-SAMPLE on each train split
# (the classic researcher degrees-of-freedom trap). The walk-forward gate
# must reject it out-of-sample: strict improvement required on BOTH metrics.

def _synthetic_fixtures(n=240, seed=7, planted_corr=False):
    rng = random.Random(seed)
    fixtures = []
    base = datetime(2024, 9, 1, tzinfo=timezone.utc)
    for i in range(n):
        kickoff = base + timedelta(days=i)
        # True home win prob varies smoothly; outcomes drawn from it.
        p_true = 0.55 + 0.15 * math.sin(i / 12.0)
        # NOTE: built-in hash() is salted per process (PYTHONHASHSEED); use a
        # stable digest so the suite is deterministic (flakiness fix
        # 2026-10-11: these gate tests passed/failed at random across runs).
        noise = (hashlib.md5(f"synth-{i:04d}".encode()).digest()[0] % 2) * 2 - 1
        p = p_true
        if planted_corr and i < 80:
            # Planted spurious correlation ONLY in the initial training
            # window (i<80, never in any walk-forward test set starting at
            # i=80): the classic "found something in-sample" trap. All test
            # data is clean, so a gate that respects chronology must reject.
            p = max(0.01, min(0.99, p_true + 0.10 * noise))
        y = 1.0 if rng.random() < p else 0.0
        fixtures.append({
            "fixture_id": f"synth-{i:04d}",
            "kickoff": kickoff.isoformat(),
            "as_of": (kickoff - timedelta(hours=2)).isoformat(),
            "home_team": f"Home{i % 8}", "away_team": f"Away{i % 8}",
            "home_score": 24 if y == 1.0 else 20,
            "away_score": 20 if y == 1.0 else 24,
            "_p_true": p_true,
            "_noise": noise,
        })
    return fixtures


def _gate_verdict_for_candidate(candidate_price_fn, planted_corr=False):
    from sportsedge.backtest import runner, splits, report, outcomes

    fixtures = _synthetic_fixtures(planted_corr=planted_corr)

    def price_fn(model_name, fixture, as_of, train):
        p = fixture["_p_true"]
        if model_name == "candidate":
            p = candidate_price_fn(fixture, train, p)
        p = max(0.01, min(0.99, p))
        return [{"market": "ML", "selection": "HOME", "model_p": p}]

    def settle_fn(fixture, market, selection, line):
        return outcomes.settle_game(
            {"home_score": fixture["home_score"],
             "away_score": fixture["away_score"]}, market, selection, line)

    sp = list(splits.walk_forward_splits(fixtures, min_train=80,
                                         test_size=40, embargo_days=0))
    result = runner.run_backtest(
        fixtures=fixtures, splits=sp, models=["existing", "candidate"],
        price_fn=price_fn, settle_fn=settle_fn, market_baseline=None)
    comp = runner.compare_models(result)
    return report.evaluate(
        candidate=comp["models"]["candidate"],
        existing=comp["models"]["existing"],
        baseline_status=comp["baseline"]["status"],
        baseline=comp["baseline"]["summary"])


def _fit_noise_coefficient(train):
    # In-sample fit: least squares of (y - p) on per-fixture noise.
    num = den = 0.0
    for fx in train:
        resid = (1.0 if fx["home_score"] > fx["away_score"] else 0.0) - fx["_p_true"]
        num += fx["_noise"] * resid
        den += fx["_noise"] * fx["_noise"]
    return num / den if den else 0.0


def _in_sample_brier_gain(candidate_price_fn, fixtures):
    # How much better the candidate looks IN-SAMPLE on the planted window.
    from sportsedge.backtest import metrics
    train = fixtures[:80]
    recs = []
    for fx in train:
        y = 1.0 if fx["home_score"] > fx["away_score"] else 0.0
        p = candidate_price_fn(fx, train, fx["_p_true"])
        p = max(0.01, min(0.99, p))
        recs.append({"model_p": p, "outcome": y})
    base = [{"model_p": fx["_p_true"], "outcome": 1.0 if fx["home_score"] > fx["away_score"] else 0.0}
            for fx in train]
    return metrics.brier_score(base) - metrics.brier_score(recs)


def test_gate_rejects_spurious_in_sample_factor():
    import importlib.util as _ilu
    pytest = __import__("pytest")
    if _ilu.find_spec("sportsedge.backtest") is None:
        pytest.skip("sportsedge.backtest not available (Phase 00 not merged)")
    # Adversarial: a spurious correlation planted in the early data makes
    # the noise factor look predictive IN-SAMPLE (researcher thinks they
    # found an edge). The walk-forward gate must reject it out-of-sample.
    fixtures = _synthetic_fixtures(planted_corr=True)

    def candidate(fixture, train, p):
        return p + _fit_noise_coefficient(train) * fixture["_noise"]

    in_sample_gain = _in_sample_brier_gain(candidate, fixtures)
    assert in_sample_gain > 0, "planted correlation should look good in-sample"

    verdict = _gate_verdict_for_candidate(candidate, planted_corr=True)
    assert verdict["verdict"] == "FAIL", verdict


def test_gate_rejects_fixed_noise():
    import importlib.util as _ilu
    pytest = __import__("pytest")
    if _ilu.find_spec("sportsedge.backtest") is None:
        pytest.skip("sportsedge.backtest not available (Phase 00 not merged)")
    def candidate(fixture, train, p):
        return p + 0.08 * fixture["_noise"]

    verdict = _gate_verdict_for_candidate(candidate)
    assert verdict["verdict"] == "FAIL", verdict


def test_gate_passes_true_signal():
    import importlib.util as _ilu
    pytest = __import__("pytest")
    if _ilu.find_spec("sportsedge.backtest") is None:
        pytest.skip("sportsedge.backtest not available (Phase 00 not merged)")
    # Sanity: the gate DOES pass a genuinely predictive factor (slightly
    # better-calibrated than the existing model), so the bar isn't impossible.
    def candidate(fixture, train, p):
        y = 1.0 if fixture["home_score"] > fixture["away_score"] else 0.0
        # NOTE: uses the fixture outcome -- lookahead, for gate-calibration
        # ONLY. Production adapters must never do this.
        return 0.9 * p + 0.1 * y

    verdict = _gate_verdict_for_candidate(candidate)
    assert verdict["verdict"] in ("PASS", "CONDITIONAL_PASS"), verdict


def test_adversarial_time_decay_stale():
    # Stale inputs: very old games get near-zero weight, not equal weight
    vals = [(10.0, 0.0), (10.0, 365.0)]  # one today, one a year ago
    m, status = ff.decay_weighted_mean(vals, 30.0)
    assert status == "TIME_DECAY_VERIFIED"
    # The year-old game should have negligible weight: mean ~10.0
    # (if it were equal-weighted, mean would be 10.0 anyway; use differing values)
    vals2 = [(0.0, 0.0), (100.0, 365.0)]
    m2, _ = ff.decay_weighted_mean(vals2, 30.0)
    assert m2 < 1.0  # stale 100 barely moves the mean


def test_adversarial_time_decay_contradictory():
    # Contradictory: negative age (future game) must raise, not silently use
    try:
        ff.time_decay_weight(-5, 30.0)
    except ValueError as exc:
        assert "NEGATIVE_AGE" in str(exc)
    else:
        raise AssertionError("future game age must raise")


def test_adversarial_weather_interaction_missing():
    # Missing temp -> fail closed, not zero-effect silently
    adj, status, _ = ff.weather_interaction_adjustment(sport="MLB", humidity_pct=80)
    assert adj == 0.0
    assert status == "WEATHER_INTERACTION_UNVERIFIED"
    # Missing pass rate -> fail closed
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="NFL", base_wind_adj=-1.5)
    assert adj == 0.0
    assert status == "WEATHER_INTERACTION_UNVERIFIED"


def test_adversarial_weather_interaction_implausible():
    # Implausible temp (200F) -> fail closed
    adj, status, _ = ff.weather_interaction_adjustment(sport="MLB", temp_f=200)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"
    # Pass rate >1 -> fail closed
    adj, status, _ = ff.weather_interaction_adjustment(
        sport="NFL", pass_rate=2.0, base_wind_adj=-1.5)
    assert adj == 0.0 and status == "WEATHER_INTERACTION_UNVERIFIED"
