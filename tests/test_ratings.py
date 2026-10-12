"""Unit tests for the SportsEdge team-rating foundation.

The critical invariant under test: the rating used for game N may only
reflect games played strictly BEFORE game N. No-lookahead is enforced
structurally by EloTracker (non-decreasing dates, rating_at uses date <
as_of) and asserted directly below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.ratings import (
    EloTracker, EloError, GameRecord, RatingError, RatingProvider,
    TeamStrength, build_means, build_provider, clear_configuration,
    configure, expected_score, get_team_strength, hfa_layer, mov_multiplier,
    params, rest_layer, season_label, travel_layer,
)
from sportsedge.ratings import history as history_mod


def utc(y, m, d, h=18):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def game(date, home, away, hs, aws, season=None):
    return GameRecord(kickoff=date, home=home, away=away,
                      home_score=hs, away_score=aws, season=season)


# ---------------------------------------------------------------- Elo math

def test_expected_score_symmetric():
    assert expected_score(1500, 1500, "NFL") == pytest.approx(0.5)
    p = expected_score(1600, 1500, "NFL")
    assert p == pytest.approx(1 - expected_score(1500, 1600, "NFL"))
    assert p > 0.5


def test_mov_multiplier_blowout_moves_more():
    small = mov_multiplier(3, 0, "NFL")
    big = mov_multiplier(30, 0, "NFL")
    assert big > small > 0


def test_mov_multiplier_expected_blowout_dampened():
    # Same 20-pt win, but one was fully expected: smaller multiplier.
    surprise = mov_multiplier(20, 0, "NFL")
    expected = mov_multiplier(20, 250, "NFL")
    assert surprise > expected > 0


def test_elo_update_beats_strong_opponent_gains_more():
    t1 = EloTracker("NFL")
    t2 = EloTracker("NFL")
    d = utc(2024, 9, 8)
    # Team A beats a 1500 team vs beating a 1700 team: bigger gain vs 1700.
    t1.record_game(date=d, home="A", away="B", home_score=24, away_score=20)
    t2.record_game(date=d, home="C", away="D", home_score=24, away_score=20)
    # Manually set D high first, then C beats D.
    t2b = EloTracker("NFL")
    t2b.record_game(date=d, home="D", away="E", home_score=40, away_score=0,
                    season="2024")
    t2b.record_game(date=d + timedelta(days=7), home="C", away="D",
                    home_score=24, away_score=20, season="2024")
    gain_vs_avg = t1.rating_at("A", d + timedelta(days=1))[0] - 1500
    gain_vs_strong = t2b.rating_at("C", d + timedelta(days=8))[0] - 1500
    assert gain_vs_strong > gain_vs_avg > 0


def test_tie_splits_points():
    t = EloTracker("NFL")
    d = utc(2024, 9, 8)
    t.record_game(date=d, home="A", away="B", home_score=20, away_score=20)
    ra, _ = t.rating_at("A", d + timedelta(days=1))
    rb, _ = t.rating_at("B", d + timedelta(days=1))
    assert ra == pytest.approx(1500.0)
    assert rb == pytest.approx(1500.0)


def test_season_regression():
    t = EloTracker("NFL")
    d = utc(2024, 9, 8)
    t.record_game(date=d, home="A", away="B", home_score=50, away_score=0,
                  season="2024")
    r_before, _ = t.rating_at("A", d + timedelta(days=1))
    assert r_before > 1500
    t.record_game(date=d + timedelta(days=300), home="A", away="C",
                  home_score=21, away_score=21, season="2025")
    r_after, _ = t.rating_at("A", d + timedelta(days=301))
    # Regression pulled the rating back toward 1500 before the new season.
    assert r_after < r_before


def test_out_of_order_record_raises():
    t = EloTracker("NFL")
    d = utc(2024, 9, 8)
    t.record_game(date=d, home="A", away="B", home_score=24, away_score=20)
    with pytest.raises(EloError):
        t.record_game(date=d - timedelta(days=1), home="A", away="C",
                      home_score=24, away_score=20)


def test_same_timestamp_allowed():
    # Same-day games (doubleheaders) must not raise.
    t = EloTracker("MLB")
    d = utc(2025, 7, 4, 13)
    t.record_game(date=d, home="A", away="B", home_score=5, away_score=3)
    t.record_game(date=d, home="C", away="D", home_score=2, away_score=1)
    assert t.games_recorded == 2


# ------------------------------------------------------- no-lookahead core

def test_rating_at_excludes_game_at_as_of():
    """rating_at(as_of) must not see a game played AT as_of (strict <)."""
    t = EloTracker("NFL")
    d1, d2 = utc(2024, 9, 8), utc(2024, 9, 15)
    t.record_game(date=d1, home="A", away="B", home_score=30, away_score=10)
    t.record_game(date=d2, home="A", away="C", home_score=10, away_score=30)
    before, n1 = t.rating_at("A", d2)
    after, n2 = t.rating_at("A", d2 + timedelta(seconds=1))
    assert n1 == 1 and n2 == 2
    assert before != after  # the d2 game only counts strictly after d2


def test_no_lookahead_invariant_record_later_does_not_change_earlier():
    """Recording a later game must not alter a rating queried earlier."""
    t = EloTracker("NFL")
    d1, d2, d3 = utc(2024, 9, 8), utc(2024, 9, 15), utc(2024, 9, 22)
    t.record_game(date=d1, home="A", away="B", home_score=30, away_score=10)
    t.record_game(date=d2, home="A", away="C", home_score=10, away_score=30)
    snap, n = t.rating_at("A", d3)  # sees d1 + d2 only
    assert n == 2
    t.record_game(date=d3, home="A", away="D", home_score=40, away_score=0)
    snap2, n2 = t.rating_at("A", d3)
    assert (snap, n) == (snap2, n2)  # unchanged: d3 game not visible at d3


def test_provider_strength_matches_tracker_at_as_of():
    p = RatingProvider("NBA")
    d1, d2 = utc(2024, 10, 22), utc(2024, 10, 24)
    p.record_games([game(d1, "Lakers", "Celtics", 110, 100, season="2024"),
                    game(d2, "Lakers", "Bulls", 90, 120, season="2024")])
    s = p.get_team_strength("Lakers", d2)
    assert s.rating_games == 1  # only d1 visible at d2
    assert s.strength_points == pytest.approx(
        (s.rating - 1500) / params.get("NBA", "elo_per_point"))


def test_unrated_team_raises_fail_closed():
    p = RatingProvider("NFL")
    with pytest.raises(RatingError):
        p.get_team_strength("No Such Team", utc(2024, 9, 8))


def test_unconfigured_module_interface_raises():
    clear_configuration()
    with pytest.raises(RatingError):
        get_team_strength("Chiefs", utc(2024, 9, 8), "NFL")


def test_module_interface_roundtrip():
    clear_configuration()
    p = RatingProvider("MLB")
    p.record_games([game(utc(2025, 4, 1), "Dodgers", "Cubs", 5, 3, season="2025")])
    configure("MLB", p)
    s = get_team_strength("Dodgers", utc(2025, 4, 2), "MLB")
    assert isinstance(s, TeamStrength)
    assert s.rated and s.rating_games == 1
    clear_configuration()


def test_team_name_normalization():
    p = RatingProvider("NFL")
    p.record_games([game(utc(2024, 9, 8), "Kansas City Chiefs",
                         "Baltimore Ravens", 27, 20, season="2024")])
    s = p.get_team_strength("kansas  city   CHIEFS", utc(2024, 9, 9))
    assert s.rated and s.rating_games == 1


def test_history_rejects_bad_records():
    with pytest.raises(Exception):
        GameRecord(kickoff=utc(2024, 9, 8), home="A", away="A",
                   home_score=1, away_score=0)
    with pytest.raises(Exception):
        GameRecord(kickoff=utc(2024, 9, 8), home="A", away="B",
                   home_score=-1, away_score=0)


def test_season_label_boundaries():
    assert season_label("NFL", utc(2024, 9, 1)) == "2024"
    assert season_label("NFL", utc(2025, 2, 9)) == "2024"   # SB in Feb
    assert season_label("NFL", utc(2025, 8, 15)) == "2024"  # preseason Aug
    assert season_label("MLB", utc(2025, 3, 27)) == "2024"  # March opener
    assert season_label("MLB", utc(2025, 4, 1)) == "2025"
    assert season_label("NBA", utc(2024, 10, 22)) == "2024"
    assert season_label("NBA", utc(2025, 6, 1)) == "2024"


# ----------------------------------------------------------------- layers

def test_hfa_layer_split_matches_production_convention():
    layer = hfa_layer("NFL")
    assert layer.home_pts == pytest.approx(0.75)
    assert layer.away_pts == pytest.approx(-0.75)
    assert layer.status == "DECLARED_LEGACY"


def test_hfa_neutral_site_zero():
    layer = hfa_layer("NFL", neutral_site=True)
    assert layer.home_pts == 0.0 and layer.away_pts == 0.0


def test_rest_and_travel_not_wired_but_declared():
    r = rest_layer("NBA", home_rest_days=1, away_rest_days=3)
    t = travel_layer("NFL", away_travel_miles=2500)
    assert r.status == "NOT_WIRED" and r.home_pts == 0.0
    assert t.status == "NOT_WIRED" and t.away_pts == 0.0
    assert r.detail["home_rest_days"] == 1  # inputs still audited


def test_build_means_components_explicit_and_audited():
    out = build_means("NFL", base_mean=22.0,
                      home_strength_pts=2.0, away_strength_pts=-1.0)
    # 22 + 2 + 0.75 (HFA half) and 22 - 1 - 0.75
    assert out["home_mean"] == pytest.approx(24.75)
    assert out["away_mean"] == pytest.approx(20.25)
    names = [a["layer"] for a in out["factor_audit"]]
    assert "league_prior" in names
    assert "team_strength_elo" in names
    assert "home_field_advantage" in names
    assert "rest_differential" in out["layers_not_wired"]
    assert "travel" in out["layers_not_wired"]


def test_build_means_rejects_unknown_sport():
    with pytest.raises(ValueError):
        build_means("NHL", base_mean=3.0, home_strength_pts=0, away_strength_pts=0)


def test_elo_strength_feeds_means_end_to_end():
    """Full path: games -> rating -> strength -> means."""
    p = build_provider("NFL", [
        game(utc(2024, 9, 8), "Chiefs", "Ravens", 27, 20, season="2024"),
        game(utc(2024, 9, 15), "Chiefs", "Bengals", 30, 17, season="2024"),
        game(utc(2024, 9, 8), "Bills", "Dolphins", 10, 31, season="2024"),
    ])
    as_of = utc(2024, 9, 22)
    hs = p.get_team_strength("Chiefs", as_of)
    aws = p.get_team_strength("Bills", as_of)
    assert hs.strength_points > 0 > aws.strength_points
    out = build_means("NFL", base_mean=22.0,
                      home_strength_pts=hs.strength_points,
                      away_strength_pts=aws.strength_points)
    assert out["home_mean"] > out["away_mean"]
    assert out["home_mean"] - out["away_mean"] > 1.5  # HFA + strength gap


def test_provider_persistence_roundtrip(tmp_path):
    p = build_provider("CFB", [
        game(utc(2024, 8, 31), "Georgia", "Clemson", 34, 3, season="2024"),
    ])
    path = p.save(tmp_path / "cfb.json")
    p2 = RatingProvider.load(path)
    s1 = p.get_team_strength("Georgia", utc(2024, 9, 1))
    s2 = p2.get_team_strength("Georgia", utc(2024, 9, 1))
    assert s1.rating == pytest.approx(s2.rating)
    assert s1.rating_games == s2.rating_games


def test_provider_load_rejects_bad_store(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(RatingError):
        RatingProvider.load(bad)


def test_params_audit_table_has_sources():
    rows = params.audit_table()
    assert rows
    for row in rows:
        assert row["source"] and row["status"]
        assert row["status"] in {"DECLARED_ADOPTED", "DECLARED_CONVENTION",
                                 "DECLARED_LEGACY", "DECLARED_UNVALIDATED",
                                 "NOT_WIRED"}
