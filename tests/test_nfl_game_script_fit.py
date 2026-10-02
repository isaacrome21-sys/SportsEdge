import copy

import pytest

from sportsedge.research.nfl_game_script_fit import (
    BUCKETS,
    DEVELOPMENT_SEASONS,
    NflGameScriptFitError,
    build_team_game_rows,
    expected_pbp_uri,
    fit_game_script_v1,
    load_prelock,
    script_multipliers,
    validate_artifact,
)


MARGINS = {
    "LE_NEG15": -21,
    "NEG14_NEG8": -10,
    "NEG7_NEG1": -3,
    "TIE": 0,
    "POS1_POS7": 3,
    "POS8_POS14": 10,
    "GE15": 21,
}

PASS_COUNTS = {
    "LE_NEG15": 45,
    "NEG14_NEG8": 41,
    "NEG7_NEG1": 37,
    "TIE": 34,
    "POS1_POS7": 32,
    "POS8_POS14": 29,
    "GE15": 27,
}

RUSH_COUNTS = {
    "LE_NEG15": 18,
    "NEG14_NEG8": 21,
    "NEG7_NEG1": 25,
    "TIE": 28,
    "POS1_POS7": 31,
    "POS8_POS14": 34,
    "GE15": 38,
}


def receipts():
    return [
        {
            "season": season,
            "source_uri": expected_pbp_uri(season),
            "raw_sha256": f"{season:064x}"[-64:],
            "retrieved_at": f"2026-10-01T12:{season % 60:02d}:00+00:00",
        }
        for season in DEVELOPMENT_SEASONS
    ]


def synthetic_team_games():
    rows = []
    bucket_names = [name for name, _lo, _hi in BUCKETS]
    # 18 teams x 9 seasons x 14 games = 2,268 team-games; exactly two games
    # per bucket per team-season. Every bucket comfortably clears n=100.
    for season in DEVELOPMENT_SEASONS:
        for team_i in range(18):
            team = f"T{team_i:02d}"
            for game_i in range(14):
                bucket = bucket_names[game_i % len(bucket_names)]
                rows.append(
                    {
                        "season": season,
                        "game_id": f"{season}_{team}_{game_i:02d}",
                        "team": team,
                        "final_margin": MARGINS[bucket],
                        "pass_plays": PASS_COUNTS[bucket],
                        "rush_plays": RUSH_COUNTS[bucket],
                    }
                )
    return rows


def test_prelock_is_frozen_before_scoring_and_keeps_integration_separate():
    prelock = load_prelock()
    assert prelock["status"] == "FROZEN_BEFORE_SCORING"
    assert prelock["fit_window"]["seasons"] == list(DEVELOPMENT_SEASONS)
    assert prelock["validation_window"]["season"] == 2025
    assert prelock["validation_window"]["one_look"] is True
    assert prelock["validation_window"]["not_fresh_promotion_evidence"] is True
    assert prelock["integration_boundary"]["this_prelock_changes_unified_engine"] is False
    assert prelock["authority"]["creates_model_p"] is False


def test_pbp_market_columns_are_ignored_by_whitelist():
    base = []
    for game_i in range(2):
        for play_i, kind in enumerate(("pass", "rush", "kneel", "scramble")):
            row = {
                "season": 2024,
                "season_type": "REG",
                "game_id": f"2024_0{game_i + 1}_AAA_BBB",
                "posteam": "AAA",
                "posteam_type": "home",
                "home_score": 24,
                "away_score": 17,
                "pass_attempt": 1 if kind == "pass" else 0,
                "rush_attempt": 1 if kind in {"rush", "scramble", "kneel"} else 0,
                "qb_scramble": 1 if kind == "scramble" else 0,
                "qb_kneel": 1 if kind == "kneel" else 0,
                # nflverse raw PBP carries these, but the model must not.
                "spread_line": -3.5,
                "total_line": 44.5,
                "vegas_wp": 0.63,
                "sportsbook_probability": 0.9,
            }
            base.append(row)

    mutated = copy.deepcopy(base)
    for row in mutated:
        row["spread_line"] = 99
        row["total_line"] = 12
        row["vegas_wp"] = 0.01
        row["sportsbook_probability"] = 0.01

    assert build_team_game_rows(base) == build_team_game_rows(mutated)
    rows = build_team_game_rows(base)
    assert all(row["pass_plays"] == 1 for row in rows)
    # kneel is excluded; scramble is classified as rush exactly once.
    assert all(row["rush_plays"] == 2 for row in rows)


def test_fit_is_deterministic_and_learns_script_direction_from_data():
    games = synthetic_team_games()
    a = fit_game_script_v1(games, source_receipts=receipts())
    b = fit_game_script_v1(list(reversed(games)), source_receipts=list(reversed(receipts())))
    assert a == b
    validate_artifact(a)

    big_loss = script_multipliers(a, final_margin=-24)
    close_loss = script_multipliers(a, final_margin=-3)
    close_win = script_multipliers(a, final_margin=3)
    big_win = script_multipliers(a, final_margin=24)

    assert big_loss["pass_multiplier"] > close_loss["pass_multiplier"]
    assert close_loss["pass_multiplier"] > close_win["pass_multiplier"]
    assert close_win["pass_multiplier"] > big_win["pass_multiplier"]

    assert big_loss["rush_multiplier"] < close_loss["rush_multiplier"]
    assert close_loss["rush_multiplier"] < close_win["rush_multiplier"]
    assert close_win["rush_multiplier"] < big_win["rush_multiplier"]

    assert a["status"] == "FITTED_RESEARCH_ONLY_NOT_VALIDATED"
    assert a["authority"]["validated_2025"] is False
    assert a["authority"]["changes_attempt9_owner"] is False


def test_fit_has_all_frozen_buckets_and_enough_rows():
    artifact = fit_game_script_v1(synthetic_team_games(), source_receipts=receipts())
    assert [row["id"] for row in artifact["buckets"]] == [
        name for name, _lo, _hi in BUCKETS
    ]
    assert all(row["n_team_games"] >= 100 for row in artifact["buckets"])
    assert all(0.4 <= row["pass_multiplier"] <= 1.8 for row in artifact["buckets"])
    assert all(0.4 <= row["rush_multiplier"] <= 1.8 for row in artifact["buckets"])


def test_artifact_tamper_fails_closed():
    artifact = fit_game_script_v1(synthetic_team_games(), source_receipts=receipts())
    bad = copy.deepcopy(artifact)
    bad["buckets"][0]["pass_multiplier"] += 0.01
    with pytest.raises(NflGameScriptFitError, match="ARTIFACT_SHA_MISMATCH"):
        validate_artifact(bad)


def test_2025_cannot_enter_fit_window():
    games = synthetic_team_games()
    games.append(
        {
            "season": 2025,
            "game_id": "2025_01_AAA_BBB",
            "team": "AAA",
            "final_margin": 3,
            "pass_plays": 34,
            "rush_plays": 28,
        }
    )
    with pytest.raises(NflGameScriptFitError, match="OUTSIDE_DEVELOPMENT_WINDOW:2025"):
        fit_game_script_v1(games, source_receipts=receipts())


def test_every_development_source_receipt_is_required_and_bound():
    games = synthetic_team_games()
    with pytest.raises(NflGameScriptFitError, match="SOURCE_RECEIPTS_MISSING:2024"):
        fit_game_script_v1(games, source_receipts=receipts()[:-1])

    bad = receipts()
    bad[-1] = dict(bad[-1])
    bad[-1]["source_uri"] = "https://example.com/not-nflverse.csv"
    with pytest.raises(NflGameScriptFitError, match="SOURCE_URI_INVALID:2024"):
        fit_game_script_v1(games, source_receipts=bad)
