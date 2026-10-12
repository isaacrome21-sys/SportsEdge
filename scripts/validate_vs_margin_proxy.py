#!/usr/bin/env python3
"""Harness validation: Elo-ratings means vs margin_proxy means, per sport.

Compares, out-of-sample and chronologically:

* ``margin_proxy`` (existing): team_half_pricing's exact construction —
  recent score differentials x 0.15, capped at +/-4.0, min 3 games —
  feeding ``base + hfa/2`` score means.
* ``elo_ratings`` (candidate): ``sportsedge.ratings`` opponent-adjusted Elo
  strength feeding the same mean construction.

Both models price ML, SPREAD (pick'em, line=0) and TOTAL (vs the league
mean total) through ``free_models.model_probability``. Settled against
verified historical scores from free endpoints (ESPN scoreboard for
NFL/CFB/NBA, MLB StatsAPI for MLB), cached locally.

Isaac's bar: the candidate must beat the existing model on BOTH Brier
score and log-loss. No historical market baseline exists (no Odds API by
Isaac's choice), so the best achievable verdict is CONDITIONAL_PASS.

Usage (from the repo root of the elo branch)::

    PYTHONPATH=~/workspace/sportsedge-elo:~/workspace/sportsedge-backtest \\
        python3 scripts/validate_vs_margin_proxy.py [--sports NFL,CFB] \\
        [--cache-dir PATH] [--json-out PATH]

Research only. Fail closed. Market-blind (no market prices anywhere).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- repo path setup: this script lives in the elo branch -------------------
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sportsedge.ratings import RatingProvider  # noqa: E402
from sportsedge.ratings.history import GameRecord  # noqa: E402


def _need_backtest():
    """Load the harness from the backtest worktree under a synthetic package
    name (``hb``): the elo branch's ``sportsedge`` package would otherwise
    shadow ``sportsedge.backtest`` on a shared sys.path."""
    import importlib.util
    import os
    import types
    bt = Path(os.environ.get(
        "BACKTEST_WORKTREE",
        str(Path.home() / "workspace" / "sportsedge-backtest")))
    bt_pkg_dir = bt / "sportsedge" / "backtest"
    if not (bt_pkg_dir / "runner.py").exists():
        sys.exit("BACKTEST_WORKTREE_REQUIRED: no harness at " + str(bt_pkg_dir)
                 + " (set BACKTEST_WORKTREE)")
    pkg = types.ModuleType("hb")
    pkg.__path__ = [str(bt_pkg_dir)]
    sys.modules["hb"] = pkg
    loaded = {}
    for name in ("metrics", "outcomes", "splits", "runner", "report"):
        spec = importlib.util.spec_from_file_location(
            f"hb.{name}", bt_pkg_dir / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"hb.{name}"] = mod
        spec.loader.exec_module(mod)
        loaded[name] = mod
    fm_path = bt / "artifacts" / "free_models.py"
    spec = importlib.util.spec_from_file_location("bt_free_models", fm_path)
    fm = importlib.util.module_from_spec(spec)
    sys.modules["bt_free_models"] = fm
    spec.loader.exec_module(fm)
    return (loaded["outcomes"], loaded["splits"], loaded["runner"],
            loaded["metrics"], loaded["report"], fm.PRIORS, fm.model_probability)


outcomes, splits, runner, metrics, report, PRIORS, model_probability = _need_backtest()

CACHE_DEFAULT = Path.home() / "workspace" / ".cache" / "ratings_val"

# Per-day fetch windows (YYYY-MM-DD). ESPN's scoreboard now ignores the
# legacy ?season=&week= params (returns the current season), so history is
# collected with ?dates=YYYYMMDD per day. Regular seasons only.
DAY_WINDOWS = {
    "NFL": [("2022-09-08", "2023-01-08"), ("2023-09-07", "2024-01-07"),
            ("2024-09-05", "2025-01-05"), ("2025-09-04", "2025-10-11")],
    "CFB": [("2022-08-27", "2022-12-10"), ("2023-08-26", "2023-12-09"),
            ("2024-08-24", "2024-12-14"), ("2025-08-23", "2025-10-11")],
    "NBA": [("2023-10-24", "2024-04-14"), ("2024-10-22", "2025-04-13")],
}
MLB_MONTHS = [(y, m) for y in (2022, 2023, 2024, 2025) for m in range(4, 11)]


def _dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _polite(delay=0.25):
    time.sleep(delay)


# ---------------------------------------------------------------- fetching

def fetch_espn_days(sport, cache_dir):
    """Per-day ESPN scoreboard fetches over the sport's season windows."""
    games = []
    n_days = 0
    for start, end in DAY_WINDOWS[sport]:
        day = datetime.strptime(start, "%Y-%m-%d").date()
        last = datetime.strptime(end, "%Y-%m-%d").date()
        while day <= last:
            stamp = day.strftime("%Y%m%d")
            try:
                if sport == "NBA":
                    # The harness never wired NBA scoreboard; fetch the same
                    # free endpoint directly with identical verified parsing.
                    events = _nba_day_events(stamp, cache_dir)
                else:
                    events = outcomes.fetch_football_scoreboard(
                        sport.lower(), dates=stamp, cache_dir=cache_dir)
                games.extend(outcomes.parse_completed_football_games(events))
            except Exception as exc:  # a single bad day must not kill the run
                print(f"  [warn] {sport} {stamp}: {exc}", file=sys.stderr)
            day += timedelta(days=1)
            n_days += 1
            _polite(0.2)
    print(f"  fetched {n_days} days", flush=True)
    return games


NBA_SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports"
                  "/basketball/nba/scoreboard")


def _nba_day_events(stamp, cache_dir):
    """Direct NBA scoreboard fetch (free, no key) with harness-style cache."""
    import hashlib
    import urllib.request
    url = NBA_SCOREBOARD + "?dates=" + stamp
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = Path(cache_dir) / (key + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("events") or []
    req = urllib.request.Request(
        url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError("NBA_SOURCE_UNAVAILABLE:" + stamp)
        data = json.loads(resp.read(8_000_000).decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("NBA_SOURCE_MALFORMED:" + stamp)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data.get("events") or []


def fetch_mlb(cache_dir):
    games = []
    for year, month in MLB_MONTHS:
        if year == 2025 and month > 10:
            continue
        start = f"{year}-{month:02d}-01"
        end = f"{year}-{month:02d}-28"  # safe upper bound; schedule trims
        if month == 2:
            end = f"{year}-{month:02d}-28"
        # last-day clamp: use calendar month length simply
        import calendar
        end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        dates = outcomes.fetch_mlb_schedule(start, end, cache_dir=cache_dir)
        games.extend(outcomes.parse_completed_mlb_games(dates))
        _polite()
    return games


def to_records(sport, raw_games):
    records = []
    seen = set()
    for g in raw_games:
        eid = str(g.get("event_id") or "").strip()
        if eid:
            if eid in seen:
                continue  # same game surfaced by two fetches; keep first
            seen.add(eid)
        records.append(GameRecord(
            kickoff=_dt(g["kickoff"]), home=g["home_team"], away=g["away_team"],
            home_score=int(g["home_score"]), away_score=int(g["away_score"]),
            event_id=g["event_id"]))
    records.sort(key=lambda r: r.kickoff)
    return records


def make_fixtures(sport, records):
    from sportsedge.ratings.history import season_label
    fixtures = []
    for i, rec in enumerate(records):
        kickoff = rec.kickoff.astimezone(timezone.utc)
        fixtures.append({
            "fixture_id": f"{sport}-{rec.event_id or i}",
            "sport": sport,
            "kickoff": kickoff.isoformat(),
            "as_of": (kickoff - timedelta(hours=2)).isoformat(),
            "home": rec.home, "away": rec.away,
            "season": season_label(sport, kickoff),
            "game": {"home_score": rec.home_score, "away_score": rec.away_score},
        })
    return fixtures


# ------------------------------------------------------------------ models

def margin_proxy_value(team_games):
    """Exact team_half_pricing construction."""
    if len(team_games) < 3:
        return 0.0
    diffs = [own - opp for _, own, opp in team_games]
    return max(-4.0, min(4.0, sum(diffs) / len(diffs) * 0.15))


class ModelCache:
    """Per-split histories: tracker (candidate) + per-team games (existing)."""

    def __init__(self):
        self._memo = {}

    def for_split(self, sport, train):
        key = id(train)
        if key not in self._memo:
            provider = RatingProvider(sport)
            team_games: dict[str, list] = {}
            for fx in train:
                kickoff = _dt(fx["kickoff"])
                home, away = fx["home"], fx["away"]
                hs, aws = fx["game"]["home_score"], fx["game"]["away_score"]
                season = fx.get("season")
                provider.tracker.record_game(
                    date=kickoff, home=home, away=away,
                    home_score=hs, away_score=aws, season=season)
                for team, own, opp in ((home, hs, aws), (away, aws, hs)):
                    k = team.strip().lower()
                    team_games.setdefault(k, []).append((kickoff, own, opp))
            self._memo[key] = (provider, team_games)
        return self._memo[key]


def clip(p):
    return min(1.0 - 1e-9, max(1e-9, p))


def price_fixture(sport, model, fixture, as_of, provider, team_games):
    base, _, _, hfa = PRIORS[sport]
    kickoff = _dt(fixture["kickoff"])
    home, away = fixture["home"], fixture["away"]
    if model == "elo_ratings":
        hs = provider.strength_or_zero(home, kickoff).strength_points
        aws = provider.strength_or_zero(away, kickoff).strength_points
    else:
        hs = margin_proxy_value(team_games.get(home.strip().lower(), []))
        aws = margin_proxy_value(team_games.get(away.strip().lower(), []))
    home_mean = base + hfa / 2 + hs
    away_mean = base - hfa / 2 + aws
    if min(home_mean, away_mean) < 0.2:
        return []  # implausible: skip for both models (production raises)
    preds = []
    win, _ = model_probability(sport, "ML", "HOME", None, home_mean, away_mean)
    preds.append({"market": "ML", "selection": "HOME", "line": None,
                  "model_p": clip(win)})
    win, _ = model_probability(sport, "SPREAD", "HOME", 0.0, home_mean, away_mean)
    preds.append({"market": "SPREAD", "selection": "HOME", "line": 0.0,
                  "model_p": clip(win)})
    total_line = round(2 * base, 1)
    win, _ = model_probability(sport, "TOTAL", "OVER", total_line,
                               home_mean, away_mean)
    preds.append({"market": "TOTAL", "selection": "OVER", "line": total_line,
                  "model_p": clip(win)})
    return preds


# -------------------------------------------------------------------- main

SPLIT_CFG = {
    "NFL": {"min_train": 250, "test_size": 150, "step": 4},
    "CFB": {"min_train": 800, "test_size": 400, "step": 6},
    "NBA": {"min_train": 800, "test_size": 400, "step": 6},
    "MLB": {"min_train": 1200, "test_size": 600, "step": 8},
}


def run_sport(sport, cache_dir):
    print(f"== {sport}: fetching history", flush=True)
    if sport == "MLB":
        raw = fetch_mlb(cache_dir)
    else:
        raw = fetch_espn_days(sport, cache_dir)
    records = to_records(sport, raw)
    print(f"== {sport}: {len(records)} verified games", flush=True)
    fixtures = make_fixtures(sport, records)
    cfg = SPLIT_CFG[sport]
    split_list = list(splits.walk_forward_splits(
        fixtures, min_train=cfg["min_train"], test_size=cfg["test_size"],
        step=cfg["step"], embargo_days=1))
    print(f"== {sport}: {len(split_list)} walk-forward splits", flush=True)
    if not split_list:
        return {"sport": sport, "error": "NO_SPLITS", "n_games": len(records)}

    cache = ModelCache()

    def price_fn(model, fixture, as_of, train):
        provider, team_games = cache.for_split(sport, train)
        return price_fixture(sport, model, fixture, as_of, provider, team_games)

    def settle_fn(fixture, market, selection, line):
        return outcomes.settle_game(fixture["game"], market, selection, line)

    result = runner.run_backtest(
        fixtures=fixtures, splits=split_list,
        models=["margin_proxy", "elo_ratings"],
        price_fn=price_fn, settle_fn=settle_fn)
    recs = result["records"]
    summ = {m: metrics.summarize(recs[m]) for m in ("margin_proxy", "elo_ratings")}
    verdict = report.evaluate(candidate=summ["elo_ratings"],
                              existing=summ["margin_proxy"],
                              baseline=None, baseline_status="MISSING")
    return {"sport": sport, "n_games": len(records),
            "n_splits": result["n_splits"],
            "predictions": {m: summ[m]["n"] for m in summ},
            "margin_proxy": summ["margin_proxy"],
            "elo_ratings": summ["elo_ratings"],
            "verdict": verdict["verdict"], "reasons": verdict["reasons"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", default="NFL,CFB,NBA,MLB")
    ap.add_argument("--cache-dir", default=str(CACHE_DEFAULT))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for sport in [s.strip().upper() for s in args.sports.split(",") if s.strip()]:
        try:
            results.append(run_sport(sport, str(cache_dir)))
        except Exception as exc:  # one sport failing must not hide others
            results.append({"sport": sport, "error": f"{type(exc).__name__}: {exc}"})
            print(f"!! {sport} failed: {exc}", file=sys.stderr)

    for r in results:
        print(json.dumps(r, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2))
        print("wrote", args.json_out)


if __name__ == "__main__":
    main()
