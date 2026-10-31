"""Saturday Oct 31, 2026 CFB card build.

Adapted from operative_run_20261030_runit/build_card.py (the proven pipeline).
Reads captures_all.json in THIS dir (captures keyed by dk_event_id, each with
main_lines_text or verbatim_body in the lane's parser-safe format), prices every
game with the repo's Lane A layer (artifacts/free_models.py) from the fresh
clone at ~/workspace/cfb-card-20261031-clone (main head 540b5e90c), then runs
EVERY row through sportsedge.lane_a_card_gates.apply_card_gates with
current_estimate() (GATE_VERSION LANE_A_CARD_GATES_V3_GUARD_FAVORED_SIDE_20261029).
Nothing is classified from raw EVs. Writes card.json, classified_20261031.json
and WATCHLIST.md in this dir.
"""
import json, pathlib, re, sys
sys.path.insert(0, "/home/hatch/workspace/cfb-card-20261031-clone")
D = pathlib.Path(__file__).parent

caps_doc = json.loads((D / "captures_all.json").read_text())
caps = caps_doc["captures"]

def parse_main_lines(body, sport):
    """Parse the lane's parser-safe main-lines block (away first, home second)."""
    out = {}
    for raw in body.splitlines():
        line = raw.strip()
        m = re.fullmatch(r"Spread\s+([+-]?[\d.]+)\s+([+-]?\d+)\s+([+-]?\d+)", line)
        if m and sport in ("NBA", "CFB", "NFL"):
            out["spread"] = (float(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"Total\s+([\d.]+)\s+([+-]?\d+)\s+([+-]?\d+)", line)
        if m:
            out["total"] = (float(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"ML\s+([+-]?\d+)\s+([+-]?\d+)", line)
        if m:
            out["ml"] = (int(m.group(1)), int(m.group(2)))
    return out

rows_by_game = {}
game_meta = {}
for ev, c in caps.items():
    ml = parse_main_lines(c.get("main_lines_text") or c["verbatim_body"], c["sport"])
    game_meta[ev] = {**{k: c[k] for k in ("sport", "away", "home", "start_ct", "captured_at", "source")},
                     "parsed": {k: list(v) for k, v in ml.items()}}
    if not all(k in ml for k in ("ml", "spread", "total")):
        game_meta[ev]["parse_status"] = "INCOMPLETE_MAIN_LINES"
        continue
    game_meta[ev]["parse_status"] = "OK"
    sport, away, home = c["sport"], c["away"], c["home"]
    kickoff, cap_at = c["start_ct"], c["captured_at"]
    def R(market, side, line, odds):
        r = {"sport": sport, "market": market, "away": away, "home": home, "side": side,
             "odds": odds, "kickoff": kickoff, "quote_captured_at": cap_at}
        if line is not None:
            r["line"] = line
        return r
    (aml, hml) = ml["ml"]; (aline, ap, hp) = ml["spread"]; (tline, op, up) = ml["total"]
    rows_by_game[ev] = [R("ML", "AWAY", None, aml), R("ML", "HOME", None, hml),
                        R("SPREAD", "AWAY", aline, ap), R("SPREAD", "HOME", -aline, hp),
                        R("TOTAL", "OVER", tline, op), R("TOTAL", "UNDER", tline, up)]

all_rows = [r for v in rows_by_game.values() for r in v]
(D / "lines_intake_20261031.json").write_text(json.dumps({"lines": all_rows}, indent=1))
(D / "game_meta.json").write_text(json.dumps(game_meta, indent=1))
print("intake rows:", len(all_rows), "games parsed OK:", sum(1 for v in game_meta.values() if v["parse_status"] == "OK"))

# ---- Lane A pricing, per game, cached (a priced game is never repriced). ----
from artifacts import free_models
cache_path = D / "engine_rows_by_game.json"
cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
for ev, grows in rows_by_game.items():
    if ev in cache:
        print("engine cache hit:", ev)
        continue
    result = free_models.run({"lines": grows})
    cache[ev] = result.get("evaluated_rows", [])
    print("priced now:", ev, "x", len(cache[ev]))
cache_path.write_text(json.dumps(cache, indent=1))
erows = [r for ev in rows_by_game for r in cache.get(ev, [])]
(D / "engine_card_raw_20261031.json").write_text(json.dumps({"evaluated_rows": erows}, indent=1))
print("evaluated_rows:", len(erows))

# ---- Adopted Lane A card gates (V3) ----
from sportsedge import lane_a_card_gates as gates
est = gates.current_estimate()
gated = gates.apply_card_gates([dict(r) for r in erows], est)

out = {"headline": [], "overconfidence": [], "flagged": [], "excluded": [], "blocked": []}
for r in gated:
    cg = r["card_gate"]
    rec = {
        "sport": r.get("sport"), "game": r.get("game"), "kickoff_utc": r.get("kickoff_utc"),
        "market": r.get("market"), "selection": r.get("selection"), "price": r.get("odds_american"),
        "line": r.get("line"),
        "model_p": round(r["estimate_p"], 4) if r.get("estimate_p") is not None else None,
        "break_even_p": round(r["book_break_even_p"], 4) if r.get("book_break_even_p") is not None else None,
        "edge_pp": round(r["edge_over_break_even_pp"], 2) if r.get("edge_over_break_even_pp") is not None else None,
        "raw_ev_pct": round((r.get("ev_per_dollar") or 0) * 100, 1),
        "effective_ev_pct": round(cg["effective_ev"] * 100, 2) if cg.get("effective_ev") is not None else None,
        "fair_price": r.get("fair_american"),
        "proj_away": round(r.get("away_mean"), 3) if r.get("away_mean") is not None else None,
        "proj_home": round(r.get("home_mean"), 3) if r.get("home_mean") is not None else None,
        "engine_status": r.get("status"), "verified_play": False,
        "label": "LEAN - unvalidated estimate", "paper": "0u",
        "model_family": "FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED",
        "quote_freshness": (r.get("quote_freshness") or {}).get("code"),
        "card_gate": cg,
    }
    bucket = cg["bucket"]
    if bucket == "HEADLINE":
        rec["bucket"] = "HEADLINE"
        rec["lean_score"] = min(79, round(50 + (rec["edge_pp"] or 0)))
        out["headline"].append(rec)
    elif bucket == "OVERCONFIDENCE":
        rec["bucket"] = "OVERCONFIDENCE"
        out["overconfidence"].append(rec)
    elif bucket == "BLOCKED":
        rec["bucket"] = "BLOCKED"; rec["reason"] = cg["reason"]
        out["blocked"].append(rec)
    else:
        rec["bucket"] = "EXCLUDED"; rec["reason"] = cg["reason"]
        out["excluded"].append(rec)

for k in ("headline", "overconfidence", "flagged"):
    out[k].sort(key=lambda x: -(x["raw_ev_pct"] or 0))
(D / "classified_20261031.json").write_text(json.dumps(out, indent=1))
card = {"run": "operative_run_20261031_cfb", "sport": "CFB", "slate_date": "2026-10-31",
        "gate_version": gates.GATE_VERSION, "k_used": est.k_used,
        "gates_applied": "Every priced row passed through sportsedge.lane_a_card_gates.apply_card_gates with current_estimate(); no row classified from raw EV.",
        "games_captured": len(caps), "games_priced": len(rows_by_game),
        "counts": {k: len(v) for k, v in out.items()}, **out}
(D / "card.json").write_text(json.dumps(card, indent=1))
print("k_used:", est.k_used)
print("counts:", card["counts"])

# ---- WATCHLIST.md: rows nearest the headline floor + full bucket list ----
near = []
for b in ("excluded", "blocked"):
    for r in out[b]:
        if r["effective_ev_pct"] is not None:
            near.append((3.0 - r["effective_ev_pct"], r))
near.sort(key=lambda t: t[0])
lines = ["# Saturday CFB watchlist — Oct 31, 2026",
         "",
         "Built from the Friday-night card (operative_run_20261031_cfb). For Saturday's",
         "T-1H / FINAL lane marks: re-price these games first, in this order.",
         "",
         "## Overconfidence bucket (full list)", ""]
if out["overconfidence"]:
    for r in out["overconfidence"]:
        lines.append(f"- {r['selection']} — {r['game']} — {r['price']} — eff EV {r['effective_ev_pct']}% (raw {r['raw_ev_pct']}%)")
else:
    lines.append("- (none)")
lines += ["", "## Nearest the headline floor (effective EV, +3% needed)", ""]
if near:
    for dist, r in near[:25]:
        lines.append(f"- {r['selection']} — {r['game']} — {r['price']} — eff EV {r['effective_ev_pct']}% ({dist:.2f} pts short) — bucket {r['bucket']}")
else:
    lines.append("- (no priced rows)")
(D / "WATCHLIST.md").write_text("\n".join(lines) + "\n")
print("watchlist written")
