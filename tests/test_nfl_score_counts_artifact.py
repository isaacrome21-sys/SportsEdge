from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.score_counts_artifact import (
    ScoreCountArtifactError,
    build_attempt_fit_artifact,
    build_forward_prediction,
    fit_from_artifact,
)
from sportsedge.sports.nfl.score_counts_g1 import (
    FEATURE_NAMES,
    FG_ATTEMPT_FEATURE_NAMES,
    FG_MODEL_ATTEMPT_RATE_X_PRIOR_MAKE,
    predict_mean,
)


SOURCE = "a" * 64
PREREG = "b" * 64
CODE = "score-counts-test-code-v1"


def team_row(season: int, game: int, home: bool) -> dict:
    side = 1 if home else -1
    row = {
        "game_id": f"{season}_{game:02d}",
        "season": season,
        "week": 1 + game,
        "game_start_ts": f"{season}-10-{1+game:02d}T17:00:00+00:00",
        "team": f"{'H' if home else 'A'}{game}",
        "opponent": f"{'A' if home else 'H'}{game}",
        "home_indicator": 1.0 if home else 0.0,
        "feature_digest": ("%064x" % (season * 1000 + game * 2 + (1 if home else 0))),
    }
    for idx, name in enumerate(FEATURE_NAMES):
        if name == "home_indicator":
            continue
        base = 0.02 * (idx + 1) + 0.001 * (season - 2018) + 0.003 * game
        row[name] = base + side * 0.004
    strength = (season - 2018) * 0.08 + game * 0.11 + (0.25 if home else 0.0)
    row["offense_touchdowns"] = int(max(0, round(1.4 + strength % 2.8)))
    row["made_field_goals"] = int(max(0, round(0.8 + (strength * 1.7) % 2.2)))
    row["field_goal_attempts"] = row["made_field_goals"] + int((season + game + int(home)) % 3 == 0)
    row["fg_attempts_per_game"] = 2.0 + 0.04 * game + (0.08 if home else 0.0)
    row["opp_fg_attempts_allowed_per_game"] = 2.1 + 0.02 * game - (0.05 if home else 0.0)
    row["fg_make_rate_shrunk"] = 0.82 + 0.01 * ((season + game) % 5)
    row["def_st_touchdowns"] = int((season + game + int(home)) % 19 == 0)
    row["safeties"] = int((season + 2 * game + int(home)) % 47 == 0)
    total_td = row["offense_touchdowns"] + row["def_st_touchdowns"]
    row["two_point_made"] = int(total_td >= 2 and (season + game) % 7 == 0)
    row["pat_made"] = max(0, total_td - row["two_point_made"] - (1 if total_td and (season + game) % 23 == 0 else 0))
    row["no_conversion"] = total_td - row["pat_made"] - row["two_point_made"]
    return row


def development_rows() -> list[dict]:
    out = []
    for season in range(2018, 2026):
        for game in range(1, 7):
            out.append(team_row(season, game, True))
            out.append(team_row(season, game, False))
    return out


def fit_artifact():
    return build_attempt_fit_artifact(
        development_rows(),
        attempt_number=1,
        source_manifest_sha256=SOURCE,
        code_identity=CODE,
        prereg_addendum_sha256=PREREG,
    )


def forward_rows() -> list[dict]:
    out = []
    for home in (True, False):
        row = team_row(2025, 5, home)
        for key in (
            "offense_touchdowns", "made_field_goals", "field_goal_attempts",
            "def_st_touchdowns", "safeties", "pat_made", "two_point_made", "no_conversion",
        ):
            row.pop(key, None)
        row["game_id"] = "2026_05_TB_DAL"
        row["season"] = 2026
        row["week"] = 5
        row["game_start_ts"] = "2026-10-09T00:15:00+00:00"
        row["team"] = "DAL" if home else "TB"
        row["opponent"] = "TB" if home else "DAL"
        row["feature_digest"] = ("c" if home else "d") * 64
        row["def_st_td_rate"] = 0.08 if home else 0.07
        row["safety_rate"] = 0.015
        row["conversion_pat_p"] = 0.91
        row["conversion_two_p"] = 0.06
        row["conversion_no_p"] = 0.03
        out.append(row)
    return out


def test_attempt_fit_artifact_is_deterministic_and_replayable():
    a = fit_artifact()
    b = fit_artifact()
    assert a == b
    assert a["artifact_sha256"] == b["artifact_sha256"]
    assert a["attempt_number"] == 1
    assert a["development_seasons"] == list(range(2018, 2026))
    assert a["development_gate"]["market_data_used"] is False
    assert a["status"] == ("DEVELOPMENT_ATTEMPT_PASS" if a["development_gate"]["pass"] else "DEVELOPMENT_ATTEMPT_FAIL")
    assert a["selection"]["shared_sigma"]["selected_sigma"] in [0.0, 0.1, 0.2, 0.3]
    fit = fit_from_artifact(a)
    assert fit.source_manifest_sha256 == SOURCE
    assert fit.code_identity == CODE
    assert predict_mean(fit.td_model, development_rows()[0]) > 0


def test_tampered_fit_artifact_fails_digest():
    art = fit_artifact()
    art["fit"]["shared_sigma"] = 0.3 if art["fit"]["shared_sigma"] != 0.3 else 0.2
    with pytest.raises(ScoreCountArtifactError, match="FIT_ARTIFACT_DIGEST_MISMATCH"):
        fit_from_artifact(art)


def test_forward_prediction_is_deterministic_market_blind_and_50k_paths():
    fit = fit_artifact()
    kwargs = dict(
        prediction_at=datetime(2026, 10, 8, 23, 0, tzinfo=timezone.utc),
        source_manifest_sha256=SOURCE,
        code_identity=CODE,
        paths=50000,
    )
    a = build_forward_prediction(fit, forward_rows(), **kwargs)
    b = build_forward_prediction(fit, forward_rows(), **kwargs)
    assert a == b
    assert a["prediction_sha256"] == b["prediction_sha256"]
    assert a["market_data_present"] is False
    assert a["outcome_data_present"] is False
    assert len(a["games"]) == 1
    game = a["games"][0]
    assert game["paths"] == 50000
    assert sum(row[2] for row in game["joint_score_distribution"]) == 50000
    assert len(game["joint_score_distribution_sha256"]) == 64


def test_forward_outcome_or_market_data_fails_closed():
    fit = fit_artifact()
    rows = forward_rows()
    rows[0]["home_score"] = 27
    with pytest.raises(ScoreCountArtifactError, match="FORWARD_ROW_FORBIDDEN_FIELD"):
        build_forward_prediction(
            fit, rows, prediction_at="2026-10-08T23:00:00Z",
            source_manifest_sha256=SOURCE, code_identity=CODE,
        )
    rows = forward_rows()
    rows[0]["spread_line"] = -3.5
    with pytest.raises(ScoreCountArtifactError, match="FORWARD_ROW_FORBIDDEN_FIELD"):
        build_forward_prediction(
            fit, rows, prediction_at="2026-10-08T23:00:00Z",
            source_manifest_sha256=SOURCE, code_identity=CODE,
        )


def test_forward_identity_and_time_boundaries_fail_closed():
    fit = fit_artifact()
    with pytest.raises(ScoreCountArtifactError, match="FORWARD_SOURCE_MANIFEST_MISMATCH"):
        build_forward_prediction(
            fit, forward_rows(), prediction_at="2026-10-08T23:00:00Z",
            source_manifest_sha256="e" * 64, code_identity=CODE,
        )
    with pytest.raises(ScoreCountArtifactError, match="FORWARD_CODE_IDENTITY_MISMATCH"):
        build_forward_prediction(
            fit, forward_rows(), prediction_at="2026-10-08T23:00:00Z",
            source_manifest_sha256=SOURCE, code_identity="different",
        )
    with pytest.raises(ScoreCountArtifactError, match="PREDICTION_MUST_PRECEDE_KICKOFF"):
        build_forward_prediction(
            fit, forward_rows(), prediction_at="2026-10-09T00:15:00Z",
            source_manifest_sha256=SOURCE, code_identity=CODE,
        )


def test_attempt_budget_is_exactly_three():
    rows = development_rows()
    with pytest.raises(ScoreCountArtifactError, match="ATTEMPT_NUMBER_OUT_OF_FROZEN_BUDGET"):
        build_attempt_fit_artifact(
            rows, attempt_number=4, source_manifest_sha256=SOURCE,
            code_identity=CODE, prereg_addendum_sha256=PREREG,
        )


def test_uninformative_model_fails_strict_development_gate():
    rows = development_rows()
    for row in rows:
        for name in FEATURE_NAMES:
            if name != "home_indicator":
                row[name] = 0.0
        # Preserve the factual home/away identity required by the joint-score
        # covariance layer. Zero only predictive features; the constant labels
        # still make this deliberately uninformative for the strict dev gate.
        row["offense_touchdowns"] = 2
        row["made_field_goals"] = 1
    art = build_attempt_fit_artifact(
        rows,
        attempt_number=1,
        source_manifest_sha256=SOURCE,
        code_identity=CODE,
        prereg_addendum_sha256=PREREG,
    )
    assert art["development_gate"]["pass"] is False
    assert art["status"] == "DEVELOPMENT_ATTEMPT_FAIL"
    for target in ("offense_touchdowns", "made_field_goals"):
        result = art["development_gate"]["targets"][target]
        assert result["fold_wins"] == 0
        assert result["minimum_fold_wins"] == 3
        assert result["pass"] is False


def test_attempt2_artifact_uses_frozen_two_stage_fg_spec_and_same_td_fit():
    rows = development_rows()
    attempt1 = build_attempt_fit_artifact(
        rows,
        attempt_number=1,
        source_manifest_sha256=SOURCE,
        code_identity=CODE,
        prereg_addendum_sha256=PREREG,
    )
    attempt2 = build_attempt_fit_artifact(
        rows,
        attempt_number=2,
        source_manifest_sha256=SOURCE,
        code_identity=CODE,
        prereg_addendum_sha256="c" * 64,
    )
    assert attempt2["attempt_number"] == 2
    assert attempt2["fit"]["fg_model_kind"] == FG_MODEL_ATTEMPT_RATE_X_PRIOR_MAKE
    assert attempt2["fit"]["fg_model"]["target"] == "field_goal_attempts"
    assert tuple(attempt2["fit"]["fg_model"]["feature_names"]) == FG_ATTEMPT_FEATURE_NAMES
    assert attempt2["development_gate"]["targets"]["made_field_goals"]["model_target"] == "field_goal_attempts"
    assert attempt2["development_gate"]["targets"]["made_field_goals"]["minimum_fold_wins"] == 3
    assert attempt2["fit"]["td_model"] == attempt1["fit"]["td_model"]
    replay = fit_from_artifact(attempt2)
    assert replay.fg_model_kind == FG_MODEL_ATTEMPT_RATE_X_PRIOR_MAKE


def test_forward_rows_reject_current_game_field_goal_attempt_label():
    fit = build_attempt_fit_artifact(
        development_rows(),
        attempt_number=2,
        source_manifest_sha256=SOURCE,
        code_identity=CODE,
        prereg_addendum_sha256="c" * 64,
    )
    rows = forward_rows()
    rows[0]["field_goal_attempts"] = 2
    with pytest.raises(ScoreCountArtifactError, match="FORWARD_ROW_FORBIDDEN_FIELD"):
        build_forward_prediction(
            fit,
            rows,
            prediction_at="2026-10-08T23:00:00Z",
            source_manifest_sha256=SOURCE,
            code_identity=CODE,
        )
