"""Tests for the NFL_PERIOD_DRIVE_STATE_V2 forward runner
(sportsedge/nfl_period_forward.py) — BUILD, NOT FROZEN.

Pin the build's contracts: the construction-of-record pins verify
and a mismatch refuses PIN_MISMATCH; every counted entry point
refuses NFL_PERIOD_FORWARD_NOT_FROZEN; the section 6 pick rule and
the section 8 close rules (validity before moved classification;
the 20% trip counting only the four capture failures; the moved
bucket's direction split; the >50% LOW_COVERAGE label) behave
exactly as the revision draft (PR #2914) writes them; the FLAG 5
B0 share fit is float-exact against the pinned screen's own
baseline_rows where the two forms coincide (week-opening games);
and a NON_COUNTED pricing of a synthetic slate reproduces, float-
exactly, the pinned construction invoked directly with the same
seed derivation and point-in-time state.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from sportsedge import nfl_period_forward as fwd

REPO_ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
KICKOFF = datetime(2024, 11, 7, 20, 15, tzinfo=ET)


def _quote(**kw):
    base = {"game_id": "g1", "market": "TOTAL_1Q", "team": None,
            "line": 13.5, "price_a": -110, "price_b": -110,
            "captured_at": (KICKOFF - timedelta(minutes=10)).isoformat(),
            "source": "TEST"}
    base.update(kw)
    return fwd.PeriodQuote(**base)


# ------------------------------------------------------------------
# Pins + counted refusals
# ------------------------------------------------------------------
def test_runner_constructs_and_pins_verify():
    runner = fwd.NflPeriodForwardRunner(repo_root=REPO_ROOT)
    assert runner.config_model_version == "UNPINNED"
    assert runner.pins["engine_sha256"] == \
        "16593a8779986f653705c481eaf0e079387933975123e386f8efd7e865b4658c"
    assert fwd.ENGINE_PIN.endswith(runner.pins["engine_sha256"])


def test_pin_mismatch_refuses(tmp_path):
    for rel, _ in fwd.EXPECTED_PINS.values():
        src = REPO_ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    engine_rel = fwd.EXPECTED_PINS["engine_sha256"][0]
    with open(tmp_path / engine_rel, "ab") as fh:
        fh.write(b"\n# drift\n")
    with pytest.raises(fwd.NflPeriodForwardError) as exc:
        fwd.NflPeriodForwardRunner(repo_root=tmp_path)
    assert exc.value.reason == "PIN_MISMATCH"


def test_counted_entry_points_refuse_not_frozen():
    runner = fwd.NflPeriodForwardRunner(repo_root=REPO_ROOT)
    for call in (runner.price_counted_slate, runner.run_forward_test):
        with pytest.raises(fwd.NflPeriodForwardError) as exc:
            call()
        assert exc.value.reason == "NFL_PERIOD_FORWARD_NOT_FROZEN"
    with pytest.raises(fwd.NflPeriodForwardError) as exc:
        runner.price_slate(None, [], [], counted=True)
    assert exc.value.reason == "NFL_PERIOD_FORWARD_NOT_FROZEN"


# ------------------------------------------------------------------
# Distribution summaries + pick rule (draft section 6)
# ------------------------------------------------------------------
def test_line_market_summary_exact():
    values = np.array([0.0, 3.0, 7.0, 10.0])
    s = fwd.line_market_summary(values, 6.5)
    assert s == {"mean": 5.0, "p_a": 0.5, "p_b": 0.5, "p_push": 0.0}
    s = fwd.line_market_summary(values, 7.0)
    assert s["p_a"] == 0.25 and s["p_b"] == 0.5 and s["p_push"] == 0.25


def test_period_values_first_half_is_q1_plus_q2():
    home = np.array([[1.0, 2.0, 4.0, 8.0]])
    away = np.array([[16.0, 32.0, 64.0, 128.0]])
    total, h, a, margin = fwd.period_values(home, away, "1H")
    assert (total[0], h[0], a[0], margin[0]) == (51.0, 3.0, 48.0, -45.0)
    total, h, a, margin = fwd.period_values(home, away, "3Q")
    assert (total[0], h[0], a[0], margin[0]) == (68.0, 4.0, 64.0, -60.0)


def test_pick_rule_thresholds_and_gap_zero():
    kw = {"p_a": 0.6, "p_b": 0.4, "novig_a": 0.5, "novig_b": 0.5}
    picked = fwd.classify_pick("TOTAL_1Q", model_mean=15.0, line=13.5, **kw)
    assert picked["classification"] == "PICKED" and picked["pick_side"] == "A"
    under = fwd.classify_pick("TOTAL_2Q", model_mean=14.9, line=13.5, **kw)
    assert under["classification"] == "NOT_PICKED"
    half = fwd.classify_pick("TOTAL_1H", model_mean=15.4, line=13.5, **kw)
    assert half["classification"] == "NOT_PICKED"  # 1H needs 2.0
    zero = fwd.classify_pick("SPREAD_1Q", model_mean=13.5, line=13.5, **kw)
    assert zero["classification"] == "NOT_PICKED"
    assert zero.get("stamp") == "GAP_ZERO" and zero["selected_side"] == "TIE"


def test_pick_rule_moneyline_edge():
    picked = fwd.classify_pick("ML_1Q", model_mean=None, line=None,
                               p_a=0.55, p_b=0.40, novig_a=0.50,
                               novig_b=0.50)
    assert picked["classification"] == "PICKED" and picked["pick_side"] == "A"
    short = fwd.classify_pick("ML_1Q", model_mean=None, line=None,
                              p_a=0.53, p_b=0.42, novig_a=0.50,
                              novig_b=0.50)
    assert short["classification"] == "NOT_PICKED"
    tied = fwd.classify_pick("ML_1H", model_mean=None, line=None,
                             p_a=0.45, p_b=0.45, novig_a=0.50,
                             novig_b=0.50)
    assert tied["selected_side"] == "TIE"


# ------------------------------------------------------------------
# Close validity + v1.1 moved rows (draft section 8)
# ------------------------------------------------------------------
def _evaluate(close, **kw):
    base = {"market": "TOTAL_1Q", "entry_line": 13.5,
            "selected_side": "A", "kickoff": KICKOFF}
    base.update(kw)
    return fwd.evaluate_close(close=close, **base)


def test_close_valid_and_exactly_sixty_minutes():
    assert _evaluate(_quote())["disposition"] == "VALID"
    edge = _quote(captured_at=(KICKOFF - timedelta(minutes=60)).isoformat())
    assert _evaluate(edge)["disposition"] == "VALID"


def test_close_capture_failure_reasons():
    assert _evaluate(None)["reason"] == "NO_CLOSE_ROW"
    single = _quote(price_b=None)
    assert _evaluate(single)["reason"] == "CLOSE_SINGLE_SIDED"
    late = _quote(captured_at=KICKOFF.isoformat())
    assert _evaluate(late)["reason"] == "CLOSE_NOT_PREKICKOFF"
    stale = _quote(captured_at=(KICKOFF - timedelta(minutes=61)).isoformat())
    assert _evaluate(stale)["reason"] == "CLOSE_STALE"


def test_close_validity_checked_before_moved_classification():
    # A stale close at a different line is a capture failure
    # (CLOSE_STALE), never a moved row.
    stale_moved = _quote(
        line=14.5,
        captured_at=(KICKOFF - timedelta(minutes=90)).isoformat())
    out = _evaluate(stale_moved)
    assert out["disposition"] == "CLV_MISSING"
    assert out["reason"] == "CLOSE_STALE"


def test_moved_direction_relative_to_selected_side():
    down = _evaluate(_quote(line=12.5))
    assert down["disposition"] == "LINE_MOVED"
    assert down["direction"] == "FAVORABLE"   # OVER helped by a lower line
    up = _evaluate(_quote(line=14.5))
    assert up["direction"] == "ADVERSE"
    under_down = _evaluate(_quote(line=12.5), selected_side="B")
    assert under_down["direction"] == "ADVERSE"
    under_up = _evaluate(_quote(line=14.5), selected_side="B")
    assert under_up["direction"] == "FAVORABLE"


def test_moneyline_close_is_never_line_moved():
    ml = _quote(market="ML_1Q", line=None, price_a=-150, price_b=130)
    out = fwd.evaluate_close(market="ML_1Q", entry_line=None,
                             selected_side="A", close=ml, kickoff=KICKOFF)
    assert out["disposition"] == "VALID"


def test_close_accounting_trip_counts_only_capture_failures():
    def row(reason=None, disposition=None, direction=None):
        return {"market": "TOTAL_1Q", "close_reason": reason,
                "close_disposition": disposition,
                "move_direction": direction}

    rows = ([row("NO_CLOSE_ROW", "CLV_MISSING")] * 2
            + [row("LINE_MOVED", "LINE_MOVED", "ADVERSE")] * 5
            + [row(None, "VALID")] * 3)
    acct = fwd.market_close_accounting(rows)["TOTAL_1Q"]
    assert acct["capture_failure_share"] == 0.2
    assert acct["insufficient_close_data"] is False  # trip is > 20%
    assert acct["moved_share"] == 0.5 and acct["low_coverage"] is False

    rows = ([row("CLOSE_STALE", "CLV_MISSING")] * 3
            + [row("LINE_MOVED", "LINE_MOVED", "FAVORABLE")] * 6
            + [row(None, "VALID")] * 1)
    acct = fwd.market_close_accounting(rows)["TOTAL_1Q"]
    assert acct["insufficient_close_data"] is True
    assert acct["low_coverage"] is True  # moved share 0.6 > 0.5
    assert acct["moved_favorable"] == 6


# ------------------------------------------------------------------
# Form gates
# ------------------------------------------------------------------
def test_quote_form_gate_refuses_coercions():
    with pytest.raises(fwd.NflPeriodForwardError):
        _quote(price_a=-110.0).validate()
    with pytest.raises(fwd.NflPeriodForwardError):
        _quote(line="13.5").validate()
    with pytest.raises(fwd.NflPeriodForwardError):
        _quote(market="TOTAL_2H").validate()
    with pytest.raises(fwd.NflPeriodForwardError):
        _quote(market="ML_1Q", line=0.0).validate()


# ------------------------------------------------------------------
# B0 share fit: float-exact vs the pinned screen's baseline_rows
# ------------------------------------------------------------------
def _synthetic_panel():
    rows = []
    panels = {  # (season, week, game, team) -> quarters
        (2023, 17, "p23a", "AAA"): (7, 3, 7, 7),
        (2023, 17, "p23a", "BBB"): (0, 7, 3, 7),
        (2023, 18, "p23b", "AAA"): (3, 7, 0, 10),
        (2023, 18, "p23b", "BBB"): (7, 7, 7, 0),
        (2024, 1, "p24a", "AAA"): (10, 0, 7, 3),
        (2024, 1, "p24a", "BBB"): (3, 10, 0, 7),
        (2024, 2, "p24b", "AAA"): (7, 7, 7, 7),
        (2024, 2, "p24b", "BBB"): (7, 0, 14, 0),
        (2024, 3, "p24c", "AAA"): (0, 3, 10, 7),
        (2024, 3, "p24c", "BBB"): (14, 3, 0, 3),
    }
    for (season, week, gid, team), q in panels.items():
        rows.append({"game_id": gid, "season": season, "week": week,
                     "team": team, "q1": float(q[0]), "q2": float(q[1]),
                     "q3": float(q[2]), "q4": float(q[3])})
    return pd.DataFrame(rows)


class _FakeWalkForward:
    def __init__(self, panel):
        self.mu_by_game_team = {(r.game_id, r.team): 22.0
                                for r in panel.itertuples()}


def test_b0_share_fit_float_exact_vs_screen_baseline_rows():
    runner = fwd.NflPeriodForwardRunner(repo_root=REPO_ROOT)
    engine = runner.engine()
    v1 = runner.v1()
    panel = _synthetic_panel()
    base = engine.baseline_rows(v1, _FakeWalkForward(panel), panel)
    base_idx = base.set_index(["game_id", "team"])

    # Week-3 game: the final-before set is every earlier game; the
    # two forms coincide, so the B0 vectors are float-exact.
    final_before = {"p23a", "p23b", "p24a", "p24b"}
    shares, fit = fwd.fit_b0_shares(panel, season=2024,
                                    final_before_game_ids=final_before)
    assert fit["basis"] == "SAME_SEASON_PRIORS"
    for team in ("AAA", "BBB"):
        mine = 22.0 * shares
        theirs = np.asarray(base_idx.loc[("p24c", team), "b0_q"],
                            dtype=float)
        assert np.array_equal(mine, theirs), team

    # Week-1 game: prior season's final shares, same agreement.
    shares, fit = fwd.fit_b0_shares(panel, season=2024,
                                    final_before_game_ids={"p23a", "p23b"})
    assert fit["basis"] == "PRIOR_SEASON_FINAL"
    for team in ("AAA", "BBB"):
        mine = 22.0 * shares
        theirs = np.asarray(base_idx.loc[("p24a", team), "b0_q"],
                            dtype=float)
        assert np.array_equal(mine, theirs), team


# ------------------------------------------------------------------
# NON_COUNTED pricing vs the pinned construction, float-exact
# ------------------------------------------------------------------
def _prepared_plays(game_specs, seed=7):
    """Prepared play frames in the pinned screen's own synthetic
    shape (cf. tests/test_nfl_period_drive_state_v2.py)."""
    engine_mod = fwd.NflPeriodForwardRunner(
        repo_root=REPO_ROOT).engine()
    rng = np.random.default_rng(seed)
    rows = []
    pid = 0
    for gid, season, week, home, away in game_specs:
        for drive in range(22):
            team = home if drive % 2 == 0 else away
            opp = away if team == home else home
            x = float(rng.integers(15, 45))
            for _ in range(rng.integers(3, 9)):
                pid += 1
                is_pass = rng.random() < 0.55
                gain = float(rng.integers(-5, 25)) if is_pass \
                    else float(rng.integers(-3, 15))
                diff = float(rng.integers(-21, 22))
                rows.append({
                    "game_id": gid, "play_id": pid, "season": season,
                    "week": week, "posteam": team, "defteam": opp,
                    "home_team": home, "away_team": away,
                    "play_type": "pass" if is_pass else "run",
                    "is_scrimmage": True,
                    "family": 1 if is_pass else 0,
                    "down": int(rng.integers(1, 5)),
                    "ydstogo": float(rng.integers(1, 15)),
                    "yardline_100": 100.0 - x,
                    "x_start": x,
                    "game_seconds_remaining": float(rng.integers(60, 3600)),
                    "pre_diff": diff,
                    "diff_b": engine_mod.diff_bucket(diff),
                    "time_b": int(rng.integers(0, 5)),
                    "pass_attempt": 1 if is_pass else 0,
                    "complete_pass": 1 if (is_pass
                                           and rng.random() < 0.62) else 0,
                    "sack": 1 if (is_pass and rng.random() < 0.07) else 0,
                    "interception": 1 if (is_pass
                                          and rng.random() < 0.02) else 0,
                    "fumble_lost": 1 if rng.random() < 0.008 else 0,
                    "yards_gained": gain,
                    "sec_consumed": float(rng.integers(4, 45)),
                    "penalty": 0, "penalty_team": None,
                    "penalty_yards": np.nan, "first_down_penalty": 0,
                    "extra_point_result": None,
                    "two_point_conv_result": None,
                    "safety": 0, "touchdown": 0,
                    "field_goal_result": None,
                    "fixed_drive": drive,
                    "fixed_drive_result": "Punt",
                    "goal_to_go": 0, "qb_scramble": 0,
                })
                x += gain
                if x >= 100 or x <= 0:
                    break
    return pd.DataFrame(rows)


def _synthetic_history():
    specs = [("s22a", 2022, 1, "AAA", "BBB"),
             ("s22b", 2022, 2, "BBB", "AAA"),
             ("s22c", 2022, 3, "AAA", "BBB"),
             ("s22d", 2022, 4, "BBB", "AAA"),
             ("s23a", 2023, 1, "AAA", "BBB"),
             ("s23b", 2023, 2, "BBB", "AAA"),
             ("s23t", 2023, 5, "AAA", "BBB")]
    plays = _prepared_plays(specs)
    runner = fwd.NflPeriodForwardRunner(repo_root=REPO_ROOT)
    engine = runner.engine()
    starts = engine.drive_starts(plays)
    starts = starts.assign(season=starts["game_id"].map(
        plays.groupby("game_id")["season"].first()))
    agg = engine.team_game_aggregates(plays, starts)
    gamedays = {"s22a": "2022-09-11", "s22b": "2022-09-18",
                "s22c": "2022-09-25", "s22d": "2022-10-02",
                "s23a": "2023-09-10", "s23b": "2023-09-17",
                "s23t": "2023-10-08"}
    games = pd.DataFrame([{
        "game_id": gid, "season": season, "week": week,
        "gameday": gamedays[gid], "gametime": "13:00",
        "game_type": "REG", "home_team": home, "away_team": away,
        "home_score": 24, "away_score": 17,
    } for gid, season, week, home, away in specs])
    panel = pd.DataFrame([{
        "game_id": gid, "season": season, "week": week, "team": team,
        "q1": 7.0, "q2": 7.0, "q3": 3.0,
        "q4": 7.0 if team == home else 0.0,
    } for gid, season, week, home, away in specs
        for team in (home, away)])
    history = fwd.PeriodHistory(
        games=games, panel=panel, plays=plays, starts=starts, agg=agg,
        input_hashes={"synthetic": "0" * 64},
        panel_integrity={"n_team_games": 14})
    return runner, engine, history


def test_price_slate_matches_pinned_construction_float_exact(monkeypatch):
    runner, engine, history = _synthetic_history()
    monkeypatch.setattr(engine, "R_REPS", 400)
    target = fwd.SlateGame(game_id="s23t", season=2023, week=5,
                           gameday="2023-10-08",
                           kickoff="2023-10-08T13:00:00-04:00",
                           home="AAA", away="BBB")
    entry_at = "2023-10-08T12:00:00-04:00"
    quotes = [
        fwd.PeriodQuote(game_id="s23t", market="TOTAL_1Q", team=None,
                        line=13.5, price_a=-110, price_b=-110,
                        captured_at=entry_at, source="TEST"),
        fwd.PeriodQuote(game_id="s23t", market="TEAM_TOTAL_1Q",
                        team="AAA", line=7.5, price_a=-110, price_b=-110,
                        captured_at=entry_at, source="TEST"),
        fwd.PeriodQuote(game_id="s23t", market="ML_1Q", team=None,
                        line=None, price_a=-150, price_b=130,
                        captured_at=entry_at, source="TEST"),
    ]
    out = runner.price_slate(history, [target], quotes)
    assert out["run"]["counted_rows"] == 0
    assert out["run"]["game_index_order"] == ["s23t"]
    rows = {r["market"]: r for r in out["rows"]}
    assert set(rows) == {"TOTAL_1Q", "TEAM_TOTAL_1Q", "ML_1Q"}
    assert all(r["counted"] is False for r in rows.values())
    assert all(r["construction_pin"] == fwd.ENGINE_PIN
               for r in rows.values())

    # Independent recomputation through the pinned machinery with
    # the same seed derivation and point-in-time state.
    fit = engine.LeagueFit(history.plays[history.plays["season"] < 2023],
                           history.starts[history.starts["season"] < 2023])
    book = engine.TeamRateBook(history.agg, None)
    for gid in history.book_order:
        if gid != "s23t":
            book.record_game(gid)
    rng = np.random.default_rng(np.random.SeedSequence([fwd.MASTER_SEED, 0]))
    sim = engine.simulate_game(fit, book.bundle("AAA", 2023),
                               book.bundle("BBB", 2023), rng)
    home_q, away_q = sim["home_q"], sim["away_q"]
    assert rows["TOTAL_1Q"]["model"]["mean"] == \
        float((home_q[:, 0] + away_q[:, 0]).mean())
    assert rows["TEAM_TOTAL_1Q"]["model"]["mean"] == \
        float(home_q[:, 0].mean())
    assert rows["ML_1Q"]["model"]["p_a"] == \
        float(np.mean(home_q[:, 0] > away_q[:, 0]))
    assert rows["TOTAL_1Q"]["baseline_ref"]["kind"] == "B0"
    assert rows["TOTAL_1Q"]["baseline_ref"]["stamp"] == \
        "B0_SHARE_FIT_READING_FLAG5"


# ------------------------------------------------------------------
# Settlement: grading + close dispositions end to end
# ------------------------------------------------------------------
def _priced_row(**kw):
    row = {"row_id": "g1:TOTAL_1Q", "game_id": "g1",
           "market": "TOTAL_1Q", "team": None,
           "kickoff": KICKOFF.isoformat(), "line": 13.5,
           "selected_side": "A", "pick": {"side": "A"},
           "entry_novig": {"a": 0.5, "b": 0.5}}
    row.update(kw)
    return row


def test_settle_records_end_to_end():
    runner = fwd.NflPeriodForwardRunner(repo_root=REPO_ROOT)
    finals = {"g1": {"status": "FINAL", "home": "AAA", "away": "BBB",
                     "home_quarters": (10, 7, 3, 7),
                     "away_quarters": (7, 3, 7, 0)},
              "g2": {"status": "VOID", "game_id": "g2"}}
    rows = [_priced_row(),
            _priced_row(row_id="g2:TOTAL_1Q", game_id="g2"),
            _priced_row(row_id="g3:TOTAL_1Q", game_id="g3")]
    closes = [_quote()]  # same line, in window -> VALID
    out = runner.settle_records(rows, closes, finals)
    by_id = {s["row_id"]: s for s in out["settlements"]}
    g1 = by_id["g1:TOTAL_1Q"]
    assert g1["disposition"] == "GRADED" and g1["actual"] == 17.0
    assert g1["result"] == "WIN" and g1["close_disposition"] == "VALID"
    assert g1["clv"] == 0.0
    assert by_id["g2:TOTAL_1Q"]["disposition"] == "VOID"
    assert by_id["g3:TOTAL_1Q"]["disposition"] == "RESULT_UNAVAILABLE"
    assert out["summary"]["counted"] is False

    moved = runner.settle_records([_priced_row()], [_quote(line=14.5)],
                                  finals)
    s = moved["settlements"][0]
    assert s["close_disposition"] == "LINE_MOVED"
    assert s["move_direction"] == "ADVERSE" and s["clv"] is None

    push = runner.settle_records(
        [_priced_row(line=17.0)], [_quote(line=17.0)], finals)
    assert push["settlements"][0]["result"] == "PUSH"
