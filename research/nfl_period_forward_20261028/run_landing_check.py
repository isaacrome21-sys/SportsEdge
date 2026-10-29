"""NON_COUNTED landing check for the NFL_PERIOD_DRIVE_STATE_V2
forward runner (sportsedge/nfl_period_forward.py) — BUILD evidence
only. NOT FROZEN; counted rows zero; no validation, forward-clock,
or PLAY credit.

Slate: 2024 Week 10 (14 REG games, Thu Nov 7 - Mon Nov 11, 2024),
priced and settled end to end through the runner on the pinned
screen's own cached inputs (hashes recorded in the output; they
equal research/nfl_period_drive_state_screen_20261028/INPUT_PINS.md).

Entry and close quotes are a labeled SYNTHETIC_LANDING_FIXTURE:
static per-market lines with a deterministic per-game rotation and
flat fixture prices, plus five engineered close exceptions
(a moved line, a missing close, a single-sided close, a stale
close, a post-kickoff close) whose section 8 dispositions the
check asserts. No real DraftKings period capture exists — the
capture-expansion precondition (draft section 4/section 15) is
still open, and nothing here claims otherwise.

Equivalence, recomputed independently of the runner's internals:
  * TNF (2024_10_CIN_BAL, the week's opening game): the runner's
    model means / ML probability equal, float-exactly, the pinned
    construction invoked directly (LeagueFit on prior seasons,
    TeamRateBook walked over games final before the entry capture,
    SeedSequence([master seed, game index 0])).
  * TNF B0: the runner's baseline means and sibling mus equal,
    float-exactly, the pinned screen's baseline_rows over the full
    panel (for a week-opening game the FLAG 5 final-before-entry
    share fit coincides with the screen's strictly-prior-weeks
    batching).

Run: PYTHONPATH=<dir containing pyarrow> python3 \
    run_landing_check.py --cache-dir <screen cache>
(the parquet cache needs a parquet engine on the path, exactly as
for the pinned screen's own runs; the repo's test environment does
not carry one)
Writes LANDING_CHECK.json + entry_records_sample.jsonl beside this
file (create-only for the records; a re-run must reproduce them
byte-identically).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from sportsedge import nfl_period_forward as fwd  # noqa: E402

ET = ZoneInfo("America/New_York")
SLATE_SEASON, SLATE_WEEK = 2024, 10
FIXTURE = "SYNTHETIC_LANDING_FIXTURE"

# Static fixture lines (value scale) + flat fixture prices.
TOTAL_LINES = {"1Q": 13.5, "2Q": 14.5, "3Q": 13.5, "4Q": 14.5, "1H": 27.5}
TEAM_TOTAL_LINES = {"1Q": 6.5, "2Q": 7.5, "3Q": 6.5, "4Q": 7.5, "1H": 13.5}
SPREAD_LINE_HOME = -2.5
ROTATION = (0.0, 1.0, -1.0, 0.5)

# Engineered close exceptions: (game_id, market, team) -> change.
MOVED = ("2024_10_BUF_IND", "TOTAL_1Q", None)          # close line +1.0
MISSING = ("2024_10_DEN_KC", "SPREAD_2Q", None)        # no close quote
SINGLE_SIDED = ("2024_10_MIN_JAX", "TOTAL_3Q", None)   # close price_b None
STALE = ("2024_10_SF_TB", "ML_1H", None)               # close at kickoff-75m
NOT_PREKICKOFF = ("2024_10_PIT_WAS", "TOTAL_4Q", None)  # close after kickoff


def _kickoff_iso(row) -> str:
    day = datetime.fromisoformat(row["gameday"]).date()
    clock = datetime.strptime(row["gametime"], "%H:%M").time()
    return datetime.combine(day, clock, tzinfo=ET).isoformat()


def build_fixture(games_meta):
    """games_meta: list of schedules row dicts in slate order.
    Returns (entry_quotes, close_quotes)."""
    entries, closes = [], []
    for gi, row in enumerate(games_meta):
        kickoff = datetime.fromisoformat(_kickoff_iso(row))
        rot = ROTATION[gi % len(ROTATION)]
        entry_at = (kickoff - timedelta(minutes=60)).isoformat()
        close_at = (kickoff - timedelta(minutes=10)).isoformat()
        for market in fwd.MARKETS:
            kind, period = market.rsplit("_", 1)
            teams = (row["home_team"], row["away_team"]) \
                if kind == "TEAM_TOTAL" else (None,)
            for team in teams:
                if kind == "TOTAL":
                    line = TOTAL_LINES[period] + rot
                elif kind == "TEAM_TOTAL":
                    line = TEAM_TOTAL_LINES[period] + (0.5 if team
                                                       == row["home_team"]
                                                       else -0.5)
                elif kind == "SPREAD":
                    line = SPREAD_LINE_HOME
                else:
                    line = None
                pa, pb = (-150, 130) if kind == "ML" else (-110, -110)
                entries.append(fwd.PeriodQuote(
                    game_id=row["game_id"], market=market, team=team,
                    line=line, price_a=pa, price_b=pb,
                    captured_at=entry_at, source=FIXTURE))
                key = (row["game_id"], market, team)
                if key == MISSING:
                    continue
                c_line, c_pa, c_pb, c_at = line, pa, pb, close_at
                if key == MOVED:
                    c_line = line + 1.0
                elif key == SINGLE_SIDED:
                    c_pb = None
                elif key == STALE:
                    c_at = (kickoff - timedelta(minutes=75)).isoformat()
                elif key == NOT_PREKICKOFF:
                    c_at = (kickoff + timedelta(minutes=5)).isoformat()
                closes.append(fwd.PeriodQuote(
                    game_id=row["game_id"], market=market, team=team,
                    line=c_line, price_a=c_pa, price_b=c_pb,
                    captured_at=c_at, source=FIXTURE))
    return entries, closes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True)
    args = ap.parse_args()

    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    runner = fwd.NflPeriodForwardRunner(repo_root=_REPO)
    check("pins_verified_at_construction", True,
          f"engine pin {runner.pins['engine_sha256'][:12]}...")
    engine, v1 = runner.engine(), runner.v1()
    history = runner.load_history(args.cache_dir)
    check("history_snapshot_hashed", len(history.snapshot_sha256) == 64,
          history.snapshot_sha256[:12])
    check("panel_integrity_rerun",
          history.panel_integrity["unexplained"] == [],
          json.dumps({k: history.panel_integrity[k]
                      for k in ("n_team_games", "exact_share",
                                "ot_only_share")}))

    games_meta = [history.schedules_by_id[g] for g in
                  history.reg_final_order
                  if history.schedules_by_id[g]["season"] == SLATE_SEASON
                  and history.schedules_by_id[g]["week"] == SLATE_WEEK]
    games_meta.sort(key=lambda r: (r["gameday"], r["gametime"],
                                   r["game_id"]))
    check("slate_is_2024_week_10_14_games", len(games_meta) == 14,
          f"{len(games_meta)} games")
    slate = [fwd.SlateGame(game_id=r["game_id"], season=r["season"],
                           week=r["week"], gameday=r["gameday"],
                           kickoff=_kickoff_iso(r), home=r["home_team"],
                           away=r["away_team"]) for r in games_meta]
    entries, closes = build_fixture(games_meta)

    for call in (runner.price_counted_slate, runner.run_forward_test):
        try:
            call()
            check(f"counted_refusal:{call.__name__}", False, "no refusal")
        except fwd.NflPeriodForwardError as exc:
            check(f"counted_refusal:{call.__name__}",
                  exc.reason == "NFL_PERIOD_FORWARD_NOT_FROZEN", exc.reason)

    out = runner.price_slate(history, slate, entries)
    rows = out["rows"]
    check("all_rows_non_counted",
          all(r["counted"] is False for r in rows)
          and out["run"]["counted_rows"] == 0,
          f"{len(rows)} rows")
    check("game_index_order_committed",
          out["run"]["game_index_order"][0] == "2024_10_CIN_BAL"
          and len(out["run"]["game_index_order"]) == 14,
          ",".join(out["run"]["game_index_order"][:3]) + ",...")
    n_expected = sum(1 for q in entries)
    check("one_row_per_entry_quote", len(rows) == n_expected,
          f"{len(rows)} rows / {n_expected} quotes")

    # --- independent equivalence: TNF sim --------------------------
    tnf = games_meta[0]
    entry_time = datetime.fromisoformat(_kickoff_iso(tnf)) \
        - timedelta(minutes=60)
    fit = engine.LeagueFit(history.plays[history.plays["season"] < 2024],
                           history.starts[history.starts["season"] < 2024])
    book = engine.TeamRateBook(history.agg, None)
    for gid in history.book_order:
        if history.end_of(gid) <= entry_time:
            book.record_game(gid)
    rng = np.random.default_rng(
        np.random.SeedSequence([fwd.MASTER_SEED, 0]))
    sim = engine.simulate_game(fit, book.bundle(tnf["home_team"], 2024),
                               book.bundle(tnf["away_team"], 2024), rng)
    hq, aq = sim["home_q"], sim["away_q"]
    tnf_rows = {r["market"]: r for r in rows
                if r["game_id"] == tnf["game_id"] and r["team"] is None}
    tnf_tt = {r["team"]: r for r in rows
              if r["game_id"] == tnf["game_id"]
              and r["market"] == "TEAM_TOTAL_1Q"}
    check("tnf_total_1q_mean_float_exact",
          tnf_rows["TOTAL_1Q"]["model"]["mean"]
          == float((hq[:, 0] + aq[:, 0]).mean()),
          repr(tnf_rows["TOTAL_1Q"]["model"]["mean"]))
    check("tnf_team_total_1q_mean_float_exact",
          tnf_tt[tnf["home_team"]]["model"]["mean"]
          == float(hq[:, 0].mean()),
          repr(tnf_tt[tnf["home_team"]]["model"]["mean"]))
    check("tnf_ml_1q_prob_float_exact",
          tnf_rows["ML_1Q"]["model"]["p_a"]
          == float(np.mean(hq[:, 0] > aq[:, 0])),
          repr(tnf_rows["ML_1Q"]["model"]["p_a"]))

    # --- independent equivalence: TNF B0 vs baseline_rows ----------
    wf = v1.WalkForward(history.games)
    v1.run_team_total_screen(wf)
    base = engine.baseline_rows(v1, wf, history.panel)
    base_idx = base.set_index(["game_id", "team"])
    b0_home = np.asarray(base_idx.loc[(tnf["game_id"], tnf["home_team"]),
                                      "b0_q"], dtype=float)
    b0_away = np.asarray(base_idx.loc[(tnf["game_id"], tnf["away_team"]),
                                      "b0_q"], dtype=float)
    check("tnf_total_1q_b0_float_exact",
          tnf_rows["TOTAL_1Q"]["baseline_ref"]["mean"]
          == float(b0_home[0] + b0_away[0]),
          repr(tnf_rows["TOTAL_1Q"]["baseline_ref"]["mean"]))
    check("tnf_spread_1q_b0_float_exact",
          tnf_rows["SPREAD_1Q"]["baseline_ref"]["mean"]
          == float(b0_home[0] - b0_away[0]),
          repr(tnf_rows["SPREAD_1Q"]["baseline_ref"]["mean"]))
    check("tnf_sibling_mu_float_exact",
          tnf_rows["TOTAL_1Q"]["baseline_ref"]["sibling_mu"]["home"]
          == float(wf.mu_by_game_team[(tnf["game_id"],
                                       tnf["home_team"])]),
          repr(tnf_rows["TOTAL_1Q"]["baseline_ref"]["sibling_mu"]["home"]))
    check("1h_baseline_emissions_absent_stamped",
          all(r["baseline_ref"]["stamp"] == "BASELINE_1H_EMISSION_ABSENT"
              for r in rows if r["period"] == "1H"),
          "no 1H emission supplied; none invented")

    # --- settlement --------------------------------------------------
    finals = {r["game_id"]: history.finals_for(r["game_id"])
              for r in games_meta}
    settled = runner.settle_records(rows, closes, finals)
    by_key = {(s["game_id"], s["market"], s["team"]): s
              for s in settled["settlements"]}
    check("all_slate_rows_graded",
          settled["summary"]["graded"] == len(rows)
          and settled["summary"]["void"] == 0,
          f"{settled['summary']['graded']} graded")
    check("engineered_moved_close",
          by_key[MOVED]["close_disposition"] == "LINE_MOVED"
          and by_key[MOVED]["move_direction"] in ("FAVORABLE", "ADVERSE"),
          by_key[MOVED]["move_direction"] or "")
    check("engineered_missing_close",
          by_key[MISSING]["close_reason"] == "NO_CLOSE_ROW", "")
    check("engineered_single_sided_close",
          by_key[SINGLE_SIDED]["close_reason"] == "CLOSE_SINGLE_SIDED", "")
    check("engineered_stale_close",
          by_key[STALE]["close_reason"] == "CLOSE_STALE", "")
    check("engineered_not_prekickoff_close",
          by_key[NOT_PREKICKOFF]["close_reason"]
          == "CLOSE_NOT_PREKICKOFF", "")
    check("settlement_non_counted",
          settled["summary"]["counted"] is False, "")

    # --- records artifact ---------------------------------------------
    here = Path(__file__).resolve().parent
    records_path = here / "entry_records_sample.jsonl"
    payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    if records_path.exists():
        check("entry_records_reproduced_byte_identical",
              records_path.read_text(encoding="utf-8") == payload, "")
    else:
        fwd.write_records(rows, records_path)
        check("entry_records_written_create_only", True, str(records_path))

    report = {
        "kind": "LANDING_CHECK",
        "state": "NON_COUNTED",
        "freeze_state": fwd.FREEZE_STATE,
        "construction_pin": fwd.ENGINE_PIN,
        "slate": {"season": SLATE_SEASON, "week": SLATE_WEEK,
                  "games": [r["game_id"] for r in games_meta]},
        "fixture": FIXTURE,
        "input_hashes": history.input_hashes,
        "history_snapshot_sha256": history.snapshot_sha256,
        "run": {k: out["run"][k] for k in
                ("game_index_order", "n_rows", "n_refusals",
                 "counted_rows", "master_seed")},
        "settlement_summary": {k: settled["summary"][k] for k in
                               ("n_rows", "graded", "void",
                                "result_unavailable", "push",
                                "mean_clv_valid_rows", "n_clv_valid_rows")},
        "checks": checks,
        "all_ok": all(c["ok"] for c in checks),
    }
    (here / "LANDING_CHECK.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({"all_ok": report["all_ok"],
                      "n_checks": len(checks),
                      "failed": [c["name"] for c in checks
                                 if not c["ok"]]}, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
