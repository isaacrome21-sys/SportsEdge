# As-run record of the 2026-10-27 rerun (see RERUN_REPORT.md in this
# directory). Paths point at the operative run record and the repo
# checkout used for the run; kept verbatim for provenance.
"""Rerun the Oct 19, 2026 ALCS G6 batter board through the CURRENT repo path.
Replicates operative_run_20261019_mlb_alcs_g6/price_batters.py exactly, except
now is pinned to the original pregame instant (board captured 17:10 CT)."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/review_2783/repo")
from sportsedge.mlb_phone_batter_pricing import phone_batter_rows
from sportsedge.mlb_public_batter_history import MLBBatterPublicSource

RUN = Path("/home/hatch/workspace/sportsedge/operative_run_20261019_mlb_alcs_g6")
AWAY, HOME = "Cleveland Guardians", "Tampa Bay Rays"
KICKOFF = "2026-10-20T00:08:00Z"
NOW = datetime(2026, 10, 19, 22, 10, tzinfo=timezone.utc)  # 17:10 CT, pregame
STARTERS = {
    "Steven Kwan", "José Ramírez", "Chase DeLauter", "Jo Adell",
    "Nathaniel Lowe", "Travis Bazzana", "Patrick Bailey", "Petey Halpin",
    "Brayan Rocchio", "Yandy Díaz", "Jonathan Aranda", "Liam Hicks",
    "Junior Caminero", "Chandler Simpson", "Victor Mesa Jr.",
    "Jonny DeLuca", "Richie Palacios", "Taylor Walls",
}

board = json.loads((RUN / "board.json").read_text())
orig = json.loads((RUN / "pricing_out.json").read_text())
blocked_keys = {}
for r in orig["priced_rows"]:
    if r.get("reason") == "HISTORY_LEAK_OR_DUPLICATE_GAME":
        blocked_keys.setdefault((r["player_name"], r["market"], r["selection"]), 0)
        blocked_keys[(r["player_name"], r["market"], r["selection"])] += 1
print("distinct blocked (player,market,side):", len(blocked_keys), "| total blocked rows:", sum(blocked_keys.values()))

rows_in = []
for r in board["rows"]:
    if r["player_name"] not in STARTERS:
        continue
    rows_in.append({
        "player_name": r["player_name"], "market": r["market"], "line": r["line"],
        "side": r["side"], "odds": r["odds"], "book": "draftkings",
        "away": AWAY, "home": HOME, "kickoff": KICKOFF,
        "quote_captured_at": board["captured_at_utc"],
    })
print("submitted rows:", len(rows_in))
judged, sources = phone_batter_rows(rows_in, now=NOW)
Path("/tmp/dh_rerun/rerun_out.json").write_text(json.dumps(
    {"judged": judged, "sources": sources}, indent=1, ensure_ascii=False))

# Per-player prior windows (for real doubleheader discovery)
src = MLBBatterPublicSource()
windows = {}
for name in sorted({r["player_name"] for r in rows_in}):
    try:
        v = src.prior_games(away=AWAY, home=HOME, player_name=name,
                            owner_kickoff=KICKOFF, as_of=NOW.isoformat())
        pairs = list(zip([t[:10] for t in v["prior_game_times_utc"]], v["prior_game_ids"]))
        windows[name] = {"count": v["prior_game_count"], "pairs": pairs,
                         "ids_unique": len({p for _, p in pairs}) == len(pairs)}
    except Exception as e:
        windows[name] = {"error": str(e)}
Path("/tmp/dh_rerun/windows.json").write_text(json.dumps(windows, indent=1, ensure_ascii=False))
for name, w in windows.items():
    if "pairs" in w:
        from collections import Counter
        dates = Counter(d for d, _ in w["pairs"])
        dh = {d: c for d, c in dates.items() if c > 1}
        print(f"{name}: {w['count']} priors, ids_unique={w['ids_unique']}, doubleheader_dates={dh}")
    else:
        print(f"{name}: ERROR {w['error']}")
