import gzip
import importlib.util
import json
from pathlib import Path

from sportsedge.sports.cfb import public_mirror as pm

ROOT = Path(__file__).resolve().parents[1]

SCHED = (
    '"game_id","season","week","season_type","neutral_site","home_id","home_team","home_division","home_points",'
    '"away_id","away_team","away_division","away_points"\n'
    '1,2018,2,"regular",FALSE,10,"UT San Antonio","fbs",30,20,"Connecticut","fbs",20\n'
    '2,2018,3,"regular",TRUE,20,"Connecticut","fbs",14,30,"Army","fbs",17\n'
    '3,2018,4,"regular",FALSE,30,"Army","fbs",NA,10,"UT San Antonio","fbs",NA\n'
    '4,2018,16,"postseason",FALSE,30,"Army","fbs",7,20,"Connecticut","fbs",3\n'
)

LINES = (
    "game_id,market_type,abbr,lines,opening_lines,book\n"
    "1,spread,UTSA,-7.0,-6.0,A\n1,spread,CONN,7.0,6.0,A\n"
    "1,spread,UTSA,-8.0,-6.5,B\n1,spread,CONN,8.0,6.5,B\n"
    "2,spread,CONN,3.0,,A\n2,spread,ARMY,-3.0,,A\n"
    "1,total,UTSA,50,,A\n"
)


def test_canon_maps_renamed_schools():
    assert pm.canon("UT San Antonio") == pm.canon("UTSA")
    assert pm.canon("Connecticut") == pm.canon("UConn")
    assert pm.canon("San José State") == pm.canon("San Jose State")
    assert pm.canon("Hawai'i") == pm.canon("Hawaii")


def test_parse_talent_kinds_and_zero_is_missing():
    a = pm.parse_talent("year,school,talent\n2018,Connecticut,400\n2018,Army,0\n", "csv_year_school")
    b = pm.parse_talent(json.dumps([{"year": 2024, "team": "UConn", "talent": 537.9}]), "json_list")
    c = pm.parse_talent("team,talent,season,rank\nUTSA,662.1,2025,0\n", "csv_team_season")
    assert a == {2018: {"uconn": 400.0}}
    assert b == {2024: {"uconn": 537.9}}
    assert c == {2025: {"utsa": 662.1}}


def test_schedule_keeps_completed_regular_only():
    s = pm.parse_schedule(SCHED)
    assert set(s) == {"1", "2"}
    assert s["2"]["neutral"] is True and s["1"]["home_pts"] == 30.0


def test_consensus_spread_signs_home_and_takes_median():
    import csv
    import io
    sched = pm.parse_schedule(SCHED)
    sp = pm.consensus_spreads(csv.DictReader(io.StringIO(LINES)), sched)
    assert sp["1"]["spread"] == -7.5 and sp["1"]["spread_open"] == -6.25 and sp["1"]["n_books"] == 2
    assert sp["2"]["spread"] == 3.0 and sp["2"]["spread_open"] is None


def test_loso_and_verdict_on_synthetic_signal():
    import random
    rnd = random.Random(0)
    games = []
    talent = {}
    for s in range(2016, 2026):
        talent[s] = {f"t{i}": 400 + 40 * i for i in range(12)}
        for k in range(300):
            h, a = rnd.sample(range(12), 2)
            td = (talent[s][f"t{h}"] - talent[s][f"t{a}"]) / 100.0
            resid = 2.0 * td + rnd.gauss(0, 3)  # talent strongly predicts the cover margin
            games.append({"season": s, "week": 5, "home": f"t{h}", "away": f"t{a}", "home_div": "fbs",
                          "away_div": "fbs", "neutral": False, "spread": -3.0, "home_pts": 3.0 + resid,
                          "away_pts": 0.0, "game_id": f"{s}-{k}"})
    X, y, seasons = pm.design(games, talent)
    pooled, per = pm.loso_ats(X, y, seasons, pm.PRIMARY_COLS, pm.PRIMARY_THRESHOLD)
    assert len(per) == 10 and pm.verdict(pooled, per)
    noise = [dict(g, home_pts=3.0 + rnd.gauss(0, 3)) for g in games]
    X, y, seasons = pm.design(noise, talent)
    pooled, per = pm.loso_ats(X, y, seasons, pm.PRIMARY_COLS, pm.PRIMARY_THRESHOLD)
    assert not pm.verdict(pooled, per)


def test_load_all_offline_and_cache_shape():
    sched18 = SCHED.encode()
    talent_csv = b"year,school,talent\n2018,UT San Antonio,500\n2018,Connecticut,450\n2018,Army,0\n"

    def fake_get(url):
        if url == pm.LINES_URL:
            return gzip.compress(LINES.encode())
        if "cfb_schedules_" in url:
            return sched18 if "2018" in url else b'"game_id","season","week","season_type"\n'
        if url.endswith(".json"):
            return b"[]"
        if "2025_talent" in url:
            return b"team,talent,season,rank\n"
        return talent_csv

    games, talent = pm.load_all([2017, 2018], get=fake_get)
    assert {g["game_id"] for g in games} == {"1", "2"}
    assert talent[2018] == {"utsa": 500.0, "uconn": 450.0}
    item = pm.to_cache_lines(games, 2018)
    assert item["1"]["spread"] == -7.5 and item["1"]["provider"] == "mirror_median"


def test_script_report_runs_on_synthetic():
    spec = importlib.util.spec_from_file_location("tm", ROOT / "scripts" / "backtest_cfb_talent_mirror.py")
    tm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tm)
    talent = {s: {"a": 600.0, "b": 500.0} for s in range(2016, 2026)}
    games = [{"season": s, "week": 3, "home": "a" if k % 2 else "b", "away": "b" if k % 2 else "a",
              "home_div": "fbs", "away_div": "fbs", "neutral": False, "spread": -1.0, "spread_open": -1.0,
              "home_pts": 10.0 + (k % 5), "away_pts": 10.0, "game_id": f"{s}{k}"}
             for s in range(2016, 2026) for k in range(20)]
    lines = []
    tm.report(games, talent, out=lines.append)
    assert any("VERDICT" in ln for ln in lines)
