from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.sports.nba.player_history import NBAPlayerBoxObservation,fit_player_role,player_history_digest

UTC=timezone.utc

def obs(day,minutes=36,points=24,reb=8,ast=6,threes=3,observed_delay=3):
    tip=datetime(2025,1,day,1,tzinfo=UTC)
    return NBAPlayerBoxObservation(str(day),"p1","T",tip,tip+timedelta(hours=observed_delay),minutes,points,reb,ast,threes,110,"provider","box-v1")

def test_fit_uses_only_observations_known_before_asof():
    rows=[obs(1,30),obs(2,40),obs(3,48)]
    role=fit_player_role(rows,player_id="p1",team="HOME",as_of=datetime(2025,1,3,1,tzinfo=UTC))
    assert role.minutes_mean == 30
    assert role.version.startswith("NBA_PLAYER_ROLE_V1:")

def test_uncertain_status_fails_closed_without_minutes_override():
    with pytest.raises(ValueError,match="explicit minutes override"):
        fit_player_role([obs(1)],player_id="p1",team="AWAY",as_of=datetime(2025,1,2,1,tzinfo=UTC),status="QUESTIONABLE")
    role=fit_player_role([obs(1)],player_id="p1",team="AWAY",as_of=datetime(2025,1,2,1,tzinfo=UTC),status="QUESTIONABLE",uncertain_minutes_override=(20,8))
    assert (role.minutes_mean,role.minutes_sd)==(20,8)

def test_out_status_zeroes_minutes_but_preserves_fitted_rates():
    role=fit_player_role([obs(1)],player_id="p1",team="HOME",as_of=datetime(2025,1,2,1,tzinfo=UTC),status="OUT")
    assert role.minutes_mean == role.minutes_sd == 0
    assert role.rebounds_per_minute > 0

def test_post_tipoff_observation_and_digest_contract():
    bad=obs(1,observed_delay=0)
    with pytest.raises(ValueError,match="post-tipoff"):
        bad.validate()
    assert len(player_history_digest([obs(1)])) == 64
