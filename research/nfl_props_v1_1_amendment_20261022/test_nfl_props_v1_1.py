"""RED-first tests for the NFL props v1.1 moved-line amendment (Part 2 #2396, 2B #2415)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nfl_props_v1_1 as v11  # noqa: E402

FREEZE = "2026-10-25T16:00:00Z"


def row(i, side="OVER", line=250.5, status="READABLE", reason=None, game="G1",
        kickoff="2026-10-25T17:00:00Z", market="PASS_YDS", clv=0.01, result="WIN"):
    return {"row_id": f"r{i}", "game_id": game, "player_id": f"p{i}", "market": market,
            "line": line, "selected_side": side, "close_status": status,
            "clv_missing_reason": reason, "kickoff": kickoff, "outcome": "OVER",
            "selected_result": result, "clv": clv if status == "READABLE" else None}


def close(i, lines, market="PASS_YDS", game="G1", at="2026-10-25T16:30:00Z",
          over=-110, under=-110):
    return [{"game_id": game, "player_id": f"p{i}", "market": market, "line": l,
             "over_price": over, "under_price": under, "captured_at": at} for l in lines]


# --- move direction (no repricing, no model) ---
@pytest.mark.parametrize("side,lines,expected", [
    ("OVER", [260.5], "FAVORABLE"), ("OVER", [240.5], "ADVERSE"),
    ("UNDER", [240.5], "FAVORABLE"), ("UNDER", [260.5], "ADVERSE"),
    ("OVER", [240.5, 260.5], "AMBIGUOUS"), ("TIE", [260.5], "NO_PICK"),
])
def test_move_direction(side, lines, expected):
    assert v11.move_direction(side, 250.5, lines) == expected


def test_move_direction_rejects_entry_line_in_close():
    with pytest.raises(ValueError):
        v11.move_direction("OVER", 250.5, [250.5])


def test_annotate_never_reprices_or_adds_clv():
    r = row(1, status="CLV_MISSING", reason="LINE_MOVED")
    out = v11.annotate_moved([r], {"rows": close(1, [260.5])})[0]
    assert out["v11_bucket"] == "LINE_MOVED" and out["move_direction"] == "FAVORABLE"
    assert out["clv"] is None and "close_novig_p_over" not in out
    assert r.get("v11_bucket") is None  # input not mutated


def test_annotate_buckets():
    rows = [row(1), row(2, status="CLV_MISSING", reason="NO_CLOSE_ROW"),
            row(3, status="CLV_MISSING", reason="CLOSE_STALE")]
    out = v11.annotate_moved(rows, {"rows": []})
    assert [o["v11_bucket"] for o in out] == ["READABLE", "CAPTURE_FAILURE", "CAPTURE_FAILURE"]


def test_unknown_reason_fails_closed():
    with pytest.raises(ValueError):
        v11.annotate_moved([row(1, status="CLV_MISSING", reason="WEIRD")], {"rows": []})


# --- sign test ---
def test_sign_test_values():
    assert v11.sign_test_adverse(0, 0)["p_value"] == 1.0
    assert v11.sign_test_adverse(5, 5)["rejects"] is False
    t = v11.sign_test_adverse(favorable=2, adverse=13)  # P(X>=13|15,.5)=0.00369
    assert abs(t["p_value"] - 0.003692626953125) < 1e-12 and t["rejects"] is True
    assert v11.sign_test_adverse(favorable=0, adverse=4)["rejects"] is False  # 1/16 > .05
    assert v11.sign_test_adverse(favorable=0, adverse=5)["rejects"] is True   # 1/32 < .05


# --- aggregation & verdict ---
def market(n_readable, n_moved_fav, n_moved_adv, n_capfail, games=40):
    rows, closes, i = [], [], 0
    for k in range(n_readable):
        rows.append(row(i, game=f"G{i % games}")); i += 1
    for d, cnt in (("F", n_moved_fav), ("A", n_moved_adv)):
        for _ in range(cnt):
            rows.append(row(i, status="CLV_MISSING", reason="LINE_MOVED", game=f"G{i % games}",
                            result="LOSS"))
            closes += close(i, [260.5 if d == "F" else 240.5], game=f"G{i % games}"); i += 1
    for _ in range(n_capfail):
        rows.append(row(i, status="CLV_MISSING", reason="NO_CLOSE_ROW", game=f"G{i % games}")); i += 1
    return v11.annotate_moved(rows, {"rows": closes})


def test_moved_out_of_20pct_limit_and_clv_but_in_win_loss():
    agg = v11.aggregate_v11(market(70, 20, 20, 5), sample_gate=None, primary_clv_beats=True)
    assert agg["capture_failure_share"] == pytest.approx(5 / 115)
    assert agg["clv_rows"] == 70
    assert agg["win_loss"]["losses"] == 40
    assert agg["verdict"] == "BEATS_MARKET" and agg["play_eligible_alone"] is True


def test_capture_failures_still_trip_20pct():
    agg = v11.aggregate_v11(market(70, 5, 5, 25), sample_gate=None, primary_clv_beats=True)
    assert agg["verdict"] == "INSUFFICIENT_CLOSE_DATA"


def test_adverse_sign_test_blocks_beats_market():
    agg = v11.aggregate_v11(market(80, 2, 13, 0), sample_gate=None, primary_clv_beats=True)
    assert agg["verdict"] == "DOES_NOT_BEAT_MARKET"
    assert agg["verdict_reason"] == "MOVED_BUCKET_ADVERSE_SIGN_TEST"


def test_ambiguous_counts_as_adverse():
    rows = market(80, 0, 0, 0) + [
        dict(v11.annotate_moved([row(900 + k, status="CLV_MISSING", reason="LINE_MOVED")],
                                {"rows": close(900 + k, [240.5, 260.5])})[0]) for k in range(5)]
    agg = v11.aggregate_v11(rows, sample_gate=None, primary_clv_beats=True)
    assert agg["moved"]["adverse_for_test"] == 5 and agg["verdict"] == "DOES_NOT_BEAT_MARKET"


def test_low_coverage_over_50pct_cannot_open_play_alone():
    agg = v11.aggregate_v11(market(40, 25, 25, 0), sample_gate=None, primary_clv_beats=True)
    assert agg["verdict"] == "LOW_COVERAGE" and agg["play_eligible_alone"] is False
    exactly_half = v11.aggregate_v11(market(50, 25, 25, 0), sample_gate=None, primary_clv_beats=True)
    assert exactly_half["verdict"] == "BEATS_MARKET"  # >50% strict


def test_sample_gate_passthrough_and_primary_fail():
    assert v11.aggregate_v11(market(70, 0, 0, 0), sample_gate="REVIEW_NOT_OPEN",
                             primary_clv_beats=True)["verdict"] == "REVIEW_NOT_OPEN"
    assert v11.aggregate_v11(market(70, 0, 0, 0), sample_gate=None,
                             primary_clv_beats=False)["verdict"] == "DOES_NOT_BEAT_MARKET"


def test_bad_sample_gate_rejected():
    with pytest.raises(ValueError):
        v11.aggregate_v11([], sample_gate="BEATS_MARKET", primary_clv_beats=True)


# --- forward-only ---
def test_rows_before_freeze_rejected():
    with pytest.raises(ValueError, match="v1"):
        v11.assert_forward_only([row(1, kickoff="2026-10-23T00:15:00Z")], FREEZE)


def test_rows_at_or_before_freeze_kickoff_rejected():
    with pytest.raises(ValueError):
        v11.assert_forward_only([row(1, kickoff=FREEZE)], FREEZE)
    v11.assert_forward_only([row(1)], FREEZE)


def test_freeze_must_precede_sunday_deadline():
    with pytest.raises(ValueError):
        v11.validate_freeze_ts("2026-10-25T17:00:01Z")
    v11.validate_freeze_ts("2026-10-25T16:59:59Z")


# --- audit fix (NOT CLEARED on e7718590): re-check v1 LINE_MOVED closes ---
MOVED = dict(status="CLV_MISSING", reason="LINE_MOVED")


def one(cl):
    return v11.annotate_moved([row(1, **MOVED)], {"rows": cl})[0]


def test_post_kickoff_other_line_is_capture_failure():
    o = one(close(1, [260.5], at="2026-10-25T19:00:00Z"))
    assert o["v11_bucket"] == "CAPTURE_FAILURE" and o["v11_reason"] == "CLOSE_NOT_PREKICKOFF"


def test_stale_other_line_is_capture_failure():
    o = one(close(1, [260.5], at="2026-10-25T15:59:00Z"))  # 61 min before kickoff
    assert o["v11_bucket"] == "CAPTURE_FAILURE" and o["v11_reason"] == "CLOSE_STALE"


def test_single_sided_other_line_is_capture_failure():
    o = one(close(1, [260.5], over=None))
    assert o["v11_bucket"] == "CAPTURE_FAILURE" and o["v11_reason"] == "CLOSE_SINGLE_SIDED"


def test_no_other_line_rows_is_capture_failure():
    o = one([])
    assert o["v11_bucket"] == "CAPTURE_FAILURE" and o["v11_reason"] == "NO_CLOSE_ROW"


def test_precedence_single_sided_then_not_prekickoff_then_stale():
    cl = close(1, [260.5], over=None) + close(1, [262.5], at="2026-10-25T19:00:00Z")
    assert one(cl)["v11_reason"] == "CLOSE_NOT_PREKICKOFF"
    cl += close(1, [264.5], at="2026-10-25T15:00:00Z")
    assert one(cl)["v11_reason"] == "CLOSE_STALE"


def test_auditor_repro_postkick_single_sided_counts_against_20pct():
    o = one(close(1, [255.5], over=None, at="2026-10-25T19:00:00Z"))
    agg = v11.aggregate_v11([o] * 10, sample_gate=None, primary_clv_beats=True)
    assert agg["verdict"] == "INSUFFICIENT_CLOSE_DATA"


def test_direction_from_final_qualifying_capture_only():
    cl = (close(1, [240.5], at="2026-10-25T16:10:00Z")      # earlier qualifying: adverse
          + close(1, [260.5], at="2026-10-25T16:50:00Z")    # final qualifying: favorable
          + close(1, [230.5], at="2026-10-25T17:30:00Z")    # post-kickoff: ignored
          + close(1, [220.5], at="2026-10-25T16:55:00Z", under=None))  # one-sided: ignored
    o = one(cl)
    assert o["v11_bucket"] == "LINE_MOVED" and o["move_direction"] == "FAVORABLE"
    assert o["v11_close_captured_at"] == "2026-10-25T16:50:00Z"


def test_close_without_timestamp_fails_closed():
    cl = close(1, [260.5]); del cl[0]["captured_at"]
    with pytest.raises(ValueError):
        one(cl)


def test_line_moved_with_two_sided_entry_line_close_is_hard_error():
    cl = close(1, [250.5]) + close(1, [260.5])
    with pytest.raises(ValueError, match="entry line"):
        one(cl)
