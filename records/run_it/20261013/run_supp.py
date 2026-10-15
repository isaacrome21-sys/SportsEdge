import sys, json
sys.path.insert(0, "/home/hatch/workspace/tmpgit/drift-compose")
sys.path.insert(0, "/home/hatch/workspace/tmpgit/drift-compose/artifacts")
from datetime import datetime, timezone
from run_it_full import run_full

NOW = datetime.now(timezone.utc)
A, H, K, Q = "Cleveland Guardians", "Tampa Bay Rays", "2026-10-14T00:00:00Z", "2026-10-13T10:08:00Z"

def grow(market, side, odds, line=None, team=None, extra=None):
    r = {"sport": "MLB", "away": A, "home": H, "kickoff": K, "market": market,
         "side": side, "odds": odds, "book": "draftkings", "quote_captured_at": Q}
    if line is not None: r["line"] = line
    if team is not None: r["team"] = team
    if extra: r.update(extra)
    return r

rows = [
    grow("TEAM_TOTALS", "OVER", 120, 3.5, A), grow("TEAM_TOTALS", "UNDER", -154, 3.5, A),
    grow("TEAM_TOTALS", "OVER", -110, 3.5, H), grow("TEAM_TOTALS", "UNDER", -120, 3.5, H),
    grow("F5_MONEYLINE", "AWAY", -115, None, None, {"event_id": "34817298", "game_pk": 849813}),
    grow("F5_MONEYLINE", "HOME", -115, None, None, {"event_id": "34817298", "game_pk": 849813}),
    grow("F5_SPREAD", "AWAY", 130, -0.5, None, {"event_id": "34817298", "game_pk": 849813}),
    grow("F5_SPREAD", "HOME", -166, 0.5, None, {"event_id": "34817298", "game_pk": 849813}),
]
print(f"supp: {len(rows)} rows; run start {NOW.isoformat()}")
card = run_full({"lines": rows, "sport": "MLB"}, now=NOW, auto_context=True, min_ev=0.02, lane="A")
with open("/home/hatch/workspace/sportsedge/run_it_20261013/card_mlb_supp.json", "w") as f:
    json.dump(card, f, indent=2, default=str)
for r in card["evaluated_rows"]:
    print(f"{r.get('market')} {r.get('selection')}: status={r.get('status')} p={r.get('estimate_p') or r.get('model_probability')} ev={r.get('ev_per_dollar')} reason={r.get('reason') or ''} blocker={r.get('blocker') or ''}")
