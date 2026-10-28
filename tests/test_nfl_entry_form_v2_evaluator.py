"""NFL_ENTRY_FORM_V2 evaluator adapter tests (DESIGN stage — NOT FROZEN).

Covers: the EF_V2_FREEZE_NOT_AUTHORIZED refusal on every counted entry
point; the v1.1 close rule (PREREG_DRAFT §8) — the five frozen reason
codes in shared-evaluator order, the moved bucket with direction, the
second verdict test's exact sign test, the 20% trip counting only true
capture failures, LOW_COVERAGE; and the §6 accuracy-kill instrument.
"""
import pytest

from sportsedge import nfl_entry_form_v2_evaluator as ev

KO = "2025-11-09T18:00:00+00:00"


def row(game="G1", market="SPREAD", decision="PICK", side="HOME",
        line=-3.5, prices=None, price=-110, d=5.0, p=0.64, proj=-8.0):
    first, second = ("HOME", "AWAY") if market == "SPREAD" else ("OVER", "UNDER")
    return {
        "row_id": f"{game}:{market}", "game_id": game, "market": market,
        "decision": decision,
        "selected_side": side if decision == "PICK" else "PASS",
        "preferred_side": side,
        "entry_line": line,
        "entry_prices": prices or {first: -110, second: -110},
        "picked_price": price if decision == "PICK" else None,
        "d": d, "p_stated": p, "projection": proj,
        "counted": False,
    }


def close(game="G1", market="SPREAD", line=-3.5, prices=None,
          captured="2025-11-09T17:50:00+00:00"):
    first, second = ("HOME", "AWAY") if market == "SPREAD" else ("OVER", "UNDER")
    return {"game_id": game, "market": market, "line": line,
            "prices": prices if prices is not None else {first: -110, second: -110},
            "captured_at": captured}


def result(home=30, away=20):
    return {"home_score": home, "away_score": away}


def grade(rows, closes, results=None, kickoffs=None):
    games = {r["game_id"] for r in rows}
    return ev.grade_records(
        rows, closes,
        results if results is not None else {g: result() for g in games},
        kickoffs if kickoffs is not None else {g: KO for g in games})


# ---------------------------------------------------------------------------
# The refusal (PREREG_DRAFT §7.6)
# ---------------------------------------------------------------------------

def test_counted_entry_points_refused():
    for call in (lambda: ev.count_rows([]),
                 lambda: ev.score_counted([], [], {}, {}),
                 lambda: ev.verdict([], [], {}, {})):
        with pytest.raises(ev.EFV2FreezeNotAuthorized) as exc:
            call()
        assert exc.value.reason == "EF_V2_FREEZE_NOT_AUTHORIZED"
    assert ev.FREEZE_PIN is None  # no freeze exists; nothing may set it here


def test_diagnostics_stamped_non_counted():
    out = grade([row()], [close()])
    assert out["counted"] is False
    assert out["markets"]["SPREAD"]["counted"] is False


# ---------------------------------------------------------------------------
# Close dispositions — the five frozen codes (PREREG §8)
# ---------------------------------------------------------------------------

def test_no_close_row():
    out = grade([row()], [])
    assert out["rows"][0]["close_status"] == "NO_CLOSE_ROW"


def test_line_moved_direction_spread():
    # Line units are home-margin (positive = home favored). HOME pick:
    # close up (toward home) = FAVORABLE, down = ADVERSE.
    fav = grade([row(line=3.5)], [close(line=6.5)])
    assert fav["rows"][0]["close_status"] == "LINE_MOVED"
    assert fav["rows"][0]["moved_direction"] == "FAVORABLE"
    adv = grade([row(line=3.5)], [close(line=1.5)])
    assert adv["rows"][0]["moved_direction"] == "ADVERSE"
    # AWAY pick; close down (toward away) = FAVORABLE.
    away = grade([row(side="AWAY", d=-5.0, line=3.5)], [close(line=1.5)])
    assert away["rows"][0]["moved_direction"] == "FAVORABLE"


def test_line_moved_direction_totals():
    over = grade([row(market="TOTAL", side="OVER", line=44.5)],
                 [close(market="TOTAL", line=47.5)])
    assert over["rows"][0]["moved_direction"] == "FAVORABLE"
    under = grade([row(market="TOTAL", side="UNDER", line=44.5, d=-5.0)],
                  [close(market="TOTAL", line=47.5)])
    assert under["rows"][0]["moved_direction"] == "ADVERSE"


def test_single_sided_judged_before_timestamps():
    single = close(prices={"HOME": -110, "AWAY": None},
                   captured="2025-11-09T18:30:00+00:00")  # also post-kickoff
    out = grade([row()], [single])
    assert out["rows"][0]["close_status"] == "CLOSE_SINGLE_SIDED"


def test_close_not_prekickoff():
    out = grade([row()], [close(captured="2025-11-09T18:00:00+00:00")])
    assert out["rows"][0]["close_status"] == "CLOSE_NOT_PREKICKOFF"


def test_close_stale_boundary():
    stale = grade([row()], [close(captured="2025-11-09T16:59:59+00:00")])
    assert stale["rows"][0]["close_status"] == "CLOSE_STALE"
    boundary = grade([row()], [close(captured="2025-11-09T17:00:00+00:00")])
    assert boundary["rows"][0]["close_status"] == "READABLE"  # exactly 60m is valid


def test_readable_clv_in_shared_evaluator_units():
    # Entry -110/-110 (novig .5); close -120/-100 -> home novig .521739...
    out = grade([row()], [close(prices={"HOME": -120, "AWAY": -100})])
    r = out["rows"][0]
    assert r["close_status"] == "READABLE"
    assert r["clv"] == pytest.approx(0.5217391304347826 - 0.5)


def test_moved_row_stays_in_winloss_at_entry_line():
    # Pick HOME at entry line 3.5 (home-margin units); final margin +10
    # wins at the entry line even though the close moved to 6.5 (never
    # repriced, PREREG §8 rule 1).
    out = grade([row(line=3.5)], [close(line=6.5)], results={"G1": result(30, 20)})
    r = out["rows"][0]
    assert r["close_status"] == "LINE_MOVED"
    assert r["outcome"] == "WIN"
    assert r["clv"] is None  # moved rows leave the primary CLV average


# ---------------------------------------------------------------------------
# Settlement / ROI
# ---------------------------------------------------------------------------

def test_settlement_spread_and_total():
    win = grade([row()], [close()], results={"G1": result(30, 20)})  # margin 10 > -3.5... line units
    assert win["rows"][0]["outcome"] == "WIN"
    push = grade([row(line=10.0)], [close(line=10.0)], results={"G1": result(30, 20)})
    assert push["rows"][0]["outcome"] == "PUSH"
    tot = grade([row(market="TOTAL", side="UNDER", line=44.5, d=-5.0)],
                [close(market="TOTAL", line=44.5)], results={"G1": result(24, 20)})
    assert tot["rows"][0]["outcome"] == "WIN"  # total 44 < 44.5


def test_roi_at_actual_prices():
    rows = [row(game="G1"), row(game="G2")]
    closes = [close(game="G1"), close(game="G2")]
    out = grade(rows, closes,
                results={"G1": result(30, 20), "G2": result(10, 30)},
                kickoffs={"G1": KO, "G2": KO})
    diag = out["markets"]["SPREAD"]
    assert diag["record"] == {"win": 1, "loss": 1, "push": 0}
    assert diag["roi"] == pytest.approx(((100 / 110) - 1) / 2)


# ---------------------------------------------------------------------------
# Moved bucket / trip / coverage (PREREG §8 rules 2-4; §6.4)
# ---------------------------------------------------------------------------

def _slate(n_move, n_fail, n_read, market="SPREAD"):
    rows, closes, results, kickoffs = [], [], {}, {}
    i = 0
    for _ in range(n_move):
        i += 1
        g = f"M{i}"
        rows.append(row(game=g, market=market))
        closes.append(close(game=g, market=market, line=-6.5))
        results[g] = result(); kickoffs[g] = KO
    for _ in range(n_fail):
        i += 1
        g = f"F{i}"
        rows.append(row(game=g, market=market))  # no close -> NO_CLOSE_ROW
        results[g] = result(); kickoffs[g] = KO
    for _ in range(n_read):
        i += 1
        g = f"R{i}"
        rows.append(row(game=g, market=market))
        closes.append(close(game=g, market=market))
        results[g] = result(); kickoffs[g] = KO
    return ev.grade_records(rows, closes, results, kickoffs)


def test_trip_counts_only_true_failures():
    out = _slate(n_move=3, n_fail=1, n_read=6)  # 10 graded picks
    diag = out["markets"]["SPREAD"]
    assert diag["close_failures"]["share_of_graded_picks"] == pytest.approx(0.10)
    assert diag["close_failures"]["trip_20pct"] is False
    assert diag["moved"]["n"] == 3
    assert diag["clv"]["n"] == 6  # moved rows excluded from CLV


def test_trip_and_coverage_kill():
    out = _slate(n_move=0, n_fail=9, n_read=21)  # 30 graded picks, 30% failures
    diag = out["markets"]["SPREAD"]
    assert diag["close_failures"]["trip_20pct"] is True
    assert diag["close_failures"]["coverage_kill_fired"] is True  # §6.4 at >=25 picks


def test_low_coverage_label():
    out = _slate(n_move=6, n_fail=0, n_read=4)  # moved 60% of graded picks
    assert out["markets"]["SPREAD"]["low_coverage"] is True


def test_sign_test_exact():
    assert ev.sign_test_p(9, 10) == pytest.approx(11 / 1024)
    assert ev.sign_test_p(10, 10) == pytest.approx(1 / 1024)
    assert ev.sign_test_p(0, 0) is None


# ---------------------------------------------------------------------------
# Accuracy kill instrument (PREREG §6.3)
# ---------------------------------------------------------------------------

def _accuracy_slate(n, gap):
    rows, closes, results, kickoffs = [], [], {}, {}
    for i in range(n):
        g = f"A{i}"
        # PASS rows are priced rows too (§6.3 counts priced games).
        rows.append(row(game=g, decision="PASS", side="HOME", line=0.0,
                        proj=10.0 + gap, d=1.0))
        closes.append(close(game=g, line=0.0))
        results[g] = {"home_score": 25, "away_score": 20}  # actual margin 5
        kickoffs[g] = KO
    return ev.grade_records(rows, closes, results, kickoffs)


def test_accuracy_kill_fires_above_one_point():
    diag = _accuracy_slate(40, 1.2)["markets"]["SPREAD"]["accuracy_kill"]
    assert diag["evaluated"] is True
    assert diag["gap"] == pytest.approx(1.2)
    assert diag["fired"] is True


def test_accuracy_kill_quiet_below_threshold_and_below_40():
    assert _accuracy_slate(40, 0.5)["markets"]["SPREAD"]["accuracy_kill"]["fired"] is False
    small = _accuracy_slate(39, 3.0)["markets"]["SPREAD"]["accuracy_kill"]
    assert small["evaluated"] is False and small["fired"] is False
