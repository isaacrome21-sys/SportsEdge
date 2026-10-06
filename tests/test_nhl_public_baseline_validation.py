from datetime import datetime,timedelta,timezone
import hashlib

from sportsedge.sports.nhl.official_boxscore_source import NHLOfficialCompletedGame
from sportsedge.sports.nhl.public_baseline_validation import validate_public_baseline


def game(i,start,home,away):
    hg=2+(i%3); ag=1+((i+1)%3)
    return NHLOfficialCompletedGame(
        game_id=str(2024000000+i),season="20242025",game_type=2,
        game_date=start.date().isoformat(),start_time_utc=start.isoformat(),
        captured_at=(start+timedelta(hours=4)).isoformat(),game_state="FINAL",
        away_team_id=away,home_team_id=home,away_abbrev=away,home_abbrev=home,
        away_regulation_goals=ag,home_regulation_goals=hg,
        away_final_goals=ag,home_final_goals=hg,
        away_sog=27+(i%4),home_sog=30+(i%5),
        away_pp_goals=i%2,away_pp_opportunities=3,
        home_pp_goals=(i+1)%2,home_pp_opportunities=3,
        away_goalies=(),home_goalies=(),
        source_uri=f"https://api-web.nhle.com/v1/gamecenter/{2024000000+i}/boxscore",
        source_raw_sha256=hashlib.sha256(str(i).encode()).hexdigest(),
        source_version="fixture",
    )


def dataset():
    teams=["A","B","C","D"]
    out=[]
    start=datetime(2024,10,1,tzinfo=timezone.utc)
    for i in range(160):
        home=teams[i%4]; away=teams[(i+1+(i//4)%2)%4]
        if home==away: away=teams[(i+2)%4]
        out.append(game(i,start+timedelta(days=i*3),home,away))
    return out


def test_temporal_validation_fits_before_holdout_and_scores_future_rows():
    result=validate_public_baseline(
        dataset(),
        fit_before="2025-07-01T00:00:00+00:00",
        validate_start="2025-07-01T00:00:00+00:00",
        validate_before="2026-05-01T00:00:00+00:00",
        min_team_games=3,
    )
    assert result.training_rows>10
    assert result.validation_rows>0
    assert result.artifact.last_start_time_utc < "2025-07-01T00:00:00+00:00"
    assert result.team_goal_mae>=0
    assert result.team_goal_rmse>=0
    assert result.poisson_negative_log_likelihood>=0
    assert "NOT_FORWARD_BETTING_EVIDENCE" in result.evidence_role


def test_validation_window_cannot_overlap_backwards():
    try:
        validate_public_baseline(
            dataset(),
            fit_before="2026-01-01T00:00:00+00:00",
            validate_start="2025-01-01T00:00:00+00:00",
            validate_before="2026-05-01T00:00:00+00:00",
            min_team_games=3,
        )
        assert False
    except ValueError as exc:
        assert "invalid NHL validation windows" in str(exc)
