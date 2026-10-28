"""Toy-slate computability verification for AMENDMENT 2 (DRAFT).

Executes the amendment's added machinery end to end on a TOY slate
of 12 invented games (all teams, lines, prices, and results are
made up for this check and labeled as such in the output): the
section-1 pick rule (thresholds 2.2 spread / 3.5 total / 2.1 team
points, derived in the amendment from the screens' pooled MAEs),
the section-2 game-cluster bootstrap interval (10,000 resamples,
seed 20261028, two-sided at level 1 - 0.05/12, nearest-rank
quantiles), and the section-3 close-validity / moved-row /
insufficiency rules with their refusal codes. The toy verifies
that every leg quantity the amendment defines is computable --
it is NOT a verdict run (12 games do not meet the section-5
review gate of >= 40 distinct graded games) and it is not
evidence about any real game.

Stdlib only. Run: python3 verify_amendment2_toy_slate.py
Writes amendment2_toy_slate_results.json next to this script and
asserts that every leg quantity was produced.
"""

import json
import math
import random
from pathlib import Path

SEED = 20261028
REPS = 10000
ALPHA = 0.05
K_AT_PACKAGE_TIME = 12
THR = {"spread": 2.2, "total": 3.5, "team": 2.1}

# Toy slate, efficiency markets. Fields: game id, model margin,
# baseline margin, actual margin (all home perspective), model
# total, baseline total, actual total, DK home spread line, spread
# prices (home, away), total prices (over, under), spread close,
# total close. A close is ("same", minutes_before_tip, close_px_a,
# close_px_b) -- a valid two-sided close at the entry line;
# ("moved", new_line, minutes) -- a valid close at a different
# line; ("stale", minutes) -- last capture older than 60:00;
# ("missing",) -- no FINAL capture. For a moved spread close the
# new_line is the new home line; for a moved total close it is the
# new total line.
GAMES = [
    ("T01", 7.0, 5.0, 9, 148.0, 145.0, 152, -4.5, -110, -110, -110, -110,
     ("same", 22, -120, 100), ("same", 22, -105, -115)),
    ("T02", 1.0, 2.5, -3, 139.0, 141.0, 133, -1.5, -110, -110, -110, -110,
     ("same", 15, -110, -110), ("same", 15, -110, -110)),
    ("T03", -8.0, -5.5, -11, 154.0, 150.0, 149, 6.5, -110, -110, -105, -115,
     ("same", 31, -110, -110), ("moved", 147.5, 12)),
    ("T04", 5.6, 3.0, 3, 144.0, 143.5, 147, -3.0, -110, -110, -110, -110,
     ("same", 9, -110, -110), ("same", 9, -110, -110)),
    ("T05", 12.0, 9.0, 6, 136.0, 138.0, 130, -9.5, -115, -105, -110, -110,
     ("moved", -11.5, 18), ("same", 18, -110, -110)),
    ("T06", -2.0, -1.0, 4, 158.0, 154.0, 159, 2.5, -110, -110, -110, -110,
     ("same", 26, -110, -110), ("missing",)),
    ("T07", 5.5, 6.5, 2, 141.5, 142.5, 138, -6.0, -110, -110, -110, -110,
     ("same", 44, -110, -110), ("same", 44, -110, -110)),
    ("T08", -13.0, -10.0, -18, 133.0, 135.5, 128, 10.5, -110, -110, -110, -110,
     ("same", 12, -115, -105), ("stale", 95)),
    ("T09", 4.2, 3.8, 8, 150.0, 147.0, 155, -4.0, -108, -112, -110, -110,
     ("same", 20, -110, -110), ("same", 20, -125, 105)),
    ("T10", 0.5, -0.5, -6, 146.5, 148.0, 142, 1.0, -110, -110, -110, -110,
     ("same", 17, -110, -110), ("same", 17, -110, -110)),
    ("T11", 9.0, 7.5, 13, 143.0, 141.0, 150, -7.5, -110, -110, -110, -110,
     ("same", 29, -110, -110), ("same", 29, 100, -120)),
    ("T12", -4.6, -3.0, -2, 138.5, 140.0, 136, 3.5, -110, -110, -110, -110,
     ("same", 11, -110, -110), ("same", 11, -110, -110)),
]

# Toy entry total lines per game (the market's total at T-1H).
TOY_TOTAL_LINES = {
    "T01": 144.5, "T02": 140.5, "T03": 149.5, "T04": 143.5,
    "T05": 137.5, "T06": 154.5, "T07": 144.5, "T08": 136.5,
    "T09": 146.5, "T10": 148.5, "T11": 139.5, "T12": 140.5,
}

# Team-total rows per game: (mu_home, base_home, act_home, line_home,
# mu_away, base_away, act_away, line_away, home_close, away_close).
# Entry prices -110 both sides; a "same" close carries its own pair.
TEAMS = {
    "T01": (78.0, 74.8, 80, 74.5, 71.7, 70.2, 72, 72.5,
            ("same", 22, -120, 100), ("same", 22, -110, -110)),
    "T02": (70.0, 71.8, 66, 70.5, 69.0, 69.2, 67, 68.5,
            ("same", 15, -110, -110), ("same", 15, -110, -110)),
    "T03": (72.2, 72.3, 68, 73.5, 80.3, 77.7, 81, 77.5,
            ("same", 31, -110, -110), ("same", 31, -110, -110)),
    "T04": (73.7, 73.3, 75, 73.5, 70.3, 70.2, 72, 71.5,
            ("same", 9, -110, -110), ("same", 9, -110, -110)),
    "T05": (74.0, 72.3, 68, 73.5, 59.0, 65.7, 62, 62.5,
            ("same", 18, -110, -110), ("moved", 60.5, 18)),
    "T06": (77.9, 76.4, 82, 77.5, 83.0, 77.6, 77, 78.5,
            ("same", 26, -110, -110), ("same", 26, -130, 110)),
    "T07": (73.5, 74.3, 70, 74.5, 68.0, 68.2, 68, 69.5,
            ("same", 44, -110, -110), ("same", 44, -110, -110)),
    "T08": (60.0, 62.8, 55, 61.5, 73.0, 72.7, 73, 71.5,
            ("stale", 95), ("same", 12, -110, -110)),
    "T09": (79.0, 75.4, 81, 75.5, 72.9, 71.6, 74, 73.5,
            ("same", 20, -115, -105), ("same", 20, -110, -110)),
    "T10": (73.5, 74.3, 68, 73.5, 73.0, 73.7, 74, 72.5,
            ("same", 17, -110, -110), ("same", 17, -110, -110)),
    "T11": (76.0, 74.3, 80, 75.5, 63.0, 66.7, 70, 66.5,
            ("same", 29, -110, -110), ("same", 29, -105, -115)),
    "T12": (64.5, 68.5, 67, 67.0, 71.5, 71.5, 69, 70.5,
            ("same", 11, -110, -110), ("same", 11, -110, -110)),
}
TT_PX = -110  # toy team-total entry price, both sides


def _imp(px):
    return (-px) / (-px + 100) if px < 0 else 100 / (px + 100)


def novig(px_a, px_b):
    """Multiplicative de-vig of a two-sided pair (American prices)."""
    pa, pb = _imp(px_a), _imp(px_b)
    return pa / (pa + pb), pb / (pa + pb)


def profit(px, result):
    """Net units on a 1-unit stake: WIN / LOSS / PUSH."""
    if result == "PUSH":
        return 0.0
    if result == "LOSS":
        return -1.0
    return (100 / -px) if px < 0 else (px / 100)


def close_state(close):
    """Section-3 validity, checked before any moved classification.

    Returns (state, minutes_before_tip). States: VALID (same-line),
    LINE_MOVED, CLOSE_STALE, NO_CLOSE_ROW. (The toy exercises these
    three refusal paths; CLOSE_SINGLE_SIDED / CLOSE_NOT_PREKICKOFF
    follow the same code path and are not separately simulated.)
    """
    kind = close[0]
    if kind == "missing":
        return "NO_CLOSE_ROW", None
    minutes = close[1] if kind in ("same", "stale") else close[2]
    if kind == "stale" or minutes > 60:
        return "CLOSE_STALE", minutes
    if kind == "moved":
        return "LINE_MOVED", minutes
    return "VALID", minutes


def settle(diff):
    return "WIN" if diff > 0 else ("PUSH" if diff == 0 else "LOSS")


def cluster_ci(clusters, seed=SEED, reps=REPS, alpha=ALPHA,
               k=K_AT_PACKAGE_TIME):
    """Game-cluster bootstrap of the mean paired difference.

    Clusters are per-game lists of paired differences; each
    resample draws len(clusters) games with replacement and
    averages all differences of the drawn games. Two-sided
    percentile interval at level 1 - alpha/k, nearest-rank.
    """
    rng = random.Random(seed)
    n = len(clusters)
    stats = []
    for _ in range(reps):
        tot, cnt = 0.0, 0
        for _ in range(n):
            c = clusters[rng.randrange(n)]
            tot += sum(c)
            cnt += len(c)
        stats.append(tot / cnt)
    stats.sort()
    level = 1 - alpha / k
    q_lo = (1 - level) / 2
    lo = stats[max(0, math.ceil(q_lo * reps) - 1)]
    hi = stats[min(reps - 1, math.ceil((1 - q_lo) * reps) - 1)]
    point = sum(sum(c) for c in clusters) / sum(len(c) for c in clusters)
    return {"point": point, "ci_lower": lo, "ci_upper": hi,
            "level": level, "reps": reps, "seed": seed,
            "accuracy_leg_pass": hi < 0}


def sign_test_p(adverse, favorable):
    """One-sided exact sign test: P(X >= adverse), X ~ Bin(m, 0.5)."""
    m = adverse + favorable
    if m == 0:
        return 1.0
    return sum(math.comb(m, x) for x in range(adverse, m + 1)) / (2 ** m)


def score_row(fam, gap, thr, px, result, state, close, entry_pair,
              side_idx, moved_favorable):
    """Apply the section-1/section-3 machinery to one priced row."""
    fam["rows"] += 1
    if state in ("NO_CLOSE_ROW", "CLOSE_STALE", "CLOSE_SINGLE_SIDED",
                 "CLOSE_NOT_PREKICKOFF"):
        fam["missing_close"] += 1
    if abs(gap) < thr:
        return
    fam["picked"].append({"px": px, "result": result,
                          "profit": profit(px, result)})
    if state == "LINE_MOVED":
        fam["moved_picked"].append(
            "FAVORABLE" if moved_favorable else "ADVERSE")
    elif state == "VALID":
        p_e = novig(*entry_pair)[side_idx]
        p_c = novig(close[2], close[3])[side_idx]
        fam["clv"].append(p_c - p_e)


def family_block(fam):
    picked = fam["picked"]
    roi = (sum(p["profit"] for p in picked) / len(picked)
           if picked else None)
    mean_clv = (sum(fam["clv"]) / len(fam["clv"]) if fam["clv"] else None)
    adv = fam["moved_picked"].count("ADVERSE")
    favn = fam["moved_picked"].count("FAVORABLE")
    p = sign_test_p(adv, favn)
    return {
        "rows_priced": fam["rows"],
        "picked_rows": len(picked),
        "roi_on_picked": roi,
        "mean_clv_picked_same_line": mean_clv,
        "clv_rows": len(fam["clv"]),
        "missing_close_rows": fam["missing_close"],
        "missing_close_share": fam["missing_close"] / fam["rows"],
        "insufficient_close_data": fam["missing_close"] / fam["rows"] > 0.2,
        "moved_picked_directions": fam["moved_picked"],
        "moved_sign_test_p": p,
        "moved_rule1_triggered": p < ALPHA / K_AT_PACKAGE_TIME,
        "moved_rule2_triggered": bool(picked) and
            len(fam["moved_picked"]) / len(picked) > 0.5,
        "market_leg_pass_point_estimates": (
            roi is not None and mean_clv is not None
            and roi > 0 and mean_clv > 0),
    }


def run():
    out = {"toy": True,
           "note": "INVENTED toy slate -- computability check only, "
                   "not a verdict and not evidence",
           "seed": SEED, "reps": REPS,
           "k_at_package_time": K_AT_PACKAGE_TIME, "thresholds": THR}

    eff = {"picked": [], "clv": [], "missing_close": 0, "rows": 0,
           "moved_picked": [], "clusters": {"spread": [], "total": []}}
    tt = {"picked": [], "clv": [], "missing_close": 0, "rows": 0,
          "moved_picked": [], "clusters": []}

    for g in GAMES:
        (gid, mu_m, b_m, act_m, mu_t, b_t, act_t, hline, sph, spa,
         tov, tun, sp_close, tot_close) = g
        mkt_margin = -hline
        eff["clusters"]["spread"].append(
            [abs(mu_m - act_m) - abs(b_m - act_m)])
        eff["clusters"]["total"].append(
            [abs(mu_t - act_t) - abs(b_t - act_t)])
        # --- spread row ---
        gap = mu_m - mkt_margin
        home = gap >= 0
        st, _ = close_state(sp_close)
        moved_fav = None
        if st == "LINE_MOVED":
            moved_fav = (gap > 0) == (-sp_close[1] > mkt_margin)
        score_row(eff, gap, THR["spread"], sph if home else spa,
                  settle((act_m - mkt_margin) if home
                         else (mkt_margin - act_m)),
                  st, sp_close, (sph, spa), 0 if home else 1, moved_fav)
        # --- total row ---
        line_t = TOY_TOTAL_LINES[gid]
        gap_t = mu_t - line_t
        over = gap_t >= 0
        st_t, _ = close_state(tot_close)
        moved_fav = None
        if st_t == "LINE_MOVED":
            moved_fav = (gap_t > 0) == (tot_close[1] > line_t)
        score_row(eff, gap_t, THR["total"], tov if over else tun,
                  settle((act_t - line_t) if over else (line_t - act_t)),
                  st_t, tot_close, (tov, tun), 0 if over else 1,
                  moved_fav)
        # --- team-total rows ---
        mu_h, b_h, a_h, ln_h, mu_a, b_a, a_a, ln_a, c_h, c_a = TEAMS[gid]
        tt["clusters"].append([abs(mu_h - a_h) - abs(b_h - a_h),
                               abs(mu_a - a_a) - abs(b_a - a_a)])
        for mu, ln, act, close in ((mu_h, ln_h, a_h, c_h),
                                   (mu_a, ln_a, a_a, c_a)):
            gap_i = mu - ln
            over_i = gap_i >= 0
            st_i, _ = close_state(close)
            moved_fav = None
            if st_i == "LINE_MOVED":
                moved_fav = (gap_i > 0) == (close[1] > ln)
            score_row(tt, gap_i, THR["team"], TT_PX,
                      settle((act - ln) if over_i else (ln - act)),
                      st_i, close, (TT_PX, TT_PX), 0 if over_i else 1,
                      moved_fav)

    out["efficiency"] = family_block(eff)
    out["efficiency"]["accuracy_spread"] = cluster_ci(
        eff["clusters"]["spread"])
    out["efficiency"]["accuracy_total"] = cluster_ci(
        eff["clusters"]["total"])
    out["team_totals"] = family_block(tt)
    out["team_totals"]["accuracy_team_points"] = cluster_ci(
        tt["clusters"])

    for fam in ("efficiency", "team_totals"):
        b = out[fam]
        assert b["picked_rows"] >= 5, fam
        assert b["roi_on_picked"] is not None, fam
        assert b["mean_clv_picked_same_line"] is not None, fam
        assert b["mean_clv_picked_same_line"] != 0.0, fam
        assert 0.0 <= b["missing_close_share"] <= 1.0, fam
        assert isinstance(b["moved_sign_test_p"], float), fam
    for key in ("accuracy_spread", "accuracy_total"):
        c = out["efficiency"][key]
        assert c["ci_lower"] <= c["point"] <= c["ci_upper"], key
    c = out["team_totals"]["accuracy_team_points"]
    assert c["ci_lower"] <= c["point"] <= c["ci_upper"]
    out["all_leg_quantities_computed"] = True
    return out


if __name__ == "__main__":
    result = run()
    path = Path(__file__).with_name("amendment2_toy_slate_results.json")
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("toy-slate verification: all leg quantities computed;",
          "results written to", path.name)
