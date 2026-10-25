"""NBA v2 matchup challenger backtest (#2447).

Protocol (declared before any run):
  dev        = SBR seasons 2011..2019 (2011-12 .. 2019-20), walk-forward,
               scored on 2013..2019 (2011-12 is rating warm-up)
  validation = 2020 (2020-21): used ONCE per attempt to choose
  final test = 2021 (2021-22): LOCKED, run once with the chosen attempt
               (`--final` flag; refuses unless chosen.json exists)
Selection rule: lowest mean validation (logloss_model - logloss_close) over
moneyline, spread, total. Max 8 attempts, all logged in attempts.jsonl.

Sources (free, git-cloned):
  odds/scores: flancast90/sportsbookreview-scraper data/nba_archive_10Y.json
  player box scores: NocturneBear/NBA-Data-2010-2024 @ a5f108b5
Engine: sportsedge/nba_v2_matchup_challenger.py (not wired to production).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from metrics import EV_THRESHOLD, american_to_decimal, git_blob_sha1, market_report, no_vig  # noqa: E402
import research_nba_elo_sbr_dateonly_screen as ELO  # noqa: E402
from sportsedge import nba_v2_matchup_challenger as M  # noqa: E402

DEV_SCORED = range(2013, 2020)
VALID, TEST = 2020, 2021
DEC_110 = american_to_decimal(-110)
BOX_COMMIT = "a5f108b5b1f08074d78b9e8e901926a9ce4c06c5"

NAME2TRI = {
    "Hawks": ["ATL"], "Celtics": ["BOS"], "Nets": ["BKN", "NJN"], "Hornets": ["CHA", "NOH"],
    "Bulls": ["CHI"], "Cavaliers": ["CLE"], "Mavericks": ["DAL"], "Nuggets": ["DEN"],
    "Pistons": ["DET"], "Warriors": ["GSW"], "Rockets": ["HOU"], "Pacers": ["IND"],
    "Clippers": ["LAC"], "Lakers": ["LAL"], "Grizzlies": ["MEM"], "Heat": ["MIA"],
    "Bucks": ["MIL"], "Timberwolves": ["MIN"], "Pelicans": ["NOP", "NOH"], "Knicks": ["NYK"],
    "Thunder": ["OKC"], "Magic": ["ORL"], "Seventysixers": ["PHI"], "Suns": ["PHX"],
    "Trailblazers": ["POR"], "Kings": ["SAC"], "Spurs": ["SAS"], "Raptors": ["TOR"],
    "Jazz": ["UTA"], "Wizards": ["WAS"],
}


def _mins(s):
    if not s:
        return 0.0
    if ":" in s:
        a, b = s.split(":")[:2]
        return float(a) + float(b) / 60.0
    return float(s)


def ordinal_from_int(d):
    return date(d // 10000, d // 100 % 100, d % 100).toordinal()


def load_box(box_dir: Path):
    games = {}
    for f in ("regular_season_totals_2010_2024.csv", "play_off_totals_2010_2024.csv"):
        for x in csv.DictReader(open(box_dir / f, newline="")):
            gid = x["GAME_ID"].lstrip("0")
            tri = x["TEAM_ABBREVIATION"]
            g = games.setdefault(gid, {"gid": gid, "day": M.day_ordinal(x["GAME_DATE"]),
                                       "season": int(x["SEASON_YEAR"][:4]), "t": {}})
            poss = float(x["FGA"]) - float(x["OREB"]) + float(x["TOV"] or 0) + 0.44 * float(x["FTA"])
            g["t"][tri] = {"pts": float(x["PTS"]), "poss": poss, "home": " vs. " in x["MATCHUP"],
                           "players": [], "inactive": set(), "active": set()}
    files = ["regular_season_box_scores_2010_2024_part_%d.csv" % i for i in (1, 2, 3)]
    files.append("play_off_box_scores_2010_2024.csv")
    for f in files:
        for x in csv.DictReader(open(box_dir / f, newline="")):
            g = games.get(x["gameId"].lstrip("0"))
            if not g or x["teamTricode"] not in g["t"]:
                continue
            t = g["t"][x["teamTricode"]]
            pid = x["personId"]
            com = (x["comment"] or "").strip()
            if com.startswith(M.INACTIVE_PREFIXES):
                t["inactive"].add(pid)
                continue
            t["active"].add(pid)
            mins = _mins(x["minutes"])
            pm = float(x["plusMinusPoints"] or 0)
            t["players"].append((pid, mins, pm))
    out = []
    for g in games.values():
        if len(g["t"]) != 2:
            continue
        h = [k for k, v in g["t"].items() if v["home"]]
        if len(h) != 1:
            continue
        a = [k for k in g["t"] if k != h[0]][0]
        g["home"], g["away"] = h[0], a
        out.append(g)
    return sorted(out, key=lambda z: (z["day"], z["gid"]))


def run_engine(box):
    """Returns {(day, home_tri): features}. Features for a date are computed
    before ANY game of that date updates the engine."""
    eng = M.MatchupEngine()
    feats = {}
    i = 0
    while i < len(box):
        j = i
        while j < len(box) and box[j]["day"] == box[i]["day"]:
            j += 1
        for g in box[i:j]:
            th, ta = g["t"][g["home"]], g["t"][g["away"]]
            f = eng.features({"day": g["day"], "season": g["season"], "home": g["home"], "away": g["away"],
                              "inactive_home": th["inactive"], "inactive_away": ta["inactive"],
                              "active_home": th["active"], "active_away": ta["active"]})
            f["_gid"] = g["gid"]
            feats[(g["day"], g["home"])] = f
        for g in box[i:j]:
            th, ta = g["t"][g["home"]], g["t"][g["away"]]
            eng.update({"day": g["day"], "season": g["season"], "home": g["home"], "away": g["away"],
                        "poss_home": th["poss"], "poss_away": ta["poss"], "pts_home": th["pts"],
                        "pts_away": ta["pts"], "players_home": th["players"], "players_away": ta["players"]})
        i = j
    return feats


def load_sbr(path):
    raw_bytes = path.read_bytes()
    sha = git_blob_sha1(raw_bytes)
    if sha != ELO.SOURCE_BLOB_SHA1:
        raise SystemExit("SOURCE_BLOB_MISMATCH")
    raw = json.loads(raw_bytes)
    rows = ELO.normalize(raw)
    extra = {}
    for x in raw:
        h = ELO.ALIASES.get(str(x.get("home_team") or ""), str(x.get("home_team") or ""))
        a = ELO.ALIASES.get(str(x.get("away_team") or ""), str(x.get("away_team") or ""))
        try:
            extra[(int(float(x["date"])), h, a)] = x
        except (TypeError, ValueError, KeyError):
            pass
    for g in rows:
        x = extra[(g["day"], g["home"], g["away"])]
        g["open_spread"] = ELO._number(x.get("home_open_spread"))
        g["close_total"] = ELO._number(x.get("close_over_under"))
        g["open_total"] = ELO._number(x.get("open_over_under"))
    return rows, sha


def join(rows, feats):
    n_ok = 0
    for g in rows:
        g["f"] = None
        d = ordinal_from_int(g["day"])
        for tri in NAME2TRI.get(g["home"], []):
            if (d, tri) in feats:
                g["f"] = feats[(d, tri)]; g["ord"] = d
                n_ok += 1
                break
    return n_ok


# ---------------- attempts ----------------
ATTEMPTS = {
    "A1_matchup": dict(spec="A1_matchup", anchor=False),
    "A2_matchup_rest": dict(spec="A2_matchup_rest", anchor=False),
    "A3_full": dict(spec="A3_full", anchor=False),
    # A4: same matchup inputs, plus the OPENING line (pregame-known, earlier
    # than the close), i.e. learns where matchup inputs disagree with open.
    "A4_full_open_anchor": dict(spec="A3_full", anchor=True),
    # A5: A4 with ridge 200.
    "A5_full_open_anchor_ridge": dict(spec="A3_full", anchor=True, ridge=200.0),
}


def design(g, cols, anchor, kind):
    f = g["f"]
    x = [f[c] for c in cols]
    if anchor:
        x.append(-g["open_spread"] if kind == "m" else g["open_total"])
    return x


def usable(g, anchor):
    if g["f"] is None or g["f"]["rating_weight"] < 8:
        return False
    if anchor and (g["open_spread"] is None or abs(g["open_spread"]) > 25
                   or g["open_total"] is None or not 170 <= g["open_total"] <= 270):
        return False
    return True


def score_season(rows, season, att):
    mcols, tcols = M.SPECS[att["spec"]]
    anchor, ridge = att["anchor"], att.get("ridge", 1.0)
    train = [g for g in rows if 2011 <= g["season"] < season and usable(g, anchor)]
    test = [g for g in rows if g["season"] == season and usable(g, anchor)]
    bm, sdm = M.fit_ols([design(g, mcols, anchor, "m") for g in train], [g["hp"] - g["ap"] for g in train], ridge)
    bt, sdt = M.fit_ols([design(g, tcols, anchor, "t") for g in train], [g["hp"] + g["ap"] for g in train], ridge)
    out = defaultdict(list)
    for g in test:
        am, at = g["hp"] - g["ap"], g["hp"] + g["ap"]
        pm = M.predict(bm, design(g, mcols, anchor, "m"))
        pt = M.predict(bt, design(g, tcols, anchor, "t"))
        if g["home_ml"] is not None and g["away_ml"] is not None and am != 0:
            pc, _ = no_vig(g["home_ml"], g["away_ml"])
            p = M.phi(pm / sdm)
            y = int(am > 0)
            r = {"p_model": p, "p_close": pc, "y": y, "bet_ev": None}
            evh = p * american_to_decimal(g["home_ml"]) - 1
            eva = (1 - p) * american_to_decimal(g["away_ml"]) - 1
            if max(evh, eva) >= EV_THRESHOLD:
                hs = evh >= eva
                r.update(bet_ev=max(evh, eva), bet_dec=american_to_decimal(g["home_ml"] if hs else g["away_ml"]),
                         bet_won=y if hs else 1 - y, clv=None)
            out["moneyline"].append(r)
        if g["spread"] is not None and am + g["spread"] != 0:
            r = {"p_model": M.phi((pm + g["spread"]) / sdm), "p_close": 0.5,
                 "y": int(am + g["spread"] > 0), "bet_ev": None}
            osp = g["open_spread"]
            if osp is not None and abs(osp) <= 25:
                po = M.phi((pm + osp) / sdm)
                ev_h, ev_a = po * DEC_110 - 1, (1 - po) * DEC_110 - 1
                if max(ev_h, ev_a) >= EV_THRESHOLD:
                    hs = ev_h >= ev_a
                    mm = am + osp
                    pmk = M.phi((-g["spread"] + osp) / sdm)
                    r.update(bet_ev=max(ev_h, ev_a), bet_dec=DEC_110,
                             bet_won=None if mm == 0 else int((mm > 0) == hs),
                             clv=(pmk - 0.5) if hs else (0.5 - pmk))
            out["spread"].append(r)
        ct = g["close_total"]
        if ct is not None and 170 <= ct <= 270 and at != ct:
            r = {"p_model": 1 - M.phi((ct - pt) / sdt), "p_close": 0.5, "y": int(at > ct), "bet_ev": None}
            ot = g["open_total"]
            if ot is not None and 170 <= ot <= 270:
                po = 1 - M.phi((ot - pt) / sdt)
                ev_o, ev_u = po * DEC_110 - 1, (1 - po) * DEC_110 - 1
                if max(ev_o, ev_u) >= EV_THRESHOLD:
                    over = ev_o >= ev_u
                    pmk = 1 - M.phi((ot - ct) / sdt)
                    r.update(bet_ev=max(ev_o, ev_u), bet_dec=DEC_110,
                             bet_won=None if at == ot else int((at > ot) == over),
                             clv=(pmk - 0.5) if over else (0.5 - pmk))
            out["total"].append(r)
    return out, {"margin_beta": [round(b, 4) for b in bm], "margin_sd": round(sdm, 3),
                 "total_beta": [round(b, 4) for b in bt], "total_sd": round(sdt, 3),
                 "n_train": len(train), "margin_cols": mcols + (["-open_spread"] if anchor else []),
                 "total_cols": tcols + (["open_total"] if anchor else [])}


def slim(rep):
    keys = ("n", "verdict", "brier_model", "brier_close_novig", "logloss_model", "logloss_close_novig",
            "bets_ev_ge_2pct", "roi_at_logged_price", "mean_clv")
    o = {k: (round(rep[k], 5) if isinstance(rep.get(k), float) else rep.get(k)) for k in keys}
    if "calibration_model" in rep:
        o["cal_slope"] = round(rep["calibration_model"]["slope"], 3)
        o["cal_ece"] = round(rep["calibration_model"]["ece"], 4)
    return o


def leakage_check(rows, box):
    """(1) every rating input day < game day; (2) scramble all same-date
    outcomes for sampled dates, re-run engine, features must match."""
    viol = sum(1 for g in rows if g["f"] is not None and g["f"]["max_rating_input_day"] >= g["ord"])
    days = sorted({g["day"] for g in box})
    ref = run_engine(box)
    checked = bad = 0
    for d in days[300::400]:
        sub = []
        for g in box:
            if g["day"] > d:
                continue
            if g["day"] == d:
                g = json.loads(json.dumps(g, default=list))
                for t in g["t"].values():
                    t["pts"] = 0.0 if t["home"] else 300.0
                    t["players"] = [(p, m, 99.0) for p, m, _ in t["players"]]
                    t["inactive"] = set(t["inactive"]); t["active"] = set(t["active"])
            sub.append(g)
        f2 = run_engine(sub)
        for k, v in f2.items():
            if k[0] == d:
                checked += 1
                bad += any(abs(v[c] - ref[k][c]) > 1e-9 for c in v if not c.startswith("_"))
    return {"rating_input_date_violations": viol, "scramble_checked": checked, "scramble_violations": bad,
            "availability_rule": "same-day inputs limited to DND/NWT inactive codes and dressed list; "
                                 "DNP-coach/in-game injury treated as available"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--box-dir", type=Path, required=True)
    ap.add_argument("--attempt", choices=list(ATTEMPTS))
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    rows, sha = load_sbr(a.source)
    box = load_box(a.box_dir)
    feats = run_engine(box)
    joined = join(rows, feats)
    log = HERE / "attempts_full.jsonl"
    if a.final:
        chosen = json.loads((HERE / "chosen.json").read_text())
        if (HERE / "final_test.json").exists():
            raise SystemExit("FINAL_TEST_ALREADY_RUN")
        att = ATTEMPTS[chosen["attempt"]]
        out, fit = score_season(rows, TEST, att)
        leak = leakage_check(rows, box)
        if leak["rating_input_date_violations"] or leak["scramble_violations"]:
            raise SystemExit(f"LEAKAGE {leak}")
        res = {"attempt": chosen["attempt"], "season": TEST, "fit": fit, "leakage_check": leak,
               "sbr_sha": sha, "box_commit": BOX_COMMIT, "joined_games": joined, "sbr_games": len(rows),
               "markets": {mk: market_report(out[mk], clv_unit="see v1 README") for mk in ("moneyline", "spread", "total")}}
        (HERE / "final_test.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
        print(json.dumps({k: slim(v) for k, v in res["markets"].items()}, indent=1))
        return
    att = ATTEMPTS[a.attempt]
    dev = defaultdict(list)
    for s in DEV_SCORED:
        o, _ = score_season(rows, s, att)
        for mk, v in o.items():
            dev[mk] += v
    val, fit = score_season(rows, VALID, att)
    entry = {"attempt": a.attempt, "config": att, "joined_games": joined, "sbr_games": len(rows),
             "dev_2013_2019": {mk: slim(market_report(dev[mk], clv_unit="")) for mk in dev},
             "validation_2020_21": {mk: slim(market_report(val[mk], clv_unit="")) for mk in val},
             "validation_fit": fit}
    with open(log, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(json.dumps(entry, indent=1))


if __name__ == "__main__":
    main()
