from datetime import datetime, timezone

from sportsedge.mlb.hitter_environment import (
    DirectionalFactors, HitterEnvironmentEffect, OutcomeFactors, SprayProfile,
    TimedEnvironmentSnapshot, aggregate_lineup_environment, hitter_environment_effect,
)

NOW = datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc)


def of(hr, xbh, single):
    return OutcomeFactors(hr=hr, xbh=xbh, single=single)


def snap(ts="2026-08-22T01:45:00Z"):
    return TimedEnvironmentSnapshot(
        stadium=DirectionalFactors(
            pull=of(1.20, 1.10, .98), center=of(1.00, 1.02, 1.00), opposite=of(.85, .96, 1.03),
        ),
        weather=DirectionalFactors(
            pull=of(1.10, 1.04, 1.00), center=of(1.04, 1.02, 1.00), opposite=of(.98, 1.00, 1.01),
        ),
        as_of_utc=ts,
        source="fixture",
    )


def test_pull_heavy_hitter_gets_different_hr_effect_than_opposite_field_hitter():
    pull = hitter_environment_effect(SprayProfile(.70, .20, .10), snap(), now_utc=NOW)
    oppo = hitter_environment_effect(SprayProfile(.10, .20, .70), snap(), now_utc=NOW)
    assert pull.combined.hr > oppo.combined.hr


def test_stadium_and_weather_are_preserved_separately():
    result = hitter_environment_effect(SprayProfile(.4, .4, .2), snap(), now_utc=NOW)
    assert result.combined.hr == result.stadium.hr * result.weather.hr
    assert result.combined.xbh == result.stadium.xbh * result.weather.xbh
    assert result.promotion_evidence is False


def test_outcomes_move_independently():
    result = hitter_environment_effect(SprayProfile(1, 0, 0), snap(), now_utc=NOW)
    assert result.combined.hr != result.combined.xbh
    assert result.combined.single != result.combined.hr


def test_stale_environment_fails_closed():
    try:
        hitter_environment_effect(SprayProfile(.4, .4, .2), snap("2026-08-21T20:00:00Z"), now_utc=NOW)
    except ValueError as exc:
        assert "STALE" in str(exc)
    else:
        raise AssertionError("stale environment must fail closed")


def test_lineup_aggregation_uses_pa_weights():
    a = hitter_environment_effect(SprayProfile(1, 0, 0), snap(), now_utc=NOW)
    b = hitter_environment_effect(SprayProfile(0, 0, 1), snap(), now_utc=NOW)
    agg = aggregate_lineup_environment((a, b), (5.0, 1.0))
    assert b.combined.hr < agg.hr < a.combined.hr
    assert agg.hr > (a.combined.hr + b.combined.hr) / 2
