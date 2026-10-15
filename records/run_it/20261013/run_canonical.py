import sys, json
sys.path.insert(0, "/home/hatch/workspace/tmpgit/drift-compose")
sys.path.insert(0, "/home/hatch/workspace/tmpgit/drift-compose/artifacts")
from datetime import datetime, timezone
from run_it_full import run_full

NOW = datetime.now(timezone.utc)
Q_REFRESH = "2026-10-13T10:08:00Z"   # DK refresh read (game markets, team totals, pitcher props)
Q_FIRST = "2026-10-13T10:04:00Z"     # DK first read (batter props)

def grow(sport, away, home, kickoff, market, side, odds, line=None, team=None, q=Q_REFRESH):
    r = {"sport": sport, "away": away, "home": home, "kickoff": kickoff,
         "market": market, "side": side, "odds": odds,
         "book": "draftkings", "quote_captured_at": q}
    if line is not None: r["line"] = line
    if team is not None: r["team"] = team
    return r

# ---------------- MLB: Cleveland @ Tampa Bay ----------------
A, H, K = "Cleveland Guardians", "Tampa Bay Rays", "2026-10-14T00:00:00Z"
mlb = [
    grow("MLB", A, H, K, "ML", "AWAY", 119), grow("MLB", A, H, K, "ML", "HOME", -143),
    grow("MLB", A, H, K, "SPREAD", "AWAY", -194, 1.5), grow("MLB", A, H, K, "SPREAD", "HOME", 159, -1.5),
    grow("MLB", A, H, K, "TOTAL", "OVER", 102, 7.0), grow("MLB", A, H, K, "TOTAL", "UNDER", -122, 7.0),
    grow("MLB", A, H, K, "TEAM_TOTALS", "AWAY_OVER", 120, 3.5, A), grow("MLB", A, H, K, "TEAM_TOTALS", "AWAY_UNDER", -154, 3.5, A),
    grow("MLB", A, H, K, "TEAM_TOTALS", "HOME_OVER", -110, 3.5, H), grow("MLB", A, H, K, "TEAM_TOTALS", "HOME_UNDER", -120, 3.5, H),
    grow("MLB", A, H, K, "NRFI", "", -145), grow("MLB", A, H, K, "YRFI", "", 110),
]
# F5 with DK event identity for the binding lane
for side, odds in (("AWAY", -115), ("HOME", -115)):
    r = grow("MLB", A, H, K, "F5_MONEYLINE", side, odds); r["event_id"] = "34817298"; mlb.append(r)
for side, odds, ln in (("AWAY", 130, -0.5), ("HOME", -166, 0.5)):
    r = grow("MLB", A, H, K, "F5_SPREAD", side, odds, ln); r["event_id"] = "34817298"; mlb.append(r)

pitchers = [
    ("Parker Messick", A, [("PITCHER_STRIKEOUTS", 4.5, -150, 117), ("PITCHER_OUTS", 14.5, -126, -105),
                            ("PITCHER_HITS_ALLOWED", 4.5, 115, -153), ("PITCHER_EARNED_RUNS", 1.5, -116, -114)]),
    ("Freddy Peralta", H, [("PITCHER_STRIKEOUTS", 3.5, -123, -104), ("PITCHER_OUTS", 13.5, -124, -107),
                            ("PITCHER_HITS_ALLOWED", 3.5, -104, -127), ("PITCHER_EARNED_RUNS", 1.5, 102, -136)]),
]
for name, team, markets in pitchers:
    for mkt, ln, oo, uo in markets:
        for side, odds in (("OVER", oo), ("UNDER", uo)):
            r = grow("MLB", A, H, K, mkt, side, odds, ln, team)
            r["player_name"] = name; mlb.append(r)

# Batter props from the first DK read (honest 10:04Z stamps)
batters = [
    # name, team, hits O/U, TB O/U, RBI O/U, runs O/U, HR 1+ price
    ("Yandy Diaz", H, (-248, 183), (125, -167), (218, -314), (110, -152), 483),
    ("Junior Caminero", H, (-229, 170), (123, -164), (170, -240), (118, -164), 339),
    ("Steven Kwan", A, (-199, 148), (175, -240), (376, -576), (152, -213), 2400),
    ("Jose Ramirez", A, (-193, 144), (163, -220), (232, -335), (135, -187), 543),
    ("Chase DeLauter", A, (-192, 144), (169, -228), (226, -325), (158, -222), 690),
    ("Jonathan Aranda", H, (-187, 140), (169, -228), (277, -408), (141, -197), 830),
    ("Victor Mesa Jr.", H, (-187, 140), (174, -236), (225, -324), (163, -230), 680),
    ("Ben Williamson", H, (-165, 124), (225, -315), (280, -412), (198, -282), 1020),
    ("Jonny DeLuca", H, (-157, 118), (215, -302), (284, -419), (192, -273), 1000),
    ("Nathaniel Lowe", A, (-150, 113), (225, -315), (253, -369), (186, -264), 680),
    ("Jo Adell", A, (-147, 110), (236, -333), (202, -289), (160, -224), 468),
    ("Travis Bazzana", A, (-134, 101), (255, -360), (294, -436), (203, -289), 800),
    ("Brayan Rocchio", A, (-127, -104), (275, -392), (347, -526), (225, -325), 1180),
    ("Ryan Vilade", H, (-123, -108), (286, -407), (279, -411), (195, -278), 730),
    ("Taylor Walls", H, (-118, -113), (295, -422), (349, -528), (218, -312), 1180),
    ("Patrick Bailey", A, (-116, -114), (280, -398), (316, -473), (231, -333), 880),
    ("Petey Halpin", A, (-115, -115), (286, -407), (338, -510), (236, -341), 960),
    ("Nick Fortes", H, (-110, -120), (300, -430), (355, -538), (236, -342), 1140),
]
for name, team, hits, tb, rbi, runs, hr in batters:
    for mkt, ln, pair in (("BATTER_HITS", 0.5, hits), ("BATTER_TOTAL_BASES", 1.5, tb),
                          ("BATTER_RBIS", 0.5, rbi), ("BATTER_RUNS", 0.5, runs)):
        for side, odds in (("OVER", pair[0]), ("UNDER", pair[1])):
            r = grow("MLB", A, H, K, mkt, side, odds, ln, team, q=Q_FIRST)
            r["player_name"] = name; mlb.append(r)
    r = grow("MLB", A, H, K, "BATTER_HOME_RUNS", "OVER", hr, 0.5, team, q=Q_FIRST)
    r["player_name"] = name; mlb.append(r)

# ---------------- CFB ----------------
def cfb_game(away, home, kickoff, ml, spread, total, tts, halves):
    rows = [
        grow("CFB", away, home, kickoff, "ML", "AWAY", ml[0]), grow("CFB", away, home, kickoff, "ML", "HOME", ml[1]),
        grow("CFB", away, home, kickoff, "SPREAD", "AWAY", spread[1], spread[0]), grow("CFB", away, home, kickoff, "SPREAD", "HOME", spread[3], spread[2]),
        grow("CFB", away, home, kickoff, "TOTAL", "OVER", total[1], total[0]), grow("CFB", away, home, kickoff, "TOTAL", "UNDER", total[2], total[0]),
    ]
    for team, ln, oo, uo, pref in tts:
        rows.append(grow("CFB", away, home, kickoff, "TEAM_TOTALS", pref + "_OVER", oo, ln, team))
        rows.append(grow("CFB", away, home, kickoff, "TEAM_TOTALS", pref + "_UNDER", uo, ln, team))
    for mkt, side, odds, ln in halves:
        rows.append(grow("CFB", away, home, kickoff, mkt, side, odds, ln))
    return rows

cfb = []
cfb += cfb_game("Delaware Blue Hens", "Middle Tennessee Blue Raiders", "2026-10-13T23:00:00Z",
    ml=(-118, -102), spread=(-1.5, -102, 1.5, -118), total=(47.5, -115, -105),
    tts=[("Delaware Blue Hens", 23.5, -135, 100, "AWAY"), ("Middle Tennessee Blue Raiders", 23.5, -120, -105, "HOME")],
    halves=[("SPREAD_1H", "AWAY", 105, -0.5), ("SPREAD_1H", "HOME", -125, 0.5),
            ("ML_1H", "AWAY", -115, None), ("ML_1H", "HOME", -105, None),
            ("TOTAL_1H", "OVER", -118, 23.5), ("TOTAL_1H", "UNDER", -102, 23.5)])
cfb += cfb_game("Florida International Panthers", "Jacksonville State Gamecocks", "2026-10-14T00:00:00Z",
    ml=(120, -142), spread=(3.0, -115, -3.0, -105), total=(43.5, -112, -108),
    tts=[("Florida International Panthers", 20.5, -115, -110, "AWAY"), ("Jacksonville State Gamecocks", 22.5, -120, -110, "HOME")],
    halves=[("SPREAD_1H", "AWAY", -110, 1.5), ("SPREAD_1H", "HOME", -110, -1.5),
            ("ML_1H", "AWAY", 124, None), ("ML_1H", "HOME", -148, None),
            ("TOTAL_1H", "OVER", -122, 21.5), ("TOTAL_1H", "UNDER", 102, 21.5)])

atd1 = [("Cam'ron Lacy", "Middle Tennessee Blue Raiders", -125), ("Antonio Martin", "Middle Tennessee Blue Raiders", 100),
        ("Jo Silver", "Delaware Blue Hens", 100), ("Sean Wilson", "Delaware Blue Hens", 120),
        ("Viron Ellison", "Delaware Blue Hens", 150), ("Terrence Brown", "Middle Tennessee Blue Raiders", 160),
        ("Da'Wain Lofton", "Delaware Blue Hens", 205), ("Markus Allen", "Middle Tennessee Blue Raiders", 235),
        ("Neo Clifton", "Middle Tennessee Blue Raiders", 245), ("Kaderris Roberts", "Delaware Blue Hens", 260),
        ("Bryson Graves", "Delaware Blue Hens", 260), ("AJ Jones", "Middle Tennessee Blue Raiders", 300),
        ("Donovan Lewis", "Delaware Blue Hens", 310), ("Delaware D/ST", "Delaware Blue Hens", 390),
        ("Middle Tennessee D/ST", "Middle Tennessee Blue Raiders", 425), ("Roman Gagliano", "Middle Tennessee Blue Raiders", 450),
        ("Nick Minicucci", "Delaware Blue Hens", 450), ("Hogan Wasson", "Middle Tennessee Blue Raiders", 475),
        ("Koraun Perdue", "Middle Tennessee Blue Raiders", 500), ("Tae'Sean Robinson", "Delaware Blue Hens", 550),
        ("Braden Streeter", "Delaware Blue Hens", 650), ("Matt McKinley-Daniels", "Delaware Blue Hens", 650),
        ("DJ Taylor", "Middle Tennessee Blue Raiders", 700), ("Ziyon Butler", "Middle Tennessee Blue Raiders", 750),
        ("Scott Moore", "Delaware Blue Hens", 1100)]
for name, team, odds in atd1:
    r = grow("CFB", "Delaware Blue Hens", "Middle Tennessee Blue Raiders", "2026-10-13T23:00:00Z",
             "ANYTIME_TD", "YES", odds, None, team, q=Q_FIRST); r["player_name"] = name; cfb.append(r)
atd2 = [("Caden Creel", "Jacksonville State Gamecocks", -160), ("Jalen Likely", "Jacksonville State Gamecocks", 110),
        ("Anthony Carrie", "Florida International Panthers", 120), ("Maguire Anderson", "Florida International Panthers", 145),
        ("Devonte Lyons", "Florida International Panthers", 165), ("Jamill Williams", "Jacksonville State Gamecocks", 245),
        ("Lucas Farrington", "Jacksonville State Gamecocks", 280), ("Deondre Johnson", "Jacksonville State Gamecocks", 285),
        ("JJ Kohl", "Florida International Panthers", 300), ("James Resar", "Florida International Panthers", 310),
        ("JoJo Stone", "Florida International Panthers", 330), ("Darius Cannon", "Jacksonville State Gamecocks", 370),
        ("Ronnel Johnson", "Jacksonville State Gamecocks", 400), ("Tyson Carter", "Florida International Panthers", 450),
        ("Luke Gilbert", "Jacksonville State Gamecocks", 475), ("Sterling Joseph", "Florida International Panthers", 475),
        ("Jacksonville State D/ST", "Jacksonville State Gamecocks", 475), ("Khristian Lando", "Jacksonville State Gamecocks", 500),
        ("Kyle McNeal", "Florida International Panthers", 500), ("FIU D/ST", "Florida International Panthers", 500),
        ("Eric Nelson", "Florida International Panthers", 550), ("Greg Gaines", "Florida International Panthers", 550),
        ("Cedric Kouemi", "Jacksonville State Gamecocks", 600), ("Jameson Scissum", "Jacksonville State Gamecocks", 1000),
        ("Jackson Verdugo", "Florida International Panthers", 1000), ("Dylan Gentry", "Jacksonville State Gamecocks", 1300)]
for name, team, odds in atd2:
    r = grow("CFB", "Florida International Panthers", "Jacksonville State Gamecocks", "2026-10-14T00:00:00Z",
             "ANYTIME_TD", "YES", odds, None, team, q=Q_FIRST); r["player_name"] = name; cfb.append(r)

if __name__ == "__main__":
    which = sys.argv[1]
    rows = mlb if which == "MLB" else cfb
    print(f"{which}: {len(rows)} intake rows; run start {NOW.isoformat()}")
    card = run_full({"lines": rows, "sport": which}, now=NOW, auto_context=True, min_ev=0.02, lane="A")
    out = f"/home/hatch/workspace/sportsedge/run_it_20261013/card_{which.lower()}_canonical.json"
    with open(out, "w") as f:
        json.dump(card, f, indent=2, default=str)
    print(f"{which}: summary:", json.dumps(card.get("summary", {}), default=str)[:600])
    print(f"{which}: written {out}")
