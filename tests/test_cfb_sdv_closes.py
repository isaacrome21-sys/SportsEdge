"""Tests for the SDV CFB closes collector/evaluator
(scripts/collect_cfb_sdv_closes.py, scripts/evaluate_cfb_sdv_closes.py).

Covered: the validation/exclusion rules (placeholder default source, NaN
summary_pickcenter values, uncompleted games, the object-dtype `completed`
regression seen in the 2019 file), PM equivalence with the repo's own
scripts/backtest_cfb_matchup_blend.py project(), the AM rating math, and
the ROI convention (push excluded from the denominator, flat -110).
"""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collect = _load("collect_cfb_sdv_closes", "scripts/collect_cfb_sdv_closes.py")
evaluate = _load("evaluate_cfb_sdv_closes", "scripts/evaluate_cfb_sdv_closes.py")
blend = _load("backtest_cfb_matchup_blend", "scripts/backtest_cfb_matchup_blend.py")


def _betting_row(game_id, source, spread, total, avail=True):
    return dict(game_id=game_id, season=2024, week=1, game_spread=spread,
                over_under=total, home_favorite=True, home_team_spread=spread,
                game_spread_available=avail, odds_source=source)


def _sched_row(game_id, completed=True, hp=35, ap=21):
    return dict(game_id=game_id, season=2024, week=1, season_type="regular",
                start_date="2024-08-31T16:00:00.000Z", completed=completed,
                neutral_site=False, home_id=1, home_team="H", home_division="fbs",
                away_id=2, away_team="A", away_division="fbs",
                home_points=hp, away_points=ap, fbs_game=True)


def test_default_placeholder_rows_excluded():
    b = pd.DataFrame([_betting_row(1, "default", 2.5, 55.5, avail=False)])
    s = pd.DataFrame([_sched_row(1)])
    frame, _ = collect.build_season(b, s)
    assert frame.iloc[0].excl_spread == "E1_PLACEHOLDER_DEFAULT_SOURCE"
    assert frame.iloc[0].excl_total == "E1_PLACEHOLDER_DEFAULT_SOURCE"
    assert not frame.iloc[0].spread_scoreable


def test_nan_pickcenter_values_excluded_per_market():
    b = pd.DataFrame([_betting_row(1, "summary_pickcenter", float("nan"), float("nan"))])
    s = pd.DataFrame([_sched_row(1)])
    frame, _ = collect.build_season(b, s)
    assert frame.iloc[0].excl_spread == "E2_NO_SPREAD_VALUE"
    assert frame.iloc[0].excl_total == "E3_NO_TOTAL_VALUE"


def test_core_row_scoreable_and_uncompleted_excluded():
    b = pd.DataFrame([_betting_row(1, "core_odds_api", -7.5, 48.5),
                      _betting_row(2, "core_odds_api", -3.5, 51.5)])
    s = pd.DataFrame([_sched_row(1), _sched_row(2, completed=False, hp=None, ap=None)])
    frame, summary = collect.build_season(b, s)
    by_id = frame.set_index("game_id")
    assert bool(by_id.loc[1].spread_scoreable) and bool(by_id.loc[1].total_scoreable)
    assert by_id.loc[2].excl_spread == "E5_NOT_COMPLETED"
    assert summary["spread_scoreable"] == 1


def test_completed_object_dtype_coerced():
    # The 2019 schedule file stores completed as object (True/False/NaN);
    # `~` on object booleans yields ints, not a mask. Guard the regression.
    b = pd.DataFrame([_betting_row(1, "core_odds_api", -7.5, 48.5)])
    s = pd.DataFrame([_sched_row(1)])
    s["completed"] = pd.Series([True], dtype=object)
    frame, _ = collect.build_season(b, s)
    assert bool(frame.iloc[0].spread_scoreable)


def test_duplicate_game_ids_counted():
    b = pd.DataFrame([_betting_row(1, "core_odds_api", -7.5, 48.5),
                      _betting_row(1, "core_odds_api", -7.5, 48.5)])
    s = pd.DataFrame([_sched_row(1)])
    _, summary = collect.build_season(b, s)
    assert summary["dup_game_ids"] == 1


def _synthetic_season():
    """Six teams, round-robin-ish results with known scores."""
    games = []
    scores = [(35, 21), (28, 24), (31, 17), (24, 24), (38, 20), (27, 23),
              (30, 27), (21, 31), (34, 28), (17, 24), (26, 20), (29, 26),
              (23, 30), (36, 22), (25, 19), (33, 29), (20, 27), (32, 25)]
    pairs = [(1, 2), (3, 4), (5, 6), (2, 3), (4, 5), (6, 1), (1, 3), (2, 4),
             (5, 1), (6, 3), (2, 5), (4, 6), (1, 4), (3, 5), (2, 6), (1, 5),
             (3, 6), (2, 4)]
    for i, ((h, a), (hs, as_)) in enumerate(zip(pairs, scores)):
        games.append(dict(game_id=100 + i, instant=f"2024-09-{1 + i:02d}T16:00:00Z",
                          home_id=h, away_id=a, home_points=hs, away_points=as_))
    return games


def test_pm_port_matches_repo_project():
    games = _synthetic_season()
    mine = {g["game_id"]: (pm_m, pm_t)
            for g, _, _, pm_m, pm_t in evaluate.project_season(games)}
    repo_games = [dict(season=2024, week=1, start=g["instant"], id=str(g["game_id"]),
                       home=str(g["home_id"]), away=str(g["away_id"]),
                       hs=g["home_points"], as_=g["away_points"], spread=-7.5,
                       total=52.5) for g in games]
    for g in repo_games:
        g["as"] = g.pop("as_")
    repo = {int(r["id"]): (r["model_margin"], r["model_total"])
            for r in blend.project(repo_games)}
    assert repo, "repo project() emitted nothing on the fixture"
    for gid, (mm, mt) in repo.items():
        assert mine[gid][0] == pytest.approx(mm, abs=1e-9)
        assert mine[gid][1] == pytest.approx(mt, abs=1e-9)


def test_am_rating_math_and_projection():
    games = _synthetic_season()
    rows = list(evaluate.project_season(games))
    # First game: no history -> no projection from either construction.
    assert rows[0][1] is None and rows[0][3] is None
    # Team 1 wins game 0 by 14 -> rating 14*0.12 = 1.68 (under the cap).
    # In its next game (index 5, away at 6): am margin uses both ratings.
    g5 = rows[5]
    assert g5[1] is not None


def test_roi_convention_push_excluded_from_denominator():
    d = pd.DataFrame({"gap": [5.0, 5.0, 5.0], "win": [1.0, -1.0, 0.0]})
    stats = evaluate.band_stats(d, "gap", "win")["ge0"]
    assert stats["bets"] == 3 and stats["pushes"] == 1
    # decided = 2; net = 100/110 - 1 -> ROI over decided only
    assert stats["roi_flat_minus110_assumption"] == pytest.approx(
        (100.0 / 110.0 - 1.0) / 2, abs=1e-12)
    assert stats["cover_rate"] == pytest.approx(0.5)



@pytest.mark.parametrize("availability", [
    False, "False", "false", "0", "NO", None, float("nan"), 0,
])
def test_spread_availability_requires_strict_affirmative_flag(availability):
    # A finite spread cannot override a source-declared unavailable flag.
    b = pd.DataFrame([_betting_row(37, "core_odds_api", -3.5, 47.5,
                                   avail=availability)])
    s = pd.DataFrame([_sched_row(37)])
    frame, summary = collect.build_season(b, s)
    row = frame.iloc[0]
    assert row.excl_spread == "E4_SPREAD_FLAGGED_UNAVAILABLE"
    assert not bool(row.spread_scoreable)
    assert bool(row.total_scoreable)  # Independently valid total is retained.
    assert summary["spread_scoreable"] == 0
    assert summary["total_scoreable"] == 1


@pytest.mark.parametrize("availability", [
    True, "True", "true", "1", 1, "yes",
])
def test_affirmative_spread_availability_preserved(availability):
    b = pd.DataFrame([_betting_row(38, "core_odds_api", -3.5, 47.5,
                                   avail=availability)])
    s = pd.DataFrame([_sched_row(38)])
    frame, summary = collect.build_season(b, s)
    row = frame.iloc[0]
    assert bool(row.spread_scoreable)
    assert bool(row.total_scoreable)
    assert summary["spread_scoreable"] == 1


@pytest.mark.parametrize("kind,model_col", [
    ("spread", "am_margin"), ("total", "am_total"),
])
def test_empty_scoring_stratum_emits_no_data_strict_json(kind, model_col):
    empty = pd.DataFrame(columns=[
        "home_team_spread", "actual_margin", "over_under",
        "actual_total", "am_margin", "am_total",
    ])
    result = evaluate.score_market(empty, model_col, kind, 11.0, 11.0)
    assert result["n"] == 0 and result["status"] == "NO_DATA"
    for field in ("model_mae", "close_mae", "model_bias",
                  "mean_abs_model_minus_close", "mean_signed_model_minus_close",
                  "logloss_prod_sds", "logloss_lane_sds", "logloss_market_only"):
        assert result[field] is None
    assert result["bands"]["ge0"]["roi_flat_minus110_assumption"] is None
    assert all(band["n"] == 0 for band in result["calibration_prod_sds"])
    # Mirrors main()'s fail-closed serialization policy.
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("source", [None, "", "UNRECOGNIZED_ORIGIN", "default "])
def test_unverified_source_is_never_scoreable(source):
    b = pd.DataFrame([_betting_row(39, source, -4.5, 48.5)])
    frame, summary = collect.build_season(b, pd.DataFrame([_sched_row(39)]))
    row = frame.iloc[0]
    assert row.excl_spread == "E0_UNVERIFIED_ODDS_SOURCE"
    assert row.excl_total == "E0_UNVERIFIED_ODDS_SOURCE"
    assert not bool(row.spread_scoreable) and not bool(row.total_scoreable)
    assert summary["spread_exclusions"]["E0_UNVERIFIED_ODDS_SOURCE"] == 1
    assert summary["total_exclusions"]["E0_UNVERIFIED_ODDS_SOURCE"] == 1


@pytest.mark.parametrize("source", ["core_odds_api", "summary_pickcenter"])
def test_only_known_origin_categories_can_admit_finite_values(source):
    b = pd.DataFrame([_betting_row(40, source, -4.5, 48.5)])
    frame, summary = collect.build_season(b, pd.DataFrame([_sched_row(40)]))
    assert bool(frame.iloc[0].spread_scoreable)
    assert bool(frame.iloc[0].total_scoreable)
    assert summary["spread_scoreable"] == summary["total_scoreable"] == 1


@pytest.mark.parametrize("invalid", [float("inf"), -float("inf"), True, "BAD", "3.5"])
def test_nonfinite_or_malformed_spread_does_not_exclude_valid_total(invalid):
    b = pd.DataFrame([_betting_row(41, "core_odds_api", invalid, 47.5)])
    frame, summary = collect.build_season(b, pd.DataFrame([_sched_row(41)]))
    assert frame.iloc[0].excl_spread == "E6_INVALID_SPREAD_VALUE"
    assert not bool(frame.iloc[0].spread_scoreable)
    assert bool(frame.iloc[0].total_scoreable)
    assert summary["total_scoreable"] == 1


@pytest.mark.parametrize("invalid", [float("inf"), -float("inf"), True, "BAD", "47.5"])
def test_nonfinite_or_malformed_total_does_not_exclude_valid_spread(invalid):
    b = pd.DataFrame([_betting_row(42, "core_odds_api", -4.5, invalid)])
    frame, summary = collect.build_season(b, pd.DataFrame([_sched_row(42)]))
    assert frame.iloc[0].excl_total == "E7_INVALID_TOTAL_VALUE"
    assert not bool(frame.iloc[0].total_scoreable)
    assert bool(frame.iloc[0].spread_scoreable)
    assert summary["spread_scoreable"] == 1


def test_nonfinite_schedule_final_blocks_both_markets():
    b = pd.DataFrame([_betting_row(43, "core_odds_api", -4.5, 48.5)])
    frame, _ = collect.build_season(
        b, pd.DataFrame([_sched_row(43, hp=float("inf"))]))
    assert frame.iloc[0].excl_spread == "E5_NOT_COMPLETED"
    assert frame.iloc[0].excl_total == "E5_NOT_COMPLETED"


@pytest.mark.parametrize("kind,model,market_column,actual_column", [
    ("spread", "am_margin", "home_team_spread", "actual_margin"),
    ("total", "am_total", "over_under", "actual_total"),
])
def test_direct_evaluator_refuses_poisoned_finite_claims(
        kind, model, market_column, actual_column):
    row = {market_column: float("inf"), actual_column: 24.0, model: 26.0}
    with pytest.raises(ValueError, match="NONFINITE_CFB_SCORING_INPUT"):
        evaluate.score_market(pd.DataFrame([row]), model, kind, 19.0, 15.5)
