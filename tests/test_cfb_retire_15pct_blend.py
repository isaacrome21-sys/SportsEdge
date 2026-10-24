"""t277: the provisional 15% market blend (Lane B) is RETIRED for CFB.

Backtest (2023-25 OOS) chose weight 0.1/0.0 on train and no weight beat the
closing market, so CFB uses no anchored blend; the only evidence-backed CFB
weight is market-only (0.0) until a market passes ruling 2026-10-23i.
Other sports' Lane B is unchanged here (out of scope; frozen NFL tests).
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest

MOD = Path(__file__).resolve().parents[1] / "artifacts" / "free_models.py"
spec = importlib.util.spec_from_file_location("free_models_t277", MOD)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
NOW = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)
START = "2026-10-24T20:00:00Z"


def cfb(**kw):
    x = {"sport": "CFB", "game": "Texas A&M Aggies @ Alabama Crimson Tide", "market": "total",
         "side": "UNDER", "line": 50.5, "odds": -110, "commence_time": START,
         "quote_captured_at": "2026-10-24T12:59:00Z"}
    x.update(kw)
    return x


def calc(row, **kw):
    return model.calculate(row, model.PublicContext(NOW), NOW, auto_context=False, **kw)


def test_cfb_weight_constant_is_market_only_and_evidence_bound():
    assert model.CFB_ANCHOR_WEIGHT == 0.0
    assert model.CFB_ANCHOR_WEIGHT_SOURCE == "OOS_GATE_RULING_2026-10-23i_MARKET_ONLY"
    assert model.CFB_LANE_B_STATUS == "RETIRED"


@pytest.mark.parametrize("market,side,line", [("total", "UNDER", 50.5), ("total", "OVER", 50.5),
                                              ("spread", "HOME", -6.5), ("h2h", "HOME", None)])
def test_cfb_lane_b_retired_on_every_market(market, side, line):
    row = cfb(market=market, side=side, line=line)
    if market == "h2h":
        row["opposite_odds"] = 120
    v = calc(row)
    b = v["pricing_lanes"]["lane_b_anchored"]
    assert b["status"] == "LANE_B_RETIRED"
    assert b["reason"] == "CFB_15PCT_BLEND_RETIRED"
    assert "estimate_p" not in b and "ev_per_dollar" not in b
    assert b["anchor"]["weight"] != 0.15 and b["anchor"]["status"] == "RETIRED"
    assert v["pricing_lane"] == "LANE_A_INDEPENDENT"


def test_cfb_explicit_lane_b_request_refused():
    v = calc(cfb(), lane="B")
    assert v["status"] == "CFB_15PCT_BLEND_RETIRED"
    assert "estimate_p" not in v


def test_cfb_market_anchor_never_reports_15pct():
    v = calc(cfb())
    anchor = v.get("market_anchor") or {}
    assert anchor.get("weight") != 0.15


def test_non_cfb_lane_b_unchanged():
    v = calc(dict(cfb(), sport="NFL", game="Detroit Lions @ Arizona Cardinals"))
    assert v["pricing_lanes"]["lane_b_anchored"]["lane"] == "LANE_B_ANCHORED"
    assert model.ANCHOR_WEIGHT == 0.15


# --- Locked decisions (2026-10-24): market-only fallback; no model edge; injury/weather gated ---

def _ctx(**kw):
    c = {"home_rating": 6.0, "away_rating": -6.0, "home_injury_pts": 0.0, "away_injury_pts": 0.0,
         "home_form": 0.0, "away_form": 0.0, "weather_total_adj": 0.0}
    c.update(kw)
    return c


def mcalc(row):
    return model.calculate(row, model.PublicContext(NOW), NOW, auto_context=False, allow_manual_context=True)


@pytest.mark.parametrize("market,side,line", [("total", "OVER", 40.5), ("total", "UNDER", 70.5),
                                              ("spread", "HOME", 10.5), ("h2h", "HOME", None)])
def test_cfb_never_claims_model_edge_market_only_fallback(market, side, line):
    row = cfb(market=market, side=side, line=line, odds=150, context=_ctx())
    if market == "h2h":
        row["opposite_odds"] = -180
    v = mcalc(row)
    assert v["status"] == "WATCH_CFB_MARKET_ONLY_NO_VALIDATED_WEIGHT"
    assert "2026-10-23i" in v["reason"]


@pytest.mark.parametrize("adj", [dict(home_injury_pts=-1.5), dict(away_injury_pts=-0.15),
                                 dict(weather_total_adj=-0.8)])
def test_unvalidated_injury_or_weather_adjustment_gate(adj):
    status, reason = model.unvalidated_adjustment_gate(model.POSITIVE_EV_STATUS, None, _ctx(**adj))
    assert status == "WATCH_UNVALIDATED_INJURY_WEATHER_ADJ"
    assert reason.startswith("UNCALIBRATED_ADJUSTMENT:")


def test_adjustment_gate_passthrough_when_zero_or_not_positive():
    assert model.unvalidated_adjustment_gate(model.POSITIVE_EV_STATUS, None, _ctx()) == (model.POSITIVE_EV_STATUS, None)
    assert model.unvalidated_adjustment_gate("BELOW_THRESHOLD", None, _ctx(weather_total_adj=-0.8)) == ("BELOW_THRESHOLD", None)


def test_experimental_weight_grid_not_reachable_from_production():
    src = MOD.read_text()
    assert "backtest_cfb_matchup_blend" not in src
    assert "WEIGHTS" not in src
