"""Unit tests for sportsedge/qb_value.py (538-adapted QB VALUE engine).

No network: these pin the published 538 coefficients, the study-fitted
calibration constants, and the Tier-1/2 selection logic. The full empirical
study lives in scripts/study_qb_adjustment.py (reproducible, point-in-time
clean).
"""
import math

from sportsedge import qb_value as qv


def test_game_value_matches_538_coefficients():
    # Hand-computed: 30 att, 20 cmp, 250 yds, 2 TD, 1 INT, 2 sacks,
    # 5 rush att, 30 rush yds, 0 rush TD.
    # -2.2*30 + 3.7*20 + 250/5 + 11.3*2 - 14.1*1 - 8*2
    #   - 1.1*5 + 0.6*30 + 15.9*0 = 63.0
    stats = {"attempts": 30, "completions": 20, "passing_yards": 250,
             "passing_tds": 2, "interceptions": 1, "sacks": 2,
             "carries": 5, "rushing_yards": 30, "rushing_tds": 0}
    assert qv.game_value(stats) == 63.0


def test_game_value_ignores_bad_inputs():
    assert qv.game_value({}) == 0.0
    assert qv.game_value({"attempts": "xx", "passing_yards": None}) == 0.0
    v = qv.game_value({"attempts": 10, "completions": float("nan")})
    assert v == -22.0  # nan coerced to 0.0


def test_calibration_constants_pinned_to_study():
    # Fit 2015-2020, validated out-of-sample 2021-2024. If the study is
    # re-run and these change, update deliberately (and the tests that
    # depend on them), never silently.
    assert qv.QB_PER_VALUE_SLOPE == 0.1176
    assert qv.QB_INTERCEPT == -0.014
    assert qv.TIER2_TOTAL_EFFECT == -0.582
    assert qv.MIN_RATED_GAMES == 10


def test_per_qb_total_effect_direction():
    # A -40 VALUE gap (backup much worse, e.g. Lamar->Huntley scale) must
    # be a negative total effect of plausible magnitude; a +10 gap positive.
    neg = qv.QB_INTERCEPT + qv.QB_PER_VALUE_SLOPE * -40.0
    pos = qv.QB_INTERCEPT + qv.QB_PER_VALUE_SLOPE * 10.0
    assert neg < 0 < pos
    assert abs(neg) < 8.0
    # Slope cross-check vs 538's own implied conversion: VALUE*3.3 = Elo,
    # ~25 Elo per spread point -> 3.3/25 = 0.132 spread pts per VALUE pt.
    # Our fitted 0.1176 own-team pts per VALUE pt is in the same neighborhood
    # (most of a QB's value is offensive), an independent sanity check.
    assert abs(qv.QB_PER_VALUE_SLOPE - 3.3 / 25) < 0.03


def test_compute_ratings_block_update_rule():
    # 538's documented update: every 10 games,
    # rating = 0.9*old + 0.1*mean(block). With constant game VALUE v and no
    # defense history (single team), rating after 10 games = 0.1*v.
    games = []
    for wk in range(1, 12):
        games.append({"season": 2020, "week": wk, "pid": "Q1", "pname": "Q B",
                      "team": "AAA", "opp": "BBB", "att": 30, "raw": 10.0})
    state = qv.compute_ratings(games)
    assert state["Q1"]["games"] == 11
    assert state["Q1"]["rating"] == 0.9 * 0.0 + 0.1 * 10.0


def _ratings_with(qb1_games=40, qb2_games=30):
    return {
        "00-1": {"rating": 45.0, "games": qb1_games, "pname": "L.Jackson"},
        "00-2": {"rating": 5.0, "games": qb2_games, "pname": "T.Huntley"},
    }


def _depth(monkeypatch, q1=("00-1", "Lamar Jackson"),
           q2=("00-2", "Tyler Huntley")):
    monkeypatch.setattr(qv, "depth_qbs_from_depth_chart",
                        lambda cache, abbr: (q1[0], q1[1], q2[0], q2[1]))


def test_qb_absence_extra_tier1_uses_gap(monkeypatch):
    _depth(monkeypatch)
    out = qv.qb_absence_extra(
        _ratings_with(), starter_name="Lamar Jackson",
        team_abbr="BAL", cache="/tmp/x")
    assert out["variant"] == "TIER1_PER_QB_VALUE"
    expected = qv.QB_INTERCEPT + qv.QB_PER_VALUE_SLOPE * (5.0 - 45.0)
    assert out["extra_total"] == expected
    assert out["audit"]["gap"] == -40.0
    assert out["audit"]["depth_qb2"] == "Tyler Huntley"


def test_qb_absence_extra_tier2_on_thin_history(monkeypatch):
    _depth(monkeypatch)
    out = qv.qb_absence_extra(
        _ratings_with(qb2_games=3), starter_name="Lamar Jackson",
        team_abbr="BAL", cache="/tmp/x")
    assert out["variant"] == "TIER2_CALIBRATED_CONSTANT"
    assert out["extra_total"] == qv.TIER2_TOTAL_EFFECT


def test_qb_absence_extra_tier2_on_identity_break(monkeypatch):
    # Injury feed names a different starter than the depth-chart QB1:
    # fail closed to Tier-2, never a mismatched rating.
    _depth(monkeypatch, q1=("00-9", "Joe Flacco"))
    out = qv.qb_absence_extra(
        _ratings_with(), starter_name="Lamar Jackson",
        team_abbr="BAL", cache="/tmp/x")
    assert out["variant"] == "TIER2_CALIBRATED_CONSTANT"
    assert out["source"] == "TIER2_IDENTITY_BREAK"


def test_names_match_abbreviated():
    assert qv._names_match("Lamar Jackson", "Lamar Jackson")
    assert qv._names_match("Lamar Jackson", "L.Jackson")
    assert not qv._names_match("Lamar Jackson", "Tyler Huntley")
    assert not qv._names_match("Lamar Jackson", "Joe Flacco")


def test_weekly_schema_b_parses(tmp_path, monkeypatch):
    # stats_player schema: passing_interceptions / sacks_suffered / team.
    p = tmp_path / "stats_player_week_2026.csv"
    p.write_text(
        "player_id,player_name,position,season,week,season_type,team,"
        "opponent_team,attempts,completions,passing_yards,passing_tds,"
        "passing_interceptions,sacks_suffered,carries,rushing_yards,"
        "rushing_tds\n"
        "00-1,Test QB,QB,2026,2,REG,BAL,KC,25,15,200,2,0,1,3,10,0\n"
        "00-2,Other QB,QB,2026,2,POST,BAL,KC,25,15,200,2,0,1,3,10,0\n")
    monkeypatch.setattr(qv, "_ensure", lambda path, url: path)
    games = list(qv._iter_weekly_qb_games([2026], str(tmp_path)))
    assert len(games) == 1  # POST row excluded
    g = games[0]
    assert g["pid"] == "00-1" and g["team"] == "BAL" and g["week"] == 2
    assert g["raw"] == qv.game_value({
        "attempts": 25, "completions": 15, "passing_yards": 200,
        "passing_tds": 2, "interceptions": 0, "sacks": 1,
        "carries": 3, "rushing_yards": 10, "rushing_tds": 0})
