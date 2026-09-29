from sportsedge.sports.nhl.goalie_saves import (
    NHLGoalieSaveParameters,
    fit_empirical_goalie_save_parameters,
    goalie_saves_over,
    simulate_goalie_save_paths,
)
from sportsedge.sports.nhl.official_boxscore_source import NHLOfficialCompletedGame, NHLGoalieBoxscore


def _game(game_id: str, start: str, *, home_sog: int, away_sog: int, home_goalie: NHLGoalieBoxscore) -> NHLOfficialCompletedGame:
    return NHLOfficialCompletedGame(
        game_id=game_id,
        season="20252026",
        game_type=2,
        game_date=start[:10],
        start_time_utc=start,
        captured_at="2026-09-29T20:00:00+00:00",
        game_state="OFF",
        away_team_id="2",
        home_team_id="1",
        away_abbrev="AWY",
        home_abbrev="HME",
        away_regulation_goals=2,
        home_regulation_goals=3,
        away_final_goals=2,
        home_final_goals=3,
        away_sog=away_sog,
        home_sog=home_sog,
        away_pp_goals=0,
        away_pp_opportunities=2,
        home_pp_goals=1,
        home_pp_opportunities=3,
        away_goalies=(NHLGoalieBoxscore("away-g", 3, 27, home_sog, 3600),),
        home_goalies=(home_goalie,),
        source_uri=f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore",
        source_raw_sha256="a" * 64,
        source_version="nhl-web-api-v1",
    )


def test_goalie_saves_are_deterministic_and_subset_of_opponent_sog():
    params = NHLGoalieSaveParameters(
        version="v1",
        goalie_id="g1",
        save_probability=0.9,
        starter_shot_share=0.95,
        source="fixture",
        history_sha256="b" * 64,
        starts=20,
        starter_status="CONFIRMED",
    )
    opponent = (20, 25, 30, 35, 40)
    first = simulate_goalie_save_paths(opponent, params, game_seed=11)
    second = simulate_goalie_save_paths(opponent, params, game_seed=11)
    assert first == second
    assert all(0 <= saves <= faced <= sog for saves, faced, sog in zip(first.saves, first.shots_faced, opponent))
    assert first.starter_status == "CONFIRMED"


def test_goalie_saves_over_preserves_probability_mass():
    params = NHLGoalieSaveParameters("v1", "g1", 0.91, 1.0, "fixture", "c" * 64, 12)
    paths = simulate_goalie_save_paths((30,) * 1000, params, game_seed=7)
    win, push, loss = goalie_saves_over(paths, 27.0)
    assert abs(win + push + loss - 1.0) < 1e-12
    assert push >= 0


def test_fit_goalie_parameters_uses_only_prior_starts():
    prior = _game(
        "2025020001",
        "2025-10-01T23:00:00+00:00",
        home_sog=30,
        away_sog=30,
        home_goalie=NHLGoalieBoxscore("g1", 3, 27, 30, 3600),
    )
    future = _game(
        "2025020002",
        "2026-10-01T23:00:00+00:00",
        home_sog=30,
        away_sog=30,
        home_goalie=NHLGoalieBoxscore("g1", 10, 0, 10, 1200),
    )
    params = fit_empirical_goalie_save_parameters(
        (future, prior),
        goalie_id="g1",
        cutoff="2026-09-29T12:00:00+00:00",
        version="fit-v1",
        min_starts=1,
    )
    assert params.starts == 1
    assert params.save_probability == 0.9
    assert params.starter_shot_share == 1.0
