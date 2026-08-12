from sportsedge.statcast_v5_data import (
    PlateAppearance, StatcastDataError, build_prior_only_game_features, parse_savant_csv,
)

class FakeTransformer:
    def predict_hit_probability(self, X): return [min(max((r[0]-70.0)/40.0,0.0),1.0) for r in X]
    def predict_contact_value(self, X): return [min(max((r[0]-70.0)/20.0,0.0),2.0) for r in X]

def pa(day,gp,ab,batter,pitcher,team_home="H",team_away="A",top=True,ev=90.0,lsa=4):
    return PlateAppearance(day,gp,batter,pitcher,"single",team_home,team_away,1,"Top" if top else "Bot",ab,ev,10.0,lsa)

def one_game(day,gp,ev=90.0):
    # Home starter 900 faces A; away starter 800 faces H. Three unique top-order batters each.
    return [
        pa(day,gp,1,101,900,top=True,ev=ev), pa(day,gp,2,102,900,top=True,ev=ev), pa(day,gp,3,103,900,top=True,ev=ev),
        pa(day,gp,4,201,800,top=False,ev=ev), pa(day,gp,5,202,800,top=False,ev=ev), pa(day,gp,6,203,800,top=False,ev=ev),
    ]

def test_expected_stat_columns_are_not_required_or_consumed():
    header="game_date,game_pk,batter,pitcher,events,home_team,away_team,inning,inning_topbot,at_bat_number,launch_speed,launch_angle,launch_speed_angle,estimated_woba_using_speedangle\n"
    row="2024-04-01,1,101,900,single,H,A,1,Top,1,100,20,6,0.999\n"
    parsed=parse_savant_csv(header+row)
    assert len(parsed)==1
    assert not hasattr(parsed[0],"estimated_woba_using_speedangle")

def test_missing_raw_barrel_classification_fails_closed():
    text="game_date,game_pk,batter,pitcher,events,home_team,away_team,inning,inning_topbot,at_bat_number,launch_speed,launch_angle\n2024-04-01,1,101,900,single,H,A,1,Top,1,100,20\n"
    try: parse_savant_csv(text)
    except StatcastDataError as exc: assert "STATCAST_COLUMNS_MISSING" in str(exc)
    else: raise AssertionError("expected fail-closed missing-column error")

def test_same_date_games_do_not_update_each_other():
    rows=one_game("2023-04-01",1,ev=80.0)+one_game("2023-04-02",2,ev=100.0)+one_game("2023-04-02",3,ev=110.0)
    out=build_prior_only_game_features(rows,FakeTransformer(),min_team_bbe=1,min_pitcher_bbe=1,min_batter_bbe=1)
    d2=[r for r in out if r.get("game_date")=="2023-04-02"]
    assert len(d2)==2 and all("blocked" not in r for r in d2)
    # Both rows must see only 4/1 state, despite different 4/2 target-game contact quality.
    assert d2[0]["away"]["off_avg_exit_velocity"]==80.0
    assert d2[1]["away"]["off_avg_exit_velocity"]==80.0
    assert d2[0]["first_inning"]["away_sp_xwoba_allowed"]==d2[1]["first_inning"]["away_sp_xwoba_allowed"]

def test_first_observed_date_blocks_until_prior_sample_exists():
    out=build_prior_only_game_features(one_game("2023-04-01",1),FakeTransformer(),min_team_bbe=1,min_pitcher_bbe=1,min_batter_bbe=1)
    assert len(out)==1 and out[0]["blocked"].startswith("STATCAST_SAMPLE_TOO_SMALL")
