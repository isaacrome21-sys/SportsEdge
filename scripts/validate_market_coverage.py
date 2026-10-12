#!/usr/bin/env python3
"""Harness validation for Phase 7 market-coverage builds (SportsEdge).

Validates each newly built market family chronologically out-of-sample:
candidate (production pricer math, train-restricted) vs a naive baseline
(train base rates). No market baseline exists anywhere (no Odds API by
Isaac's choice), so the best achievable verdict is CONDITIONAL_PASS.

Run with cwd anywhere; the harness is loaded from
~/workspace/sportsedge-backtest WITHOUT copying it into the branch.
Network: free ESPN scoreboard + MLB StatsAPI only, cached under
/tmp/coverage_backtest_cache so reruns never re-hit the network.

Outputs: verdict table on stdout + JSON at /tmp/coverage_harness_verdicts.json.
Research only.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
import types
from datetime import datetime, timedelta, timezone

WORKTREE = "/home/hatch/workspace/sportsedge-coverage"
HARNESS = "/home/hatch/workspace/sportsedge-backtest/sportsedge/backtest"
CACHE = "/tmp/coverage_backtest_cache"

# --- load harness as hb.* (no copy into the branch) ---------------------------
_hb = types.ModuleType("hb")
_hb.__path__ = [HARNESS]
sys.modules["hb"] = _hb
for _name in ("metrics", "splits", "outcomes", "runner", "report"):
    _spec = importlib.util.spec_from_file_location(
        f"hb.{_name}", f"{HARNESS}/{_name}.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"hb.{_name}"] = _mod
    _spec.loader.exec_module(_mod)
from hb import outcomes, report, runner, splits  # noqa: E402

# --- load coverage pricer math (standalone module, no relative imports) ------
sys.path.insert(0, WORKTREE)
_spec = importlib.util.spec_from_file_location(
    "coverage_mod", f"{WORKTREE}/sportsedge/market_coverage.py")
cov = importlib.util.module_from_spec(_spec)
sys.modules["coverage_mod"] = cov
_spec.loader.exec_module(cov)

# --- load F5 distribution math as se.* ----------------------------------------
_se = types.ModuleType("se")
_se.__path__ = [f"{WORKTREE}/sportsedge"]
sys.modules["se"] = _se
for _name in ("source_lineage", "mlb_empirical_bayes", "f5_distribution"):
    _spec = importlib.util.spec_from_file_location(
        f"se.{_name}", f"{WORKTREE}/sportsedge/{_name}.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"se.{_name}"] = _mod
    _spec.loader.exec_module(_mod)
from se import f5_distribution as f5d  # noqa: E402

PRIORS = {"NFL": (22.0, 13.5, 13.7, 1.5),
          "CFB": (28.0, 18.5, 19.0, 2.5),
          "MLB": (4.4, None, None, 0.20)}


def _clock(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return d.astimezone(timezone.utc)


def train_means(sport, home_team, away_team, kickoff_dt, train):
    """Train-restricted score means mirroring free_models' formula (no lookahead)."""
    base, _, _, hfa = PRIORS[sport]
    cap = 0.7 if sport == "MLB" else 3.0

    def rating(team):
        games = [f for f in train
                 if f["kickoff_dt"] < kickoff_dt
                 and team in (f["home_team"], f["away_team"])]
        games.sort(key=lambda f: f["kickoff_dt"], reverse=True)
        games = games[:5]
        if not games:
            return 0.0
        margins = [(f["home_score"] - f["away_score"])
                   if f["home_team"] == team
                   else (f["away_score"] - f["home_score"]) for f in games]
        return max(-cap, min(cap, sum(margins) / len(margins) * 0.12))

    return (base + hfa / 2 + rating(home_team),
            base - hfa / 2 + rating(away_team))


# --- fixture builders ---------------------------------------------------------

def _qscores(comp):
    vals = {}
    for ls in comp.get("linescores") or []:
        try:
            vals[int(ls.get("period"))] = float(ls.get("value"))
        except (TypeError, ValueError):
            continue
    if not all(p in vals for p in (1, 2, 3, 4)):
        return None
    return [vals[p] for p in (1, 2, 3, 4)]


def football_fixtures(sport, start_date, end_date):
    """Fetch ESPN scoreboard day-by-day (the documented reliable path)."""
    events = []
    seen = set()
    day = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    while day <= end:
        for ev in outcomes.fetch_football_scoreboard(
                sport, dates=day.strftime("%Y%m%d"), cache_dir=CACHE):
            eid = str(ev.get("id") or "")
            if eid and eid not in seen:
                seen.add(eid)
                events.append(ev)
        day += timedelta(days=1)
    out = []
    for ev in events:
        if ((ev.get("status") or {}).get("type") or {}).get("completed") is not True:
            continue
        comp = (ev.get("competitions") or [{}])[0]
        comps = comp.get("competitors") or []
        home = next((c for c in comps if c.get("homeAway") == "home"), None)
        away = next((c for c in comps if c.get("homeAway") == "away"), None)
        if home is None or away is None:
            continue
        hq, aq = _qscores(home), _qscores(away)
        if hq is None or aq is None:
            continue
        try:
            hs = int(float(home.get("score")))
            aws = int(float(away.get("score")))
        except (TypeError, ValueError):
            continue
        kickoff = _clock(ev.get("date"))
        out.append({
            "fixture_id": f"{sport}-2024-{ev.get('id')}",
            "kickoff": kickoff.isoformat(),
            "as_of": (kickoff - timedelta(hours=1)).isoformat(),
            "kickoff_dt": kickoff,
            "sport": sport.upper(),
            "home_team": str((home.get("team") or {}).get("displayName") or ""),
            "away_team": str((away.get("team") or {}).get("displayName") or ""),
            "home_score": hs, "away_score": aws,
            "home_q": hq, "away_q": aq,
        })
    out.sort(key=lambda f: f["kickoff_dt"])
    return out


def _inning_runs(game):
    """Return (end-of-9 home/away, f5 home/away or None) from linescore innings."""
    innings = ((game.get("linescore") or {}).get("innings")) or []
    by_num = {}
    for inn in innings:
        try:
            num = int(inn.get("num"))
        except (TypeError, ValueError):
            continue
        by_num[num] = inn
    h9 = a9 = 0
    for num in range(1, 10):
        inn = by_num.get(num)
        if inn is None:
            continue
        try:
            a9 += int((inn.get("away") or {}).get("runs") or 0)
            h9 += int((inn.get("home") or {}).get("runs") or 0)
        except (TypeError, ValueError):
            continue
    f5 = None
    if all(n in by_num for n in range(1, 6)):
        try:
            ah = sum(int((by_num[n].get("away") or {}).get("runs") or 0)
                     for n in range(1, 6))
            hh = sum(int((by_num[n].get("home") or {}).get("runs") or 0)
                     for n in range(1, 6))
            f5 = (hh, ah)
        except (TypeError, ValueError):
            f5 = None
    return (h9, a9), f5


def mlb_fixtures():
    months = [("2024-04-01", "2024-04-30"), ("2024-05-01", "2024-05-31"),
              ("2024-06-01", "2024-06-30"), ("2024-07-01", "2024-07-31"),
              ("2024-08-01", "2024-08-31"), ("2024-09-01", "2024-09-30")]
    out = []
    seen_pk = set()
    for start, end in months:
        dates = outcomes.fetch_mlb_schedule(start, end, cache_dir=CACHE)
        for day in dates:
            if not isinstance(day, dict):
                continue
            for game in day.get("games") or []:
                if not isinstance(game, dict):
                    continue
                if str(((game.get("status") or {}).get("detailedState") or "")) != "Final":
                    continue
                pk = game.get("gamePk")
                if pk in seen_pk:
                    continue
                seen_pk.add(pk)
                teams = game.get("teams") or {}
                home = teams.get("home") or {}
                away = teams.get("away") or {}
                try:
                    hs = int(home.get("score"))
                    aws = int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                (h9, a9), f5 = _inning_runs(game)
                kickoff = _clock(game.get("gameDate"))
                out.append({
                    "fixture_id": f"mlb-2024-{game.get('gamePk')}",
                    "kickoff": kickoff.isoformat(),
                    "as_of": (kickoff - timedelta(hours=1)).isoformat(),
                    "kickoff_dt": kickoff,
                    "sport": "MLB",
                    "home_team": str(((home.get("team") or {}).get("name")) or ""),
                    "away_team": str(((away.get("team") or {}).get("name")) or ""),
                    "home_score": hs, "away_score": aws,
                    "home_9": h9, "away_9": a9, "f5": f5,
                })
    out.sort(key=lambda f: f["kickoff_dt"])
    return out

# --- panels -------------------------------------------------------------------

NFL_Q_TOTAL_LINES = [7.5, 9.5, 11.5]
NFL_Q_SPREAD_LINES = [-1.5, -0.5, 0.5, 1.5]
NFL_Q_TT_LINES = [3.5, 5.5, 7.5]
NFL_ALT_SPREAD = [-13.5, -10.5, -6.5, -3.5, 3.5, 6.5, 10.5, 13.5]
NFL_ALT_TOTAL = [37.5, 41.5, 44.5, 47.5, 51.5]
MLB_ALT_TOTAL = [6.5, 7.5, 8.5, 9.5, 10.5]
CFB_Q_TOTAL_LINES = [10.5, 13.5, 16.5]
CFB_Q_SPREAD_LINES = [-6.5, -3.5, -0.5, 0.5, 3.5, 6.5]
CFB_Q_TT_LINES = [7.5, 10.5, 13.5]
CFB_ALT_SPREAD = [-20.5, -13.5, -6.5, 6.5, 13.5, 20.5]
CFB_ALT_TOTAL = [44.5, 51.5, 58.5, 65.5]

MARGIN_BAND_DEFS = [(b[0], b[1], b[2], b[3]) for b in cov.MARGIN_BANDS]


def _naive_table(train, settle):
    """Train base rate per (market, selection, line); outcomes graded 0/0.5/1."""
    sums, counts = {}, {}
    for f in train:
        for market, selection, line in _panel_keys(f):
            try:
                y = settle(f, market, selection, line)
            except Exception:  # noqa: BLE001 - unsettleable keys skipped
                continue
            key = (market, selection, line)
            sums[key] = sums.get(key, 0.0) + y
            counts[key] = counts.get(key, 0) + 1
    return {k: sums[k] / counts[k] for k in sums}


_PANELS = {}


def panel(name):
    def deco(fn):
        _PANELS[name] = fn
        return fn
    return deco


@panel("nfl_q_totals")
def panel_nfl_q_totals(f):
    keys = []
    for q in (1, 2, 3, 4):
        for line in NFL_Q_TOTAL_LINES:
            keys += [(f"TOTAL_{q}Q", "OVER", line), (f"TOTAL_{q}Q", "UNDER", line)]
    return keys


@panel("nfl_q_spreads")
def panel_nfl_q_spreads(f):
    keys = []
    for q in (1, 2, 3, 4):
        for line in NFL_Q_SPREAD_LINES:
            keys += [(f"SPREAD_{q}Q", "HOME", line), (f"SPREAD_{q}Q", "AWAY", line)]
    return keys


@panel("nfl_q_ml")
def panel_nfl_q_ml(f):
    keys = []
    for q in (1, 2, 3, 4):
        keys += [(f"ML_{q}Q", "HOME", None), (f"ML_{q}Q", "AWAY", None)]
    return keys


@panel("nfl_q_team_totals")
def panel_nfl_q_team_totals(f):
    keys = []
    for q in (1, 2, 3, 4):
        for line in NFL_Q_TT_LINES:
            for ts in ("HOME_OVER", "HOME_UNDER", "AWAY_OVER", "AWAY_UNDER"):
                keys.append((f"TEAM_TOTAL_{q}Q", ts, line))
    return keys


@panel("nfl_quarters")
def panel_nfl_quarters(f):
    return (panel_nfl_q_totals(f) + panel_nfl_q_spreads(f)
            + panel_nfl_q_ml(f) + panel_nfl_q_team_totals(f))


@panel("nfl_margin_bands")
def panel_nfl_margin(f):
    return [("MARGIN_BAND", b[0], None) for b in MARGIN_BAND_DEFS]


@panel("nfl_alt_spreads")
def panel_nfl_alt_spreads(f):
    keys = []
    for line in NFL_ALT_SPREAD:
        keys += [("SPREAD", "HOME", line), ("SPREAD", "AWAY", line)]
    return keys


@panel("nfl_alt_totals")
def panel_nfl_alt_totals(f):
    keys = []
    for line in NFL_ALT_TOTAL:
        keys += [("TOTAL", "OVER", line), ("TOTAL", "UNDER", line)]
    return keys


@panel("nfl_alternates")
def panel_nfl_alt(f):
    return panel_nfl_alt_spreads(f) + panel_nfl_alt_totals(f)


@panel("mlb_3way")
def panel_mlb_3way(f):
    return [("ML_3WAY", s, None) for s in ("HOME", "AWAY", "TIE")]


@panel("mlb_alt_totals")
def panel_mlb_alt(f):
    keys = []
    for line in MLB_ALT_TOTAL:
        keys += [("TOTAL", "OVER", line), ("TOTAL", "UNDER", line)]
    return keys


@panel("mlb_f5_moneyline")
def panel_mlb_f5(f):
    return [("F5_MONEYLINE", s, None) for s in ("HOME", "AWAY")]


@panel("cfb_q_totals")
def panel_cfb_q_totals(f):
    keys = []
    for q in (1, 2, 3, 4):
        for line in CFB_Q_TOTAL_LINES:
            keys += [(f"TOTAL_{q}Q", "OVER", line), (f"TOTAL_{q}Q", "UNDER", line)]
    return keys


@panel("cfb_q_spreads")
def panel_cfb_q_spreads(f):
    keys = []
    for q in (1, 2, 3, 4):
        for line in CFB_Q_SPREAD_LINES:
            keys += [(f"SPREAD_{q}Q", "HOME", line), (f"SPREAD_{q}Q", "AWAY", line)]
    return keys


@panel("cfb_q_ml")
def panel_cfb_q_ml(f):
    keys = []
    for q in (1, 2, 3, 4):
        keys += [(f"ML_{q}Q", "HOME", None), (f"ML_{q}Q", "AWAY", None)]
    return keys


@panel("cfb_q_team_totals")
def panel_cfb_q_team_totals(f):
    keys = []
    for q in (1, 2, 3, 4):
        for line in CFB_Q_TT_LINES:
            for ts in ("HOME_OVER", "HOME_UNDER", "AWAY_OVER", "AWAY_UNDER"):
                keys.append((f"TEAM_TOTAL_{q}Q", ts, line))
    return keys


@panel("cfb_quarters")
def panel_cfb_quarters(f):
    return (panel_cfb_q_totals(f) + panel_cfb_q_spreads(f)
            + panel_cfb_q_ml(f) + panel_cfb_q_team_totals(f))


@panel("cfb_margin_bands")
def panel_cfb_margin(f):
    return [("MARGIN_BAND", b[0], None) for b in MARGIN_BAND_DEFS]


@panel("cfb_alt_spreads")
def panel_cfb_alt_spreads(f):
    keys = []
    for line in CFB_ALT_SPREAD:
        keys += [("SPREAD", "HOME", line), ("SPREAD", "AWAY", line)]
    return keys


@panel("cfb_alt_totals")
def panel_cfb_alt_totals(f):
    keys = []
    for line in CFB_ALT_TOTAL:
        keys += [("TOTAL", "OVER", line), ("TOTAL", "UNDER", line)]
    return keys


@panel("cfb_alternates")
def panel_cfb_alt(f):
    return panel_cfb_alt_spreads(f) + panel_cfb_alt_totals(f)


def _panel_keys(fixture):
    return _PANELS[_ACTIVE_PANEL](fixture)


# --- candidate pricers (exact production math, train-restricted) --------------

def _candidate_prob(sport, fixture, market, selection, line, home_mean, away_mean,
                    _pmf_cache=None):
    if market == "ML_3WAY":
        ph, pa, pt = cov._mlb_3way(home_mean, away_mean)
        return {"HOME": ph, "AWAY": pa, "TIE": pt}[selection]
    if market == "MARGIN_BAND":
        band = next(b for b in MARGIN_BAND_DEFS if b[0] == selection)
        _, _, sd_margin, _ = PRIORS[sport]
        prob, _tie = cov._margin_band_prob(home_mean, away_mean, sd_margin,
                                           band[1], band[2], band[3])
        return prob
    q = cov.quarter_of(market)
    if q is not None:
        hq, aq, sdt_q, sdm_q = cov._quarter_params(sport, home_mean, away_mean)
        if market.startswith("SPREAD_"):
            win, _ = cov._normal_win_push("SPREAD", selection, line, hq, aq,
                                          sdt_q, sdm_q)
            return win
        if market.startswith("TOTAL_"):
            win, _ = cov._normal_win_push("TOTAL", selection, line, hq, aq,
                                          sdt_q, sdm_q)
            return win
        if market.startswith("ML_"):
            win, _ = cov._quarter_ml(hq, aq, sdm_q, selection)
            return win
        team_tok, ou = selection.rsplit("_", 1)
        team_mean = hq if team_tok == "HOME" else aq
        sd_team = sdt_q / math.sqrt(2.0)
        over = 1 - cov.cdf(line, team_mean, sd_team)
        under = cov.cdf(line, team_mean, sd_team)
        return over if ou == "OVER" else under
    # alternates on the base distribution
    if market in ("SPREAD", "TOTAL"):
        if sport == "MLB":
            if _pmf_cache is None:
                _pmf_cache = {}
            pkey = (round(home_mean, 6), round(away_mean, 6))
            if pkey not in _pmf_cache:
                _pmf_cache[pkey] = (cov.poisson(home_mean),
                                    cov.poisson(away_mean))
            a, b = _pmf_cache[pkey]
            win = 0.0
            for h, ph in enumerate(a):
                for aw, pa in enumerate(b):
                    if market == "TOTAL":
                        score = h + aw
                        target = (score - line if selection == "OVER"
                                  else line - score)
                    else:
                        score = (h - aw if selection == "HOME" else aw - h)
                        target = score + line
                    if target > 1e-9:
                        win += ph * pa
            return win
        _, sd_total, sd_margin, _ = PRIORS[sport]
        win, _ = cov._normal_win_push(market, selection, line, home_mean,
                                      away_mean, sd_total, sd_margin)
        return win
    raise ValueError("PANEL_MARKET_UNHANDLED:" + market)


def _f5_split_index(train):
    """Per-split F5 index. The split invariant (all train kickoffs < all test
    kickoffs) makes every train game strictly prior: no per-fixture filtering."""
    by_team = {}
    halves = []
    for f in train:
        f5 = f.get("f5")
        if f5 is None:
            continue
        hh, ah = f5
        halves.append(hh)
        halves.append(ah)
        by_team.setdefault(f["home_team"], []).append((hh, ah))
        by_team.setdefault(f["away_team"], []).append((ah, hh))
    return by_team, halves


def _f5_candidate_prob(fixture, selection, f5_idx):
    """Empirical F5 distribution from strictly-prior train F5 scores."""
    by_team, halves = f5_idx
    if len(halves) < 200:
        return None
    a_rows = by_team.get(fixture["away_team"], [])[-30:]
    h_rows = by_team.get(fixture["home_team"], [])[-30:]
    if len(a_rows) < 10 or len(h_rows) < 10:
        return None
    counts = {}
    for v in halves:
        counts[v] = counts.get(v, 0) + 1
    features = {
        "away_f5_runs_for": [r[0] for r in a_rows],
        "away_f5_runs_against": [r[1] for r in a_rows],
        "home_f5_runs_for": [r[0] for r in h_rows],
        "home_f5_runs_against": [r[1] for r in h_rows],
        "league_f5_pmf": {str(k): v / len(halves) for k, v in sorted(counts.items())},
        "league_prior_halves": len(halves),
        "league_prior_strength": 30,
    }
    dist = f5d.build_f5_distribution(features, league_prior_strength=30)
    readout = f5d.read_f5_probability(dist, market="F5_MONEYLINE", side=selection)
    return readout.probability


# --- settlement ----------------------------------------------------------------

def _settle(fixture, market, selection, line):
    if market == "ML_3WAY":
        h9, a9 = fixture["home_9"], fixture["away_9"]
        want = {"HOME": h9 > a9, "AWAY": a9 > h9, "TIE": h9 == a9}[selection]
        return 1.0 if want else 0.0
    if market == "MARGIN_BAND":
        band = next(b for b in MARGIN_BAND_DEFS if b[0] == selection)
        margin = (fixture["home_score"] - fixture["away_score"]
                  if band[1] == "HOME"
                  else fixture["away_score"] - fixture["home_score"])
        if margin == 0:
            return 0.5
        if margin < 0:
            return 0.0
        lo, hi = band[2], band[3]
        return 1.0 if (margin >= lo and (hi is None or margin <= hi)) else 0.0
    q = cov.quarter_of(market)
    if q is not None:
        hq = fixture["home_q"][q - 1]
        aq = fixture["away_q"][q - 1]
        if market.startswith("SPREAD_"):
            m = (hq - aq + line) if selection == "HOME" else (aq - hq + line)
            return 1.0 if m > 0 else (0.0 if m < 0 else 0.5)
        if market.startswith("TOTAL_"):
            t = hq + aq
            over = t > line if selection == "OVER" else t < line
            if t == line:
                return 0.5
            return 1.0 if over else 0.0
        if market.startswith("ML_"):
            if hq == aq:
                return 0.5
            win = (hq > aq) if selection == "HOME" else (aq > hq)
            return 1.0 if win else 0.0
        team_tok, ou = selection.rsplit("_", 1)
        score = hq if team_tok == "HOME" else aq
        if score == line:
            return 0.5
        over = score > line
        return 1.0 if (over == (ou == "OVER")) else 0.0
    if market == "F5_MONEYLINE":
        hh, ah = fixture["f5"]
        if hh == ah:
            return 0.5
        win = (hh > ah) if selection == "HOME" else (ah > hh)
        return 1.0 if win else 0.0
    # alternates: reuse the harness's own settlement on final scores
    game = {"home_score": fixture["home_score"],
            "away_score": fixture["away_score"]}
    return outcomes.settle_game(game, market, selection, line)


# --- run one family ------------------------------------------------------------

_ACTIVE_PANEL = None


def run_family(name, fixtures, *, min_train, test_size, sport, embargo_days=1,
               step=1):
    global _ACTIVE_PANEL
    _ACTIVE_PANEL = name
    spl = list(splits.walk_forward_splits(fixtures, min_train=min_train,
                                          test_size=test_size, step=step,
                                          embargo_days=embargo_days))
    naive_cache = {}
    f5_cache = {}
    pmf_cache = {}

    def price_fn(model, fixture, as_of, train):
        key = id(train)
        if key not in naive_cache:
            naive_cache[key] = _naive_table(train, _settle)
        table = naive_cache[key]
        if key not in f5_cache:
            f5_cache[key] = _f5_split_index(train)
        f5_idx = f5_cache[key]
        pmfs = pmf_cache.setdefault(key, {})
        preds = []
        if model == "candidate":
            hm, am = train_means(sport, fixture["home_team"],
                                 fixture["away_team"],
                                 fixture["kickoff_dt"], train)
            for market, selection, line in _panel_keys(fixture):
                if market == "F5_MONEYLINE":
                    if fixture.get("f5") is None:
                        continue  # unsettleable: no verified innings 1-5
                    p = _f5_candidate_prob(fixture, selection, f5_idx)
                    if p is None:
                        continue
                else:
                    p = _candidate_prob(sport, fixture, market, selection,
                                        line, hm, am, _pmf_cache=pmfs)
                preds.append({"market": market, "selection": selection,
                              "line": line, "model_p": p})
        else:
            for market, selection, line in _panel_keys(fixture):
                if market == "F5_MONEYLINE" and fixture.get("f5") is None:
                    continue  # unsettleable: no verified innings 1-5
                p = table.get((market, selection, line))
                if p is None:
                    continue
                preds.append({"market": market, "selection": selection,
                              "line": line, "model_p": p})
        return preds

    result = runner.run_backtest(fixtures=fixtures, splits=spl,
                                 models=["candidate", "naive"],
                                 price_fn=price_fn, settle_fn=_settle,
                                 market_baseline=None)
    comp = runner.compare_models(result)
    verdict = report.evaluate(candidate=comp["models"]["candidate"],
                              existing=comp["models"]["naive"],
                              baseline_status="MISSING")
    return {"family": name, "sport": sport,
            "n_splits": comp["n_splits"],
            "candidate": comp["models"]["candidate"],
            "naive": comp["models"]["naive"],
            "verdict": verdict["verdict"],
            "reasons": verdict["reasons"]}


def main():
    only = set(sys.argv[1:]) or None
    print("loading fixtures ...", flush=True)
    nfl = football_fixtures("nfl", "2024-09-05", "2025-01-06")
    cfb = football_fixtures("cfb", "2024-08-24", "2024-12-15")
    mlb = mlb_fixtures()
    print(f"fixtures: NFL={len(nfl)} CFB={len(cfb)} MLB={len(mlb)}", flush=True)
    families = [
        ("nfl_q_totals", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_q_spreads", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_q_ml", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_q_team_totals", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_margin_bands", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_alternates", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_alt_spreads", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("nfl_alt_totals", nfl, dict(min_train=100, test_size=24, sport="NFL")),
        ("mlb_3way", mlb, dict(min_train=400, test_size=60, sport="MLB",
                               embargo_days=0, step=60)),
        ("mlb_alt_totals", mlb, dict(min_train=400, test_size=60, sport="MLB",
                                     embargo_days=0, step=60)),
        ("mlb_f5_moneyline", mlb, dict(min_train=400, test_size=60, sport="MLB",
                                       embargo_days=0, step=60)),
        ("cfb_q_totals", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_q_spreads", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_q_ml", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_q_team_totals", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_margin_bands", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_alternates", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_alt_spreads", cfb, dict(min_train=150, test_size=40, sport="CFB")),
        ("cfb_alt_totals", cfb, dict(min_train=150, test_size=40, sport="CFB")),
    ]
    verdicts = []
    out_path = ("/tmp/coverage_harness_verdicts_mlb.json" if only
                else "/tmp/coverage_harness_verdicts.json")
    for name, fixtures, kw in families:
        if only is not None and name not in only:
            continue
        print(f"running {name} ...", flush=True)
        v = run_family(name, fixtures, **kw)
        verdicts.append(v)
        with open(out_path, "w") as fh:
            json.dump({"research_only": True, "verdicts": verdicts}, fh,
                      indent=2, default=str)
        c, n = v["candidate"], v["naive"]
        print(f"  {name}: {v['verdict']} n={c.get('n')} "
              f"brier {c.get('brier', 0):.4f} vs naive {n.get('brier', 0):.4f} | "
              f"logloss {c.get('log_loss', 0):.4f} vs naive {n.get('log_loss', 0):.4f}")
        for r in v["reasons"]:
            print(f"    - {r}")
    print("wrote " + out_path)


if __name__ == "__main__":
    main()
