"""NFL_ANCHORED_RATINGS_V1: unfrozen historical design-data falsification.

The nflverse game schedule supplies historical consensus *closing* lines,
not timestamped DraftKings quotes. No CLV, counted rows, picks or promotion.
For each date, scores/ratings/HFA/sigma use *strictly previous* dates only.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from math import erf, isfinite, sqrt
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable

WEIGHT = 0.15
DISAGREEMENT_CAP = 4.0
QB_CAP = 4.0
WEATHER_CAP = 2.0  # unfrozen research assumption
SIGMA_FLOOR = 12.5
BANDS = ((0, 1), (1, 2), (2, 3), (3, float("inf")))
BAND_MIN_N = 20


@dataclass(frozen=True)
class Game:
    day: str
    game_id: str
    home: str
    away: str
    home_score: int
    away_score: int
    spread_close: float | None
    total_close: float | None
    neutral: bool = False
    home_qb_delta: float = 0.0
    away_qb_delta: float = 0.0
    weather_total_delta: float = 0.0


def finite(raw: object, field: str) -> float:
    try:
        value = float(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field}_NOT_NUMERIC") from exc
    if not isfinite(value):
        raise ValueError(f"{field}_NONFINITE")
    return value


def read_games(path: Path) -> list[Game]:
    out = []
    ids = set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type") not in (None, "", "REG"):
                continue
            if r.get("home_score") in ("", None) or r.get("away_score") in ("", None):
                continue
            game_id, day = str(r.get("game_id") or ""), str(r.get("gameday") or "")
            home, away = str(r.get("home_team") or ""), str(r.get("away_team") or "")
            if not game_id or game_id in ids or not day or not home or not away or home == away:
                raise ValueError(f"BAD_OR_DUPLICATE_GAME_ID:{game_id}")
            ids.add(game_id)
            date.fromisoformat(day)
            hs, aas = finite(r["home_score"], "HOME_SCORE"), finite(r["away_score"], "AWAY_SCORE")
            if hs < 0 or aas < 0 or not hs.is_integer() or not aas.is_integer():
                raise ValueError("BAD_FINAL_SCORE")
            qbh = finite(r.get("home_qb_delta") or 0, "HOME_QB_CHANGE")
            qba = finite(r.get("away_qb_delta") or 0, "AWAY_QB_CHANGE")
            weather = finite(r.get("weather_total_delta") or 0, "WEATHER_TOTAL")
            if abs(qbh) > QB_CAP or abs(qba) > QB_CAP:
                raise ValueError("QB_CHANGE_EXCEEDS_4_POINTS")
            if abs(weather) > WEATHER_CAP:
                raise ValueError("WEATHER_EXCEEDS_RESEARCH_CAP")
            # nflverse's scores/consensus market file does not attest PIT QB
            # announcements or weather. Never let manual retrospective deltas
            # become fitted signal without a separately reviewed as-of adapter.
            if qbh or qba or weather:
                raise ValueError("PIT_QB_WEATHER_CONTEXT_RECEIPT_REQUIRED")
            def close(field):
                return None if r.get(field) in ("", None) else finite(r[field], field)
            out.append(Game(day, game_id, home, away, int(hs), int(aas),
                            close("spread_line"), close("total_line"),
                            str(r.get("neutral_site") or "").lower() in ("1", "true", "yes"),
                            qbh, qba, weather))
    return sorted(out, key=lambda g: (g.day, g.game_id))


def issue(raw: float, close: float) -> float:
    """Immutable proposed issuance formula, at most 0.6 point off market."""
    return close + WEIGHT * max(-DISAGREEMENT_CAP, min(DISAGREEMENT_CAP, raw - close))


def fit_as_of(history: list[Game]) -> tuple[float, float, dict[str, tuple[float, float]]]:
    if len(history) < 32:
        raise ValueError("LEAGUE_PRIOR_SAMPLE_TOO_SMALL")
    level = mean((g.home_score + g.away_score) / 2 for g in history)
    observed = defaultdict(list)
    for g in history:
        side = 0 if g.neutral else 0.5
        observed[g.home].append((g.home_score, g.away_score, g.away, side))
        observed[g.away].append((g.away_score, g.home_score, g.home, -side))
    offense, defense = ({t: 0.0 for t in observed}, {t: 0.0 for t in observed})
    home_games = [g for g in history if not g.neutral]
    fitted_hfa = 0.0
    for _ in range(8):
        new_o = {t: len(rows)/(len(rows)+6) * mean(
                     pf-level-defense[opp]-fitted_hfa*side for pf,pa,opp,side in rows)
                 for t, rows in observed.items()}
        new_d = {t: len(rows)/(len(rows)+6) * mean(
                     pa-level-offense[opp]+fitted_hfa*side for pf,pa,opp,side in rows)
                 for t, rows in observed.items()}
        o_mean, d_mean = mean(new_o.values()), mean(new_d.values())
        offense = {t: value - o_mean for t,value in new_o.items()}
        defense = {t: value - d_mean for t,value in new_d.items()}
        if home_games:
            residuals = [
                (g.home_score-g.away_score) -
                ((offense[g.home]+defense[g.away]) -
                 (offense[g.away]+defense[g.home]))
                for g in home_games
            ]
            fitted_hfa = len(home_games)/(len(home_games)+64) * mean(residuals)
    return level, fitted_hfa, {t:(offense[t],defense[t]) for t in observed}


def _above(center: float, threshold: float, sigma: float) -> float:
    return .5 * (1 + erf((center - threshold)/(sigma*sqrt(2))))


def screen_market(rows: list[dict], name: str) -> dict:
    if not rows:
        return {"market": name, "status": "FAILED_SCREEN", "failures": ["NO_ROWS"], "n": 0}
    mae_model = mean(abs(r["issued"] - r["actual"]) for r in rows)
    mae_close = mean(abs(r["close"] - r["actual"]) for r in rows)
    buckets = [[] for _ in BANDS]
    for r in rows:
        diff = abs(r["raw"]-r["close"])
        i = next(i for i,(lower,upper) in enumerate(BANDS) if lower <= diff < upper)
        buckets[i].append(r)
    bands = [{
        "raw_disagreement_points": [low, high if isfinite(high) else None],
        "n": len(bucket),
        "predicted_cover": mean(r["pred_cover"] for r in bucket) if bucket else None,
        "realized_cover": mean(r["real_cover"] for r in bucket) if bucket else None,
    } for (low,high),bucket in zip(BANDS,buckets)]
    failures = []
    if mae_model > mae_close + 1e-12:
        failures.append("ANCHORED_MAE_EXCEEDS_CONSENSUS_CLOSE")
    if name == "spread" and len(rows) >= 20:
        mx = mean(r["close"] for r in rows)
        my = mean(r["actual"] for r in rows)
        cov = mean((r["close"]-mx)*(r["actual"]-my) for r in rows)
        if cov <= 0:
            failures.append("SPREAD_CLOSE_SIGN_NOT_CONFIRMED")
    if any(b["n"] < BAND_MIN_N for b in bands):
        failures.append("INSUFFICIENT_BAND_N")
    if any(b["predicted_cover"] - b["realized_cover"] > .075 for b in bands if b["n"]):
        failures.append("OVERSTATED_COVER_GT_7_5PP")
    if all(b["n"] >= BAND_MIN_N for b in bands):
        rates = [b["realized_cover"] for b in bands]
        if any(a >= b for a,b in zip(rates,rates[1:])):
            failures.append("NONRISING_REALIZED_COVER_BANDS")
    return {"market":name, "n":len(rows), "anchored_mae":mae_model,
            "consensus_close_mae":mae_close, "bands":bands,
            "failures":failures, "status":"FAILED_SCREEN" if failures else "PASS_DESIGN_SCREEN"}


def screen(games: Iterable[Game], *, design_years: frozenset[int]) -> dict:
    """Same-date isolation + prior-only fitted ratings and sigma."""
    ordered = sorted(games, key=lambda g:(g.day,g.game_id))
    if len({g.game_id for g in ordered}) != len(ordered):
        raise ValueError("DUPLICATE_GAME_IDS")
    history = []
    residuals = {"spread":[], "total":[]}
    samples = {"spread":[], "total":[]}
    skipped = defaultdict(int)
    for day, group in groupby(ordered, key=lambda g:g.day):
        slate = list(group)
        if len(history) < 32:
            skipped["LEAGUE_HISTORY_LT_32"] += len(slate)
            history.extend(slate)
            continue
        level,hfa,ratings = fit_as_of(history)
        n_team = defaultdict(int)
        for g in history:
            n_team[g.home] += 1; n_team[g.away] += 1
        sigma = {k:max(SIGMA_FLOOR,pstdev(v) if len(v)>=20 else 0)
                 for k,v in residuals.items()}
        new_errors = {"spread":[], "total":[]}
        for g in slate:
            if min(n_team[g.home],n_team[g.away]) < 5:
                skipped["TEAM_PRIORS_LT_5"] += 1
                continue
            ho,hd = ratings[g.home]; ao,ad = ratings[g.away]
            home_score = level + ho + ad + (0 if g.neutral else hfa/2) + g.home_qb_delta
            away_score = level + ao + hd - (0 if g.neutral else hfa/2) + g.away_qb_delta
            raw_values = {"spread":home_score-away_score,
                          "total":max(0.0,home_score+away_score+g.weather_total_delta)}
            actual_values = {"spread":g.home_score-g.away_score,
                             "total":g.home_score+g.away_score}
            for k in raw_values:
                new_errors[k].append(raw_values[k]-actual_values[k])
            if int(day[:4]) not in design_years:
                continue
            for k,close in (("spread",g.spread_close),("total",g.total_close)):
                if close is None:
                    skipped["CONSENSUS_CLOSE_MISSING"] += 1
                    continue
                raw,actual = raw_values[k],actual_values[k]
                if raw == close or actual == close:
                    skipped["PUSH_OR_UNDIRECTED"] += 1
                    continue
                center = issue(raw,close)
                p = _above(center,close,sigma[k])
                pick_over = raw > close
                samples[k].append({"game_id":g.game_id,"day":day,"raw":raw,
                                   "close":close,"issued":center,"actual":actual,
                                   "pred_cover":p if pick_over else 1-p,
                                   "real_cover":float(actual>close if pick_over else actual<close)})
        history.extend(slate)
        for k in residuals:
            residuals[k].extend(new_errors[k])
    result = {"schema":"NFL_ANCHORED_RATINGS_V1_DESIGN_SCREEN_V1",
              "engine":"NFL_ANCHORED_RATINGS_V1","status":"FAILED_SCREEN",
              "data_role":"HISTORICAL_NFLVERSE_CONSENSUS_CLOSE_NOT_DK_NOT_CLV",
              "verified_clv":False,"counted_rows":0,"promotion_authority":False,
              "paper_units":0,"design_years":sorted(design_years),
              "assumptions":{"issue_weight":WEIGHT,"raw_disagreement_cap":DISAGREEMENT_CAP,
                             "qb_change_cap":QB_CAP,"weather_total_cap":WEATHER_CAP,
                             "sigma_floor":SIGMA_FLOOR,"band_min_n":BAND_MIN_N,
                             "qb_weather_in_historical_screen":"ZERO_UNLESS_PIT_RECEIPTS_ADMITTED_BY_FUTURE_REVIEW"},
              "skipped":dict(skipped),
              "screens":{k:screen_market(v,k) for k,v in samples.items()}}
    if all(s["status"]=="PASS_DESIGN_SCREEN" for s in result["screens"].values()):
        result["status"]="PASS_DESIGN_SCREEN"
    return result


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nflverse-games-csv",required=True,type=Path)
    p.add_argument("--design-years",default="2023,2024,2025")
    a=p.parse_args()
    years=frozenset(int(s.strip()) for s in a.design_years.split(",") if s.strip())
    if not years:
        raise SystemExit("DESIGN_YEARS_EMPTY")
    out=screen(read_games(a.nflverse_games_csv),design_years=years)
    print(json.dumps(out,sort_keys=True,indent=2))
    return 0 if out["status"]=="PASS_DESIGN_SCREEN" else 2


if __name__=="__main__":
    raise SystemExit(main())
