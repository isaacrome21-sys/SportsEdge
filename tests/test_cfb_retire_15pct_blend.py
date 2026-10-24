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
