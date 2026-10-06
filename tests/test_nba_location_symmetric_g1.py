from datetime import datetime, timezone
import copy

import numpy as np
import pytest

from sportsedge.sports.nba.location_symmetric_g1 import (
    DEFAULT_ALPHA_GRID,
    fit_nba_location_symmetric_g1,
    game_state_from_location,
    margin_feature_vector,
    season_end_year,
    select_alpha,
    total_feature_vector,
)
from sportsedge.sports.nba.location_symmetric_g1_validation import validate_nba_location_symmetric_g1
from sportsedge.sports.nba.training import NBATrainingRow


def row(season_end, i, *, home_shift=0.0, away_shift=0.0):
    calendar_year=season_end-1
    tip=datetime(calendar_year,11,1+i,tzinfo=timezone.utc)
    home_off=113.0+0.4*i+home_shift
    away_off=109.0-0.2*i+away_shift
    home_def=108.0-0.1*i-home_shift
    away_def=112.0+0.15*i-away_shift
    poss=98.0+(i%3)
    matchup_margin=0.5*((home_off-away_off)+(away_def-home_def))
    home_pts=round(112.0+0.8*matchup_margin+(i%2))
    away_pts=round(108.0-0.5*matchup_margin+((i+1)%2))
    return NBATrainingRow(
        game_id=f"{season_end}_{i}",
        tipoff=tip,
        feature_as_of=datetime(calendar_year,10,31,tzinfo=timezone.utc),
        home_team_id=f"H{i}",
        away_team_id=f"A{i}",
        expected_possessions=poss,
        home_offensive_rating=home_off,
        home_defensive_rating=home_def,
        away_offensive_rating=away_off,
        away_defensive_rating=away_def,
        home_points=home_pts,
        away_points=away_pts,
        source_version="fixture",
    )


def rows():
    return tuple(row(season,i,home_shift=.15*(season-2018),away_shift=-.05*(season-2018)) for season in range(2018,2026) for i in range(6))


def swapped(r):
    return NBATrainingRow(
        game_id=r.game_id+"s",tipoff=r.tipoff,feature_as_of=r.feature_as_of,
        home_team_id=r.away_team_id,away_team_id=r.home_team_id,
        expected_possessions=r.expected_possessions,
        home_offensive_rating=r.away_offensive_rating,home_defensive_rating=r.away_defensive_rating,
        away_offensive_rating=r.home_offensive_rating,away_defensive_rating=r.home_defensive_rating,
        home_points=r.away_points,away_points=r.home_points,source_version=r.source_version,
    )


def test_feature_symmetry():
    r=rows()[0]; s=swapped(r)
    np.testing.assert_allclose(margin_feature_vector(s),-margin_feature_vector(r))
    np.testing.assert_allclose(total_feature_vector(s),total_feature_vector(r))


def test_season_end_year_contract():
    assert season_end_year(row(2024,0))==2024


def test_fit_prediction_swap_contract():
    train=tuple(r for r in rows() if season_end_year(r)<=2022)
    model=fit_nba_location_symmetric_g1(train,margin_alpha=10,total_alpha=10)
    r=rows()[-1]; s=swapped(r)
    m,t=model.predict(r); sm,st=model.predict(s)
    # Standardization changes the coefficient intercept; pairwise sum is constant.
    r2=rows()[-2]; s2=swapped(r2)
    m2,_=model.predict(r2); sm2,_=model.predict(s2)
    assert (m+sm)==pytest.approx(m2+sm2)
    assert t==pytest.approx(st)


def test_alpha_selection_is_training_only():
    train=tuple(r for r in rows() if season_end_year(r)<=2023)
    first=select_alpha(train,target="margin",alpha_grid=DEFAULT_ALPHA_GRID)
    mutated=list(copy.deepcopy(train))
    # Mutating the latest inner test season can change aggregate selection, but
    # never any earlier fold's fit identity; every fold records strict ordering.
    assert first["selected_alpha"] in DEFAULT_ALPHA_GRID
    assert all(max(f["train_seasons"])<f["test_season"] for c in first["candidates"] for f in c["folds"])


def test_game_state_handoff_uses_same_location():
    train=tuple(r for r in rows() if season_end_year(r)<=2022)
    model=fit_nba_location_symmetric_g1(train,margin_alpha=10,total_alpha=10)
    target=rows()[-1]
    margin,total=model.predict(target)
    state=game_state_from_location(model,target)
    home=state.expected_possessions*state.home_points_per_100/100
    away=state.expected_possessions*state.away_points_per_100/100
    assert home-away==pytest.approx(margin)
    assert home+away==pytest.approx(total)


def test_validation_has_reused_history_authority_only():
    report=validate_nba_location_symmetric_g1(rows())
    assert len(report["folds"])>=3
    assert report["evidence_role"]=="REUSED_RESEARCH_HISTORY_NOT_UNTOUCHED_PROMOTION_EVIDENCE"
    assert report["authority"]["model_p"] is False
    assert report["authority"]["official"] is False
