"""Guards for the Amendment 2 counted machinery
(sportsedge/cbb_amendment2_machinery.py) -- the G-1/G-2/G-3 build
for CBB_TORVIK_EFFICIENCY_V1 and its team-totals readout.

The centerpiece is a reproduction test: the amendment's own
toy-slate computability proof (research/nba_cbb_activation_
20261028/verify_amendment2_toy_slate.py, pinned in the adoption
record) publishes every leg quantity for a 12-game invented
slate in AMENDMENT_2_DRAFT.md section 7. Feeding that same slate
through this module must reproduce those quantities -- the
machinery is the amendment's arithmetic, not a reinterpretation.

The toy tables below are copied from the pinned verifier. Toy
spread lines there are HOME lines; the production record
convention is the away line (side A's line), so spread entry
lines enter the records negated, and toy close pairs (home,
away) enter as (side_b, side_a). Toy finals are margin/total
pairs; home/away points are recovered as (total +/- margin)/2.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import cbb_amendment2_machinery as m
from sportsedge.cbb_torvik_efficiency_v1 import (
    CbbForwardError,
    no_vig_pair,
)

TIP = datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc)
TIP_ISO = "2026-11-02T18:30:00Z"

# Toy slate, efficiency markets (pinned verifier's GAMES):
# game id, model margin, baseline margin, actual margin, model
# total, baseline total, actual total, DK home spread line,
# spread prices (home, away), total prices (over, under), spread
# close, total close. Close forms: ("same", minutes, px_a, px_b)
# with pair order (home, away) for spread and (over, under) for
# totals; ("moved", new_line, minutes) with new_line a HOME line
# for spread and the total line for totals; ("stale", minutes);
# ("missing",).
GAMES = [
    ("T01", 7.0, 5.0, 9, 148.0, 145.0, 152, -4.5, -110, -110, -110, -110,
     ("same", 22, -120, 100), ("same", 22, -105, -115)),
    ("T02", 1.0, 2.5, -3, 139.0, 141.0, 133, -1.5, -110, -110, -110, -110,
     ("same", 15, -110, -110), ("same", 15, -110, -110)),
    ("T03", -8.0, -5.5, -11, 154.0, 150.0, 149, 6.5, -110, -110, -105, -115,
     ("same", 31, -110, -110), ("moved", 147.5, 12)),
    ("T04", 5.6, 3.0, 3, 144.0, 143.5, 147, -3.0, -110, -110, -110, -110,
     ("same", 9, -110, -110), ("same", 9, -110, -110)),
    ("T05", 12.0, 9.0, 6, 136.0, 138.0, 130, -9.5, -115, -105, -110, -110,
     ("moved", -11.5, 18), ("same", 18, -110, -110)),
    ("T06", -2.0, -1.0, 4, 158.0, 154.0, 159, 2.5, -110, -110, -110, -110,
     ("same", 26, -110, -110), ("missing",)),
    ("T07", 5.5, 6.5, 2, 141.5, 142.5, 138, -6.0, -110, -110, -110, -110,
     ("same", 44, -110, -110), ("same", 44, -110, -110)),
    ("T08", -13.0, -10.0, -18, 133.0, 135.5, 128, 10.5, -110, -110, -110, -110,
     ("same", 12, -115, -105), ("stale", 95)),
    ("T09", 4.2, 3.8, 8, 150.0, 147.0, 155, -4.0, -108, -112, -110, -110,
     ("same", 20, -110, -110), ("same", 20, -125, 105)),
    ("T10", 0.5, -0.5, -6, 146.5, 148.0, 142, 1.0, -110, -110, -110, -110,
     ("same", 17, -110, -110), ("same", 17, -110, -110)),
    ("T11", 9.0, 7.5, 13, 143.0, 141.0, 150, -7.5, -110, -110, -110, -110,
     ("same", 29, -110, -110), ("same", 29, 100, -120)),
    ("T12", -4.6, -3.0, -2, 138.5, 140.0, 136, 3.5, -110, -110, -110, -110,
     ("same", 11, -110, -110), ("same", 11, -110, -110)),
]

TOY_TOTAL_LINES = {
    "T01": 144.5, "T02": 140.5, "T03": 149.5, "T04": 143.5,
    "T05": 137.5, "T06": 154.5, "T07": 144.5, "T08": 136.5,
    "T09": 146.5, "T10": 148.5, "T11": 139.5, "T12": 140.5,
}

# Team-total rows per game: (mu_home, base_home, act_home, line_home,
# mu_away, base_away, act_away, line_away, home_close, away_close).
# Closes use the total-market pair order (over, under).
TEAMS = {
    "T01": (78.0, 74.8, 80, 74.5, 71.7, 70.2, 72, 72.5,
            ("same", 22, -120, 100), ("same", 22, -110, -110)),
    "T02": (70.0, 71.8, 66, 70.5, 69.0, 69.2, 67, 68.5,
            ("same", 15, -110, -110), ("same", 15, -110, -110)),
    "T03": (72.2, 72.3, 68, 73.5, 80.3, 77.7, 81, 77.5,
            ("same", 31, -110, -110), ("same", 31, -110, -110)),
    "T04": (73.7, 73.3, 75, 73.5, 70.3, 70.2, 72, 71.5,
            ("same", 9, -110, -110), ("same", 9, -110, -110)),
    "T05": (74.0, 72.3, 68, 73.5, 59.0, 65.7, 62, 62.5,
            ("same", 18, -110, -110), ("moved", 60.5, 18)),
    "T06": (77.9, 76.4, 82, 77.5, 83.0, 77.6, 77, 78.5,
            ("same", 26, -110, -110), ("same", 26, -130, 110)),
    "T07": (73.5, 74.3, 70, 74.5, 68.0, 68.2, 68, 69.5,
            ("same", 44, -110, -110), ("same", 44, -110, -110)),
    "T08": (60.0, 62.8, 55, 61.5, 73.0, 72.7, 73, 71.5,
            ("stale", 95), ("same", 12, -110, -110)),
    "T09": (79.0, 75.4, 81, 75.5, 72.9, 71.6, 74, 73.5,
            ("same", 20, -115, -105), ("same", 20, -110, -110)),
    "T10": (73.5, 74.3, 68, 73.5, 73.0, 73.7, 74, 72.5,
            ("same", 17, -110, -110), ("same", 17, -110, -110)),
    "T11": (76.0, 74.3, 80, 75.5, 63.0, 66.7, 70, 66.5,
            ("same", 29, -110, -110), ("same", 29, -105, -115)),
    "T12": (64.5, 68.5, 67, 67.0, 71.5, 71.5, 69, 70.5,
            ("same", 11, -110, -110), ("same", 11, -110, -110)),
}
TT_PX = -110


def _cap(minutes_before):
    return (TIP - timedelta(minutes=minutes_before)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _close_from_toy(toy_close, entry_line, spread=False):
    """Translate a toy close tuple into the machinery's close
    mapping, or None for a missing close."""
    kind = toy_close[0]
    if kind == "missing":
        return None
    if kind == "stale":
        return {"line": entry_line, "side_a_price": -110,
                "side_b_price": -110, "captured_at": _cap(toy_close[1])}
    if kind == "moved":
        new_line = -toy_close[1] if spread else toy_close[1]
        return {"line": new_line, "side_a_price": -110,
                "side_b_price": -110, "captured_at": _cap(toy_close[2])}
    # "same": toy pair order is (home, away) for spread,
    # (over, under) otherwise = production (side_b, side_a) for
    # spread and (side_a, side_b) otherwise.
    if spread:
        return {"line": entry_line, "side_a_price": toy_close[3],
                "side_b_price": toy_close[2],
                "captured_at": _cap(toy_close[1])}
    return {"line": entry_line, "side_a_price": toy_close[2],
            "side_b_price": toy_close[3],
            "captured_at": _cap(toy_close[1])}


def _toy_efficiency():
    records, finals, closes = [], {}, {}
    for g in GAMES:
        (gid, mu_m, b_m, act_m, mu_t, b_t, act_t, hline, sph, spa,
         tov, tun, sp_close, tot_close) = g
        finals[gid] = {"home_points": (act_t + act_m) / 2,
                       "away_points": (act_t - act_m) / 2}
        spread_line = -hline        # production: the away line
        rid = f"{gid}:spread"
        prob_a, prob_b = no_vig_pair(spa, sph)
        records.append({
            "row_id": rid, "espn_event_id": gid, "market": "SPREAD",
            "tip_utc": TIP_ISO, "line": spread_line,
            "side_a": "AWAY", "side_b": "HOME",
            "side_a_price": spa, "side_b_price": sph,
            "no_vig_prob_side_a": prob_a, "no_vig_prob_side_b": prob_b,
            "model_margin_home_candidate": mu_m,
            "model_margin_home_baseline_simple": b_m})
        c = _close_from_toy(sp_close, spread_line, spread=True)
        if c is not None:
            closes[rid] = c
        total_line = TOY_TOTAL_LINES[gid]
        rid = f"{gid}:total"
        prob_a, prob_b = no_vig_pair(tov, tun)
        records.append({
            "row_id": rid, "espn_event_id": gid, "market": "TOTAL",
            "tip_utc": TIP_ISO, "line": total_line,
            "side_a": "OVER", "side_b": "UNDER",
            "side_a_price": tov, "side_b_price": tun,
            "no_vig_prob_side_a": prob_a, "no_vig_prob_side_b": prob_b,
            "model_total_candidate": mu_t,
            "model_total_baseline_simple": b_t})
        c = _close_from_toy(tot_close, total_line)
        if c is not None:
            closes[rid] = c
    return records, finals, closes


def _toy_team_totals():
    records, finals, closes = [], {}, {}
    for gid, t in TEAMS.items():
        (mu_h, b_h, a_h, ln_h, mu_a, b_a, a_a, ln_a, c_h, c_a) = t
        finals[gid] = {"home_points": a_h, "away_points": a_a}
        for venue, mu, b, ln, close in (
                ("HOME", mu_h, b_h, ln_h, c_h),
                ("AWAY", mu_a, b_a, ln_a, c_a)):
            rid = f"{gid}:tt:{venue.lower()}"
            records.append({
                "row_id": rid, "espn_event_id": gid,
                "market": "TEAM_TOTAL", "venue": venue,
                "tip_utc": TIP_ISO, "line": ln,
                "side_a": "OVER", "side_b": "UNDER",
                "side_a_price": TT_PX, "side_b_price": TT_PX,
                "no_vig_prob_over": 0.5, "no_vig_prob_under": 0.5,
                "model_team_points_candidate": mu,
                "model_team_points_baseline_simple": b})
            c = _close_from_toy(close, ln)
            if c is not None:
                closes[rid] = c
    return records, finals, closes


def test_toy_slate_efficiency_quantities_reproduce():
    records, finals, closes = _toy_efficiency()
    q = m.compute_review_quantities(records, finals, closes, k=12)
    # AMENDMENT_2_DRAFT.md section 7, efficiency block.
    assert q["rows_priced"] == 24
    assert q["market_leg"]["picked_rows"] == 10
    assert q["market_leg"]["roi_on_picked"] == pytest.approx(
        0.4364, abs=1e-4)
    assert q["market_leg"]["mean_clv_picked_same_line"] == \
        pytest.approx(0.0018, abs=1e-4)
    assert q["market_leg"]["clv_rows"] == 6
    assert q["missing_close_rows"] == 2
    assert q["missing_close_share"] == pytest.approx(2 / 24)
    assert q["insufficient_close_data_share"] is False
    assert q["market_leg"]["moved_adverse"] == 1
    assert q["market_leg"]["moved_favorable"] == 1
    assert q["market_leg"]["moved_sign_test_p"] == pytest.approx(0.75)
    assert q["market_leg"]["moved_rule1_market_leg_fails"] is False
    assert q["market_leg"]["moved_rule2_insufficient_close_data"] \
        is False
    spread = q["accuracy"]["SPREAD"]
    assert spread["mean_paired_difference"] == pytest.approx(-0.225)
    assert spread["ci_lower"] == pytest.approx(-1.733, abs=1e-3)
    assert spread["ci_upper"] == pytest.approx(1.367, abs=1e-3)
    total = q["accuracy"]["TOTAL"]
    assert total["mean_paired_difference"] == pytest.approx(-1.583,
                                                            abs=1e-3)
    assert total["ci_lower"] == pytest.approx(-2.792, abs=1e-3)
    assert total["ci_upper"] == pytest.approx(0.292, abs=1e-3)
    # Determinism under the pinned seed: identical repeat output.
    q2 = m.compute_review_quantities(records, finals, closes, k=12)
    assert q == q2


def test_toy_slate_team_total_quantities_reproduce():
    records, finals, closes = _toy_team_totals()
    q = m.compute_review_quantities(records, finals, closes, k=12)
    # AMENDMENT_2_DRAFT.md section 7, team-totals block.
    assert q["rows_priced"] == 24
    assert q["market_leg"]["picked_rows"] == 7
    assert q["market_leg"]["roi_on_picked"] == pytest.approx(
        0.2338, abs=1e-4)
    assert q["market_leg"]["mean_clv_picked_same_line"] == \
        pytest.approx(0.0144, abs=1e-4)
    assert q["market_leg"]["clv_rows"] == 6
    assert q["missing_close_rows"] == 1
    assert q["missing_close_share"] == pytest.approx(1 / 24)
    assert q["market_leg"]["moved_sign_test_p"] == pytest.approx(1.0)
    acc = q["accuracy"]["TEAM_TOTAL"]
    assert acc["mean_paired_difference"] == pytest.approx(-0.4625)
    assert acc["ci_lower"] == pytest.approx(-1.496, abs=1e-3)
    assert acc["ci_upper"] == pytest.approx(0.625, abs=1e-3)


# ------------------------------------------------------------------
# Designation (section 1.1/1.2): thresholds, boundaries, GAP_ZERO.
# ------------------------------------------------------------------

def test_designate_pick_thresholds_and_boundaries():
    # SPREAD threshold 2.2: exactly at the threshold is PICKED.
    d = m.designate_pick("SPREAD", 6.7, 4.5)
    assert d["gap"] == pytest.approx(2.2) and d["classification"] == \
        "PICKED" and d["designated_side"] == "HOME"
    d = m.designate_pick("SPREAD", 6.6, 4.5)
    assert d["classification"] == "PASSED" and \
        d["designated_side"] == "HOME"
    # Negative gaps designate AWAY.
    d = m.designate_pick("SPREAD", -8.0, -4.5)
    assert d["gap"] == pytest.approx(-3.5) and \
        d["classification"] == "PICKED" and \
        d["designated_side"] == "AWAY"
    # The captured line is the away spread = M_mkt: a model that
    # rates the home team 1.5 worse than the market's -4.5 away
    # line still designates HOME (it fades the market's away lean).
    d = m.designate_pick("SPREAD", -3.0, -4.5)
    assert d["gap"] == pytest.approx(1.5) and \
        d["designated_side"] == "HOME"
    # TOTAL threshold 3.5, TEAM_TOTAL threshold 2.1.
    assert m.designate_pick("TOTAL", 149.0, 145.5)[
        "classification"] == "PICKED"
    assert m.designate_pick("TOTAL", 148.9, 145.5)[
        "classification"] == "PASSED"
    # (The rule reads the computed float gap, exactly as the toy
    # proof does; 76.7 - 74.5 is 2.2000... in binary floating
    # point, 76.5 - 74.5 is exactly 2.0.)
    assert m.designate_pick("TEAM_TOTAL", 76.7, 74.5)[
        "classification"] == "PICKED"
    assert m.designate_pick("TEAM_TOTAL", 76.5, 74.5)[
        "classification"] == "PASSED"
    assert m.designate_pick("TOTAL", 140.0, 145.5)[
        "designated_side"] == "UNDER"


def test_designate_pick_gap_zero_has_no_side():
    d = m.designate_pick("TOTAL", 145.5, 145.5)
    assert d["gap"] == 0.0 and d["designated_side"] is None
    assert d["classification"] == "GAP_ZERO"


def test_profit_units_and_settlement():
    assert m.profit_units(-110, "WIN") == pytest.approx(100 / 110)
    assert m.profit_units(150, "WIN") == pytest.approx(1.5)
    assert m.profit_units(-110, "LOSS") == -1.0
    assert m.profit_units(-110, "PUSH") == 0.0
    # Settlement is on the ENTRY line.
    assert m.settle_pick("SPREAD", "HOME", 4.5, 80, 70) == "WIN"
    assert m.settle_pick("SPREAD", "AWAY", 4.5, 80, 70) == "LOSS"
    assert m.settle_pick("SPREAD", "HOME", 10.0, 80, 70) == "PUSH"
    assert m.settle_pick("TOTAL", "UNDER", 155.5, 80, 70) == "WIN"
    assert m.settle_pick("TOTAL", "UNDER", 145.5, 80, 70) == "LOSS"
    assert m.settle_pick("TOTAL", "OVER", 150.0, 80, 70) == "PUSH"
    assert m.settle_pick("TEAM_TOTAL", "OVER", 74.5, 80, 70) == "WIN"


# ------------------------------------------------------------------
# Close validity (section 3.1/3.2): order, boundaries, directions.
# ------------------------------------------------------------------

def _close_record(market="TOTAL", line=145.5, model=150.0):
    rec = {"row_id": "r1", "espn_event_id": "g1", "market": market,
           "tip_utc": TIP_ISO, "line": line, "side_a": "OVER",
           "side_b": "UNDER", "side_a_price": -110,
           "side_b_price": -110, "no_vig_prob_side_a": 0.5,
           "no_vig_prob_side_b": 0.5,
           "model_total_candidate": model,
           "model_total_baseline_simple": model - 1.0}
    if market == "SPREAD":
        rec.update({"side_a": "AWAY", "side_b": "HOME",
                    "model_margin_home_candidate": model,
                    "model_margin_home_baseline_simple": model - 1.0})
        rec.pop("model_total_candidate")
        rec.pop("model_total_baseline_simple")
    return rec


def _close(line=145.5, pa=-110, pb=-110, minutes=30):
    return {"line": line, "side_a_price": pa, "side_b_price": pb,
            "captured_at": _cap(minutes)}


def test_close_validity_boundaries():
    rec = _close_record()
    # Exactly 60:00 before tip is valid; 60:00 + 1 second is stale.
    assert m.classify_close(rec, _close(minutes=60), TIP)["state"] \
        == "VALID"
    stale = _close(minutes=60)
    stale["captured_at"] = (TIP - timedelta(minutes=60, seconds=1)
                            ).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert m.classify_close(rec, stale, TIP)["state"] == "CLOSE_STALE"
    # At or after tip is not a close at all.
    assert m.classify_close(rec, _close(minutes=0), TIP)["state"] \
        == "CLOSE_NOT_PREKICKOFF"
    late = _close(minutes=30)
    late["captured_at"] = (TIP + timedelta(minutes=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    assert m.classify_close(rec, late, TIP)["state"] == \
        "CLOSE_NOT_PREKICKOFF"
    # Missing and single-sided.
    assert m.classify_close(rec, None, TIP)["state"] == "NO_CLOSE_ROW"
    assert m.classify_close(rec, _close(pb=None), TIP)["state"] == \
        "CLOSE_SINGLE_SIDED"


def test_close_validity_precedes_moved_classification():
    rec = _close_record()
    moved_but_stale = _close(line=150.5, minutes=95)
    assert m.classify_close(rec, moved_but_stale, TIP)["state"] == \
        "CLOSE_STALE"


def test_close_malformed_refuses():
    rec = _close_record()
    with pytest.raises(CbbForwardError) as exc:
        m.classify_close(rec, _close(pa="-110"), TIP)
    assert exc.value.reason == "CLOSE_RECORD_INVALID"
    bad_ts = _close()
    bad_ts["captured_at"] = "not-a-timestamp"
    with pytest.raises(CbbForwardError) as exc:
        m.classify_close(rec, bad_ts, TIP)
    assert exc.value.reason == "CLOSE_RECORD_INVALID"


def test_moved_direction_per_side_and_market():
    # OVER pick (gap +4.5), total line rose -> FAVORABLE.
    rec = _close_record()
    out = m.classify_close(rec, _close(line=147.5), TIP)
    assert out["state"] == "LINE_MOVED" and \
        out["moved_direction"] == "FAVORABLE"
    # UNDER pick, total line rose -> ADVERSE.
    rec_under = _close_record(model=140.0)
    out = m.classify_close(rec_under, _close(line=147.5), TIP)
    assert out["moved_direction"] == "ADVERSE"
    # SPREAD: HOME pick, away line (M_mkt) rose -> FAVORABLE;
    # AWAY pick, away line rose -> ADVERSE.
    rec_home = _close_record(market="SPREAD", line=4.5, model=9.0)
    out = m.classify_close(rec_home, _close(line=6.5), TIP)
    assert out["moved_direction"] == "FAVORABLE"
    rec_away = _close_record(market="SPREAD", line=4.5, model=-2.0)
    out = m.classify_close(rec_away, _close(line=6.5), TIP)
    assert out["moved_direction"] == "ADVERSE"
    # A PASSED row's moved close carries no bucket direction.
    rec_passed = _close_record(model=147.0)
    out = m.classify_close(rec_passed, _close(line=147.5), TIP)
    assert out["state"] == "LINE_MOVED" and \
        out["moved_direction"] is None


def test_sign_test_values():
    assert m.sign_test_p(0, 0) == 1.0
    assert m.sign_test_p(1, 1) == pytest.approx(0.75)
    assert m.sign_test_p(3, 0) == pytest.approx(0.125)
    assert m.sign_test_p(8, 0) == pytest.approx(0.5 ** 8)


# ------------------------------------------------------------------
# Quantity-level rules (sections 1.3/1.4, 3.2, 3.3) on small
# synthetic sets -- computability, not verdicts.
# ------------------------------------------------------------------

def _row(rid, gid, *, market="TOTAL", line=145.5, model=150.0,
         baseline=146.0, pa=-110, pb=-110, venue=None):
    rec = {"row_id": rid, "espn_event_id": gid, "market": market,
           "tip_utc": TIP_ISO, "line": line,
           "side_a": "AWAY" if market == "SPREAD" else "OVER",
           "side_b": "HOME" if market == "SPREAD" else "UNDER",
           "side_a_price": pa, "side_b_price": pb}
    prob_a, prob_b = no_vig_pair(pa, pb)
    if market == "TEAM_TOTAL":
        rec.update({"venue": venue or "HOME",
                    "no_vig_prob_over": prob_a,
                    "no_vig_prob_under": prob_b,
                    "model_team_points_candidate": model,
                    "model_team_points_baseline_simple": baseline})
    elif market == "SPREAD":
        rec.update({"no_vig_prob_side_a": prob_a,
                    "no_vig_prob_side_b": prob_b,
                    "model_margin_home_candidate": model,
                    "model_margin_home_baseline_simple": baseline})
    else:
        rec.update({"no_vig_prob_side_a": prob_a,
                    "no_vig_prob_side_b": prob_b,
                    "model_total_candidate": model,
                    "model_total_baseline_simple": baseline})
    return rec


def _same_close(line, minutes=30, pa=-110, pb=-110):
    return {"line": line, "side_a_price": pa, "side_b_price": pb,
            "captured_at": _cap(minutes)}


def test_insufficiency_share_boundary_is_strictly_over_20pct():
    records, finals, closes = [], {}, {}
    for i in range(10):
        gid = f"g{i}"
        records.append(_row(f"r{i}", gid))
        finals[gid] = {"home_points": 80, "away_points": 70}
        if i >= 2:      # 2 of 10 rows lack a close = exactly 20%
            closes[f"r{i}"] = _same_close(145.5)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["missing_close_share"] == pytest.approx(0.2)
    assert q["insufficient_close_data_share"] is False
    assert q["verdict"] != "INSUFFICIENT_CLOSE_DATA" or \
        q["market_leg"]["moved_rule2_insufficient_close_data"]
    records.append(_row("r10", "g10"))
    finals["g10"] = {"home_points": 80, "away_points": 70}
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["missing_close_share"] == pytest.approx(3 / 11)
    assert q["insufficient_close_data_share"] is True
    assert q["verdict"] == "INSUFFICIENT_CLOSE_DATA"


def test_moved_rule1_fails_market_leg_despite_positive_figures():
    records, finals, closes = [], {}, {}
    # 8 picked rows, all moved ADVERSE (line fell against OVER).
    for i in range(8):
        gid = f"a{i}"
        records.append(_row(f"ra{i}", gid))
        finals[gid] = {"home_points": 90, "away_points": 70}
        closes[f"ra{i}"] = _same_close(143.5)
    # 2 picked rows with same-line closes, winning, positive CLV.
    for i in range(2):
        gid = f"b{i}"
        records.append(_row(f"rb{i}", gid))
        finals[gid] = {"home_points": 90, "away_points": 70}
        closes[f"rb{i}"] = _same_close(145.5, pa=-130, pb=110)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    leg = q["market_leg"]
    assert leg["moved_adverse"] == 8 and leg["moved_favorable"] == 0
    assert leg["moved_sign_test_p"] == pytest.approx(0.5 ** 8)
    assert leg["moved_sign_test_p"] < 0.05 / 12
    assert leg["roi_on_picked"] > 0 and \
        leg["mean_clv_picked_same_line"] > 0
    assert leg["moved_rule1_market_leg_fails"] is True
    assert leg["market_leg_pass"] is False


def test_moved_rule2_over_half_picked_moved_is_insufficient():
    records, finals, closes = [], {}, {}
    for i in range(3):
        gid = f"g{i}"
        records.append(_row(f"r{i}", gid))
        finals[gid] = {"home_points": 90, "away_points": 70}
    closes["r0"] = _same_close(147.5)   # moved FAVORABLE
    closes["r1"] = _same_close(147.5)   # moved FAVORABLE
    closes["r2"] = _same_close(145.5)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["market_leg"]["moved_rule2_insufficient_close_data"] \
        is True
    assert q["verdict"] == "INSUFFICIENT_CLOSE_DATA"
    # Exactly half moved does not trigger rule 2.
    closes["r1"] = _same_close(145.5)
    records.append(_row("r3", "g3"))
    finals["g3"] = {"home_points": 90, "away_points": 70}
    closes["r3"] = _same_close(145.5)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["market_leg"]["moved_rule2_insufficient_close_data"] \
        is False


def test_empty_picked_set_and_undefined_clv_fail_market_leg():
    records, finals, closes = [], {}, {}
    for i in range(4):
        gid = f"g{i}"
        records.append(_row(f"r{i}", gid, model=146.0))  # PASSED
        finals[gid] = {"home_points": 80, "away_points": 70}
        closes[f"r{i}"] = _same_close(145.5)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["market_leg"]["picked_rows"] == 0
    assert q["market_leg"]["roi_on_picked"] is None
    assert q["market_leg"]["market_leg_pass"] is False
    # Picked rows whose closes all moved: CLV undefined -> no pass.
    records, finals, closes = [], {}, {}
    for i in range(3):
        gid = f"h{i}"
        records.append(_row(f"s{i}", gid))
        finals[gid] = {"home_points": 90, "away_points": 70}
        closes[f"s{i}"] = _same_close(147.5)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["market_leg"]["roi_on_picked"] is not None
    assert q["market_leg"]["mean_clv_picked_same_line"] is None
    assert q["market_leg"]["market_leg_pass"] is False


def test_void_and_unavailable_rows_leave_every_leg():
    records, finals, closes = [], {}, {}
    records.append(_row("rv", "gv"))
    finals["gv"] = {"void": True}
    records.append(_row("ru", "gu"))            # no final at all
    records.append(_row("rg", "gg"))
    finals["gg"] = {"home_points": 90, "away_points": 70}
    closes["rg"] = _same_close(145.5)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["dispositions"]["VOID"] == 1
    assert q["dispositions"]["RESULT_UNAVAILABLE"] == 1
    # The share base excludes both: 1 share row, 0 missing.
    assert q["missing_close_rows"] == 0
    assert q["missing_close_share"] == 0.0
    assert q["graded_games"] == 1
    assert q["accuracy"]["TOTAL"]["games"] == 1


def test_disposition_precedence_and_gap_zero_counting():
    records, finals, closes = [], {}, {}
    # GAP_ZERO row with a valid close -> GAP_ZERO.
    records.append(_row("rz", "gz", model=145.5))
    finals["gz"] = {"home_points": 80, "away_points": 70}
    closes["rz"] = _same_close(145.5)
    # GAP_ZERO row with NO close: disposition is the close
    # failure, but the factual gap-zero count still reports it.
    records.append(_row("rz2", "gz2", model=145.5))
    finals["gz2"] = {"home_points": 80, "away_points": 70}
    # Picked row that pushes on a whole-number line -> PUSH.
    records.append(_row("rp", "gp", line=150.0, model=155.0))
    finals["gp"] = {"home_points": 80, "away_points": 70}
    closes["rp"] = _same_close(150.0)
    q = m.compute_review_quantities(records, finals, closes, k=12)
    assert q["dispositions"]["GAP_ZERO"] == 1
    assert q["dispositions"]["NO_CLOSE_ROW"] == 1
    assert q["dispositions"]["PUSH"] == 1
    assert q["gap_zero_rows"] == 2
    assert q["market_leg"]["pushes"] == 1
    # Push stays in the ROI denominator: (0 + nothing else picked).
    assert q["market_leg"]["picked_rows"] == 1
    assert q["market_leg"]["roi_on_picked"] == 0.0


def test_machinery_refusals_are_fail_closed():
    records, finals, closes = [], {}, {}
    bad = _row("rb", "gb")
    bad["classification"] = "PICK_RULE_UNDEFINED"   # pre-A2 stamp
    records.append(bad)
    finals["gb"] = {"home_points": 80, "away_points": 70}
    with pytest.raises(CbbForwardError) as exc:
        m.compute_review_quantities(records, finals, closes, k=12)
    assert exc.value.reason == "ROW_CLASSIFICATION_MISMATCH"
    bad2 = _row("rb2", "gb")
    bad2["disposition"] = "SOME_INVENTED_CODE"
    with pytest.raises(CbbForwardError) as exc:
        m.compute_review_quantities([bad2], finals, closes, k=12)
    assert exc.value.reason == "UNDECLARED_REFUSAL_CODE"
    with pytest.raises(CbbForwardError) as exc:
        m.compute_review_quantities([], finals, closes, k=0)
    assert exc.value.reason == "K_INVALID"


# ------------------------------------------------------------------
# The gated review (preregistration section 5 + amendment
# section 4): gate, one-review discipline, verdicts, k.
# ------------------------------------------------------------------

def _slate(n_games, *, candidate_wins=True, close_home_price=-120):
    """An efficiency slate of n_games: the candidate is exact on
    margin and total, the baseline is off by 5; spread rows are
    PICKED HOME (gap 5.5) and win; total rows are PASSED."""
    records, finals, closes = [], {}, {}
    for i in range(n_games):
        gid = f"s{i}"
        finals[gid] = {"home_points": 80, "away_points": 70}
        margin_model = 10.0 if candidate_wins else 0.0
        records.append(_row(
            f"{gid}:spread", gid, market="SPREAD", line=4.5,
            model=margin_model, baseline=5.0))
        records.append(_row(
            f"{gid}:total", gid, market="TOTAL", line=148.0,
            model=150.0 if candidate_wins else 140.0,
            baseline=145.0))
        closes[f"{gid}:spread"] = _same_close(
            4.5, pa=100, pb=close_home_price)
        closes[f"{gid}:total"] = _same_close(148.0)
    return records, finals, closes


def test_review_not_due_before_40_graded_games_shows_no_figures():
    records, finals, closes = _slate(39)
    out = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_verdict=12)
    assert out["review_status"] == "REVIEW_NOT_DUE"
    assert out["verdict"] is None and out["graded_games"] == 39
    # No interim looks: no leg figures are computed or returned.
    assert "accuracy" not in out and "market_leg" not in out
    assert "missing_close_share" not in out
    # A void 40th game does not open the gate.
    records.append(_row("vx:spread", "vx", market="SPREAD", line=4.5,
                        model=10.0, baseline=5.0))
    finals["vx"] = {"void": True}
    out = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_verdict=12)
    assert out["review_status"] == "REVIEW_NOT_DUE"
    assert out["graded_games"] == 39


def test_review_at_gate_pass_and_fail():
    records, finals, closes = _slate(40)
    out = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_verdict=12)
    assert out["review_status"] == "REVIEW_RECORDED"
    assert out["graded_games"] == 40
    assert out["accuracy_leg_pass"] is True
    assert out["market_leg"]["market_leg_pass"] is True
    assert out["market_leg"]["mean_clv_picked_same_line"] > 0
    assert out["verdict"] == "PASS"
    # Same slate with a worse-than-baseline candidate: FAIL.
    records, finals, closes = _slate(40, candidate_wins=False)
    out = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_verdict=12)
    assert out["accuracy_leg_pass"] is False
    assert out["verdict"] == "FAIL"


def test_review_insufficient_close_data_at_gate():
    records, finals, closes = _slate(40)
    for i in range(10):     # 10 of 80 rows lose their close = 12.5%
        closes.pop(f"s{i}:total")
    for i in range(10, 18):  # +8 spread rows -> 18/80 = 22.5% > 20%
        closes.pop(f"s{i}:spread")
    out = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_verdict=12)
    assert out["review_status"] == "REVIEW_RECORDED"
    assert out["missing_close_share"] == pytest.approx(18 / 80)
    assert out["verdict"] == "INSUFFICIENT_CLOSE_DATA"


def test_one_review_only_and_k_larger_governs():
    records, finals, closes = _slate(40)
    with pytest.raises(CbbForwardError) as exc:
        m.evaluate_forward_test(
            records, finals, closes,
            family_id="CBB_TORVIK_EFFICIENCY_V1", k_at_verdict=12,
            review_already_recorded=True)
    assert exc.value.reason == "VERDICT_REVIEW_ALREADY_RECORDED"
    out = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_freeze=13, k_at_verdict=12)
    assert out["k"] == 13
    assert out["accuracy"]["SPREAD"]["ci_level"] == pytest.approx(
        1 - 0.05 / 13)
    # The bootstrap is deterministic at the gate too.
    out2 = m.evaluate_forward_test(
        records, finals, closes, family_id="CBB_TORVIK_EFFICIENCY_V1",
        k_at_freeze=13, k_at_verdict=12)
    assert out == out2


def test_cluster_bootstrap_matches_toy_algorithm_shape():
    clusters = [[-1.0], [0.5], [-2.0], [1.0]]
    ci = m.cluster_bootstrap_ci(clusters, k=12)
    assert ci["reps"] == 10000 and ci["seed"] == 20261028
    assert ci["level"] == pytest.approx(1 - 0.05 / 12)
    assert ci["point"] == pytest.approx(-0.375)
    assert ci["ci_lower"] <= ci["point"] <= ci["ci_upper"]
    assert math.isfinite(ci["ci_lower"]) and math.isfinite(
        ci["ci_upper"])


def test_duplicate_rows_and_missing_venue_refuse():
    records, finals, closes = [], {}, {}
    rec = _row("rd", "gd")
    records.extend([rec, dict(rec)])
    finals["gd"] = {"home_points": 80, "away_points": 70}
    with pytest.raises(CbbForwardError) as exc:
        m.compute_review_quantities(records, finals, closes, k=12)
    assert exc.value.reason == "DUPLICATE_ROW_ID"
    tt = _row("rt", "gt", market="TEAM_TOTAL")
    tt.pop("venue")
    with pytest.raises(CbbForwardError) as exc:
        m.compute_review_quantities(
            [tt], {"gt": {"home_points": 80, "away_points": 70}},
            {}, k=12)
    assert exc.value.reason == "ROW_RECORD_INVALID"
