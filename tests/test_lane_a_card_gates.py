"""Lane A card gates — adopted recalibration + >=6pt disagreement guard.

Adopted Oct 28, 2026 by owner-delegated decision (Isaac: "Do what you
think is best"; see research/lane_a_recalibration_20261028/
ADOPTION_RECORD.md). These tests pin:

- headline/bucket placement reads the RECALIBRATED (effective) EV,
  never the raw Lane A EV — at the adoption-time estimate (k floored
  to 0) nothing headlines: paired rows carry the (<= 0) EV of the
  frozen-policy POWER_V1 fair probability since gate V2 (Oct 29,
  2026 de-vig ruling), unpaired rows exactly ~0 on their break-even
  anchor;
- the disagreement guard buckets a row at >= 6.0 points of
  model-vs-market disagreement REGARDLESS of EV, on the real Oct 28,
  2026 card numbers that motivated it (Wizards +10.5: 7.35 points;
  Pelicans +5: 8.24 points), and does NOT fire at 5.74 points
  (Clippers +5.5) — where the recalibration is what catches the row;
- with a positive fitted k, a small-disagreement row can headline and
  a big-disagreement row still cannot;
- fail-closed paths: recalibration not applied -> BLOCKED; guard not
  evaluable in a guard-scope sport -> BLOCKED;
- MLB rows are recalibrated but outside the guard's scope;
- inputs are never mutated;
- gate V3 (Oct 29, 2026): on a paired market the guard fires only on
  the model-favored side (positive raw model edge); the mirror side
  classifies on its own merits instead of being bucketed by the
  pair's shared disagreement (the Oct 29 both-sides totals defect).
  Unpaired rows keep the pair-blind guard; a frozen-policy
  sensitivity-blocked pair still blocks both sides.
"""
import copy

import pytest

from sportsedge import lane_a_card_gates as gates
from sportsedge import lane_a_recalibration as rc


def _view(model_p, implied_p, odds, margin, total, home_mean, away_mean):
    return {
        "lane": "LANE_A_INDEPENDENT",
        "estimate_p": model_p,
        "push_p": 0.0,
        "loss_p": 1.0 - model_p,
        "ev_per_dollar": round(rc.ev_per_dollar(model_p, 0.0, odds), 6),
        "book_break_even_p": implied_p,
        "projected_home_margin": margin,
        "projected_total": total,
        "home_mean": home_mean,
        "away_mean": away_mean,
    }


def _row(sport, game, market, selection, line, odds, model_p, implied_p,
         margin, total, home_mean, away_mean):
    view = _view(model_p, implied_p, odds, margin, total, home_mean, away_mean)
    return {
        "sport": sport, "game": game, "market": market,
        "selection": selection, "line": line, "odds_american": odds,
        "estimate_p": model_p, "push_p": 0.0,
        "ev_per_dollar": view["ev_per_dollar"],
        "book_break_even_p": implied_p,
        "home_mean": home_mean, "away_mean": away_mean,
        "pricing_lanes": {"lane_a_independent": view},
        "independent_projection": view,
    }


def _diagnostic_estimate():
    estimate = gates.current_estimate()
    assert estimate.n_decided_legs == 183
    assert estimate.k_raw == pytest.approx(-0.461)
    assert estimate.k_used == 0.0
    return estimate


def _positive_k_estimate():
    rows = [{"model_p": 0.62, "implied_p": 0.52,
             "outcome": "WIN" if i < 114 else "LOSS"} for i in range(200)]
    estimate = rc.estimate_k(rows)
    assert estimate.k_used == pytest.approx(0.50)
    return estimate


# Real Oct 28, 2026 card numbers (operative_run_20261028_runit).
def _was_cle_rows():
    g = "Washington Wizards @ Cleveland Cavaliers"
    m, t, am, hm = 3.15, 224.69, 110.77, 113.92
    return [
        _row("NBA", g, "SPREAD", "Washington Wizards +10.5", 10.5, -108,
             0.7217, 108 / 208, m, t, am, hm),
        _row("NBA", g, "SPREAD", "Cleveland Cavaliers -10.5", -10.5, -112,
             0.2782, 112 / 212, m, t, am, hm),
        _row("NBA", g, "ML", "Washington Wizards ML", None, 320,
             0.4005, 100 / 420, m, t, am, hm),
        _row("NBA", g, "TOTAL", "UNDER 239.5", 239.5, -115,
             0.7820, 115 / 215, m, t, am, hm),
    ]


def _den_no_rows():
    g = "Denver Nuggets @ New Orleans Pelicans"
    m, t, am, hm = 3.24, 223.36, 110.06, 113.30
    return [
        _row("NBA", g, "SPREAD", "Denver Nuggets -5", -5.0, -105,
             0.2554, 105 / 205, m, t, am, hm),
        _row("NBA", g, "SPREAD", "New Orleans Pelicans +5", 5.0, -115,
             0.7321, 115 / 215, m, t, am, hm),
    ]


def _lal_lac_rows():
    g = "Los Angeles Lakers @ LA Clippers"
    m, t, am, hm = 0.24, 224.96, 112.36, 112.60
    return [
        _row("NBA", g, "SPREAD", "Los Angeles Lakers -5.5", -5.5, -105,
             0.3230, 105 / 205, m, t, am, hm),
        _row("NBA", g, "SPREAD", "LA Clippers +5.5", 5.5, -115,
             0.6772, 115 / 215, m, t, am, hm),
    ]


def _by_selection(rows):
    return {r["selection"]: r for r in rows}


# ------------------------------------------------------- market margin

def test_market_home_margins_from_spread_pairs():
    margins = gates.market_home_margins(_was_cle_rows() + _den_no_rows())
    assert margins["Washington Wizards @ Cleveland Cavaliers"] == pytest.approx(10.5)
    # Away favorite -5 / home +5 both imply a market home margin of -5.
    assert margins["Denver Nuggets @ New Orleans Pelicans"] == pytest.approx(-5.0)


# ------------------------------------------------------- the Oct 28 rows

def test_wizards_spread_guard_fires_at_735_points():
    out = _by_selection(gates.apply_card_gates(_was_cle_rows(), _diagnostic_estimate()))
    gate = out["Washington Wizards +10.5"]["card_gate"]
    assert gate["disagreement_points"] == pytest.approx(7.35)
    assert gate["disagreement_kind"] == "MARGIN"
    assert gate["guard_triggered"] is True
    assert gate["bucket"] == "OVERCONFIDENCE"
    assert gate["reason"] == gates.REASON_GUARD_MARGIN
    # Gate V3: the mirror side of the pair carries the same measured
    # disagreement but does NOT trip the guard — Cleveland's raw
    # model edge is negative (0.2782 vs the -112 break-even), so the
    # row is suppressed as the mirror and classifies on its own
    # merits: EXCLUDED below threshold at k = 0.
    mirror = out["Cleveland Cavaliers -10.5"]["card_gate"]
    assert mirror["disagreement_points"] == pytest.approx(7.35)
    assert mirror["guard_triggered"] is False
    assert mirror["guard_mirror_suppressed"] is True
    assert mirror["guard_model_edge"] < 0
    assert mirror["bucket"] == "EXCLUDED"
    assert mirror["reason"] == gates.REASON_BELOW_THRESHOLD


def test_wizards_ml_uses_the_games_market_margin():
    out = _by_selection(gates.apply_card_gates(_was_cle_rows(), _diagnostic_estimate()))
    gate = out["Washington Wizards ML"]["card_gate"]
    assert gate["disagreement_points"] == pytest.approx(7.35)
    assert gate["guard_triggered"] is True
    assert gate["bucket"] == "OVERCONFIDENCE"


def test_under_guard_fires_on_total_disagreement():
    out = _by_selection(gates.apply_card_gates(_was_cle_rows(), _positive_k_estimate()))
    gate = out["UNDER 239.5"]["card_gate"]
    assert gate["disagreement_kind"] == "TOTAL"
    assert gate["disagreement_points"] == pytest.approx(14.81)
    assert gate["guard_triggered"] is True
    assert gate["bucket"] == "OVERCONFIDENCE"
    assert gate["reason"] == gates.REASON_GUARD_TOTAL
    # Even though the positive-k effective EV would clear the floor:
    assert gate["effective_ev"] > gates.HEADLINE_FLOOR_EV


def test_pelicans_spread_guard_fires_at_824_points():
    out = _by_selection(gates.apply_card_gates(_den_no_rows(), _diagnostic_estimate()))
    gate = out["New Orleans Pelicans +5"]["card_gate"]
    assert gate["disagreement_points"] == pytest.approx(8.24)
    assert gate["guard_triggered"] is True
    assert gate["bucket"] == "OVERCONFIDENCE"


def test_clippers_below_guard_threshold_caught_by_recalibration():
    out = _by_selection(gates.apply_card_gates(_lal_lac_rows(), _diagnostic_estimate()))
    gate = out["LA Clippers +5.5"]["card_gate"]
    assert gate["disagreement_points"] == pytest.approx(5.74)
    assert gate["guard_triggered"] is False
    # k = 0 (gate V2): p_used is the pair's POWER_V1 fair probability
    # (0.5116 for the -105/-115 pair), whose EV at -115 is ~-4.35% —
    # the claimed +26.6% raw EV recalibrates to a negative effective
    # EV, still below every threshold, still caught by recalibration.
    assert gate["market_baseline"]["source"] == gates.BASELINE_POLICY_POWER_V1
    assert gate["market_baseline"]["fair_p"] == pytest.approx(0.5116, abs=1e-3)
    assert gate["effective_ev"] == pytest.approx(-0.0435, abs=1e-3)
    assert gate["bucket"] == "EXCLUDED"
    assert gate["reason"] == gates.REASON_BELOW_THRESHOLD


def test_k_zero_no_lane_a_row_headlines():
    rows = _was_cle_rows() + _den_no_rows() + _lal_lac_rows()
    out = gates.apply_card_gates(rows, _diagnostic_estimate())
    assert all(r["card_gate"]["bucket"] != "HEADLINE" for r in out)
    assert all(r["card_gate"]["k_used"] == 0.0 for r in out)


# ------------------------------------------------------- positive-k paths

def test_positive_k_small_disagreement_can_headline():
    g = "Alpha @ Beta"
    rows = [
        _row("NBA", g, "SPREAD", "Alpha +4.5", 4.5, -110,
             0.40, 110 / 210, 4.9, 220.0, 107.55, 112.45),
        _row("NBA", g, "SPREAD", "Beta -4.5", -4.5, -110,
             0.62, 110 / 210, 4.9, 220.0, 107.55, 112.45),
    ]
    out = _by_selection(gates.apply_card_gates(rows, _positive_k_estimate()))
    gate = out["Beta -4.5"]["card_gate"]
    assert gate["disagreement_points"] == pytest.approx(0.4)
    assert gate["guard_triggered"] is False
    # Gate V2 basis: the -110/-110 pair de-vigs (POWER_V1) to exactly
    # 0.5, so p_used = 0.5 + k*(0.62 - 0.5) = 0.56 and the effective
    # EV is ~+6.9% (the V1 break-even anchor gave ~+9.2%).
    assert gate["effective_ev"] == pytest.approx(0.0691, abs=1e-3)
    assert gate["bucket"] == "HEADLINE"


def test_positive_k_big_disagreement_still_bucketed():
    g = "New York Knicks @ Chicago Bulls"
    rows = [
        _row("NBA", g, "SPREAD", "New York Knicks -7.5", -7.5, -105,
             0.30, 105 / 205, -0.4, 223.3, 111.85, 111.45),
        _row("NBA", g, "SPREAD", "Chicago Bulls +7.5", 7.5, -115,
             0.7150, 115 / 215, -0.4, 223.3, 111.85, 111.45),
    ]
    out = _by_selection(gates.apply_card_gates(rows, _positive_k_estimate()))
    gate = out["Chicago Bulls +7.5"]["card_gate"]
    assert gate["disagreement_points"] == pytest.approx(7.1)
    assert gate["effective_ev"] > gates.HEADLINE_FLOOR_EV
    assert gate["bucket"] == "OVERCONFIDENCE"
    assert gate["reason"] == gates.REASON_GUARD_MARGIN


# ------------------------------------------------------- scope + fail-closed

def test_mlb_recalibrated_but_outside_guard_scope():
    g = "Milwaukee Brewers @ Tampa Bay Rays"
    rows = [
        _row("MLB", g, "TOTAL", "UNDER 6.5", 6.5, -110,
             0.80, 110 / 210, 0.4, 14.0, 6.8, 7.2),
    ]
    out = gates.apply_card_gates(rows, _diagnostic_estimate())
    gate = out[0]["card_gate"]
    assert gate["guard_scope"] is False
    assert gate["guard_triggered"] is False
    assert gate["effective_ev"] == pytest.approx(0.0, abs=5e-6)
    assert gate["bucket"] == "EXCLUDED"


def test_missing_lane_a_view_is_blocked():
    row = {"sport": "NBA", "game": "Alpha @ Beta", "market": "ML",
           "selection": "Beta ML", "line": None, "odds_american": -110,
           "estimate_p": 0.62, "ev_per_dollar": 0.18}
    out = gates.apply_card_gates([row], _diagnostic_estimate())
    gate = out[0]["card_gate"]
    assert gate["recalibration_status"] == "NOT_APPLIED_INPUT_MISSING"
    assert gate["bucket"] == "BLOCKED"
    assert gate["reason"] == gates.REASON_RECALIBRATION_NOT_APPLIED


def test_ml_row_without_spread_pair_is_blocked_not_headlined():
    g = "Alpha @ Beta"
    rows = [
        _row("NBA", g, "ML", "Beta ML", None, 170,
             0.62, 100 / 270, 0.24, 224.96, 112.36, 112.60),
    ]
    out = gates.apply_card_gates(rows, _positive_k_estimate())
    gate = out[0]["card_gate"]
    assert gate["guard_evaluable"] is False
    assert gate["effective_ev"] > gates.HEADLINE_FLOOR_EV
    assert gate["bucket"] == "BLOCKED"
    assert gate["reason"] == gates.REASON_GUARD_NOT_EVALUABLE


def test_non_mapping_row_refused_by_name():
    with pytest.raises(ValueError, match="CARD_GATE_ROW_NOT_OBJECT"):
        gates.apply_card_gates([{"sport": "NBA"}, "not-a-row"],
                               _diagnostic_estimate())


def test_inputs_never_mutated():
    rows = _was_cle_rows()
    before = copy.deepcopy(rows)
    gates.apply_card_gates(rows, _diagnostic_estimate())
    assert rows == before
    assert all("card_gate" not in r and "recalibration" not in r for r in rows)


# ------------------------------------------- de-vig baseline (gate V2)

def test_paired_dog_baseline_is_power_not_proportional():
    # Wizards ML +320 / Cavaliers -400 (the missing side supplied):
    # proportional de-vig would give the dog 0.2381/(0.2381+0.8) =
    # 0.2294; POWER_V1 gives ~0.2135 — the frozen policy removes more
    # of the longshot's share, exactly the A2 direction.
    g = "Washington Wizards @ Cleveland Cavaliers"
    m, t, am, hm = 3.15, 224.69, 110.77, 113.92
    rows = [
        _row("NBA", g, "ML", "Washington Wizards ML", None, 320,
             0.4005, 100 / 420, m, t, am, hm),
        _row("NBA", g, "ML", "Cleveland Cavaliers ML", None, -400,
             0.5995, 400 / 500, m, t, am, hm),
    ]
    out = _by_selection(gates.apply_card_gates(rows, _diagnostic_estimate()))
    base = out["Washington Wizards ML"]["card_gate"]["market_baseline"]
    assert base["source"] == gates.BASELINE_POLICY_POWER_V1
    assert base["method"] == "POWER_V1"
    assert base["policy_id"] == "EDGE_FLOOR_DEVIG_V1"
    assert base["fair_p"] == pytest.approx(0.2135, abs=1e-3)
    assert base["fair_p"] < 0.2294  # below the proportional share
    assert base["engine_book_break_even_p"] == pytest.approx(100 / 420)


def test_longshot_sensitivity_blocked_pair_is_blocked():
    # +750 / -1200: a side >= +400 triggers the frozen policy's
    # sensitivity gate and the three methods spread ~2.6pp > the
    # 1.0pp limit, so the policy BLOCKs — neither row may anchor.
    g = "Troy Trojans @ James Madison Dukes"
    m, t, am, hm = -14.0, 51.0, 20.0, 34.0
    rows = [
        _row("CFB", g, "ML", "Troy Trojans ML", None, 750,
             0.3000, 100 / 850, m, t, am, hm),
        _row("CFB", g, "ML", "James Madison Dukes ML", None, -1200,
             0.7000, 1200 / 1300, m, t, am, hm),
    ]
    out = gates.apply_card_gates(rows, _diagnostic_estimate())
    for row in out:
        gate = row["card_gate"]
        assert gate["bucket"] == "BLOCKED"
        assert gate["reason"] == gates.REASON_DEVIG_SENSITIVITY_BLOCKED
        assert gate["market_baseline"]["source"] == (
            gates.BASELINE_DEVIG_SENSITIVITY_BLOCKED
        )
        assert gate["market_baseline"]["policy_id"] == "EDGE_FLOOR_DEVIG_V1"


def test_unpaired_row_keeps_break_even_anchor_stamped():
    g = "Milwaukee Brewers @ Tampa Bay Rays"
    rows = [
        _row("MLB", g, "TOTAL", "UNDER 6.5", 6.5, -110,
             0.80, 110 / 210, 0.4, 14.0, 6.8, 7.2),
    ]
    out = gates.apply_card_gates(rows, _diagnostic_estimate())
    base = out[0]["card_gate"]["market_baseline"]
    assert base["source"] == gates.BASELINE_BREAK_EVEN_UNPAIRED
    assert base["method"] is None
    assert base["fair_p"] is None
    # Break-even anchor at k = 0: effective EV stays exactly ~0.
    assert out[0]["card_gate"]["effective_ev"] == pytest.approx(0.0, abs=5e-6)


# --------------------------------- guard favored side (gate V3)

def test_paired_total_guard_buckets_favored_side_only():
    # The Oct 29, 2026 SAC@NOP shape: the model projects 221.68
    # against a 235.5 market total (13.82 points of disagreement).
    # The model's claim is the UNDER (raw edge +0.238); the OVER is
    # the mirror image of the same disagreement, not a second claim.
    g = "Sacramento Kings @ New Orleans Pelicans"
    rows = [
        _row("NBA", g, "TOTAL", "OVER 235.5", 235.5, -108,
             0.2335, 108 / 208, 6.0, 221.68, 107.84, 113.84),
        _row("NBA", g, "TOTAL", "UNDER 235.5", 235.5, -112,
             0.7665, 112 / 212, 6.0, 221.68, 107.84, 113.84),
    ]
    out = _by_selection(gates.apply_card_gates(rows, _diagnostic_estimate()))
    under = out["UNDER 235.5"]["card_gate"]
    assert under["disagreement_points"] == pytest.approx(13.82)
    assert under["guard_paired"] is True
    assert under["guard_model_edge"] > 0
    assert under["guard_triggered"] is True
    assert under["guard_mirror_suppressed"] is False
    assert under["bucket"] == "OVERCONFIDENCE"
    assert under["reason"] == gates.REASON_GUARD_TOTAL
    over = out["OVER 235.5"]["card_gate"]
    # The disagreement is still measured and stamped on the mirror;
    # only the trigger is side-aware.
    assert over["disagreement_points"] == pytest.approx(13.82)
    assert over["guard_model_edge"] < 0
    assert over["guard_triggered"] is False
    assert over["guard_mirror_suppressed"] is True
    # On its own merits at k = 0 the mirror is below threshold.
    assert over["bucket"] == "EXCLUDED"
    assert over["reason"] == gates.REASON_BELOW_THRESHOLD


def test_paired_ml_and_spread_guard_buckets_favored_side_only():
    # The Oct 29, 2026 FAU@UNT shape (projected home margin +6.336
    # vs the market's +14, 7.664 points), with ML prices inside the
    # frozen policy's longshot gate so the guard — not the
    # sensitivity BLOCK — is what decides the ML pair.
    g = "Florida Atlantic Owls @ North Texas Mean Green"
    m, t, am, hm = 6.336, 74.336, 34.0, 40.336
    rows = [
        _row("CFB", g, "SPREAD", "Florida Atlantic Owls +14", 14.0, -108,
             0.6469, 108 / 208, m, t, am, hm),
        _row("CFB", g, "SPREAD", "North Texas Mean Green -14", -14.0, -112,
             0.3337, 112 / 212, m, t, am, hm),
        _row("CFB", g, "ML", "Florida Atlantic Owls ML", None, 240,
             0.3694, 100 / 340, m, t, am, hm),
        _row("CFB", g, "ML", "North Texas Mean Green ML", None, -280,
             0.6306, 280 / 380, m, t, am, hm),
    ]
    out = _by_selection(gates.apply_card_gates(rows, _diagnostic_estimate()))
    for sel in ("Florida Atlantic Owls +14", "Florida Atlantic Owls ML"):
        gate = out[sel]["card_gate"]
        assert gate["disagreement_points"] == pytest.approx(7.664)
        assert gate["guard_triggered"] is True
        assert gate["bucket"] == "OVERCONFIDENCE"
        assert gate["reason"] == gates.REASON_GUARD_MARGIN
    spread_mirror = out["North Texas Mean Green -14"]["card_gate"]
    assert spread_mirror["guard_triggered"] is False
    assert spread_mirror["guard_mirror_suppressed"] is True
    assert spread_mirror["bucket"] == "EXCLUDED"
    assert spread_mirror["reason"] == gates.REASON_BELOW_THRESHOLD
    # The ML mirror classifies on its own merits: -280 trips the
    # price cap, a normal-path exclusion, not a guard bucket.
    ml_mirror = out["North Texas Mean Green ML"]["card_gate"]
    assert ml_mirror["guard_triggered"] is False
    assert ml_mirror["guard_mirror_suppressed"] is True
    assert ml_mirror["bucket"] == "EXCLUDED"
    assert ml_mirror["reason"] == gates.REASON_PRICE_CAP


def test_unpaired_spread_row_guard_unchanged():
    # A lone spread row has no mirror in the set, so the favored-side
    # rule has nothing to reason about: the guard fires pair-blind,
    # even on a row whose raw model edge is negative.
    g = "Alpha @ Beta"
    rows = [
        _row("NBA", g, "SPREAD", "Alpha +10.5", 10.5, -108,
             0.40, 108 / 208, 3.15, 224.69, 110.77, 113.92),
    ]
    out = gates.apply_card_gates(rows, _diagnostic_estimate())
    gate = out[0]["card_gate"]
    assert gate["guard_paired"] is False
    assert gate["guard_model_edge"] < 0
    assert gate["disagreement_points"] == pytest.approx(7.35)
    assert gate["guard_triggered"] is True
    assert gate["guard_mirror_suppressed"] is False
    assert gate["bucket"] == "OVERCONFIDENCE"
    assert gate["reason"] == gates.REASON_GUARD_MARGIN


def test_sensitivity_blocked_pair_blocks_both_even_when_guard_evaluable():
    # The spread pair is present, so the ML guard IS evaluable and
    # the disagreement is 33.5 points; Troy's raw ML edge is even
    # positive. The frozen policy's sensitivity BLOCK is a different
    # mechanism (no trustworthy baseline for either side) and still
    # governs: both ML rows BLOCKED, neither re-routed by the
    # favored-side rule.
    g = "Troy Trojans @ James Madison Dukes"
    m, t, am, hm = -14.0, 51.0, 32.5, 18.5
    rows = [
        _row("CFB", g, "SPREAD", "Troy Trojans +19.5", 19.5, -110,
             0.3000, 110 / 210, m, t, am, hm),
        _row("CFB", g, "SPREAD", "James Madison Dukes -19.5", -19.5, -110,
             0.7000, 110 / 210, m, t, am, hm),
        _row("CFB", g, "ML", "Troy Trojans ML", None, 750,
             0.3000, 100 / 850, m, t, am, hm),
        _row("CFB", g, "ML", "James Madison Dukes ML", None, -1200,
             0.7000, 1200 / 1300, m, t, am, hm),
    ]
    out = _by_selection(gates.apply_card_gates(rows, _diagnostic_estimate()))
    troy = out["Troy Trojans ML"]["card_gate"]
    assert troy["disagreement_points"] == pytest.approx(33.5)
    assert troy["guard_model_edge"] > 0
    assert troy["bucket"] == "BLOCKED"
    assert troy["reason"] == gates.REASON_DEVIG_SENSITIVITY_BLOCKED
    jmu = out["James Madison Dukes ML"]["card_gate"]
    assert jmu["bucket"] == "BLOCKED"
    assert jmu["reason"] == gates.REASON_DEVIG_SENSITIVITY_BLOCKED
