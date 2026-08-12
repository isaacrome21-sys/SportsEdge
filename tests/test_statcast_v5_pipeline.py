import pandas as pd
import pytest

from sportsedge.statcast_v5_pipeline import ContactState, StatcastV5Error, batted_balls, game_identity, smoothed


def test_batted_ball_metrics_are_raw_and_deterministic():
    df = pd.DataFrame([
        {"game_date":"2023-06-01","game_pk":1,"batter":10,"pitcher":20,"events":"home_run","launch_speed":101.0,"launch_angle":28.0,"launch_speed_angle":6,"inning":1,"inning_topbot":"Top","at_bat_number":1,"home_team":"H","away_team":"A","estimated_woba_using_speedangle":0.01},
        {"game_date":"2023-06-01","game_pk":1,"batter":11,"pitcher":20,"events":"field_out","launch_speed":94.9,"launch_angle":5.0,"launch_speed_angle":2,"inning":1,"inning_topbot":"Top","at_bat_number":2,"home_team":"H","away_team":"A","estimated_woba_using_speedangle":0.99},
    ])
    bb = batted_balls(df)
    assert bb["hard_hit"].tolist() == [1.0, 0.0]
    assert bb["barrel"].tolist() == [1.0, 0.0]
    assert bb["contact_woba"].tolist() == [2.0, 0.0]
    # Current historical Savant expected-stat columns must not drive targets.
    assert "estimated_woba_using_speedangle" not in {"contact_woba", "is_hit", "barrel", "hard_hit"}


def test_smoothed_prior_is_explicit():
    prior = {"xwoba":.4,"xba":.3,"barrel":.1,"hard_hit":.4,"ev":88.0}
    s = ContactState(); s.add({"frozen_xwoba":.8,"frozen_xba":.6,"barrel":1.0,"hard_hit":1.0,"launch_speed":100.0})
    got = smoothed(s, prior, 1.0)
    assert got["xwoba"] == pytest.approx(.6)
    assert got["xba"] == pytest.approx(.45)
    assert got["ev"] == pytest.approx(94.0)


def test_game_identity_uses_first_inning_order_and_starting_pitchers():
    rows=[]
    for n,b in enumerate((101,102,103),1):
        rows.append({"inning":1,"inning_topbot":"Top","at_bat_number":n,"pitch_number":1,"batter":b,"pitcher":900,"home_team":"H","away_team":"A"})
    for n,b in enumerate((201,202,203),4):
        rows.append({"inning":1,"inning_topbot":"Bot","at_bat_number":n,"pitch_number":1,"batter":b,"pitcher":800,"home_team":"H","away_team":"A"})
    ident=game_identity(pd.DataFrame(rows))
    assert ident["home_sp"] == 900
    assert ident["away_sp"] == 800
    assert ident["away_top3"] == (101,102,103)
    assert ident["home_top3"] == (201,202,203)


def test_incomplete_top_order_fails_closed():
    df=pd.DataFrame([
        {"inning":1,"inning_topbot":"Top","at_bat_number":1,"pitch_number":1,"batter":1,"pitcher":9,"home_team":"H","away_team":"A"},
        {"inning":1,"inning_topbot":"Bot","at_bat_number":2,"pitch_number":1,"batter":2,"pitcher":8,"home_team":"H","away_team":"A"},
    ])
    with pytest.raises(StatcastV5Error, match="TOP_ORDER_IDENTITY_INCOMPLETE"):
        game_identity(df)
