#!/usr/bin/env python3
"""Harness backtest: NFL anytime-TD candidate vs naive position baseline.

RUN FROM the backtest worktree so the harness package resolves, with the
TD-scorer worktree on PYTHONPATH:

    cd ~/workspace/sportsedge-backtest
    PYTHONPATH=~/workspace/sportsedge-tdprops \
      python3 ~/workspace/sportsedge-tdprops/scripts/backtest_nfl_anytime_td.py \
        --cache /tmp/nfl_td_cache --seasons 2023,2024,2025,2026 \
        --test-season 2026 --max-week 5 \
        --out /tmp/nfl_td/anytime_td_backtest.md

Chronological discipline: fixtures are completed 2026 games sorted by kickoff;
price_fn ignores the harness `train` list and instead PIT-filters the governed
nflverse tables on kickoff < fixture kickoff strictly inside the model.  This
is equivalent to train-only learning and is auditable per prediction
(`evidence.pit` on every priced prop).

Settlement: rushing_tds + receiving_tds >= 1 from nflverse player_stats
(return TDs excluded -- the model prices offensive TDs only; documented).

Market baseline: MISSING (no Odds API by Isaac's choice) -> best achievable
verdict is CONDITIONAL_PASS.  Research only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--seasons", default="2023,2024,2025,2026")
    ap.add_argument("--test-season", type=int, default=2026)
    ap.add_argument("--max-week", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-train", type=int, default=8)
    ap.add_argument("--test-size", type=int, default=8)
    ap.add_argument("--step", type=int, default=4)
    ap.add_argument("--backtest-dir",
                    default=str(Path.home() / "workspace/sportsedge-backtest"
                                / "sportsedge/backtest"))
    args = ap.parse_args()

    import importlib.util
    _bt_dir = Path(args.backtest_dir)
    _spec = importlib.util.spec_from_file_location(
        "td_harness", _bt_dir / "__init__.py",
        submodule_search_locations=[str(_bt_dir)])
    _hb = importlib.util.module_from_spec(_spec)
    sys.modules["td_harness"] = _hb
    _spec.loader.exec_module(_hb)
    from td_harness import runner, splits, metrics, report  # noqa: E402

    from sportsedge import nfl_anytime_td as td

    seasons = [int(s) for s in args.seasons.split(",")]
    print("loading nflverse history...", flush=True)
    history = td.load_td_history(seasons=seasons, cache_dir=args.cache)
    print("proofs:", len(history["proofs"]), flush=True)

    games = history["games"]
    now = datetime.now(timezone.utc)
    test_games = games[
        (games["season"] == args.test_season)
        & (games["game_type"] == "REG")
        & (games["week"].astype(int) <= args.max_week)
        & (games["kickoff"] < now)
        & games["home_score"].notna() & games["away_score"].notna()
    ].sort_values("kickoff")
    print(f"test games: {len(test_games)}", flush=True)

    fixtures = [
        {"fixture_id": str(r["game_id"]), "kickoff": r["kickoff"].isoformat(),
         "as_of": r["kickoff"].isoformat(),
         "home": str(r["home_team"]), "away": str(r["away_team"])}
        for _, r in test_games.iterrows()
    ]

    ps26 = history["player_stats"]
    elig_pos = td.ELIGIBLE_POSITION_GROUPS

    # per-fixture caches (all PIT-safe: built from kickoff < fixture kickoff)
    fixture_cache: dict[str, dict] = {}

    def _fixture_data(fixture):
        fid = fixture["fixture_id"]
        if fid in fixture_cache:
            return fixture_cache[fid]
        ko = datetime.fromisoformat(fixture["kickoff"])
        ps_pit = history["player_stats"][history["player_stats"]["kickoff"] < ko]
        tg_pit = history["team_games"][history["team_games"]["kickoff"] < ko]
        rz_pit = history["rz_player"][history["rz_player"]["kickoff"] < ko]
        snaps_pit = history["snaps"][history["snaps"]["kickoff"] < ko].copy()
        snaps_pit["_nk"] = snaps_pit["player"].astype(str).map(td._norm_name)
        lookup = (snaps_pit.dropna(subset=["offense_pct"])
                  .groupby(["game_id", "team", "_nk"])["offense_pct"].max())
        h = dict(history, player_stats=ps_pit, team_games=tg_pit,
                 rz_player=rz_pit, snaps=snaps_pit, snap_lookup=lookup)
        priors = td.position_priors(h, as_of=ko)
        # naive position baseline: per-game anytime-TD rate by position
        base = (ps_pit[ps_pit["position_group"].isin(elig_pos)]
                .groupby("position_group")["off_tds"]
                .apply(lambda s: float((s >= 1).mean())))
        data = {"h": h, "ko": ko, "priors": priors,
                "base_rates": base.to_dict()}
        for team in (fixture["home"], fixture["away"]):
            data[f"plays_{team}"] = td.team_play_expectation(h, team=team, as_of=ko)
        data[f"opp_{fixture['home']}"] = td.opponent_factor(
            h, opponent=fixture["away"], as_of=ko)
        data[f"opp_{fixture['away']}"] = td.opponent_factor(
            h, opponent=fixture["home"], as_of=ko)
        fixture_cache[fid] = data
        return data

    def _players_for(fixture):
        g = ps26[(ps26["game_id"] == fixture["fixture_id"])
                 & (ps26["position_group"].isin(elig_pos))]
        return g.drop_duplicates("player_id")

    blocked_counts: dict[str, int] = {}
    priced = {"naive_position_baseline": 0, "anytime_td_candidate": 0}
    # Paired comparison: the baseline is evaluated on exactly the players the
    # candidate priced (candidate runs first).  Unpaired n's made the first
    # run's verdict unfair (different base rates).
    priced_pids: dict[str, set[str]] = {}

    def price_fn(model_name, fixture, as_of, train):
        data = _fixture_data(fixture)
        h, ko = data["h"], data["ko"]
        fid = fixture["fixture_id"]
        preds = []
        if model_name == "anytime_td_candidate":
            priced_pids[fid] = set()
        for _, r in _players_for(fixture).iterrows():
            pid = str(r["player_id"])
            team = str(r["team"])
            opp_team = fixture["away"] if team == fixture["home"] else fixture["home"]
            if model_name == "naive_position_baseline":
                if pid not in priced_pids.get(fid, set()):
                    continue
                p = data["base_rates"].get(str(r["position_group"]))
                if p is None:
                    continue
                p = min(1 - 1e-4, max(1e-4, float(p)))
                preds.append({"market": "ANYTIME_TD", "selection": pid,
                              "model_p": p})
                priced[model_name] += 1
            else:
                try:
                    out = td.estimate_anytime_td(
                        h, player_id=pid,
                        player_name=str(r["player_display_name"]),
                        team=team, opponent=opp_team,
                        game_id=fixture["fixture_id"], kickoff=ko,
                        priors=data["priors"],
                        team_plays=data[f"plays_{team}"],
                        opp=data[f"opp_{team}"])
                except td.NflTdError as exc:
                    reason = str(exc).split(":")[0]
                    blocked_counts[reason] = blocked_counts.get(reason, 0) + 1
                    continue
                preds.append({"market": "ANYTIME_TD", "selection": pid,
                              "model_p": float(out["model_p"])})
                priced[model_name] += 1
                priced_pids[fid].add(pid)
        return preds

    settle_lookup = (ps26.set_index(["game_id", "player_id"])["off_tds"] >= 1)

    def settle_fn(fixture, market, selection, line):
        try:
            hit = settle_lookup.loc[(fixture["fixture_id"], str(selection))]
        except KeyError:
            raise ValueError("SETTLE_ROW_MISSING:" + str(selection))
        return 1.0 if bool(hit) else 0.0

    sp = list(splits.walk_forward_splits(
        fixtures, min_train=args.min_train, test_size=args.test_size,
        step=args.step))
    print(f"splits: {len(sp)}", flush=True)
    result = runner.run_backtest(
        fixtures=fixtures, splits=sp,
        models=["anytime_td_candidate", "naive_position_baseline"],
        price_fn=price_fn, settle_fn=settle_fn, market_baseline=None)
    comp = runner.compare_models(result)
    verdict = report.evaluate(
        candidate=comp["models"]["anytime_td_candidate"],
        existing=comp["models"]["naive_position_baseline"],
        baseline_status=comp["baseline"]["status"],
        baseline=comp["baseline"]["summary"])

    cand_n = comp["models"]["anytime_td_candidate"]["n"]
    base_n = comp["models"]["naive_position_baseline"]["n"]
    total_blocked = sum(blocked_counts.values())
    playable_share = (priced["anytime_td_candidate"]
                      / max(1, priced["anytime_td_candidate"] + total_blocked))

    md = report.to_markdown(
        verdict,
        candidate_records=result["records"]["anytime_td_candidate"],
        title="NFL anytime-TD backtest: candidate vs naive position baseline")
    extra = (
        "\n## Coverage (playable share)\n\n"
        f"- candidate priced: {priced['anytime_td_candidate']}\n"
        f"- baseline priced: {base_n}\n"
        f"- blocked by reason: {json.dumps(blocked_counts, indent=2, sort_keys=True)}\n"
        f"- playable share (priced / (priced + blocked)): {playable_share:.3f}\n"
        "\nPlayable share is Isaac's health metric: fail-closed discipline must\n"
        "not collapse into a machine that prices nothing.\n"
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md + extra + "\n", encoding="utf-8")
    out_path.with_suffix(".json").write_text(
        report.to_json(verdict) + "\n", encoding="utf-8")
    print(md)
    print(extra)
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
