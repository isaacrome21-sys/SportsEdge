#!/usr/bin/env python3
"""
MLB_GAME_STATE_V1 - historical design screen (DESIGN.md section 5).

Implements the successor construction exactly as designed (PR #2887),
the V1-shaped state-information control, V1's Phase D baselines, and the
section 5.2 pass criteria. One configuration; every constant is declared
in BUILD_RECORD.md and in CONFIG below. No tuning: a changed constant is
a new version.

CONSTRUCTION (design 4.1/4.2), per game, strictly prior at all times:
  * PA run values from Retrosheet: v(PA) = runs during the PA
    + RE(state after) - RE(state before), with RE the run-expectancy
    matrix fitted on the fold's fit window from the same PA triples.
  * Lineup offense: each slot's batter carries a shrunk runs/PA profile
    by (batting side used, pitcher hand), shrunk to the fit-window
    league cell mean; the profile is expressed through his shrunk
    outcome-class distribution times fit-window class run values, so
    the pinned COMPONENT park factors scale the class probabilities
    (renormalized) at the game's park.
  * Starter phase: the opposing starter's shrunk runs-allowed/PA by
    batter hand (PA-based), expected innings and the <3-prior-starts
    unknown-prior rule carried from V1 section 2.2 (StatsAPI machinery,
    same constants as the Phase D full run).
  * Bullpen phase: the opponent's relievers pooled by an availability
    function of trailing-3-day pitches/appearances (declared in
    BUILD_RECORD.md): full weight, half weight at own rate, or
    next-man-up tier rate when over the workload threshold; pool
    prevention split by batter hand.
  * Context: weather term (Open-Meteo Previous Runs previous_day1 at
    the first-pitch hour; coefficients fitted on fit-window games only;
    roof/NO_DATA games neutral) and a bounded umpire term (shrunk
    run-environment tendency, log-multiplier capped at +/-0.03).
  * Win probability from a calibration layer - logistic on
    (lambda differential, lambda total) - fitted on fit-window games
    only. Totals/team-total point estimates are the lambda means (with
    the fit-window home split applied for team totals, declared).

CONTROL (design 5.2 criterion 2): V1-shaped season-rate lambdas - the
Phase D full-fidelity machinery (team OFF/PIT season rates with the
starter/bullpen decomposition, V1's own constants and park handling) -
with NO state inputs, run on identical folds and data, with the SAME
calibration-layer protocol fitted on its own fit-window lambdas.

BASELINES (V1 Phase D spec, ported): home base rate (fit window);
simple Elo (K=20, HFA grid-searched on the fit window by log loss);
league-average totals (fit-window means).

FOLDS (design 5.1): fit <=2022 -> 2023, fit <=2023 -> 2024,
fit <=2024 -> 2025. Market-proxy leg on the 2025 fold vs the pinned
consensus close (design-grade, date-only; see data_manifest.json).

POINT-IN-TIME: one merged chronological stream per fold (StatsAPI games
for the rate machinery, Retrosheet games for PA state); every feature
for a game is computed before that game's records update any history; a
watermark assertion enforces (date, gamePk) order. --audit re-runs the
2024 fold on data truncated at 2024-12-31 and asserts bit-identical
predictions.
"""
import gzip
import json
import math
import os
import sys

import numpy as np

# ---------------- declared configuration (BUILD_RECORD.md) -------------
K_SHRINK = 20.0        # V1 team OFF/PIT shrinkage (pseudo-games)
KS_OUTS = 150          # V1 starter-rate prior weight (outs)
KS_STARTS = 5          # V1 expected-innings prior weight (starts)
KBP_OUTS = 180         # V1 bullpen-rate prior weight (outs)
MIN_STARTS = 3         # V1 unknown-prior threshold (prior starts)
KB_PA = 250.0          # batter class-profile shrinkage (pseudo-PAs)
KP_PA = 200.0          # pitcher prevention shrinkage (pseudo-PAs)
KU_GAMES = 40.0        # umpire tendency shrinkage (pseudo-games)
UMP_CAP = 0.03         # umpire log-multiplier cap (design: bounded term)
POOL_WINDOW_DAYS = 14  # bullpen pool: appearances in trailing 14 days
AVAIL_FULL_P, AVAIL_FULL_A = 40, 2    # <=40 pitches & <=2 apps in 3d: full
AVAIL_HALF_P, AVAIL_HALF_A = 65, 3    # <=65 & <=3: half weight, own rate
TIER_DELTA = 0.010     # next-man-up tier: +0.010 runs/PA allowed vs league
PA_RATE_FLOOR = 0.02   # per-PA run-rate floor in the additive formulation
WX_CLAMP = 0.25        # weather log-multiplier clamp
BOOT_REPS = 2000
BOOT_SEED = 20261028
FOLDS = [(2022, 2023), (2023, 2024), (2024, 2025)]
CLASSES = ["OUT", "BB", "HBP", "1B", "2B", "3B", "HR", "ROE", "FC", "OTHER"]
PARK_COMPONENT = {"1B": "1B", "2B": "2B", "3B": "3B", "BB": "BB", "HR": "HR"}
MAXR = 26

TEAM_NAME = {
    108: "Los Angeles Angels", 109: "Arizona Diamondbacks",
    110: "Baltimore Orioles", 111: "Boston Red Sox",
    112: "Chicago Cubs", 113: "Cincinnati Reds",
    114: "Cleveland Guardians", 115: "Colorado Rockies",
    116: "Detroit Tigers", 117: "Houston Astros",
    118: "Kansas City Royals", 119: "Los Angeles Dodgers",
    120: "Washington Nationals", 121: "New York Mets",
    133: "Oakland Athletics", 134: "Pittsburgh Pirates",
    135: "San Diego Padres", 136: "Seattle Mariners",
    137: "San Francisco Giants", 138: "St. Louis Cardinals",
    139: "Tampa Bay Rays", 140: "Texas Rangers",
    141: "Toronto Blue Jays", 142: "Minnesota Twins",
    143: "Philadelphia Phillies", 144: "Atlanta Braves",
    145: "Chicago White Sox", 146: "Miami Marlins",
    147: "New York Yankees", 158: "Milwaukee Brewers",
}
# 2025 relocation clubs priced on their pinned-table entry (design 3 #5:
# flagged rows, declared treatment at build).
RELOCATED_2025 = {133, 139}


def nb_pmf(mu, r, kmax=MAXR):
    from math import exp, lgamma, log
    out = []
    for k in range(kmax + 1):
        lp = (lgamma(k + r) - lgamma(r) - lgamma(k + 1)
              + r * log(r / (r + mu)) + (k * log(mu / (r + mu)) if k else 0.0))
        out.append(exp(lp))
    s = sum(out)
    return np.array([x / s for x in out])


def fit_logistic(X, y, iters=100):
    """IRLS logistic regression with a tiny ridge for stability."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    beta = np.zeros(X.shape[1])
    ridge = 1e-6
    for _ in range(iters):
        z = X @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        W = np.maximum(p * (1 - p), 1e-9)
        XtW = X.T * W
        H = XtW @ X + ridge * np.eye(X.shape[1])
        g = X.T @ (y - p) - ridge * beta
        step = np.linalg.solve(H, g)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def logistic_probs(beta, X):
    z = np.asarray(X, dtype=float) @ beta
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


# ---------------- data containers --------------------------------------

class Data:
    def __init__(self, here, data_dir):
        self.stats = json.load(open(os.path.join(data_dir, "statsapi", "statsapi_games_2021_2025.json")))
        with gzip.open(os.path.join(data_dir, "pa", "pa_dataset.json.gz"), "rt") as fh:
            pa = json.load(fh)
        self.pa_games = pa["games"]
        self.pa_index = {g["retro_id"]: i for i, g in enumerate(self.pa_games)}
        self.pas = pa["pas"]
        self.pas_by_game = {}
        for i, p in enumerate(self.pas):
            self.pas_by_game.setdefault(p["g"], []).append(i)
        pf = json.load(open(os.path.join(here, "..", "..", "data", "park_factors_2022_2024.json")))
        self.pf_runs = {k: float(v["park_factor_runs"])
                        for k, v in (pf.get("teams") or {}).items()
                        if isinstance(v, dict) and "park_factor_runs" in v}
        cpf = json.load(open(os.path.join(here, "..", "..", "data", "component_park_factors_2022_2024.json")))
        self.pf_comp = cpf.get("teams") or {}
        self.weather = WeatherIndex(os.path.join(data_dir, "weather"))
        self.proxy2025 = {}
        proxy_path = os.path.join(data_dir, "market_proxy", "mlb_2025_closing_odds.csv")
        if os.path.exists(proxy_path):
            import csv
            name_to_id = {v: k for k, v in TEAM_NAME.items()}
            name_to_id["Cleveland Indians"] = 114
            for row in csv.DictReader(open(proxy_path)):
                if row["season_type"] != "regular":
                    continue
                hid = name_to_id.get(row["home_team"])
                aid = name_to_id.get(row["away_team"])
                if hid and aid and row["close_home_win_prob"]:
                    self.proxy2025[(row["date_et"], hid, aid)] = float(row["close_home_win_prob"])
        # starter identity map: Retrosheet person id -> StatsAPI pid,
        # from observed starter pairs in matched games (majority vote).
        self.starter_map = self._build_starter_map()

    def _build_starter_map(self):
        from collections import Counter, defaultdict
        votes = defaultdict(Counter)
        stats_by_pk = {g["pk"]: g for g in self.stats}
        for g in self.pa_games:
            if g["pk"] is None:
                continue
            api = stats_by_pk.get(g["pk"])
            if api is None:
                continue
            for team in (0, 1):
                lu = [p for p in g["lineups"][str(team)] if p["pos"] == 1]
                lines = api["a_pitchers"] if team == 0 else api["h_pitchers"]
                if lu and lines:
                    votes[lu[0]["pid"]][lines[0]["pid"]] += 1
        out = {}
        for retro_id, ctr in votes.items():
            pid, n = ctr.most_common(1)[0]
            if n >= 2:
                out[retro_id] = pid
        return out


class WeatherIndex:
    """First-pitch-hour Previous Runs features from the pinned pulls."""

    def __init__(self, weather_dir):
        self.series = {}
        man_path = os.path.join(weather_dir, "weather_pin_manifest.json")
        self.manifest = json.load(open(man_path)) if os.path.exists(man_path) else {"pulls": []}
        self.meta = {}
        for pull in self.manifest.get("pulls", []):
            path = os.path.join(weather_dir, pull["file"])
            if not os.path.exists(path):
                continue
            payload = json.load(open(path))
            hourly = payload.get("hourly") or {}
            times = hourly.get("time") or []
            idx = {t: i for i, t in enumerate(times)}
            self.series[(pull["venue_id"], pull["season"])] = (hourly, idx)
            self.meta[(pull["venue_id"], pull["season"])] = pull

    def features(self, venue_id, season, game_date_utc):
        """(temp_f, wind_out_mph, precip_in) or None (roof / NO_DATA)."""
        key = (venue_id, season)
        meta = self.meta.get(key)
        if meta is None or meta.get("roof"):
            return None
        hourly, idx = self.series[key]
        hour = (game_date_utc or "")[:13] + ":00"
        i = idx.get(hour)
        if i is None:
            return None
        def val(name):
            s = hourly.get(f"{name}_previous_day1") or []
            v = s[i] if i < len(s) else None
            return None if v is None else float(v)
        temp = val("temperature_2m")
        wspd = val("wind_speed_10m")
        wdir = val("wind_direction_10m")
        precip = val("precipitation")
        if temp is None or wspd is None or wdir is None or precip is None:
            return None
        travel = (wdir + 180.0) % 360.0
        wind_out = wspd * math.cos(math.radians(travel - meta["cf_bearing_deg"]))
        return (temp, wind_out, precip)


# ---------------- fold setup: fit-window constants ---------------------

class FoldSetup:
    def __init__(self, data, fit_end):
        self.fit_end = fit_end
        fit = [g for g in data.stats if g["season"] <= fit_end]
        self.L = float(np.mean([g["hs"] for g in fit] + [g["as_"] for g in fit]))
        home_ratio = np.mean([g["hs"] for g in fit]) / np.mean([g["as_"] for g in fit])
        self.home_log = 0.5 * math.log(home_ratio)
        self.base_rate = float(np.mean([1.0 if g["hs"] > g["as_"] else 0.0 for g in fit]))
        tg = np.array([g["hs"] for g in fit] + [g["as_"] for g in fit], dtype=float)
        var = tg.var()
        self.r_nb = float(tg.mean() ** 2 / max(var - tg.mean(), 0.05))
        tot_runs = sum(g["hs"] + g["as_"] for g in fit)
        tot_outs = sum(g["h_tot_outs"] + g["a_tot_outs"] for g in fit)
        self.L_ra9 = 27.0 * tot_runs / tot_outs
        self.L_bp9 = 27.0 * sum(
            (sum(p["runs"] for p in g["h_pitchers"][1:]) + sum(p["runs"] for p in g["a_pitchers"][1:]))
            for g in fit) / max(1, sum(
            (sum(p["outs"] for p in g["h_pitchers"][1:]) + sum(p["outs"] for p in g["a_pitchers"][1:]))
            for g in fit))
        self.L_ipstart = (sum(g["h_pitchers"][0]["outs"] + g["a_pitchers"][0]["outs"]
                              for g in fit if g["h_pitchers"] and g["a_pitchers"])
                          / (2.0 * len(fit))) / 3.0
        self.league_total = float(np.mean([g["hs"] + g["as_"] for g in fit]))
        self.L_g = self.league_total  # league runs per game (both teams)
        # ---- PA aggregates on fit-window universe games
        fit_gidx = {i for i, g in enumerate(data.pa_games) if g["season"] <= fit_end}
        # RE matrix: mean runs-rest-of-half by state_before
        rest_sum, rest_n = {}, {}
        for p in data.pas:
            if p["g"] in fit_gidx:
                rest_sum[p["state"]] = rest_sum.get(p["state"], 0.0) + p["rest"]
                rest_n[p["state"]] = rest_n.get(p["state"], 0) + 1
        by_outs = {}
        for s, n in rest_n.items():
            o = s % 3
            by_outs.setdefault(o, []).append(s)
        overall_rest = sum(rest_sum.values()) / max(1, sum(rest_n.values()))
        self.RE = {}
        for s in range(24):
            if rest_n.get(s):
                self.RE[s] = rest_sum[s] / rest_n[s]
            elif by_outs.get(s % 3):
                pool = by_outs[s % 3]
                self.RE[s] = sum(rest_sum[x] for x in pool) / sum(rest_n[x] for x in pool)
            else:
                self.RE[s] = overall_rest
        # PA values on fit PAs (state_after = next PA's state in the half)
        cell_sum, cell_n = {}, {}
        bhand_sum, bhand_n = {}, {}
        cls_sum, cls_n = {}, {}
        cls_cell = {}
        slot_n = {}
        tot_v = 0.0
        tot_n = 0
        for gi in sorted(fit_gidx):
            seq = [data.pas[i] for i in data.pas_by_game[gi]]
            for p, v in zip(seq, self._pa_values(seq)):
                tot_v += v
                tot_n += 1
                key = (p["bhand"], p["phand"])
                cell_sum[key] = cell_sum.get(key, 0.0) + v
                cell_n[key] = cell_n.get(key, 0) + 1
                bhand_sum[p["bhand"]] = bhand_sum.get(p["bhand"], 0.0) + v
                bhand_n[p["bhand"]] = bhand_n.get(p["bhand"], 0) + 1
                cls_sum[p["cls"]] = cls_sum.get(p["cls"], 0.0) + v
                cls_n[p["cls"]] = cls_n.get(p["cls"], 0) + 1
                cc = cls_cell.setdefault(key, {})
                cc[p["cls"]] = cc.get(p["cls"], 0) + 1
                if p["slot"]:
                    slot_n[p["slot"]] = slot_n.get(p["slot"], 0) + 1
        self.L_pa = tot_v / max(1, tot_n)
        self.cell_mean = {k: cell_sum[k] / cell_n[k] for k in cell_n}
        self.bhand_mean = {k: bhand_sum[k] / bhand_n[k] for k in bhand_n}
        self.cls_lw = {c: (cls_sum[c] / cls_n[c] if cls_n.get(c) else self.L_pa)
                       for c in CLASSES}
        self.cls_share = {}
        for key, cc in cls_cell.items():
            n = sum(cc.values())
            self.cls_share[key] = {c: cc.get(c, 0) / n for c in CLASSES}
        tot_slots = sum(slot_n.values())
        self.slot_share = {s: slot_n.get(s, 0) / tot_slots for s in range(1, 10)}
        team_pas = [data.pa_games[i]["pa_total"] / 2.0 for i in fit_gidx]
        self.N_pa = float(np.mean(team_pas)) if team_pas else 38.0
        fit_runs = sum(data.pa_games[i]["runs_vis"] + data.pa_games[i]["runs_home"]
                       for i in fit_gidx)
        fit_pas_n = sum(data.pa_games[i]["pa_total"] for i in fit_gidx)
        self.L_runs_pa = fit_runs / max(1, fit_pas_n)
        ph_n = {}
        for p in data.pas:
            if p["g"] in fit_gidx:
                ph_n[p["phand"]] = ph_n.get(p["phand"], 0) + 1
        tot_ph = sum(ph_n.values()) or 1
        self.phand_share = {h: ph_n.get(h, 0) / tot_ph for h in ("L", "R")}
        self.fit_gidx = fit_gidx

    def _pa_values(self, seq):
        """RE-delta run values for one game's PA sequence (parse order)."""
        out = []
        for i, p in enumerate(seq):
            nxt = None
            if i + 1 < len(seq):
                q = seq[i + 1]
                if q["inning"] == p["inning"] and q["team"] == p["team"]:
                    nxt = q["state"]
            re_after = self.RE[nxt] if nxt is not None else 0.0
            out.append(p["runs"] + re_after - self.RE[p["state"]])
        return out


def season_finals(stats, season):
    off, pit, n, bpr, bpo = {}, {}, {}, {}, {}
    for g in stats:
        if g["season"] != season:
            continue
        off[g["at"]] = off.get(g["at"], 0) + g["as_"]
        pit[g["at"]] = pit.get(g["at"], 0) + g["hs"]
        off[g["ht"]] = off.get(g["ht"], 0) + g["hs"]
        pit[g["ht"]] = pit.get(g["ht"], 0) + g["as_"]
        n[g["at"]] = n.get(g["at"], 0) + 1
        n[g["ht"]] = n.get(g["ht"], 0) + 1
        for tid, lines in ((g["ht"], g["h_pitchers"]), (g["at"], g["a_pitchers"])):
            bpr[tid] = bpr.get(tid, 0) + sum(p["runs"] for p in lines[1:])
            bpo[tid] = bpo.get(tid, 0) + sum(p["outs"] for p in lines[1:])
    bp9 = {t: (27.0 * bpr[t] / bpo[t] if bpo.get(t) else None) for t in bpr}
    return ({t: off[t] / n[t] for t in n},
            {t: pit[t] / n[t] for t in n}, bp9)


# ---------------- walk-forward state -----------------------------------

def ordinal(date_str):
    import datetime
    return datetime.date.fromisoformat(date_str).toordinal()


class WalkState:
    """All strictly-prior histories, updated only after a game is scored."""

    def __init__(self, data, setup):
        self.data = data
        self.setup = setup
        self.cur_season = None
        self.scored, self.allowed, self.played = {}, {}, {}
        self.bp_runs_cum, self.bp_outs_cum = {}, {}
        self.poff = self.ppit = self.pbp = {}
        self.starter_hist = {}       # stats pid -> [starts, outs, runs]
        self.batter_cls = {}         # (retro, bhand, phand) -> {cls: n}
        self.prev_hist = {}          # (retro pitcher, bhand) -> [sum_v, n]
        self.team_bp_prev = {}       # (team id, bhand) -> [sum_v, n]
        self.apps = {}               # (team id, retro pid) -> [(ord, pitches, started, outs)]
        self.apps_by_team = {}       # team id -> set of retro pids
        self.ump = {}                # retro ump id -> [games, runs]
        self.player_bats = {}
        self.player_throws = {}
        for g in data.pa_games:
            for team in (0, 1):
                for p in g["lineups"][str(team)]:
                    self.player_bats[p["pid"]] = p["bats"]
                    self.player_throws[p["pid"]] = p["throws"]
        self.watermark = None

    # ---- season machinery (V1 port) ----
    def _season_roll(self, season):
        self.cur_season = season
        self.scored, self.allowed, self.played = {}, {}, {}
        self.bp_runs_cum, self.bp_outs_cum = {}, {}
        self.poff, self.ppit, self.pbp = season_finals(self.data.stats, season - 1)

    def _shrunk(self, t, table, prior_table):
        L = self.setup.L
        n = self.played.get(t, 0)
        mix = prior_table.get(t, L) if n < 20 else L
        return (table.get(t, 0.0) + K_SHRINK * mix) / (n + K_SHRINK)

    def bullpen9(self, t):
        n = self.played.get(t, 0)
        mix = (self.pbp.get(t) or self.setup.L_bp9) if n < 20 else self.setup.L_bp9
        r = self.bp_runs_cum.get(t, 0)
        o = self.bp_outs_cum.get(t, 0)
        return 27.0 * (r + (mix / 27.0) * KBP_OUTS) / (o + KBP_OUTS)

    def starter9(self, pid):
        h = self.starter_hist.get(pid)
        if h is None or h[0] < MIN_STARTS:
            return self.setup.L_ra9, self.setup.L_ipstart, True
        n_s, outs_s, runs_s = h
        rate9 = 27.0 * (runs_s + (self.setup.L_ra9 / 27.0) * KS_OUTS) / (outs_s + KS_OUTS)
        exp_inn = (outs_s / 3.0 + KS_STARTS * self.setup.L_ipstart) / (n_s + KS_STARTS)
        return rate9, min(max(exp_inn, 1.0), 8.75), False

    def control_lams(self, g):
        """V1-shaped lambdas (Phase D full fidelity), home_log included."""
        s = self.setup
        off_h = self._shrunk(g["ht"], self.scored, self.poff)
        off_a = self._shrunk(g["at"], self.scored, self.poff)
        def pit_full(opp_team, opp_lines):
            st = opp_lines[0] if opp_lines else {"pid": None}
            s_rate, s_inn, _u = self.starter9(st["pid"])
            bp = self.bullpen9(opp_team)
            return (s_inn * s_rate + (9.0 - s_inn) * bp) / 9.0, s_inn
        pit_h, inn_h = pit_full(g["ht"], g["h_pitchers"])
        pit_a, inn_a = pit_full(g["at"], g["a_pitchers"])
        pf = math.sqrt(self.data.pf_runs.get(TEAM_NAME.get(g["ht"], ""), 1.0))
        def lam(off_t, pit_o, is_home):
            return (s.L * (off_t / s.L) * (pit_o / s.L)
                    * math.exp(s.home_log if is_home else -s.home_log) * pf)
        return lam(off_h, pit_a, True), lam(off_a, pit_h, False), inn_h, inn_a

    # ---- PA-state histories ----
    def resolve_side(self, batter, phand):
        bats = self.player_bats.get(batter)
        if bats == "B":
            return "L" if phand == "R" else "R"
        return bats

    def off_value(self, batter, side, phand, park_name):
        s = self.setup
        cell = (side, phand)
        counts = self.batter_cls.get((batter, side, phand), {})
        n = sum(counts.values())
        q_league = s.cls_share.get(cell)
        lw = s.cls_lw
        if q_league is None:
            return s.cell_mean.get(cell, s.L_pa)
        comp = (self.data.pf_comp.get(park_name) or {})
        num = 0.0
        den = 0.0
        for c in CLASSES:
            q = (counts.get(c, 0) + KB_PA * q_league[c]) / (n + KB_PA)
            pf_c = 1.0
            if c in PARK_COMPONENT:
                cell_pf = comp.get(PARK_COMPONENT[c])
                if cell_pf:
                    pf_c = float(cell_pf["pf"])
            num += q * pf_c * lw[c]
            den += q * pf_c
        # class probabilities scaled by the park's component factors and
        # renormalized (den); expectation over fit-window class values
        return num / den if den > 0 else s.cell_mean.get(cell, s.L_pa)

    def prev_value(self, pitcher, bhand):
        s = self.setup
        sv, n = self.prev_hist.get((pitcher, bhand), (0.0, 0))
        anchor = s.bhand_mean.get(bhand, s.L_pa)
        return (sv + KP_PA * anchor) / (n + KP_PA)

    def ump_log(self, ump_id):
        s = self.setup
        if not ump_id or ump_id == "(none)":
            return 0.0
        games, runs = self.ump.get(ump_id, (0, 0.0))
        shrunk_rate = (runs + KU_GAMES * s.L_g) / (games + KU_GAMES)
        return max(-UMP_CAP, min(UMP_CAP, math.log(shrunk_rate / s.L_g)))

    def bullpen_pool(self, team_id, ord_now, exclude_retro):
        """Availability-weighted bullpen prevention by batter side.

        Returns (prev_by_side, mix_by_pitcher_hand, pool_n).
        Pitch counts are the StatsAPI boxscore lines aligned to the
        Retrosheet appearance order (see BUILD_RECORD.md reading R6).
        """
        s = self.setup
        pool = []
        for rpid in self.apps_by_team.get(team_id, ()):
            if rpid in exclude_retro:
                continue
            app_list = self.apps[(team_id, rpid)]
            recent = [a for a in app_list if 0 < ord_now - a[0] <= POOL_WINDOW_DAYS and not a[2]]
            if not recent:
                continue
            last3 = [a for a in app_list if 0 < ord_now - a[0] <= 3 and not a[2]]
            p3 = sum(a[1] for a in last3)
            a3 = len(last3)
            u = sum(a[3] for a in recent)  # relief outs in window = usage
            if u <= 0:
                continue
            if p3 <= AVAIL_FULL_P and a3 <= AVAIL_FULL_A:
                w, tier = 1.0, False
            elif p3 <= AVAIL_HALF_P and a3 <= AVAIL_HALF_A:
                w, tier = 0.5, False
            else:
                w, tier = 0.5, True
            pool.append((rpid, u * w, tier))
        if not pool:
            return None, None, 0
        tot_w = sum(w for _, w, _ in pool)
        prev_by_side, mix = {}, {}
        for side in ("L", "R"):
            anchor = s.bhand_mean.get(side, s.L_pa)
            prev_by_side[side] = sum(
                w * ((anchor + TIER_DELTA) if tier else self.prev_value(rpid, side))
                for rpid, w, tier in pool) / tot_w
        for hand in ("L", "R"):
            mix[hand] = sum(w for rpid, w, _ in pool
                            if self.player_throws.get(rpid) == hand) / tot_w
        rest = 1.0 - mix["L"] - mix["R"]
        if rest > 0:
            mix["L"] += rest / 2.0
            mix["R"] += rest / 2.0
        return prev_by_side, mix, len(pool)


    # ---- GS lambda construction ----
    def gs_lams(self, g, api):
        """State-conditioned run means for one Retrosheet game.

        Returns dict with full / no-lineup / no-availability lambda pairs
        (visitor, home) before context multipliers.
        """
        s = self.setup
        park_name = TEAM_NAME.get(g["home_id"], "")
        ord_now = ordinal(g["date"])
        out = {}
        variants = {"full": [0.0, 0.0], "nl": [0.0, 0.0], "na": [0.0, 0.0]}
        diag = {"pool": {}, "unknown_starter": {}}
        for T in (0, 1):
            bat_id = g["vis_id"] if T == 0 else g["home_id"]
            fld_id = g["home_id"] if T == 0 else g["vis_id"]
            lineup = [p for p in g["lineups"][str(T)] if 1 <= p["slot"] <= 9]
            opp_lineup = g["lineups"][str(1 - T)]
            starter = next((p for p in opp_lineup if p["pos"] == 1), None)
            s_retro = starter["pid"] if starter else None
            s_pid = self.data.starter_map.get(s_retro)
            if s_pid is not None:
                _r9, exp_inn, unknown = self.starter9(s_pid)
            else:
                exp_inn, unknown = s.L_ipstart, True
            diag["unknown_starter"][T] = bool(unknown)
            phi = min(max(exp_inn / 9.0, 0.05), 0.97)
            phand_s = self.player_throws.get(s_retro)
            prev_bp, mix, pool_n = self.bullpen_pool(fld_id, ord_now, {s_retro})
            diag["pool"][T] = pool_n
            if prev_bp is None:
                prev_bp = {side: s.bhand_mean.get(side, s.L_pa) for side in ("L", "R")}
                mix = dict(s.phand_share)
            # team bullpen prevention (no-availability ablation source)
            prev_bp_na = {}
            for side in ("L", "R"):
                sv, n = self.team_bp_prev.get((fld_id, side), (0.0, 0))
                prev_bp_na[side] = (sv + KP_PA * s.bhand_mean.get(side, s.L_pa)) / (n + KP_PA)
            # PA values are RE-deltas from the BATTER's perspective
            # (league mean ~0 by construction). A pitcher's prev_value is
            # the mean delta he ALLOWS on that same scale (elite < 0,
            # poor > 0), so the run rate is ADDITIVE:
            #   rate = L_runs_pa + off_delta(batter) + allowed_delta(pitcher)
            team_delta = (self._shrunk(bat_id, self.scored, self.poff) / s.L - 1.0) * s.L_runs_pa
            acc = {"full": [0.0, 0.0], "nl": [0.0, 0.0], "na": [0.0, 0.0]}
            for slot_p in lineup:
                share = s.slot_share.get(slot_p["slot"], 0.0)
                if share == 0.0:
                    continue
                batter = slot_p["pid"]
                # starter phase
                side_s = self.resolve_side(batter, phand_s) if phand_s else None
                if side_s:
                    off_d_s = self.off_value(batter, side_s, phand_s, park_name)
                    prev_d_s = (s.bhand_mean.get(side_s, 0.0) if unknown
                                else self.prev_value(s_retro, side_s))
                else:
                    off_d_s, prev_d_s = 0.0, 0.0
                # bullpen phase (full + no-availability share prev source)
                off_d_b = prev_d_b = prev_d_b_na = 0.0
                for h in ("L", "R"):
                    if mix.get(h, 0.0) == 0.0:
                        continue
                    side_h = self.resolve_side(batter, h)
                    if side_h is None:
                        continue
                    off_d_b += mix[h] * self.off_value(batter, side_h, h, park_name)
                    prev_d_b += mix[h] * prev_bp[side_h]
                    prev_d_b_na += mix[h] * prev_bp_na[side_h]
                rate_s = max(s.L_runs_pa + off_d_s + prev_d_s, PA_RATE_FLOOR)
                rate_s_nl = max(s.L_runs_pa + team_delta + prev_d_s, PA_RATE_FLOOR)
                rate_b = max(s.L_runs_pa + off_d_b + prev_d_b, PA_RATE_FLOOR)
                rate_b_nl = max(s.L_runs_pa + team_delta + prev_d_b, PA_RATE_FLOOR)
                rate_b_na = max(s.L_runs_pa + off_d_b + prev_d_b_na, PA_RATE_FLOOR)
                acc["full"][0] += share * rate_s
                acc["full"][1] += share * rate_b
                acc["nl"][0] += share * rate_s_nl
                acc["nl"][1] += share * rate_b_nl
                acc["na"][0] += share * rate_s
                acc["na"][1] += share * rate_b_na
            for name in variants:
                lam = s.N_pa * (phi * acc[name][0] + (1 - phi) * acc[name][1])
                variants[name][T] = lam
        out["lam_full"] = (variants["full"][0], variants["full"][1])    # (vis, home)
        out["lam_nl"] = (variants["nl"][0], variants["nl"][1])
        out["lam_na"] = (variants["na"][0], variants["na"][1])
        out["diag"] = diag
        return out

    # ---- history updates (called only after the game is scored) ----
    def update_stats_game(self, g):
        # season roll is the fold loop's job (it must happen BEFORE the
        # season's first game is scored, not at its first update)
        assert self.cur_season == g["season"], "season roll missed"
        for tid, lines, sc, al in (
                (g["ht"], g["h_pitchers"], g["hs"], g["as_"]),
                (g["at"], g["a_pitchers"], g["as_"], g["hs"])):
            self.scored[tid] = self.scored.get(tid, 0) + sc
            self.allowed[tid] = self.allowed.get(tid, 0) + al
            self.played[tid] = self.played.get(tid, 0) + 1
            self.bp_runs_cum[tid] = self.bp_runs_cum.get(tid, 0) + sum(p["runs"] for p in lines[1:])
            self.bp_outs_cum[tid] = self.bp_outs_cum.get(tid, 0) + sum(p["outs"] for p in lines[1:])
            if lines:
                st = lines[0]
                h = self.starter_hist.setdefault(st["pid"], [0, 0, 0])
                h[0] += 1
                h[1] += st["outs"]
                h[2] += st["runs"]
        key = (g["date"], g["pk"])
        assert self.watermark is None or self.watermark < key, "watermark order"
        self.watermark = key

    def update_pa_game(self, g, api):
        seq = [self.data.pas[i] for i in self.data.pas_by_game[
            self.data.pa_index[g["retro_id"]]]]
        vals = self.setup._pa_values(seq)
        starters = {}
        for team in (0, 1):
            st = next((p for p in g["lineups"][str(team)] if p["pos"] == 1), None)
            starters[team] = st["pid"] if st else None
        for p, v in zip(seq, vals):
            bc = self.batter_cls.setdefault((p["batter"], p["bhand"], p["phand"]), {})
            bc[p["cls"]] = bc.get(p["cls"], 0) + 1
            pv = self.prev_hist.setdefault((p["pitcher"], p["bhand"]), [0.0, 0])
            pv[0] += v
            pv[1] += 1
            fld_team = 1 - p["team"]
            fld_id = g["home_id"] if fld_team == 1 else g["vis_id"]
            if p["pitcher"] != starters[fld_team]:
                tb = self.team_bp_prev.setdefault((fld_id, p["bhand"]), [0.0, 0])
                tb[0] += v
                tb[1] += 1
        # appearances: align Retrosheet appearance order to StatsAPI lines
        if api is not None:
            ord_now = ordinal(g["date"])
            for team in (0, 1):
                fld_id = g["vis_id"] if team == 0 else g["home_id"]
                retro_list = g["pitchers"][str(team)]
                api_lines = api["a_pitchers"] if team == 0 else api["h_pitchers"]
                aligned = len(retro_list) == len(api_lines)
                for i, rp in enumerate(retro_list):
                    if aligned:
                        pitches = api_lines[i]["pitches"]
                        outs = api_lines[i]["outs"]
                    else:
                        pitches = rp["pitches_seq"]
                        outs = 0
                    self.apps.setdefault((fld_id, rp["pid"]), []).append(
                        (ord_now, pitches, i == 0, outs))
                    self.apps_by_team.setdefault(fld_id, set()).add(rp["pid"])
        ump_id = g["umphome"]
        if ump_id and ump_id != "(none)":
            u = self.ump.setdefault(ump_id, [0, 0.0])
            u[0] += 1
            u[1] += g["runs_vis"] + g["runs_home"]


# ---------------- fold runner ------------------------------------------

def elo_probs_fold(data, fit_end, test_season):
    """V1 Phase D Elo, ported: K=20, HFA grid-searched on fit log loss."""
    fit = [g for g in data.stats if g["season"] <= fit_end]
    test = [g for g in data.stats if g["season"] == test_season]
    def elo_run(hfa_pts):
        elo, probs = {}, {}
        for g in fit + test:
            rh = elo.get(g["ht"], 1500.0) + hfa_pts
            ra = elo.get(g["at"], 1500.0)
            ph = 1 / (1 + 10 ** (-(rh - ra) / 400))
            probs[g["pk"]] = ph
            y = 1.0 if g["hs"] > g["as_"] else 0.0
            elo[g["ht"]] = elo.get(g["ht"], 1500.0) + 20 * (y - ph)
            elo[g["at"]] = elo.get(g["at"], 1500.0) + 20 * ((1 - y) - (1 - ph))
        return probs
    best_hfa, best_ll, best = 0, 1e18, None
    for hfa in range(0, 61, 5):
        pr = elo_run(hfa)
        ll = -np.mean([math.log(min(max(pr[g["pk"]], 1e-9), 1 - 1e-9)) if g["hs"] > g["as_"]
                       else math.log(min(max(1 - pr[g["pk"]], 1e-9), 1 - 1e-9)) for g in fit])
        if ll < best_ll:
            best_ll, best_hfa, best = ll, hfa, pr
    return best, best_hfa


def _wx_log(beta, wx):
    if beta is None or wx is None:
        return 0.0
    temp, wind_out, precip = wx
    v = (beta[0] + beta[1] * (temp - 70.0) / 10.0 + beta[2] * wind_out / 5.0
         + beta[3] * (1.0 if precip > 0.02 else 0.0))
    return max(-WX_CLAMP, min(WX_CLAMP, v))


VARIANTS = ("full", "ctrl", "nl", "na", "nu", "nw")


def run_fold(data, fit_end, test_season, truncate_date=None):
    setup = FoldSetup(data, fit_end)
    ws = WalkState(data, setup)
    elo, elo_hfa = elo_probs_fold(data, fit_end, test_season)
    stats_by_pk = {g["pk"]: g for g in data.stats}
    pa_by_pk = {pg["pk"]: pg for pg in data.pa_games if pg["pk"] is not None}
    items = []
    for g in data.stats:
        if g["season"] > test_season:
            continue
        if truncate_date and g["date"] > truncate_date:
            continue
        items.append((g["date"], g["pk"], g, pa_by_pk.get(g["pk"])))
    for pg in data.pa_games:
        if pg["pk"] is None and pg["season"] <= test_season:
            if truncate_date and pg["date"] > truncate_date:
                continue
            items.append((pg["date"], 10 ** 9, None, pg))
    items.sort(key=lambda x: (x[0], x[1]))
    fit_rows, test_rows = [], []
    n_scored_fit = 0
    for date, pk, api, pg in items:
        season = (api or pg)["season"]
        if api is not None and ws.cur_season != season:
            ws._season_roll(season)
        if pg is not None and api is not None and pg.get("score_agree"):
            cl_h, cl_a, _ih, _ia = ws.control_lams(api)
            gs = ws.gs_lams(pg, api)
            row = dict(
                pk=pk, season=season, date=date,
                ht=api["ht"], at=api["at"],
                y=1.0 if api["hs"] > api["as_"] else 0.0,
                hs=api["hs"], as_=api["as_"],
                lam_ctrl=(cl_h, cl_a),
                lam_full=(gs["lam_full"][1], gs["lam_full"][0]),
                lam_nl=(gs["lam_nl"][1], gs["lam_nl"][0]),
                lam_na=(gs["lam_na"][1], gs["lam_na"][0]),
                ump_log=ws.ump_log(pg["umphome"]),
                wx=data.weather.features(pg["venue_id"], season, pg["game_date_utc"]),
                p_base=setup.base_rate, p_elo=elo.get(pk),
                total_base=setup.league_total, team_base=setup.L,
                relocated=bool(season == 2025 and pg["home_id"] in RELOCATED_2025),
                pool_home=gs["diag"]["pool"].get(1, 0), pool_vis=gs["diag"]["pool"].get(0, 0),
                unk_home=gs["diag"]["unknown_starter"].get(1, False),
                unk_vis=gs["diag"]["unknown_starter"].get(0, False))
            if season <= fit_end:
                fit_rows.append(row)
                n_scored_fit += 1
            else:
                test_rows.append(row)
        if api is not None:
            ws.update_stats_game(api)
        if pg is not None:
            ws.update_pa_game(pg, api)
    # ---- context fitting on fit rows only
    wx_rows = [r for r in fit_rows if r["wx"] is not None]
    if len(wx_rows) >= 200:
        X = np.array([[1.0, (r["wx"][0] - 70.0) / 10.0, r["wx"][1] / 5.0,
                       1.0 if r["wx"][2] > 0.02 else 0.0] for r in wx_rows])
        yv = np.array([math.log((r["hs"] + r["as_"] + 0.5)
                                / (r["lam_full"][0] + r["lam_full"][1] + 0.5))
                       for r in wx_rows])
        wx_beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        wx_beta = [float(x) for x in wx_beta]
    else:
        wx_beta = None
    def lam_post(row, variant):
        if variant == "ctrl":
            return row["lam_ctrl"]
        pre = {"full": row["lam_full"], "nl": row["lam_nl"], "na": row["lam_na"],
               "nu": row["lam_full"], "nw": row["lam_full"]}[variant]
        wl = 0.0 if variant == "nw" else _wx_log(wx_beta, row["wx"])
        ul = 0.0 if variant == "nu" else row["ump_log"]
        m = math.exp(wl + ul)
        return (pre[0] * m, pre[1] * m)
    layer_beta = {}
    for variant in VARIANTS:
        X = np.array([[1.0, (lambda p: p[0] - p[1])(lam_post(r, variant)),
                       (lambda p: p[0] + p[1])(lam_post(r, variant))] for r in fit_rows])
        yv = np.array([r["y"] for r in fit_rows])
        layer_beta[variant] = fit_logistic(X, yv)
    for row in test_rows + fit_rows:
        for variant in VARIANTS:
            lp = lam_post(row, variant)
            row[f"lam_post_{variant}"] = lp
            row[f"p_{variant}"] = float(logistic_probs(
                layer_beta[variant], [[1.0, lp[0] - lp[1], lp[0] + lp[1]]])[0])
    diag = dict(fit_end=fit_end, test_season=test_season,
                home_log=float(setup.home_log),
                n_fit_rows=len(fit_rows), n_test_rows=len(test_rows),
                wx_beta=wx_beta, wx_fit_rows=len(wx_rows),
                elo_hfa=elo_hfa, layer_beta={k: [float(x) for x in v] for k, v in layer_beta.items()},
                L=float(setup.L), L_pa=float(setup.L_pa), N_pa=float(setup.N_pa),
                r_nb=float(setup.r_nb), base_rate=float(setup.base_rate))
    return test_rows, fit_rows, diag


# ---------------- metrics + verdict ------------------------------------

def brier_ll(rows, key):
    p = np.array([min(max(r[key], 1e-9), 1 - 1e-9) for r in rows])
    y = np.array([r["y"] for r in rows])
    return (float(np.mean((p - y) ** 2)),
            float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))))


def totals_mae(rows, lam_key, home_log):
    te, tte = [], []
    for r in rows:
        lh, la = r[lam_key]
        th, ta = lh * math.exp(home_log), la * math.exp(-home_log)
        te.append(abs((th + ta) - (r["hs"] + r["as_"])))
        tte.append((abs(th - r["hs"]) + abs(ta - r["as_"])) / 2.0)
    return float(np.mean(te)), float(np.mean(tte))


def base_totals_mae(rows):
    te = [abs(r["total_base"] - (r["hs"] + r["as_"])) for r in rows]
    tte = [(abs(r["team_base"] - r["hs"]) + abs(r["team_base"] - r["as_"])) / 2.0
           for r in rows]
    return float(np.mean(te)), float(np.mean(tte))


def deciles(rows, key="p_full"):
    srt = sorted(rows, key=lambda r: r[key])
    out = []
    n = len(srt)
    for i in range(10):
        chunk = srt[i * n // 10:(i + 1) * n // 10]
        if chunk:
            out.append(dict(decile=i + 1, n=len(chunk),
                            mean_p=float(np.mean([r[key] for r in chunk])),
                            realized=float(np.mean([r["y"] for r in chunk])),
                            dev=float(abs(np.mean([r[key] for r in chunk])
                                            - np.mean([r["y"] for r in chunk])))))
    return out


def bootstrap_delta(rows, key_a, key_b, reps=BOOT_REPS, seed=BOOT_SEED):
    """Paired game-level bootstrap of Brier(key_a) - Brier(key_b)."""
    rng = np.random.default_rng(seed)
    pa = np.array([r[key_a] for r in rows])
    pb = np.array([r[key_b] for r in rows])
    y = np.array([r["y"] for r in rows])
    da = (pa - y) ** 2
    db = (pb - y) ** 2
    d = da - db
    n = len(rows)
    idx = rng.integers(0, n, size=(reps, n))
    means = d[idx].mean(axis=1)
    return dict(delta=float(d.mean()),
                ci_lo=float(np.quantile(means, 0.025)),
                ci_hi=float(np.quantile(means, 0.975)))


def run_screen(data):
    all_test, fold_diags, per_fold = [], {}, {}
    for fit_end, test_season in FOLDS:
        test_rows, fit_rows, diag = run_fold(data, fit_end, test_season)
        fold_diags[test_season] = diag
        all_test.extend(test_rows)
        per_fold[test_season] = test_rows
    # home_log per fold for the team-total split (carried in fold diags)
    hl = {ts: fold_diags[ts]["home_log"] for ts in fold_diags}
    out = {"folds": {}, "pooled": {}}
    for test_season, rows in per_fold.items():
        f = {}
        for variant in ("full", "ctrl"):
            f[f"brier_{variant}"], f[f"ll_{variant}"] = brier_ll(rows, f"p_{variant}")
        f["brier_base"], f["ll_base"] = brier_ll(rows, "p_base")
        f["brier_elo"], f["ll_elo"] = brier_ll(rows, "p_elo")
        f["total_mae_full"], f["team_mae_full"] = totals_mae(rows, "lam_post_full", hl[test_season])
        f["total_mae_ctrl"], f["team_mae_ctrl"] = totals_mae(rows, "lam_ctrl", 0.0)
        f["total_mae_base"], f["team_mae_base"] = base_totals_mae(rows)
        f["n"] = len(rows)
        out["folds"][test_season] = f
    p = {}
    for variant in ("full", "ctrl"):
        p[f"brier_{variant}"], p[f"ll_{variant}"] = brier_ll(all_test, f"p_{variant}")
    p["brier_base"], p["ll_base"] = brier_ll(all_test, "p_base")
    p["brier_elo"], p["ll_elo"] = brier_ll(all_test, "p_elo")
    # pooled totals: fold-specific home split applied per row
    te, tte, tec, ttec = [], [], [], []
    for r in all_test:
        h = hl[r["season"]]
        lh, la = r["lam_post_full"]
        th, ta = lh * math.exp(h), la * math.exp(-h)
        te.append(abs((th + ta) - (r["hs"] + r["as_"])))
        tte.append((abs(th - r["hs"]) + abs(ta - r["as_"])) / 2.0)
        ch, ca = r["lam_ctrl"]
        tec.append(abs((ch + ca) - (r["hs"] + r["as_"])))
        ttec.append((abs(ch - r["hs"]) + abs(ca - r["as_"])) / 2.0)
    p["total_mae_full"], p["team_mae_full"] = float(np.mean(te)), float(np.mean(tte))
    p["total_mae_ctrl"], p["team_mae_ctrl"] = float(np.mean(tec)), float(np.mean(ttec))
    p["total_mae_base"], p["team_mae_base"] = base_totals_mae(all_test)
    p["n"] = len(all_test)
    p["deciles_full"] = deciles(all_test)
    out["pooled"] = p
    # market-proxy leg (2025 fold)
    rows25 = per_fold[2025]
    matched = [r for r in rows25 if (r["date"], r["ht"], r["at"]) in data.proxy2025]
    for r in matched:
        r["p_proxy"] = data.proxy2025[(r["date"], r["ht"], r["at"])]
    proxy = dict(n_matched=len(matched), n_fold=len(rows25))
    if matched:
        proxy["brier_proxy"], proxy["ll_proxy"] = brier_ll(matched, "p_proxy")
        proxy["brier_full_on_matched"], proxy["ll_full_on_matched"] = brier_ll(matched, "p_full")
    out["market_proxy_2025"] = proxy
    # ablations (pooled Brier + bootstrap vs full)
    abl = {}
    for variant, label in (("nl", "lineup_platoon_off"), ("na", "availability_off"),
                           ("nu", "umpire_off"), ("nw", "weather_off")):
        b, l = brier_ll(all_test, f"p_{variant}")
        abl[label] = dict(brier=b, ll=l,
                          delta_vs_full=bootstrap_delta(all_test, f"p_{variant}", "p_full"))
    out["ablations"] = abl
    out["control_delta"] = bootstrap_delta(all_test, "p_full", "p_ctrl")
    # ---- criteria (design 5.2)
    crit = {}
    crit["1_pooled_brier_beats_base_elo"] = bool(
        p["brier_full"] < p["brier_base"] and p["brier_full"] < p["brier_elo"])
    crit["1_pooled_ll_beats_base_elo"] = bool(
        p["ll_full"] < p["ll_base"] and p["ll_full"] < p["ll_elo"])
    crit["1_pooled_totals_beat_league_avg"] = bool(
        p["total_mae_full"] < p["total_mae_base"] and p["team_mae_full"] < p["team_mae_base"])
    crit["1_every_fold"] = all(
        f["brier_full"] < f["brier_base"] and f["brier_full"] < f["brier_elo"]
        and f["ll_full"] < f["ll_base"] and f["ll_full"] < f["ll_elo"]
        and f["total_mae_full"] < f["total_mae_base"]
        and f["team_mae_full"] < f["team_mae_base"]
        for f in out["folds"].values())
    crit["2_beats_v1_shaped_control_pooled_brier"] = bool(p["brier_full"] < p["brier_ctrl"])
    crit["3_calibration_gate"] = all(
        d["dev"] <= 0.075 for d in p["deciles_full"] if d["n"] >= 200)
    crit["4_market_proxy_2025_brier"] = bool(
        matched and proxy["brier_full_on_matched"] < proxy["brier_proxy"])
    out["criteria"] = crit
    out["verdict"] = ("SCREEN_PASS" if all(crit.values()) else "FAILED_SCREEN")
    out["fold_diags"] = {str(k): {kk: vv for kk, vv in v.items() if kk != "layer_beta"}
                         for k, v in fold_diags.items()}
    out["layer_beta"] = {str(k): v["layer_beta"] for k, v in fold_diags.items()}
    return out, all_test


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "pulls")
    data = Data(here, data_dir)
    if "--audit" in sys.argv:
        full_rows, _, _ = run_fold(data, 2023, 2024)
        trunc_rows, _, _ = run_fold(data, 2023, 2024, truncate_date="2024-12-31")
        f = {r["pk"]: r["p_full"] for r in full_rows}
        t = {r["pk"]: r["p_full"] for r in trunc_rows}
        assert set(f) == set(t), "audit: game sets differ"
        diffs = [pk for pk in f if f[pk] != t[pk]]
        print(f"AUDIT: {len(f)} predictions for the 2024 fold; bit-identical "
              f"under future-data truncation: {len(diffs) == 0} (diffs: {len(diffs)})")
        assert not diffs
        return
    out, _rows = run_screen(data)
    out_path = os.path.join(here, "screen_results.json")
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps({k: out[k] for k in ("pooled", "criteria", "verdict")}, indent=1))


if __name__ == "__main__":
    main()
