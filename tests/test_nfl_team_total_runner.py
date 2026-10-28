"""Tests for the NFL team-totals forward runner (the freeze pin's
record path): sportsedge/nfl_team_total_runner.py.

Covers the preregistration's section 12 checklist item for section 6b:
the runner records Lane A's emitted means alongside the candidate rows
for the same team-game — proven here by comparing each record's Lane A
mean against a direct Lane A ``calculate`` emission for that game.
Also covers the runner's fail-closed refusal set, its create-only
record writer, and the section 7 close dispositions at settlement.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artifacts import free_models as lane_a
from sportsedge import nfl_team_total_dist as eng
from sportsedge import nfl_team_total_runner as runner
from sportsedge.forward_validation.core import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
CT = timezone(timedelta(hours=-5))
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=CT)
KICKOFF = "2026-11-01T19:20:00-05:00"


def G(season, week, gameday, gid, home, away, hs, as_):
    return eng.GameRecord(season=season, week=week, gameday=gameday,
                          game_id=gid, home_team=home, away_team=away,
                          home_score=hs, away_score=as_)


def _history():
    return [
        G(2025, 10, "2025-11-02", "2025_10_BUF_KC", "KC", "BUF", 30, 20),
        G(2025, 12, "2025-11-23", "2025_12_DEN_BUF", "BUF", "DEN", 24, 27),
        G(2025, 14, "2025-12-07", "2025_14_MIA_KC", "KC", "MIA", 17, 23),
        G(2026, 1, "2026-09-10", "2026_01_KC_DEN", "DEN", "KC", 21, 28),
        G(2026, 3, "2026-09-27", "2026_03_BUF_MIA", "MIA", "BUF", 13, 31),
        G(2026, 5, "2026-10-11", "2026_05_DEN_KC", "KC", "DEN", 26, 19),
        G(2026, 7, "2026-10-25", "2026_07_BUF_DEN", "DEN", "BUF", 22, 25),
    ]


def _quote(line=24.5, over=-110, under=-110, at=None):
    at = at or (NOW - timedelta(seconds=60))
    stamp = at.isoformat()
    return runner.PairedQuote(line=line, over_price=over,
                              under_price=under, over_captured_at=stamp,
                              under_captured_at=stamp)


def _game(**overrides):
    base = dict(
        game_id="2026_09_BUF_KC", season=2026, week=9,
        gameday="2026-11-01", home_team="KC", away_team="BUF",
        home_name="Kansas City Chiefs", away_name="Buffalo Bills",
        kickoff=KICKOFF,
        entry_quotes={"KC": _quote(24.5), "BUF": _quote(23.5)},
        total_line=47.5, total_over_price=-110)
    base.update(overrides)
    return runner.SlateGame(**base)


def _price(games, **kw):
    r = runner.TeamTotalRunner(_history())
    kw.setdefault("lane_a_provider", None)
    kw.setdefault("lane_a_auto_context", False)
    return r.price_slate("2026-11-01", games, now=NOW, **kw)


def _lane_a_direct(game, team_side):
    row = {"sport": "NFL", "market": "TOTAL", "side": "OVER",
           "line": game.total_line, "odds": game.total_over_price,
           "away": game.away_name, "home": game.home_name,
           "commence_time": game.kickoff}
    result = lane_a.calculate(row, None, NOW, auto_context=False, lane="A")
    view = result["pricing_lanes"]["lane_a_independent"]
    return view["home_mean"] if team_side == "HOME" else view["away_mean"]


# ---------------------------------------------------------------------------
# Pricing + the section 6b Lane A recording (preregistration section 12)
# ---------------------------------------------------------------------------

def test_runner_prices_rows_and_records_lane_a_means():
    game = _game()
    out = _price([game])
    assert out["refusals"] == []
    assert len(out["records"]) == 2
    # Independent engine recomputation for the candidate means.
    engine = eng.TeamTotalDistEngine()
    engine.process_snapshot(_history())
    home_pred, away_pred = engine.predict_game(
        G(2026, 9, "2026-11-01", game.game_id, "KC", "BUF", None, None))
    by_team = {r["team"]: r for r in out["records"]}
    for team, pred, side in (("KC", home_pred, "HOME"),
                             ("BUF", away_pred, "AWAY")):
        rec = by_team[team]
        assert rec["mu"] == pytest.approx(pred.mu)
        assert rec["b1_team_mean"] == pytest.approx(pred.b1_team_mean)
        assert rec["b2_league_mean"] == pytest.approx(pred.b2_league_mean)
        # Section 6b: the recorded Lane A mean IS Lane A's own emission
        # for the same team-game (direct calculate() comparison).
        assert rec["lane_a"]["team_mean"] == pytest.approx(
            _lane_a_direct(game, side))
        assert rec["lane_a"]["artifacts_free_models_sha256"] == \
            hashlib.sha256(Path(lane_a.__file__).read_bytes()).hexdigest()
        # Distribution + probabilities are a real partition.
        assert sum(rec["distribution"]["pmf"]) == pytest.approx(1.0, abs=1e-6)
        mp = rec["model_p"]
        assert mp["OVER"] + mp["UNDER"] + mp["PUSH"] == pytest.approx(1.0)
        # Freeze pins carried on the record (preregistration section 11).
        assert rec["engine_sha256"] == hashlib.sha256(
            (REPO_ROOT / "sportsedge" / "nfl_team_total_dist.py")
            .read_bytes()).hexdigest()
        assert rec["runner_sha256"] == hashlib.sha256(
            (REPO_ROOT / "sportsedge" / "nfl_team_total_runner.py")
            .read_bytes()).hexdigest()
        cfg = load_config(REPO_ROOT / "sportsedge" / "forward_validation"
                          / "configs" / "nfl_team_total.json")
        assert rec["model_version"] == cfg.model_version
        assert rec["config_sha256"] == cfg.sha256
        assert rec["prereg_sha256"] == cfg.prereg_sha256
        assert rec["history_snapshot_sha256"] == \
            runner.history_snapshot_sha256(_history())
        assert rec["label"] == "PROSPECTIVE"
        assert rec["pick"] in ("PICKED_OVER", "PICKED_UNDER", "PASSED")
        assert rec["gap"] == pytest.approx(
            rec["mu"] - rec["entry"]["line"])


def test_pick_rule_boundaries():
    probe = _price([_game()])["records"]
    mu_kc = next(r["mu"] for r in probe if r["team"] == "KC")
    at_boundary = _game(entry_quotes={
        "KC": _quote(line=mu_kc - 2.0), "BUF": _quote(line=23.5)})
    rec = next(r for r in _price([at_boundary])["records"]
               if r["team"] == "KC")
    assert rec["pick"] == "PICKED_OVER"
    inside = _game(entry_quotes={
        "KC": _quote(line=mu_kc - 1.9), "BUF": _quote(line=23.5)})
    rec = next(r for r in _price([inside])["records"] if r["team"] == "KC")
    assert rec["pick"] == "PASSED"


# ---------------------------------------------------------------------------
# Fail-closed refusals (one code per row; the slate never aborts)
# ---------------------------------------------------------------------------

def test_lane_a_emission_missing_refuses_rows():
    out = _price([_game(total_line=None)])
    assert out["records"] == []
    assert {r["reason"] for r in out["refusals"]} == \
        {"LANE_A_EMISSION_MISSING"}


def test_entry_refusal_codes():
    cases = [
        ({"KC": _quote(under=None)}, "ENTRY_SINGLE_SIDED"),
        ({"KC": _quote(over=-50)}, "PRICE_INVALID"),
        ({"KC": _quote(line=-3)}, "LINE_INVALID"),
        ({"KC": runner.PairedQuote(
            line=24.5, over_price=-110, under_price=-110,
            over_captured_at=(NOW - timedelta(seconds=60)).isoformat(),
            under_captured_at=(NOW - timedelta(seconds=200)).isoformat())},
         "ENTRY_PAIR_SPAN_EXCEEDED"),
        ({"KC": _quote(at=NOW - timedelta(seconds=300))}, "QUOTE_STALE_180S"),
        ({"KC": _quote(at=NOW + timedelta(hours=8))}, "ENTRY_NOT_PRE_EVENT"),
    ]
    for quotes, code in cases:
        full = {"KC": _quote(), "BUF": _quote()}
        full.update(quotes)
        out = _price([_game(entry_quotes=full)])
        reasons = {r["team"]: r["reason"] for r in out["refusals"]}
        assert reasons.get("KC") == code, (code, reasons)
        # The other team's row still prices: a bad row never aborts.
        assert any(r["team"] == "BUF" for r in out["records"]) or \
            code == "ENTRY_NOT_PRE_EVENT"
    missing = _price([_game(entry_quotes={"BUF": _quote()})])
    assert {r["team"]: r["reason"] for r in missing["refusals"]} == \
        {"KC": "ENTRY_CAPTURE_MISSING"}


def test_duplicate_row_refused():
    game = _game()
    out = _price([game, game])
    reasons = [r["reason"] for r in out["refusals"]]
    assert reasons == ["DUPLICATE_ROW", "DUPLICATE_ROW"]
    assert len(out["records"]) == 2


def test_model_version_mismatch_refuses_run(tmp_path):
    cfg = json.loads((REPO_ROOT / "sportsedge" / "forward_validation"
                      / "configs" / "nfl_team_total.json").read_text())
    cfg["model_version"] = "nfl_team_total_dist_v1@sha256:" + "0" * 64
    bad = tmp_path / "nfl_team_total.json"
    bad.write_text(json.dumps(cfg))
    with pytest.raises(runner.RunnerRefusal) as ei:
        runner.TeamTotalRunner(_history(), config_path=bad)
    assert ei.value.code == "MODEL_VERSION_MISMATCH"


def test_history_snapshot_invalid_refuses_run():
    bad = _history() + [G(2026, 8, "2026-10-29", "2026_08_KC_BUF",
                          "BUF", "KC", None, None)]
    with pytest.raises(runner.RunnerRefusal) as ei:
        runner.TeamTotalRunner(bad)
    assert ei.value.code == "HISTORY_SNAPSHOT_INVALID"


def test_record_writer_is_create_only(tmp_path):
    out = _price([_game()])
    path = runner.write_entry_records(out["records"],
                                      tmp_path / "slate.jsonl")
    lines = path.read_text().strip().split("\n")
    assert [json.loads(x)["row_id"] for x in lines] == \
        [r["row_id"] for r in out["records"]]
    with pytest.raises(runner.RunnerRefusal):
        runner.write_entry_records(out["records"], path)


# ---------------------------------------------------------------------------
# Settlement: section 7 close dispositions
# ---------------------------------------------------------------------------

def _record(team="KC", line=24.5):
    game = _game(entry_quotes={"KC": _quote(line=line),
                               "BUF": _quote(line=23.5)})
    out = _price([game])
    return next(r for r in out["records"] if r["team"] == team)


def _close_quote(line=24.5, over=-110, under=-110, minutes_before=40):
    kickoff = datetime.fromisoformat(KICKOFF)
    stamp = (kickoff - timedelta(minutes=minutes_before)).isoformat()
    return runner.PairedQuote(line=line, over_price=over,
                              under_price=under, over_captured_at=stamp,
                              under_captured_at=stamp)


def test_close_readable_graded_and_push():
    rec = _record()
    settled = runner.evaluate_close(rec, [_close_quote()],
                                    final_team_points=27)
    assert settled["close_status"] == "READABLE"
    assert settled["close"]["line"] == 24.5
    assert settled["settlement"] == "GRADED"
    assert settled["final_team_points"] == 27
    whole = _record(line=24.0)
    pushed = runner.evaluate_close(whole, [_close_quote(line=24.0)],
                                   final_team_points=24)
    assert pushed.get("push") is True


def test_close_moved_direction_adverse_for_over_pick():
    rec = _record(line=10.5)  # mu ~ 24 -> gap >> +2 -> PICKED_OVER
    assert rec["pick"] == "PICKED_OVER"
    settled = runner.evaluate_close(
        rec, [_close_quote(line=13.5, over=-110, under=-110)],
        final_team_points=27)
    assert settled["close_status"] == "LINE_MOVED"
    assert settled["moved_side"] == "OVER"
    assert settled["moved_direction"] == "ADVERSE"


def test_close_dispositions():
    rec = _record()
    kickoff = datetime.fromisoformat(KICKOFF)
    assert runner.evaluate_close(rec, [])["close_status"] == "NO_CLOSE_ROW"
    post = runner.PairedQuote(
        line=24.5, over_price=-110, under_price=-110,
        over_captured_at=(kickoff + timedelta(minutes=1)).isoformat(),
        under_captured_at=(kickoff + timedelta(minutes=1)).isoformat())
    assert runner.evaluate_close(rec, [post])["close_status"] == \
        "CLOSE_NOT_PREKICKOFF"
    assert runner.evaluate_close(
        rec, [_close_quote(minutes_before=70)])["close_status"] == \
        "CLOSE_STALE"
    single = runner.PairedQuote(
        line=24.5, over_price=-110, under_price=None,
        over_captured_at=(kickoff - timedelta(minutes=30)).isoformat(),
        under_captured_at=(kickoff - timedelta(minutes=30)).isoformat())
    assert runner.evaluate_close(rec, [single])["close_status"] == \
        "CLOSE_SINGLE_SIDED"
    span = runner.PairedQuote(
        line=24.5, over_price=-110, under_price=-110,
        over_captured_at=(kickoff - timedelta(minutes=30)).isoformat(),
        under_captured_at=(kickoff - timedelta(minutes=27)).isoformat())
    assert runner.evaluate_close(rec, [span])["close_status"] == \
        "PAIR_SPAN_EXCEEDED"
    assert runner.evaluate_close(rec, [_close_quote()],
                                  void=True)["settlement"] == "VOID"
    assert runner.evaluate_close(rec, [_close_quote()])["settlement"] == \
        "RESULT_UNAVAILABLE"
