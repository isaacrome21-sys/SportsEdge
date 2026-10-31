"""PAPER PLAYS section of the one shared RUN IT card (owner ruling 2026-10-31).

This is NOT a second card. It runs on the SAME priced rows the shared RUN IT pipeline already produced
(Lane A evaluated_rows from the shared DK capture). It adds a ranked paper-plays list so every slate logs bets
toward verified, even while the strict gates surface 0 plays. Same rows + same commit give the same plays.

Pricing is market-anchored. We start from DK's de-vigged price and move only K of the way toward the model:
    p = p_market + K * (p_model - p_market)
K is frozen here. It changes only by a new commit with a reason, re-fit from ledger CLV.

  python simple/paper_plays.py --priced <engine evaluated_rows json> --slate 2026-10-31 --sport CFB [--log]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from odds import devig_pair, ev_per_unit  # noqa: E402

K = 0.20            # share of model-vs-market disagreement we believe
MIN_EV = 0.01       # 1% adjusted EV to make the card
RAW_EV_CAP = 0.40   # owner rule: raw model EV above +40% is quarantined, never a play
PRICE_CAP = -165    # standing guard: no favourites shorter than -165
STARS = [(0.05, 5), (0.04, 4), (0.03, 3), (0.02, 2), (0.01, 1)]
VERSION = "PAPER_PLAYS_V1"


def stars(ev):
    for floor, s in STARS:
        if ev >= floor:
            return s
    return 0


def units(s):
    return 0.1 if s == 1 else 0.25


def pair_key(r):
    m = r.get("market")
    line = r.get("line")
    if m == "SPREAD" and line is not None:
        line = abs(float(line))
    return (r.get("game"), m, r.get("team_totals_team"), line)


def build(rows):
    groups = {}
    for r in rows:
        if r.get("odds_american") is None or r.get("estimate_p") is None:
            continue
        groups.setdefault(pair_key(r), []).append(r)
    plays, skipped = [], {"no_pair": 0, "raw_ev_cap": 0, "below_min": 0}
    for key, g in groups.items():
        if len(g) != 2:
            skipped["no_pair"] += 1
            continue
        a, b = g
        pa, pb = devig_pair(a["odds_american"], b["odds_american"])
        best = None
        for r, pm in ((a, pa), (b, pb)):
            if r["odds_american"] < PRICE_CAP:
                continue
            if (r.get("ev_per_dollar") or 0) > RAW_EV_CAP:
                skipped["raw_ev_cap"] += 1
                continue
            p = pm + K * (r["estimate_p"] - pm)
            ev = ev_per_unit(p, r["odds_american"])
            if best is None or ev > best[0]:
                best = (ev, r, p, pm)
        if best is None:
            continue
        ev, r, p, pm = best
        if ev < MIN_EV:
            skipped["below_min"] += 1
            continue
        s = stars(ev)
        plays.append(dict(
            sport=r.get("sport"), game=r.get("game"), kickoff_utc=r.get("kickoff_utc"),
            market=r.get("market"), selection=r.get("selection"), line=r.get("line"),
            odds=r["odds_american"], p_market=round(pm, 4), p_model=round(r["estimate_p"], 4),
            p_used=round(p, 4), ev=round(ev, 4), stars=s, units=units(s)))
    plays.sort(key=lambda x: (-x["ev"], x["game"] or "", x["market"] or "", x["selection"] or ""))
    return plays, skipped


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--priced", required=True, help="JSON with evaluated_rows (or a list of rows)")
    ap.add_argument("--slate", required=True, help="YYYY-MM-DD")
    ap.add_argument("--sport", required=True)
    ap.add_argument("--captured_at", default="", help="DK capture time of the input lines")
    ap.add_argument("--log", action="store_true", help="also append plays to simple/ledger.csv")
    ap.add_argument("--agent", default="claude")
    a = ap.parse_args()

    doc = json.load(open(a.priced))
    rows = doc["evaluated_rows"] if isinstance(doc, dict) else doc
    rows = [r for r in rows if (r.get("sport") or a.sport) == a.sport]
    plays, skipped = build(rows)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                cwd=os.path.dirname(__file__)).stdout.strip()
    except OSError:
        commit = ""
    card = dict(version=VERSION, slate=a.slate, sport=a.sport, K=K, min_ev=MIN_EV,
                raw_ev_cap=RAW_EV_CAP, input=a.priced, input_sha256=sha256(a.priced),
                captured_at=a.captured_at, built_at_commit=commit,
                rows_in=len(rows), skipped=skipped, plays=plays)
    out_dir = os.path.join(os.path.dirname(__file__), "paper_plays")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"{a.slate}_{a.sport}")
    with open(base + ".json", "w") as f:
        json.dump(card, f, indent=1)
    lines = [f"# RUN IT paper plays — {a.sport} {a.slate}", "",
             f"Paper only. {len(plays)} plays, ranked by EV. Market-anchored (K={K}). Input sha256 `{card['input_sha256'][:12]}`.", ""]
    for i, p in enumerate(plays, 1):
        lines.append(f"{i}. {'★' * p['stars']} {p['selection']} ({p['odds']:+d}) — {p['game']} — EV {p['ev']*100:.1f}% — {p['units']}u")
    if not plays:
        lines.append("No plays today.")
    with open(base + ".md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    if a.log:
        import ledger
        for p in plays:
            ns = argparse.Namespace(agent=a.agent, model=VERSION, sport=a.sport, market=p["market"],
                                    event=f"{p['game']} {a.slate}", side=p["selection"],
                                    line="" if p["line"] is None else p["line"], odds=p["odds"],
                                    prob=p["p_used"], captured_at=a.captured_at,
                                    source=f"{a.priced} sha256={card['input_sha256'][:12]}", note="")
            ledger.add(ns)


if __name__ == "__main__":
    main()
