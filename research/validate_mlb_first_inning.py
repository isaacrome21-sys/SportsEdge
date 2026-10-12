#!/usr/bin/env python3
"""Harness validation for the Phase 1 MLB first-inning model (Isaac's bar).

RUN WITH:  cd ~/workspace/sportsedge-backtest && python \\
               ~/workspace/sportsedge-firstinning/research/validate_mlb_first_inning.py

What it does:
  1. Collects verified MLB StatsAPI linescores for the 2024 + 2025 regular
     seasons (cached; free public data only).
  2. Builds one fixture per completed game with STRICTLY-PRIOR team pools
     (last <=30 games before the fixture date, home/away venue split).
  3. Chronological out-of-sample split: train = 2024 season, test = 2025.
  4. Compares the candidate (team-rate Poisson/Jeffreys model) against a
     NAIVE HISTORICAL-RATE baseline (overall outcome rate in the train
     window -- no market baseline exists; Isaac does not use the Odds API,
     so the baseline leg is documented as naive-rate, not market).
  5. Scores with the harness (Brier, log-loss) and checks calibration via
     reliability bins.

THE BAR (new market -- the existing model cannot price it):
  PASS iff, per market, on out-of-sample fixtures where the candidate
  priced (n >= 100):
    (a) candidate Brier  < naive Brier, AND
    (b) candidate log-loss < naive log-loss, AND
    (c) calibration: in every reliability bin with n >= 30,
        |mean_p - hit_rate| <= 0.10.
  Otherwise FAIL with explicit reasons. No market-baseline leg exists;
  that gap is documented, not filled.

Writes research/first_inning_backtest_report.json (predictions + verdicts).
Research only. No betting authority.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKTEST_ROOT = Path.home() / "workspace" / "sportsedge-backtest"
MY_ROOT = Path.home() / "workspace" / "sportsedge-firstinning"
CACHE_DIR = MY_ROOT / "research" / ".cache_first_inning"
REPORT_PATH = MY_ROOT / "research" / "first_inning_backtest_report.json"

sys.path.insert(0, str(BACKTEST_ROOT))
from sportsedge.backtest.runner import run_backtest, compare_models
from sportsedge.backtest import metrics, splits


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_data = _load("fi_data", MY_ROOT / "sportsedge" / "mlb_first_inning_data.py")
_model = _load("fi_model", MY_ROOT / "sportsedge" / "mlb_first_inning_model.py")

MIN_N = 100
CAL_BIN_MIN_N = 30
CAL_MAX_DEVIATION = 0.10

# (market, selection, line, side) validation keys. _AWAY/_HOME suffixes keep
# (fixture_id, market, selection, line) unique in harness records.
KEYS = []
for _mkt, _side, _ln in [
    ("FIRST_INNING_RUNS", None, 0.5),
    ("FIRST_INNING_TEAM_RUNS_AWAY", "AWAY", 0.5),
    ("FIRST_INNING_TEAM_RUNS_HOME", "HOME", 0.5),
    ("FIRST_INNING_HITS_AWAY", "AWAY", 0.5),
    ("FIRST_INNING_HITS_HOME", "HOME", 0.5),
    ("TEAM_HITS_AWAY", "AWAY", 6.5),
    ("TEAM_HITS_HOME", "HOME", 6.5),
]:
    for _sel in ("OVER", "UNDER"):
        KEYS.append((_mkt, _sel, _ln, _side))


def collect_games():
    src = _data.MLBFirstInningPublicSource(cache_dir=str(CACHE_DIR))
    dates = []
    for chunk in src.schedule_range("2024-03-28", "2025-09-28", chunk_days=7):
        dates.extend(chunk)
    games, skipped = _data.collect_completed_games(dates, game_types=("R",))
    print(f"collected {len(games)} completed regular-season games "
          f"({skipped} skipped)", flush=True)
    return games


def dedupe_games(games):
    """One record per gamePk (rescheduled games can be listed under two
    dates); keep the earliest game_date."""
    seen, dupes, out = set(), 0, []
    for game in games:  # already sorted by (game_date, game_pk)
        if game["game_pk"] in seen:
            dupes += 1
            continue
        seen.add(game["game_pk"])
        out.append(game)
    return out, dupes


def build_fixtures(games):
    histories = _data.build_team_histories(games)
    games_by_pk = {g["game_pk"]: g for g in games}
    fixtures = []
    for game in games:
        kickoff = datetime.fromisoformat(
            game["game_date"].replace("Z", "+00:00")).astimezone(timezone.utc)
        as_of = kickoff - timedelta(hours=1)
        try:
            pools_away = _data.prior_pools(
                histories, game["away_id"], was_home=False,
                before_iso=game["game_date"])
            pools_home = _data.prior_pools(
                histories, game["home_id"], was_home=True,
                before_iso=game["game_date"])
        except _data.FirstInningDataError:
            continue
        fixtures.append({
            "fixture_id": game["game_pk"],
            "kickoff": kickoff.isoformat(),
            "as_of": as_of.isoformat(),
            "pools_away": pools_away,
            "pools_home": pools_home,
            "probable_away_pitcher": game["probable_away_pitcher"],
            "probable_home_pitcher": game["probable_home_pitcher"],
            "settle": {
                "i1_away_runs": game["inn1_away_runs"],
                "i1_home_runs": game["inn1_home_runs"],
                "i1_away_hits": game["inn1_away_hits"],
                "i1_home_hits": game["inn1_home_hits"],
                "g_away_hits": game["game_away_hits"],
                "g_home_hits": game["game_home_hits"],
            },
        })
    fixtures.sort(key=lambda f: f["kickoff"])
    print(f"{len(fixtures)} fixtures with team histories", flush=True)
    return fixtures, games_by_pk


def build_starter_pools(fixtures, games_by_pk, label):
    """Verified 1st-inning runs-allowed per probable starter, strictly prior.

    Returns {fixture_id: (away_allowed, home_allowed)} with missing entries
    where the starter gate fails. gameLogs are cached; one fetch per
    (pitcher, season).
    """
    src = _data.MLBFirstInningPublicSource(cache_dir=str(CACHE_DIR))
    log_cache = {}

    def starts_for(pid):
        if pid not in log_cache:
            log_cache[pid] = _data.pitcher_prior_starts(
                pid, seasons=(2024, 2025), source=src)
        return log_cache[pid]

    out = {}
    n_ok = n_fail = 0
    for fx in fixtures:
        before = fx["kickoff"][:10]
        pair = []
        ok = True
        for key in ("probable_away_pitcher", "probable_home_pitcher"):
            info = fx.get(key) or {}
            pid = info.get("id")
            if pid is None:
                ok = False
                break
            prior = [s for s in starts_for(pid) if s["date"] < before][
                -_data.MAX_STARTER_STARTS:]
            allowed = []
            for s in prior:
                game = games_by_pk.get(s["game_pk"])
                if game is None:
                    continue
                if s["team_id"] == game["away_id"]:
                    allowed.append(game["inn1_home_runs"])
                elif s["team_id"] == game["home_id"]:
                    allowed.append(game["inn1_away_runs"])
            if len(allowed) < _data.MIN_STARTER_STARTS:
                ok = False
                break
            pair.append(allowed)
        if ok:
            out[fx["fixture_id"]] = (pair[0], pair[1])
            n_ok += 1
        else:
            n_fail += 1
    print(f"starter pools ({label}): {n_ok} fixtures verifiable, "
          f"{n_fail} fail-closed", flush=True)
    return out


def settle_fixture(fixture, market, selection, line):
    s = fixture["settle"]
    if market == "FIRST_INNING_RUNS":
        total = s["i1_away_runs"] + s["i1_home_runs"]
        won = (total >= 1) if selection == "OVER" else (total == 0)
    elif market == "FIRST_INNING_TEAM_RUNS_AWAY":
        won = (s["i1_away_runs"] >= 1) if selection == "OVER" else (s["i1_away_runs"] == 0)
    elif market == "FIRST_INNING_TEAM_RUNS_HOME":
        won = (s["i1_home_runs"] >= 1) if selection == "OVER" else (s["i1_home_runs"] == 0)
    elif market == "FIRST_INNING_HITS_AWAY":
        won = (s["i1_away_hits"] >= 1) if selection == "OVER" else (s["i1_away_hits"] == 0)
    elif market == "FIRST_INNING_HITS_HOME":
        won = (s["i1_home_hits"] >= 1) if selection == "OVER" else (s["i1_home_hits"] == 0)
    elif market == "TEAM_HITS_AWAY":
        won = (s["g_away_hits"] > line) if selection == "OVER" else (s["g_away_hits"] < line)
    elif market == "TEAM_HITS_HOME":
        won = (s["g_home_hits"] > line) if selection == "OVER" else (s["g_home_hits"] < line)
    else:
        raise ValueError("VALIDATION_MARKET_UNKNOWN:" + market)
    return 1.0 if won else 0.0


def starter_lambda_total(fixture, pools):
    """Raw (uncalibrated) total 1st-inning run expectancy, or None."""
    if not pools:
        return None
    pa, ph = fixture["pools_away"], fixture["pools_home"]
    away_allowed, home_allowed = pools
    try:
        out = _model.price_game_first_inning_runs_with_starter(
            away_for=pa["inn1_for"], home_starter_allowed=home_allowed,
            home_for=ph["inn1_for"], away_starter_allowed=away_allowed,
            line=0.5)
        return out["lambda_away"] + out["lambda_home"]
    except _model.FirstInningModelError:
        return None


def fit_calibration(train, starter_pools):
    """One-parameter train-only calibration: shrink raw lambda toward the
    train mean. p = 1 - exp(-(w*lam + (1-w)*lam_bar)); w picked by grid
    search minimizing Brier on TRAIN predictions only. No test peeking."""
    rows = []
    for fx in train:
        pools = starter_pools.get(fx["fixture_id"])
        lam = starter_lambda_total(fx, pools)
        if lam is None:
            continue
        y = settle_fixture(fx, "FIRST_INNING_RUNS", "OVER", 0.5)
        rows.append((lam, y))
    lam_bar = sum(l for l, _ in rows) / len(rows)
    best_w, best_b = 1.0, float("inf")
    w = 0.0
    while w <= 1.001:
        b = sum(( (1 - __import__("math").exp(-(w * l + (1 - w) * lam_bar))) - y) ** 2
                for l, y in rows) / len(rows)
        if b < best_b:
            best_b, best_w = b, w
        w += 0.05
    print(f"calibration fit on train: n={len(rows)} lam_bar={lam_bar:.4f} "
          f"w={best_w:.2f} train_brier={best_b:.4f}", flush=True)
    return best_w, lam_bar


def binary_predictions(fixture, pools):
    """Binary-indicator starter model (the harness candidate).

    Returns game YRFI/NRFI plus per-team 1st-inning over/under 0.5
    (the per-half scoring probabilities are the team-run markets).
    """
    if not pools:
        return []
    pa, ph = fixture["pools_away"], fixture["pools_home"]
    away_allowed, home_allowed = pools
    try:
        out = _model.price_first_inning_binary(
            away_score_ind=[1 if v >= 1 else 0 for v in pa["inn1_for"]],
            home_starter_allow_ind=[1 if v >= 1 else 0 for v in home_allowed],
            home_score_ind=[1 if v >= 1 else 0 for v in ph["inn1_for"]],
            away_starter_allow_ind=[1 if v >= 1 else 0 for v in away_allowed],
        )
        return [("FIRST_INNING_RUNS", "OVER", 0.5, out["p_over"]),
                ("FIRST_INNING_RUNS", "UNDER", 0.5, out["p_under"]),
                ("FIRST_INNING_TEAM_RUNS_AWAY", "OVER", 0.5,
                 out["p_away_scores"]),
                ("FIRST_INNING_TEAM_RUNS_AWAY", "UNDER", 0.5,
                 1.0 - out["p_away_scores"]),
                ("FIRST_INNING_TEAM_RUNS_HOME", "OVER", 0.5,
                 out["p_home_scores"]),
                ("FIRST_INNING_TEAM_RUNS_HOME", "UNDER", 0.5,
                 1.0 - out["p_home_scores"])]
    except _model.FirstInningModelError:
        return []


def candidate_predictions(fixture, starter_model=False,
                          starter_pools=None):
    pa, ph = fixture["pools_away"], fixture["pools_home"]
    preds = []
    if starter_model:
        if not starter_pools:
            return []
        away_allowed, home_allowed = starter_pools
        try:
            out = _model.price_game_first_inning_runs_with_starter(
                away_for=pa["inn1_for"],
                home_starter_allowed=home_allowed,
                home_for=ph["inn1_for"],
                away_starter_allowed=away_allowed,
                line=0.5)
            preds.append(("FIRST_INNING_RUNS", "OVER", 0.5, out["p_over"]))
            preds.append(("FIRST_INNING_RUNS", "UNDER", 0.5, out["p_under"]))
        except _model.FirstInningModelError:
            pass
        return preds
    try:
        out = _model.price_game_first_inning_runs(
            away_for=pa["inn1_for"], home_against=ph["inn1_against"],
            home_for=ph["inn1_for"], away_against=pa["inn1_against"], line=0.5)
        preds.append(("FIRST_INNING_RUNS", "OVER", 0.5, out["p_over"]))
        preds.append(("FIRST_INNING_RUNS", "UNDER", 0.5, out["p_under"]))
    except _model.FirstInningModelError:
        pass
    for mkt, side, stat_for, stat_against, ln, fn in [
        ("FIRST_INNING_TEAM_RUNS_AWAY", "AWAY", "inn1_for", "inn1_against", 0.5,
         _model.price_team_first_inning),
        ("FIRST_INNING_TEAM_RUNS_HOME", "HOME", "inn1_for", "inn1_against", 0.5,
         _model.price_team_first_inning),
        ("FIRST_INNING_HITS_AWAY", "AWAY", "inn1_hits_for", "inn1_hits_against", 0.5,
         _model.price_team_first_inning),
        ("FIRST_INNING_HITS_HOME", "HOME", "inn1_hits_for", "inn1_hits_against", 0.5,
         _model.price_team_first_inning),
    ]:
        pools = pa if side == "AWAY" else ph
        model_market = ("FIRST_INNING_TEAM_RUNS" if "TEAM_RUNS" in mkt
                        else "FIRST_INNING_HITS")
        try:
            out = fn(model_market,
                     team_for=pools[stat_for], team_against=pools[stat_against],
                     line=ln)
            preds.append((mkt, "OVER", ln, out["p_over"]))
            preds.append((mkt, "UNDER", ln, out["p_under"]))
        except _model.FirstInningModelError:
            pass
    for mkt, side in [("TEAM_HITS_AWAY", "AWAY"), ("TEAM_HITS_HOME", "HOME")]:
        pools = pa if side == "AWAY" else ph
        try:
            out = _model.price_team_hits(team_for=pools["game_hits_for"],
                                         team_against=pools["game_hits_against"],
                                         line=6.5)
            preds.append((mkt, "OVER", 6.5, out["p_over"]))
            preds.append((mkt, "UNDER", 6.5, out["p_under"]))
        except _model.FirstInningModelError:
            pass
    return preds


def main():
    games = collect_games()
    games, dupes = dedupe_games(games)
    print(f"{dupes} duplicate gamePk listings removed", flush=True)
    fixtures, games_by_pk = build_fixtures(games)
    split = splits.fixed_split(fixtures, cutoff="2025-01-01T00:00:00+00:00")
    train, test = split.train, split.test
    print(f"train={len(train)} (2024) test={len(test)} (2025)", flush=True)
    starter_pools_train = build_starter_pools(train, games_by_pk, "train")
    starter_pools_test = build_starter_pools(test, games_by_pk, "test")
    starter_pools = {**starter_pools_train, **starter_pools_test}
    cal_w, cal_lam_bar = fit_calibration(train, starter_pools_train)

    # Naive historical-rate baseline: outcome rate per (market, selection,
    # line) over the train window. Team markets pool both sides.
    naive_sums, naive_counts = {}, {}
    for fx in train:
        for mkt, sel, ln, _side in KEYS:
            base = mkt.replace("_AWAY", "").replace("_HOME", "")
            key = (base, sel, ln)
            y = settle_fixture(fx, mkt, sel, ln)
            naive_sums[key] = naive_sums.get(key, 0.0) + y
            naive_counts[key] = naive_counts.get(key, 0) + 1
    naive_rates = {k: min(1 - 1e-6, max(1e-6, naive_sums[k] / naive_counts[k]))
                   for k in naive_sums}

    def price_fn(model, fixture, as_of, train_fixtures):
        preds = []
        if model == "first_inning_team_rates":
            for mkt, sel, ln, p in candidate_predictions(fixture):
                preds.append({"market": mkt, "selection": sel, "line": ln,
                              "model_p": p})
        elif model == "first_inning_with_starter":
            pools = starter_pools.get(fixture["fixture_id"])
            for mkt, sel, ln, p in candidate_predictions(
                    fixture, starter_model=True, starter_pools=pools):
                preds.append({"market": mkt, "selection": sel, "line": ln,
                              "model_p": p})
        elif model == "first_inning_starter_calibrated":
            import math
            pools = starter_pools.get(fixture["fixture_id"])
            lam = starter_lambda_total(fixture, pools)
            if lam is not None:
                p_over = min(1 - 1e-6, max(1e-6,
                             1 - math.exp(-(cal_w * lam + (1 - cal_w) * cal_lam_bar))))
                preds.append({"market": "FIRST_INNING_RUNS",
                              "selection": "OVER", "line": 0.5,
                              "model_p": p_over})
                preds.append({"market": "FIRST_INNING_RUNS",
                              "selection": "UNDER", "line": 0.5,
                              "model_p": 1 - p_over})
        elif model == "first_inning_binary_starter":
            pools = starter_pools.get(fixture["fixture_id"])
            for mkt, sel, ln, p in binary_predictions(fixture, pools):
                preds.append({"market": mkt, "selection": sel, "line": ln,
                              "model_p": p})
        elif model == "naive_historical_rate":
            for mkt, sel, ln, _side in KEYS:
                base = mkt.replace("_AWAY", "").replace("_HOME", "")
                p = naive_rates.get((base, sel, ln))
                if p is None:
                    continue
                preds.append({"market": mkt, "selection": sel, "line": ln,
                              "model_p": p})
        else:
            raise ValueError("VALIDATION_MODEL_UNKNOWN:" + model)
        return preds

    def settle_fn(fixture, market, selection, line):
        return settle_fixture(fixture, market, selection, line)

    result = run_backtest(fixtures=fixtures, splits=[split],
                          models=["first_inning_team_rates",
                                  "first_inning_with_starter",
                                  "first_inning_starter_calibrated",
                                  "first_inning_binary_starter",
                                  "naive_historical_rate"],
                          price_fn=price_fn, settle_fn=settle_fn)
    compared = compare_models(result)
    print(json.dumps({m: compared["models"][m]
                      for m in compared["models"]}, indent=1))

    # Head-to-head per market on aligned records (only fixtures the
    # candidate priced), plus calibration and the verdict.
    naive_recs = result["records"]["naive_historical_rate"]
    naive_by_key = {(r["fixture_id"], r["market"], r["selection"], r["line"]): r
                    for r in naive_recs}
    verdicts = {}
    report_records = {"naive_historical_rate": [
        [r["fixture_id"], r["market"], r["selection"], r["line"],
         round(r["model_p"], 6), r["outcome"]] for r in naive_recs]}
    for model in ("first_inning_team_rates", "first_inning_with_starter",
                  "first_inning_starter_calibrated",
                  "first_inning_binary_starter"):
        cand_recs = result["records"][model]
        report_records[model] = []
        markets = sorted({r["market"] for r in cand_recs})
        for mkt in markets:
            cands = [r for r in cand_recs if r["market"] == mkt]
            aligned_c, aligned_n = [], []
            for r in cands:
                n = naive_by_key.get((r["fixture_id"], r["market"],
                                      r["selection"], r["line"]))
                if n is None:
                    continue
                aligned_c.append(r)
                aligned_n.append(n)
            n = len(aligned_c)
            vkey = model + "::" + mkt
            entry = {"model": model, "market": mkt, "n": n,
                     "candidate": None, "naive": None,
                     "calibration": None, "verdict": None, "reasons": []}
            if n < MIN_N:
                entry["verdict"] = "FAIL"
                entry["reasons"].append(f"INSUFFICIENT_SAMPLE:n={n}<{MIN_N}")
                verdicts[vkey] = entry
                continue
            cs, ns = metrics.summarize(aligned_c), metrics.summarize(aligned_n)
            entry["candidate"] = cs
            entry["naive"] = ns
            bins = metrics.calibration_bins(aligned_c, n_bins=10)
            entry["calibration"] = bins
            worst = 0.0
            for b in bins:
                if b["n"] is not None and b["n"] >= CAL_BIN_MIN_N \
                        and b["mean_p"] is not None and b["hit_rate"] is not None:
                    worst = max(worst, abs(b["mean_p"] - b["hit_rate"]))
            entry["worst_calibration_deviation"] = round(worst, 4)
            reasons = []
            if not (cs["brier"] < ns["brier"]):
                reasons.append(f"BRIER_NOT_BETTER:cand={cs['brier']:.4f}_vs_naive={ns['brier']:.4f}")
            if not (cs["log_loss"] < ns["log_loss"]):
                reasons.append(f"LOGLOSS_NOT_BETTER:cand={cs['log_loss']:.4f}_vs_naive={ns['log_loss']:.4f}")
            if worst > CAL_MAX_DEVIATION:
                reasons.append(f"MISCALIBRATED:worst_bin_deviation={worst:.3f}")
            entry["verdict"] = "PASS" if not reasons else "FAIL"
            entry["reasons"] = reasons
            verdicts[vkey] = entry
            for r in aligned_c:
                report_records[model].append(
                    [r["fixture_id"], r["market"], r["selection"], r["line"],
                     round(r["model_p"], 6), r["outcome"]])

    print("\n=== PER-MARKET VERDICTS (bar: beat naive on Brier AND log-loss, "
          "n>=100, calibration |mean_p-hit_rate|<=0.10 in bins n>=30) ===")
    for vkey in sorted(verdicts):
        v = verdicts[vkey]
        c, nv = v["candidate"], v["naive"]
        if c is None:
            print(f"{vkey}: {v['verdict']} ({'; '.join(v['reasons'])})")
        else:
            print(f"{vkey}: {v['verdict']} n={v['n']} "
                  f"brier {c['brier']:.4f} vs {nv['brier']:.4f} | "
                  f"logloss {c['log_loss']:.4f} vs {nv['log_loss']:.4f} | "
                  f"worst_cal_dev {v['worst_calibration_deviation']:.3f} "
                  f"{'; '.join(v['reasons'])}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({
        "schema": "SPORTSEDGE_FIRST_INNING_BACKTEST_V1",
        "bar": ("PASS iff per market: n>=100, candidate Brier < naive Brier, "
                "candidate log-loss < naive log-loss, and calibration "
                "|mean_p-hit_rate|<=0.10 in all reliability bins with n>=30. "
                "No market baseline exists (no Odds API); the baseline leg is "
                "the naive historical train-window rate, documented as such."),
        "model_version": _model.FIRST_INNING_MODEL_VERSION,
        "data_version": _data.FIRST_INNING_DATA_VERSION,
        "design": ("train=2024 regular season, test=2025 regular season; "
                   "features strictly prior (game_date < fixture date); "
                   "team pools capped at last 30, min 10 per pool; starter "
                   "pools: last 15 verified starts, min 5, 1st-inning runs "
                   "allowed from gameLog starts x verified linescores; "
                   "Jeffreys-smoothed Poisson rates, 50/50 offense/(defense or "
                   "starter) blend, independent halves; no league priors, "
                   "no odds. Verdict keys are 'model::market'."),
        "n_train": len(train),
        "n_test": len(test),
        "verdicts": verdicts,
        "records": report_records,
        "research_only": True,
    }, indent=1) + "\n", encoding="utf-8")
    print("\nreport:", REPORT_PATH)


if __name__ == "__main__":
    main()
