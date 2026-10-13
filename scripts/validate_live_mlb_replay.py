#!/usr/bin/env python3
"""Harness validation: MLB live in-game ML repricing via tick-by-tick replay.

Replays completed 2025 MLB games at half-inning boundaries using archived
StatsAPI play-by-play (feed/live works for historical games). At each tick
the live repricing (sportsedge.live_reprice.reprice_mlb) is compared against
holding the static pregame probability.

- candidate model: live-updated P(HOME) from current state
- existing model: static pregame P(HOME) (same means estimator, so the
  comparison isolates the live-update factor)
- market baseline: MISSING (no Odds API by Isaac's choice) -> best verdict
  is CONDITIONAL_PASS.

Pregame means (documented simple estimator, no lookahead): for each team,
mean runs scored / allowed over its <=20 games before the fixture date
(requires >=5); home_mean = (home_rs + away_ra)/2,
away_mean = (away_rs + home_ra)/2.

Ticks stop at baseball-rules finality (walk-offs, home lead after top 9th+).

RUN WITH: cwd=~/workspace/sportsedge-backtest
  python3 ~/workspace/sportsedge-live/scripts/validate_live_mlb_replay.py

Network: free StatsAPI only, cached under
~/workspace/sportsedge-live/data/live_validation_cache. 429 -> hard stop.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

LIVE_ROOT = Path("/home/hatch/workspace/sportsedge-live")
BACKTEST_ROOT = Path("/home/hatch/workspace/sportsedge-backtest")

# Both repos have a top-level `sportsedge` package. Import the backtest
# harness modules FIRST (bound to local aliases), then switch sys.path so
# the live branch's `sportsedge` resolves for the live modules.
sys.path.insert(0, str(BACKTEST_ROOT))
from sportsedge.backtest import metrics as bt_metrics  # noqa: E402
from sportsedge.backtest import report as bt_report  # noqa: E402
sys.path.remove(str(BACKTEST_ROOT))
sys.path.insert(0, str(LIVE_ROOT))
for _mod in [m for m in list(sys.modules)
             if m == "sportsedge" or m.startswith("sportsedge.")]:
    if not _mod.startswith("sportsedge.backtest"):
        del sys.modules[_mod]

from sportsedge.live_reprice import reprice_mlb  # noqa: E402
from sportsedge.live_state import MLBGameState  # noqa: E402
from sportsedge.live_validation import (  # noqa: E402
    LiveEvaluationRow, brier_vs_market)

metrics, report = bt_metrics, bt_report

CACHE_DIR = LIVE_ROOT / "data" / "live_validation_cache"
REPORT_PATH = LIVE_ROOT / "data" / "live_validation_report.json"

GAME_DATES = ["2025-04-15", "2025-05-13", "2025-06-10",
              "2025-07-08", "2025-08-05", "2025-09-02"]
MAX_GAMES = 45
MIN_PRIOR_GAMES = 5
PRIOR_WINDOW_DAYS = 45
MAX_PRIOR_USED = 20
REQUEST_SPACING = 0.35
NOW = datetime.now(timezone.utc)


class RateLimited(RuntimeError):
    pass


def get_json(url: str):
    key = hashlib.sha1(url.encode()).hexdigest()
    path = CACHE_DIR / (key + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    time.sleep(REQUEST_SPACING)
    req = Request(url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                                "Accept": "application/json"})
    try:
        with urlopen(req, timeout=60) as r:
            if r.status == 429:
                raise RateLimited(url)
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        if "429" in type(exc).__name__ or "429" in str(exc):
            raise RateLimited(url) from exc
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def schedule_games(start: str, end: str):
    url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1"
           f"&startDate={start}&endDate={end}")
    data = get_json(url)
    games = []
    for day in data.get("dates") or []:
        for g in day.get("games") or []:
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            teams = g.get("teams") or {}
            try:
                games.append({
                    "game_pk": int(g["gamePk"]),
                    "date": day.get("date"),
                    "away_id": int(teams["away"]["team"]["id"]),
                    "home_id": int(teams["home"]["team"]["id"]),
                    "away_name": teams["away"]["team"]["name"],
                    "home_name": teams["home"]["team"]["name"],
                    "away_score": int(teams["away"]["score"]),
                    "home_score": int(teams["home"]["score"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
    return games


def team_histories(game_date: str):
    """Per-team list of (date, runs_scored, runs_allowed) before game_date."""
    end = (date.fromisoformat(game_date) - timedelta(days=1)).isoformat()
    start = (date.fromisoformat(game_date)
             - timedelta(days=PRIOR_WINDOW_DAYS)).isoformat()
    games = schedule_games(start, end)
    hist: dict[int, list] = {}
    for g in games:
        if g["date"] >= game_date:
            continue
        hist.setdefault(g["away_id"], []).append(
            (g["date"], g["away_score"], g["home_score"]))
        hist.setdefault(g["home_id"], []).append(
            (g["date"], g["home_score"], g["away_score"]))
    for lst in hist.values():
        lst.sort()
    return hist


def estimate_means(game, hist):
    away_h = hist.get(game["away_id"], [])[-MAX_PRIOR_USED:]
    home_h = hist.get(game["home_id"], [])[-MAX_PRIOR_USED:]
    if len(away_h) < MIN_PRIOR_GAMES or len(home_h) < MIN_PRIOR_GAMES:
        return None
    a_rs = sum(r[1] for r in away_h) / len(away_h)
    a_ra = sum(r[2] for r in away_h) / len(away_h)
    h_rs = sum(r[1] for r in home_h) / len(home_h)
    h_ra = sum(r[2] for r in home_h) / len(home_h)
    home_mean = (h_rs + a_ra) / 2
    away_mean = (a_rs + h_ra) / 2
    if min(home_mean, away_mean) < 0.2:
        return None
    return home_mean, away_mean


def half_inning_ticks(feed):
    """Yield (inning, half, away_runs, home_runs) at each boundary.

    half is the NEXT half-inning to be played ('top'/'bottom'), outs=0.
    Stops at baseball-rules finality.
    """
    linescore = (feed.get("liveData") or {}).get("linescore") or {}
    innings = linescore.get("innings") or []
    # tick 0: first pitch
    yield 1, "top", 0, 0
    away_total = home_total = 0
    for entry in innings:
        num = entry.get("num")
        a = (entry.get("away") or {}).get("runs") or 0
        h = (entry.get("home") or {}).get("runs")
        away_total += a
        # Decided after the top of the 9th+ (home leads): the bottom half
        # is never played -- no tick, mirroring real live usage.
        if num >= 9 and away_total < home_total:
            return
        # after top of `num`: next is bottom of `num`
        yield num, "bottom", away_total, home_total
        if h is None:
            return  # bottom not played
        home_total += h
        # Decided in the bottom of the 9th+: no further ticks.
        if num >= 9 and away_total != home_total:
            return
        # after bottom of `num`: next is top of `num+1`
        yield num + 1, "top", away_total, home_total


def make_state(game_pk, inning, half, away_score, home_score,
               away_name, home_name):
    return MLBGameState(
        game_pk=game_pk, observed_at=NOW, source_as_of=NOW, status="LIVE",
        inning=inning, half=half, outs=0, balls=None, strikes=None,
        bases=(False, False, False), bases_provenance="REPLAY_BOUNDARY",
        batter_id=None, batter_name=None, pitcher_id=None, pitcher_name=None,
        home_score=home_score, away_score=away_score,
        home_team=home_name, away_team=away_name)


def main():
    print("== MLB live-repricing harness replay ==")
    print("cwd must be ~/workspace/sportsedge-backtest; game dates:",
          ", ".join(GAME_DATES))
    games = []
    for d in GAME_DATES:
        games.extend(schedule_games(d, d))
        if len(games) >= MAX_GAMES:
            break
    games = games[:MAX_GAMES]
    print(f"sampled {len(games)} completed games")

    cand_records, exist_records = [], []
    clustered = []  # (game_pk, cand_p, exist_p, outcome)
    skipped = {"no_means": 0, "feed_failed": 0}
    games_used = 0

    for n, game in enumerate(games):
        hist = team_histories(game["date"])
        means = estimate_means(game, hist)
        if means is None:
            skipped["no_means"] += 1
            continue
        home_mean, away_mean = means
        try:
            feed = get_json(
                f"https://statsapi.mlb.com/api/v1.1/game/"
                f"{game['game_pk']}/feed/live")
        except Exception as exc:
            print(f"  game {game['game_pk']}: feed failed ({type(exc).__name__})")
            skipped["feed_failed"] += 1
            continue
        outcome = 1.0 if game["home_score"] > game["away_score"] else 0.0
        pregame_p = None
        ticks = 0
        for inning, half, a, h in half_inning_ticks(feed):
            # Sanity: replay scores must match the recorded final at the end.
            state = make_state(game["game_pk"], inning, half, a, h,
                               game["away_name"], game["home_name"])
            try:
                r = reprice_mlb(state, home_mean, away_mean, "ML", "HOME")
            except Exception as exc:
                print(f"  game {game['game_pk']} tick {inning}{half}: "
                      f"reprice failed ({exc})")
                break
            p = r.model_p
            if not (0.0 < p < 1.0):
                print(f"  game {game['game_pk']}: degenerate p={p} at "
                      f"{inning}{half} -- flagged, excluded from log-loss leg")
            if pregame_p is None:
                pregame_p = p
            cand_records.append({"model_p": p, "outcome": outcome})
            exist_records.append({"model_p": pregame_p, "outcome": outcome})
            clustered.append((game["game_pk"], p, pregame_p, outcome))
            ticks += 1
        # Final-score cross-check.
        if ticks:
            games_used += 1
        if (n + 1) % 10 == 0:
            print(f"  ... {n + 1}/{len(games)} games replayed")

    print(f"games used: {games_used}, skipped: {skipped}")
    print(f"predictions: {len(cand_records)}")

    degenerate = sum(1 for r in cand_records
                     if r["model_p"] <= 0.0 or r["model_p"] >= 1.0)
    print(f"degenerate probabilities: {degenerate}")
    paired = [(c, e) for c, e in zip(cand_records, exist_records)
              if 0.0 < c["model_p"] < 1.0]
    safe_cand = [c for c, _ in paired]
    safe_exist = [e for _, e in paired]

    cand_summary = metrics.summarize(safe_cand)
    exist_summary = metrics.summarize(safe_exist)
    verdict = report.evaluate(candidate=cand_summary, existing=exist_summary,
                              baseline=None, baseline_status="MISSING",
                              min_n=30)

    # Game-clustered Brier: live vs static (uses this branch's live_validation).
    rows = [LiveEvaluationRow(event_id=str(g), snapshot_id=f"{g}:{i}",
                              model_p=c, market_p=e, outcome=o)
            for i, (g, c, e, o) in enumerate(clustered)]
    model_brier, market_brier = brier_vs_market(rows)

    calib = metrics.calibration_bins(safe_cand, n_bins=10)

    result = {
        "schema": "SPORTSEDGE_LIVE_VALIDATION_REPORT_V1",
        "generated_at_utc": NOW.isoformat(),
        "research_only": True,
        "config": {"game_dates": GAME_DATES, "max_games": MAX_GAMES,
                   "min_prior_games": MIN_PRIOR_GAMES,
                   "prior_window_days": PRIOR_WINDOW_DAYS,
                   "means_estimator": "PRIOR_GAMES_RS_RA_AVG_NO_LOOKAHEAD"},
        "games_used": games_used,
        "predictions": len(safe_cand),
        "degenerate_excluded": degenerate,
        "skipped": skipped,
        "candidate_summary": cand_summary,
        "existing_summary": exist_summary,
        "clustered_brier": {
            "model_live": {"value": model_brier.value,
                           "game_clusters": model_brier.game_clusters,
                           "snapshots": model_brier.snapshots},
            "market_static_pregame": {"value": market_brier.value,
                                      "game_clusters": market_brier.game_clusters,
                                      "snapshots": market_brier.snapshots},
        },
        "calibration_bins": calib,
        "verdict": verdict,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, indent=2) + "\n",
                           encoding="utf-8")
    print("\n" + report.to_markdown(verdict, candidate_records=safe_cand,
                                    title="MLB live ML repricing vs static pregame"))
    print(f"\nreport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
