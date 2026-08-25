from sportsedge.ufc_history import build_history_from_text


EVENTS = """EVENT,URL,DATE,LOCATION
E1,,January 01, 2025,Las Vegas
E2,,February 01, 2025,Las Vegas
"""

RESULTS = """EVENT,BOUT,OUTCOME,WEIGHTCLASS,METHOD,ROUND,TIME,TIME FORMAT,REFEREE,DETAILS,URL
E1,Alice Alpha vs. Bob Beta,W/L,Lightweight Bout,Decision - Unanimous,3,5:00,3 Rnd (5-5-5),,,
E2,Alice Alpha vs. Carol Gamma,L/W,Lightweight Bout,Decision - Unanimous,3,5:00,3 Rnd (5-5-5),,,
"""

FIGHTERS = """FIGHTER,HEIGHT,WEIGHT,REACH,STANCE,DOB,URL
Alice Alpha,5' 8\",155 lbs.,70\",Orthodox,Jan 01 1995,
Bob Beta,5' 9\",155 lbs.,71\",Southpaw,Jan 01 1994,
Carol Gamma,5' 7\",155 lbs.,69\",Orthodox,Jan 01 1996,
"""


def _stats(alice_first="10 of 20"):
    return f"""EVENT,BOUT,ROUND,FIGHTER,KD,SIG.STR.,SIG.STR. %,TOTAL STR.,TD,TD %,SUB.ATT,REV.,CTRL,HEAD,BODY,LEG,DISTANCE,CLINCH,GROUND
E1,Alice Alpha vs. Bob Beta,Round 1,Alice Alpha,1,{alice_first},50%,{alice_first},1 of 2,50%,0,0,1:00,,,,,,,
E1,Alice Alpha vs. Bob Beta,Round 1,Bob Beta,0,5 of 15,33%,5 of 15,0 of 1,0%,0,0,0:10,,,,,,,
E2,Alice Alpha vs. Carol Gamma,Round 1,Alice Alpha,0,8 of 18,44%,8 of 18,0 of 1,0%,0,0,0:20,,,,,,,
E2,Alice Alpha vs. Carol Gamma,Round 1,Carol Gamma,0,12 of 24,50%,12 of 24,1 of 2,50%,1,0,1:30,,,,,,,
"""


def _bundle(alice_first="10 of 20"):
    return build_history_from_text(
        events_text=EVENTS,
        results_text=RESULTS,
        stats_text=_stats(alice_first),
        fighters_text=FIGHTERS,
        min_date="2025-01-01",
    )


def test_current_fight_stats_do_not_leak_into_current_prediction_row():
    normal = _bundle("10 of 20")
    extreme = _bundle("100 of 100")

    assert len(normal.training_rows) == 2
    assert normal.training_rows[0].features == extreme.training_rows[0].features
    assert normal.training_rows[0].features["elo_diff"] == 0.0
    assert normal.training_rows[0].features["experience_diff"] == 0.0

    # Fight 1 is allowed to affect only later rows.
    assert normal.training_rows[1].features["slpm_diff"] != extreme.training_rows[1].features["slpm_diff"]
    assert normal.training_rows[1].features["elo_diff"] > 0.0
    assert normal.training_rows[1].features["experience_diff"] == 1.0


def test_metadata_and_live_snapshot_use_pre_fight_experience_then_current_state():
    bundle = _bundle()
    first, second = bundle.metadata

    assert first["fighter_a_experience"] == 0
    assert first["fighter_b_experience"] == 0
    assert second["fighter_a_experience"] == 1
    assert second["fighter_b_experience"] == 0
    assert first["scheduled_rounds"] == 3
    assert bundle.last_fight_date == "2025-02-01"

    live = bundle.snapshot_dict("Alice Alpha", "2025-03-01", "Lightweight")
    assert live["wins"] == 1
    assert live["losses"] == 1
    assert live["sig_strikes_landed_pm"] > 0
    assert live["sig_strikes_absorbed_pm"] > 0
    assert live["days_since_last_fight"] == 28.0


def test_unknown_fighter_is_neutral_but_explicitly_high_missingness():
    bundle = _bundle()
    snap = bundle.snapshot_dict("Never Fought", "2025-03-01", "Welterweight")
    assert snap["elo"] == 1500.0
    assert snap["recent_win_rate"] == 0.5
    assert snap["strength_of_schedule"] == 0.5
    assert snap["missingness"] == 1.0
