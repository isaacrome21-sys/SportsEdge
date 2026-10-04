from sportsedge.sports.nfl.v2k_drive_core import DriveRow
from sportsedge.sports.nfl.v2k_drive_core_v2 import fit_attempt2

def row(g,i,off,defn,ob,db,oa,da,out="PUNT_OTHER"):
    return DriveRow(g,2020,1,"2020-01-01",i,off,defn,75.0,out,ob,db,oa,da,4,60,source_manifest_sha256="x",source_code_sha="y")

def test_attempt2_home_identity_is_schedule_bound():
    rows=(row("g",0,"A","B",0,0,7,0,"TD"),row("g",1,"B","A",0,7,3,7,"FG"))
    fit=fit_attempt2(rows,{"g":{"home_team":"A","away_team":"B"}})
    assert fit.home_field.league_points==4.0
    assert fit.margin_clustering.signed_key_mass[3]==0.0

def test_attempt2_refuses_missing_home_identity():
    rows=(row("g",0,"A","B",0,0,0,0),)
    try: fit_attempt2(rows,{})
    except ValueError as e: assert str(e)=="V2K_ATTEMPT2_HOME_IDENTITY_MISSING"
    else: raise AssertionError("missing schedule identity accepted")
