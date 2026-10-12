"""Harness validation: NBA game-market model vs naive baseline (ML leg).

RUN WITH: cwd=~/workspace/sportsedge-backtest
    python3 ~/workspace/sportsedge-nba/scripts/validate_nba_game_markets.py

What this validates (Isaac's bar, research-only):
  - candidate: the branch's verified NBA game-market path
    (ESPN scoreboard -> ratings_model.replay on train only ->
    nba_game_market_pricing ML probabilities)
  - existing: naive baseline (train home-win-rate for ML; train league
    averages for margin/total diagnostics). There is no production NBA
    pricer yet; the naive model is the honest "no model" leg.
  - market baseline: MISSING (no Odds API by Isaac's choice) -> the best
    achievable verdict is CONDITIONAL_PASS, never a validated edge.

Spread/total have no market lines to settle binary outcomes against, so
they are reported as point-forecast MAE diagnostics (candidate vs naive),
not as part of the PASS/FAIL verdict.

Historical games: real 2024-25 NBA regular-season scoreboard pages from the
free ESPN API, cached under the branch data dir (reproducible, no re-hit).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRANCH = Path.home() / "workspace" / "sportsedge-nba"
CACHE_DIR = BRANCH / "data" / "backtest_nba_cache"
REPORT_PATH = BRANCH / "docs" / "NBA_HARNESS_VALIDATION_2026-10-11.md"

# The harness and the branch both ship a top-level ``sportsedge`` package, so
# a plain sys.path insert would shadow one of them. Import the harness by
# package path, then load the branch's NBA modules under a synthetic
# ``branch_nba`` package (no files copied, neither repo modified).
sys.path.insert(0, str(Path.cwd()))

from sportsedge.backtest import metrics, outcomes, report, runner, splits  # noqa: E402

import importlib.util as _ilu  # noqa: E402
import types as _types  # noqa: E402


def _load_branch_nba():
    pkg = _types.ModuleType("branch_nba")
    pkg.__path__ = [str(BRANCH / "sportsedge" / "sports" / "nba")]
    sys.modules["branch_nba"] = pkg
    loaded = {}
    for name in ("espn_verified_source", "ratings_model",
                 "nba_game_market_pricing"):
        spec = _ilu.spec_from_file_location(
            f"branch_nba.{name}",
            BRANCH / "sportsedge" / "sports" / "nba" / f"{name}.py")
        mod = _ilu.module_from_spec(spec)
        sys.modules[f"branch_nba.{name}"] = mod
        spec.loader.exec_module(mod)
        loaded[name] = mod
    return loaded


_branch = _load_branch_nba()
NBASource = _branch["espn_verified_source"].NBASource
fit_verified_games = _branch["nba_game_market_pricing"].fit_verified_games
price_game_markets = _branch["nba_game_market_pricing"].price_game_markets

# Every 4th day across the 2024-25 regular season -> ~40 scoreboard pages.
START = datetime(2024, 10, 23, tzinfo=timezone.utc)
END = datetime(2025, 4, 10, tzinfo=timezone.utc)


def fetch_games() -> list:
    src = NBASource()
    games: list[dict] = []
    day = START
    n_pages = 0
    while day <= END:
        dates = day.strftime("%Y%m%d")
        cache_file = CACHE_DIR / f"scoreboard_{dates}.json"
        if cache_file.exists():
            events = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            events = src.scoreboard(dates)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(events), encoding="utf-8")
        n_pages += 1
        games.extend(src.parse_completed_games(events,
                                                     skip_unregistered_teams=True))
        day += timedelta(days=4)
    print(f"fetched {n_pages} scoreboard pages -> {len(games)} completed games "
          f"(All-Star exhibitions skipped)")
    return games


def build_fixtures(games: list) -> list:
    fixtures = []
    for g in games:
        kickoff = datetime.fromisoformat(g["tipoff"].replace("Z", "+00:00"))
        fixtures.append({
            "fixture_id": f"nba2425:{g['event_id']}",
            "kickoff": kickoff.isoformat(),
            "as_of": (kickoff - timedelta(minutes=60)).isoformat(),
            **g,
        })
    fixtures.sort(key=lambda f: (f["kickoff"], f["fixture_id"]))
    return fixtures


def naive_home_rate(train: list) -> float:
    wins = sum(1 for g in train if g["home_score"] > g["away_score"])
    return wins / len(train) if train else 0.5


def price_fn(model_name: str, fixture: dict, as_of: str, train: list) -> list:
    if model_name == "candidate":
        ratings, sig_m, sig_t = fit_verified_games(list(train))
        prices = price_game_markets(
            home_team_id=fixture["home_team_id"],
            away_team_id=fixture["away_team_id"],
            ratings=ratings, sigma_margin=sig_m, sigma_total=sig_t)
        p_home = prices.ml_home_probability
    elif model_name == "existing":
        p_home = naive_home_rate(train)
        p_home = min(0.99, max(0.01, p_home))
    else:
        raise ValueError("unknown model " + model_name)
    return [
        {"market": "ML", "selection": "HOME", "model_p": p_home},
        {"market": "ML", "selection": "AWAY", "model_p": 1.0 - p_home},
    ]


def settle_fn(fixture: dict, market: str, selection: str, line=None) -> float:
    return outcomes.settle_game(
        {"home_score": fixture["home_score"], "away_score": fixture["away_score"]},
        market, selection, line)


def margin_total_diagnostics(fixtures_by_split):
    """Point-forecast MAE for margin/total: candidate vs naive (diagnostic)."""
    import math
    cand_m = []
    naive_m = []
    cand_t = []
    naive_t = []
    for train, test in fixtures_by_split:
        ratings, sig_m, sig_t = fit_verified_games(list(train))
        league_margin = sum(g["home_score"] - g["away_score"] for g in train) / len(train)
        league_total = sum(g["home_score"] + g["away_score"] for g in train) / len(train)
        for f in test:
            hp, ap = ratings.predict(f["home_team_id"], f["away_team_id"])
            cm, ct = hp - ap, hp + ap
            am = f["home_score"] - f["away_score"]
            at = f["home_score"] + f["away_score"]
            cand_m.append(abs(cm - am))
            naive_m.append(abs(league_margin - am))
            cand_t.append(abs(ct - at))
            naive_t.append(abs(league_total - at))
    def mae(xs):
        return sum(xs) / len(xs)
    return {
        "n": len(cand_m),
        "margin_mae_candidate": mae(cand_m),
        "margin_mae_naive": mae(naive_m),
        "total_mae_candidate": mae(cand_t),
        "total_mae_naive": mae(naive_t),
    }


def main() -> None:
    games = fetch_games()
    fixtures = build_fixtures(games)
    sp = list(splits.walk_forward_splits(fixtures, min_train=120,
                                         test_size=40, embargo_days=1))
    print(f"walk-forward splits: {len(sp)}")

    result = runner.run_backtest(
        fixtures=fixtures, splits=sp,
        models=["candidate", "existing"],
        price_fn=price_fn, settle_fn=settle_fn,
        market_baseline=None)  # MISSING by Isaac's choice (no Odds API)
    comp = runner.compare_models(result)
    verdict = report.evaluate(
        candidate=comp["models"]["candidate"],
        existing=comp["models"]["existing"],
        baseline_status=comp["baseline"]["status"],
        baseline=comp["baseline"]["summary"])

    diag = margin_total_diagnostics([(s.train, s.test) for s in sp])

    md = report.to_markdown(verdict,
                            candidate_records=result["records"]["candidate"],
                            title="NBA game-market harness validation (ML leg)")
    md += "\n## Spread/total point-forecast diagnostics (not part of the verdict)\n\n"
    md += ("No market lines exist to settle spread/total as binary outcomes "
           "(no Odds API by Isaac's choice), so these are MAE diagnostics only.\n\n")
    md += (f"- n test games: {diag['n']}\n"
           f"- margin MAE: candidate {diag['margin_mae_candidate']:.2f} vs naive "
           f"{diag['margin_mae_naive']:.2f}\n"
           f"- total MAE: candidate {diag['total_mae_candidate']:.2f} vs naive "
           f"{diag['total_mae_naive']:.2f}\n")
    md += ("\n## Provenance\n\n"
           f"- {len(games)} real 2024-25 NBA games from the free ESPN scoreboard "
           f"API ({START.date()} to {END.date()}, every 4th day), cached at "
           f"`data/backtest_nba_cache/`\n"
           "- candidate: sportsedge.sports.nba.nba_game_market_pricing "
           "(ratings replay on train only, residual sigmas from train)\n"
           "- existing: naive train home-win-rate (ML) / train league averages "
           "(margin/total diagnostics)\n"
           "- market baseline: MISSING (no Odds API)\n"
           "- research only; no betting authority.\n")
    print(md)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(f"\nreport written to {REPORT_PATH}")
    print("VERDICT:", verdict["verdict"])


if __name__ == "__main__":
    main()
