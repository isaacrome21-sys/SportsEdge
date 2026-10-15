"""NBA 2024-25 FIT-ONLY preprocessing, features and baseline/candidate fitting.

Owner ruling #2267 (2026-10-15): design approved in principle; 2024-25 fit window
GO for fit-only/preprocessing; 2025-26 scoring on HOLD. This module therefore:

  * reads ONLY the 2024-25 ESPN caches (directory basenames ``nba_cache`` /
    ``nba_cache_q``) and refuses any other source, any path naming 2025-26, and
    any game whose tipoff falls outside [2024-10-01, 2025-07-01) UTC;
  * computes strictly-pregame features (only games with an earlier tipoff);
  * fits the candidate (existing ``nba_game_market_pricing.fit_verified_games``
    with default ``NBARatingsParams``) and the public baselines named in the
    proposal (ML: constant / Elo K20 home+100 carry 0.75 / point-diff SRS
    logistic; total: league mean+SD / rolling-10 with shrinkage);
  * computes NO holdout prediction, NO log loss, NO CRPS, NO verdict.

RESEARCH_ONLY / NO_VALIDATION. Hyperparameters below are DRAFT constants pending
the owner freeze (FROZEN_BEFORE_EVALUATION); nothing here is a frozen prereg.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
FIT_START = datetime(2024, 10, 1, tzinfo=timezone.utc)
FIT_END_EXCL = datetime(2025, 7, 1, tzinfo=timezone.utc)
ALLOWED_CACHE_DIRS = frozenset({"nba_cache", "nba_cache_q"})
FORBIDDEN_MARKERS = ("2025_26", "2025-26", "202526")
# NBA Cup final 2024 (OKC vs MIL, 2024-12-17 ET) does not count in standings.
CUP_FINAL_EVENT_IDS = frozenset({"401734908"})
NBA_FRANCHISES = frozenset({
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS", "HOU", "IND",
    "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NO", "NY", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SA", "TOR", "UTAH", "WSH",
})
DRAFT_PARAMS = {
    "elo_k": 20.0, "elo_home": 100.0, "elo_init": 1500.0, "elo_carry": 0.75,
    "srs_min_games": 5, "rolling_window": 10, "rolling_shrink_k": 5.0,
    "bootstrap_seed": 20261015, "bootstrap_resamples": 2000,
}


class FitError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class FitGame:
    event_id: str
    tipoff: datetime
    home: str
    away: str
    home_pts: int
    away_pts: int


def _guard_path(path) -> Path:
    p = Path(path)
    text = str(p)
    if any(m in text for m in FORBIDDEN_MARKERS):
        raise FitError("NBA_FIT_HOLDOUT_PATH_FORBIDDEN", text)
    if p.name not in ALLOWED_CACHE_DIRS:
        raise FitError("NBA_FIT_SOURCE_NOT_ALLOWED", p.name)
    return p


def _tipoff(value) -> datetime:
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise FitError("NBA_FIT_TIPOFF_INVALID", str(value)) from exc
    if dt.tzinfo is None:
        raise FitError("NBA_FIT_TIPOFF_NAIVE", str(value))
    return dt.astimezone(timezone.utc)


def _parse(row) -> FitGame | None:
    """None = excluded by rule (All-Star / Cup final); raises on window leakage."""
    t = _tipoff(row.get("date"))
    if not FIT_START <= t < FIT_END_EXCL:
        raise FitError("NBA_FIT_WINDOW_VIOLATION", f"{row.get('id')}@{t.isoformat()}")
    teams = row.get("teams") or []
    if len(teams) != 2:
        raise FitError("NBA_FIT_TEAMS_INVALID", str(row.get("id")))
    side = {x.get("homeAway"): x for x in teams}
    if set(side) != {"home", "away"}:
        raise FitError("NBA_FIT_HOME_AWAY_INVALID", str(row.get("id")))
    eid = str(row.get("id"))
    if eid in CUP_FINAL_EVENT_IDS:
        return None
    h, a = side["home"], side["away"]
    if h.get("abbr") not in NBA_FRANCHISES or a.get("abbr") not in NBA_FRANCHISES:
        return None
    hp, ap = h.get("score"), a.get("score")
    for v in (hp, ap):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise FitError("NBA_FIT_SCORE_INVALID", eid)
    if hp == ap:
        raise FitError("NBA_FIT_TIED_FINAL", eid)
    return FitGame(eid, t, h["abbr"], a["abbr"], hp, ap)


def load_fit_games(cache_dir):
    """Load 2024-25 fit games. Returns (games, manifest)."""
    d = _guard_path(cache_dir)
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    games, excluded, hashes = {}, defaultdict(int), {}
    for name in files:
        raw = (d / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        g = _parse(json.loads(raw))
        if g is None:
            excluded["ALL_STAR_OR_CUP_FINAL"] += 1
            continue
        if g.event_id in games:
            raise FitError("NBA_FIT_DUPLICATE_EVENT", g.event_id)
        games[g.event_id] = g
    ordered = sorted(games.values(), key=lambda g: (g.tipoff, g.event_id))
    dataset_sha = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(hashes.items()))
                                 .encode()).hexdigest()
    manifest = {"source_dir": d.name, "files": len(files), "games": len(ordered),
                "excluded": dict(excluded), "dataset_sha256": dataset_sha,
                "first_tipoff": ordered[0].tipoff.isoformat() if ordered else None,
                "last_tipoff": ordered[-1].tipoff.isoformat() if ordered else None}
    return ordered, manifest


def pregame_features(games):
    """Per-game features from strictly earlier tipoffs only (same-tipoff games hidden)."""
    hist = defaultdict(list)   # team -> [(tipoff, pf, pa)]
    out = []
    w = DRAFT_PARAMS["rolling_window"]
    ordered = sorted(games, key=lambda g: (g.tipoff, g.event_id))
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j].tipoff == ordered[i].tipoff:
            j += 1
        batch = ordered[i:j]
        for g in batch:
            row = {"event_id": g.event_id, "tipoff": g.tipoff.isoformat()}
            for side, team in (("home", g.home), ("away", g.away)):
                h = hist[team]
                n = len(h)
                last = h[-w:]
                row[f"{side}_gp"] = n
                row[f"{side}_pf_mean"] = sum(x[1] for x in h) / n if n else None
                row[f"{side}_pa_mean"] = sum(x[2] for x in h) / n if n else None
                row[f"{side}_pf_last"] = sum(x[1] for x in last) / len(last) if last else None
                row[f"{side}_pa_last"] = sum(x[2] for x in last) / len(last) if last else None
                rest = (g.tipoff - h[-1][0]).total_seconds() / 86400 if h else None
                row[f"{side}_rest_days"] = None if rest is None else min(rest, 3.0)
                row[f"{side}_b2b"] = rest is not None and rest < 1.6
            out.append(row)
        for g in batch:
            hist[g.home].append((g.tipoff, g.home_pts, g.away_pts))
            hist[g.away].append((g.tipoff, g.away_pts, g.home_pts))
        i = j
    return out


def _elo(games):
    p = DRAFT_PARAMS
    r = defaultdict(lambda: p["elo_init"])
    for g in sorted(games, key=lambda g: (g.tipoff, g.event_id)):
        exp_home = 1 / (1 + 10 ** (-(r[g.home] + p["elo_home"] - r[g.away]) / 400))
        s = 1.0 if g.home_pts > g.away_pts else 0.0
        r[g.home] += p["elo_k"] * (s - exp_home)
        r[g.away] -= p["elo_k"] * (s - exp_home)
    carried = {t: p["elo_init"] + p["elo_carry"] * (v - p["elo_init"]) for t, v in r.items()}
    return {"end_of_fit": dict(r), "carried_to_next_season": carried}


def _logistic_fit(xs, ys, iters=50):
    """Newton-Raphson for P(y=1)=sigmoid(a + b*x) on fit-window rows only."""
    a = b = 0.0
    for _ in range(iters):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            pr = 1 / (1 + math.exp(-(a + b * x)))
            ga += y - pr
            gb += (y - pr) * x
            w = pr * (1 - pr)
            haa += w; hab += w * x; hbb += w * x * x
        det = haa * hbb - hab * hab
        if det <= 0:
            raise FitError("NBA_FIT_LOGISTIC_SINGULAR")
        a += (hbb * ga - hab * gb) / det
        b += (haa * gb - hab * ga) / det
    if not (math.isfinite(a) and math.isfinite(b)):
        raise FitError("NBA_FIT_LOGISTIC_NONFINITE")
    return a, b


def fit_all(games, features=None):
    """Fit candidate + baselines on the fit window. No holdout, no scores."""
    if len(games) < 100:
        raise FitError("NBA_FIT_TOO_FEW_GAMES", str(len(games)))
    for g in games:
        if not FIT_START <= g.tipoff < FIT_END_EXCL:
            raise FitError("NBA_FIT_WINDOW_VIOLATION", g.event_id)
    feats = features or pregame_features(games)
    by_id = {g.event_id: g for g in games}
    totals = [g.home_pts + g.away_pts for g in games]
    t_mean = sum(totals) / len(totals)
    t_sd = math.sqrt(sum((t - t_mean) ** 2 for t in totals) / len(totals))
    home_rate = sum(g.home_pts > g.away_pts for g in games) / len(games)
    xs, ys, resid = [], [], []
    k = DRAFT_PARAMS["rolling_shrink_k"]
    for f in feats:
        g = by_id[f["event_id"]]
        if min(f["home_gp"], f["away_gp"]) >= DRAFT_PARAMS["srs_min_games"]:
            xs.append((f["home_pf_mean"] - f["home_pa_mean"]) - (f["away_pf_mean"] - f["away_pa_mean"]))
            ys.append(1.0 if g.home_pts > g.away_pts else 0.0)
        if f["home_pf_last"] is not None and f["away_pf_last"] is not None:
            n = min(f["home_gp"], f["away_gp"], DRAFT_PARAMS["rolling_window"])
            wt = n / (n + k)
            hh = wt * (f["home_pf_last"] + f["away_pa_last"]) / 2 + (1 - wt) * t_mean / 2
            aa = wt * (f["away_pf_last"] + f["home_pa_last"]) / 2 + (1 - wt) * t_mean / 2
            resid.append((g.home_pts + g.away_pts) - (hh + aa))
    srs_a, srs_b = _logistic_fit(xs, ys)
    r_sd = math.sqrt(sum(e * e for e in resid) / len(resid))
    from sportsedge.sports.nba.nba_game_market_pricing import fit_verified_games
    cand_rows = [{"tipoff": g.tipoff.isoformat(), "event_id": g.event_id, "home_team_id": g.home,
                  "away_team_id": g.away, "home_score": g.home_pts, "away_score": g.away_pts}
                 for g in games]
    ratings, sig_m, sig_t = fit_verified_games(cand_rows)
    return {
        "schema": "NBA_FIT_2024_25_ARTIFACT_DRAFT_V1",
        "status": STATUS, "validation": VALIDATION,
        "fit_window": [FIT_START.isoformat(), FIT_END_EXCL.isoformat()],
        "n_games": len(games), "draft_params": dict(DRAFT_PARAMS),
        "baselines": {
            "ML_B0_constant": {"home_win_rate": home_rate},
            "ML_B1_elo": _elo(games),
            "ML_B2_srs_logistic": {"intercept": srs_a, "slope": srs_b, "rows": len(xs)},
            "TOTAL_T0_league": {"mean": t_mean, "sd": t_sd},
            "TOTAL_T1_rolling": {"window": DRAFT_PARAMS["rolling_window"],
                                 "shrink_k": k, "residual_sd": r_sd, "rows": len(resid)},
        },
        "candidate": {"entry_point": "sportsedge.sports.nba.nba_game_market_pricing.fit_verified_games",
                      "params": "NBARatingsParams() defaults",
                      "sigma_margin": sig_m, "sigma_total": sig_t,
                      "league": ratings.league, "hca": ratings.hca},
        "holdout_touched": False, "scores": None,
    }
