from sportsedge.sports.nhl.official_boxscore_source import NHLOfficialCompletedGame
from sportsedge.sports.nhl.team_shot_history import fit_matchup_team_shot_parameters


def game(game_id, start, home_id, away_id, home_sog, away_sog, captured="2026-09-28T12:00:00+00:00"):
    return NHLOfficialCompletedGame(
        game_id=game_id,
        season="20252026",
        game_type=2,
        game_date=start[:10],
        start_time_utc=start,
        captured_at=captured,
        game_state="OFF",
        away_team_id=away_id,
        home_team_id=home_id,
        away_abbrev=f"A{away_id}",
        home_abbrev=f"H{home_id}",
        away_regulation_goals=2,
        home_regulation_goals=3,
        away_final_goals=2,
        home_final_goals=3,
        away_sog=away_sog,
        home_sog=home_sog,
        away_pp_goals=None,
        away_pp_opportunities=None,
        home_pp_goals=None,
        home_pp_opportunities=None,
        away_goalies=(),
        home_goalies=(),
        source_uri=f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore",
        source_raw_sha256="a" * 64,
        source_version="nhl-web-api-v1",
    )


def test_matchup_team_shot_fit_uses_only_receipts_before_cutoff():
    rows = (
        game("1", "2025-10-01T23:00:00+00:00", "1", "3", 40, 20),
        game("2", "2025-10-03T23:00:00+00:00", "3", "1", 30, 36),
        game("3", "2025-10-05T23:00:00+00:00", "2", "4", 28, 35),
        game("4", "2025-10-07T23:00:00+00:00", "4", "2", 33, 30),
        game("5", "2026-10-01T23:00:00+00:00", "1", "2", 100, 1, captured="2026-10-02T12:00:00+00:00"),
    )
    fit = fit_matchup_team_shot_parameters(
        rows,
        home_team_id="1",
        away_team_id="2",
        cutoff="2026-09-29T12:00:00+00:00",
        version="sog-v1",
        min_games=2,
        shrinkage_games=0.0,
    )
    assert fit.home_games == 2
    assert fit.away_games == 2
    assert fit.parameters.home_expected_sog == 36.0
    assert fit.parameters.away_expected_sog == 27.0
    assert len(fit.history_sha256) == 64


def test_matchup_team_shot_fit_rejects_backfill_retrieved_after_target_cutoff():
    rows = (
        game("1", "2025-10-01T23:00:00+00:00", "1", "2", 30, 29, captured="2026-10-01T12:00:00+00:00"),
    )
    try:
        fit_matchup_team_shot_parameters(
            rows,
            home_team_id="1",
            away_team_id="2",
            cutoff="2026-09-29T12:00:00+00:00",
            version="sog-v1",
            min_games=1,
        )
    except ValueError as exc:
        assert "no eligible" in str(exc)
    else:
        raise AssertionError("post-cutoff backfill must not become PIT input")
