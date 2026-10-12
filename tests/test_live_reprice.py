"""Tests for sportsedge.live_reprice: math, invariants, fail-closed paths."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts.free_models import model_probability

from sportsedge.live_reprice import (
    NOT_WIRED_LIVE_FIELDS,
    LiveRepriceError,
    football_remaining_fraction,
    mlb_outs_used,
    mlb_remaining_means,
    reprice_football,
    reprice_mlb,
)
from sportsedge.live_state import FootballGameState, MLBGameState

NOW = datetime(2026, 10, 11, 23, 40, tzinfo=timezone.utc)


def mlb_state(**over):
    base = dict(game_pk=7, observed_at=NOW, source_as_of=NOW, status="LIVE",
                inning=5, half="top", outs=1, balls=2, strikes=1,
                bases=(True, False, False), bases_provenance="test",
                batter_id=1, batter_name="Batter", pitcher_id=2,
                pitcher_name="Pitcher", home_score=1, away_score=3,
                home_team="Home", away_team="Away")
    base.update(over)
    return MLBGameState(**base)


def football_state(**over):
    base = dict(sport="NFL", event_id="e1", observed_at=NOW,
                source_as_of=NOW, status="LIVE", quarter=3,
                clock_seconds=450, clock_display="7:30", down=2, distance=7,
                yard_line_raw="35", yard_line_100=None, possession="HOME",
                timeouts_home=2, timeouts_away=3, home_score=17, away_score=14,
                home_team="Home", away_team="Away")
    base.update(over)
    return FootballGameState(**base)


# ---------------------------------------------------------------------------
# MLB outs accounting
# ---------------------------------------------------------------------------

def test_mlb_outs_used_top():
    away_used, home_used = mlb_outs_used(mlb_state(inning=5, half="top", outs=1))
    assert (away_used, home_used) == (13, 12)


def test_mlb_outs_used_bottom():
    away_used, home_used = mlb_outs_used(mlb_state(inning=5, half="bottom", outs=2))
    assert (away_used, home_used) == (15, 14)


def test_mlb_outs_used_incomplete_state_fails():
    with pytest.raises(LiveRepriceError):
        mlb_outs_used(mlb_state(inning=None))


def test_mlb_remaining_means_scale_by_outs():
    rem_h, rem_a, frac, note = mlb_remaining_means(
        mlb_state(inning=5, half="top", outs=1), 4.5, 4.3)
    assert rem_a == pytest.approx(4.3 * 14 / 27)
    assert rem_h == pytest.approx(4.5 * 15 / 27)
    assert 0 < frac < 1


def test_mlb_extras_grant_half_inning_each():
    rem_h, rem_a, frac, note = mlb_remaining_means(
        mlb_state(inning=10, half="top", outs=1), 4.5, 4.3)
    assert rem_a == pytest.approx(4.3 * 2 / 27)
    assert rem_h == pytest.approx(4.5 * 3 / 27)
    assert "EXTRAS" in note


# ---------------------------------------------------------------------------
# MLB repricing behavior
# ---------------------------------------------------------------------------

def test_mlb_reprice_trailing_team_below_half():
    r = reprice_mlb(mlb_state(), 4.5, 4.3, "ML", "HOME")
    assert r.model_p < 0.5
    assert r.push_p == 0.0


def test_mlb_reprice_leading_team_above_half():
    r = reprice_mlb(mlb_state(), 4.5, 4.3, "ML", "AWAY")
    assert r.model_p > 0.5


def test_mlb_reprice_monotone_in_score():
    low = reprice_mlb(mlb_state(home_score=1), 4.5, 4.3, "ML", "HOME").model_p
    high = reprice_mlb(mlb_state(home_score=4), 4.5, 4.3, "ML", "HOME").model_p
    assert high > low


def test_mlb_reprice_total_push_mass():
    r = reprice_mlb(mlb_state(), 4.5, 4.3, "TOTAL", "OVER", 8)
    assert r.push_p > 0  # integer total line carries push mass


def test_mlb_reprice_matches_pregame_at_first_pitch():
    s = mlb_state(inning=1, half="top", outs=0, home_score=0, away_score=0)
    for market, side, line in [("ML", "HOME", None), ("SPREAD", "HOME", -1.5),
                               ("TOTAL", "OVER", 8.5)]:
        live = reprice_mlb(s, 4.5, 4.3, market, side, line)
        pre_win, pre_push = model_probability("MLB", market, side, line, 4.5, 4.3)
        assert live.model_p == pytest.approx(pre_win, abs=1e-9)
        assert live.push_p == pytest.approx(pre_push, abs=1e-9)


def test_mlb_reprice_blocks_non_live():
    with pytest.raises(LiveRepriceError) as exc:
        reprice_mlb(mlb_state(status="FINAL"), 4.5, 4.3, "ML", "HOME")
    assert "GAME_NOT_LIVE" in str(exc.value)


def test_mlb_reprice_blocks_unsupported_market():
    with pytest.raises(LiveRepriceError):
        reprice_mlb(mlb_state(), 4.5, 4.3, "NRFI", "HOME")


def test_mlb_reprice_carries_not_wired_fields():
    r = reprice_mlb(mlb_state(), 4.5, 4.3, "ML", "HOME")
    fields = [f for f, _ in r.not_wired]
    assert "mlb_bases_outs_count" in fields
    assert "mlb_batter_pitcher" in fields


# ---------------------------------------------------------------------------
# Football repricing
# ---------------------------------------------------------------------------

def test_football_remaining_fraction():
    assert football_remaining_fraction(football_state()) == pytest.approx(0.375)
    assert football_remaining_fraction(
        football_state(quarter=1, clock_seconds=900)) == pytest.approx(1.0)


def test_football_overtime_blocked():
    with pytest.raises(LiveRepriceError) as exc:
        reprice_football(football_state(quarter=5, clock_seconds=600),
                         24.0, 21.0, "ML", "HOME")
    assert "LIVE_OT_DYNAMICS_UNMODELED" in str(exc.value)


def test_football_reprice_leading_team_favored():
    r = reprice_football(football_state(), 24.0, 21.0, "ML", "HOME")
    assert r.model_p > 0.5


def test_football_reprice_monotone_in_clock():
    early = reprice_football(football_state(quarter=2, clock_seconds=900,
                                            home_score=17, away_score=14),
                             24.0, 21.0, "ML", "HOME").model_p
    late = reprice_football(football_state(quarter=4, clock_seconds=60,
                                           home_score=17, away_score=14),
                            24.0, 21.0, "ML", "HOME").model_p
    assert late > early  # same lead is safer late


def test_football_f1_equals_pregame():
    s = football_state(quarter=1, clock_seconds=900, home_score=0,
                       away_score=0)
    for market, side, line in [("ML", "HOME", None), ("ML", "AWAY", None),
                               ("SPREAD", "HOME", -3.5), ("SPREAD", "AWAY", 3.5),
                               ("TOTAL", "OVER", 45.5), ("TOTAL", "UNDER", 45.5),
                               ("TOTAL", "OVER", 45.0)]:
        live = reprice_football(s, 24.0, 21.0, market, side, line)
        pre_win, pre_push = model_probability("NFL", market, side, line,
                                              24.0, 21.0)
        assert live.model_p == pytest.approx(pre_win, abs=1e-9), (market, side, line)
        assert live.push_p == pytest.approx(pre_push, abs=1e-9), (market, side, line)


def test_football_reprice_blocks_non_live():
    with pytest.raises(LiveRepriceError):
        reprice_football(football_state(status="FINAL"), 24.0, 21.0,
                         "ML", "HOME")


def test_football_reprice_missing_clock_fails():
    with pytest.raises(LiveRepriceError):
        reprice_football(football_state(clock_seconds=None), 24.0, 21.0,
                         "ML", "HOME")


def test_football_not_wired_fields_present():
    r = reprice_football(football_state(), 24.0, 21.0, "ML", "HOME")
    fields = [f for f, _ in r.not_wired]
    assert "football_down_distance_yardline_possession" in fields
    assert "football_timeouts" in fields


def test_not_wired_catalog_covers_spec_fields():
    fields = [f for f, _ in NOT_WIRED_LIVE_FIELDS]
    for required in ("mlb_bases_outs_count", "mlb_batter_pitcher",
                     "football_down_distance_yardline_possession",
                     "football_timeouts", "live_first_inning_markets"):
        assert required in fields
