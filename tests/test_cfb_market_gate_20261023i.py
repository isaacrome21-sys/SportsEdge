"""Ruling 2026-10-23i: every CFB market is blocked from candidate status until
its recorded 2025 out-of-sample Brier beats closing no-vig with a CI.
Also t273 F1 (FBS-only recalibration). SCREEN / NOT_VALIDATED."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from artifacts import free_models as fm
from sportsedge.sports.cfb import market_gate as mg
from sportsedge import team_half_pricing as thp

NOW = datetime(2026, 10, 24, 3, tzinfo=timezone.utc)
KICK = NOW + timedelta(hours=14)


def _ctx(opp=1.0, home_off=30.0):
    c = {k: 0.0 for k in fm.CONTEXT_KEYS["CFB"]}
    c.update(cfb_opp_adjusted=opp, cfb_league_mean_pts=27.0, cfb_hfa=3.0,
             home_off_rating=home_off, home_total_rating=70.0, away_total_rating=70.0,
             home_rating=8.0)
    return c


def _row(market, side, line, odds=-110):
    return {"sport": "CFB", "away": "Away St", "home": "Home U", "market": market,
            "side": side, "line": line, "odds": odds, "kickoff": KICK.isoformat(),
            "quote_captured_at": NOW.isoformat()}


def test_recorded_metrics_file_drives_gate():
    m = mg.load_metrics()
    assert m["ruling"] == "2026-10-23i"
    for k in ("OPP:SPREAD", "OPP:TOTAL", "OPP:ML"):
        e = m["markets"][k]
        assert {"model_brier", "market_no_vig_brier", "diff_ci95"} <= set(e)
        # gate is computed, never stored as a hand-set pass flag
        assert "allowed" not in e
        assert mg.gate("CFB", k)["allowed"] == (e["diff_ci95"][1] < 0)


def test_gate_logic_from_numbers(monkeypatch):
    monkeypatch.setattr(mg, "load_metrics", lambda: {"ruling": "2026-10-23i", "markets": {
        "OPP:TOTAL": {"model_brier": 0.24, "market_no_vig_brier": 0.25, "diff_ci95": [-0.02, -0.001]},
        "OPP:SPREAD": {"model_brier": 0.249, "market_no_vig_brier": 0.25, "diff_ci95": [-0.004, 0.002]}}})
    assert mg.gate("CFB", "OPP:TOTAL")["allowed"] is True
    g = mg.gate("CFB", "OPP:SPREAD")
    assert g["allowed"] is False and g["reason"].startswith("NOT_BETTER_THAN_MARKET")
    for k in ("OPP:ML", "T272:SPREAD", "TEAM_TOTALS", "1H_SPREAD"):
        assert mg.gate("CFB", k)["allowed"] is False
        assert "NOT_BETTER_THAN_MARKET" in mg.gate("CFB", k)["reason"]


@pytest.mark.parametrize("market,side,line,opp", [
    ("TOTAL", "OVER", 48.5, 1.0), ("SPREAD", "HOME", -3.5, 1.0), ("ML", "HOME", None, 1.0),
    ("TOTAL", "OVER", 48.5, 0.0), ("SPREAD", "HOME", -3.5, 0.0), ("ML", "HOME", None, 0.0)])
def test_calculate_blocks_cfb_markets(monkeypatch, market, side, line, opp):
    monkeypatch.setattr(mg, "load_metrics", lambda: {"ruling": "2026-10-23i", "markets": {}})
    monkeypatch.setattr(fm, "context_for", lambda *a, **k: (_ctx(opp), KICK, []))
    r = fm.calculate(_row(market, side, line, odds=+150), None, NOW)
    assert r["status"] == mg.BLOCK_STATUS
    assert "NOT_BETTER_THAN_MARKET" in r["reason"]
    assert r["status"] != fm.POSITIVE_EV_STATUS
    assert r["pricing_lanes"]["lane_a_independent"]["estimate_p"] is not None
    if opp == 1.0 and market != "ML":
        assert "raw_estimate_p" in r["pricing_lanes"]["lane_a_independent"]


def test_team_half_derivatives_gated(monkeypatch):
    monkeypatch.setattr(mg, "load_metrics", lambda: {"ruling": "2026-10-23i", "markets": {}})
    priced = {"status": "RESEARCH_CANDIDATE_NOT_VALIDATED", "estimate_p": 0.6}
    out = thp.apply_cfb_market_gate(dict(priced), "CFB", "TEAM_TOTALS")
    assert out["status"] == mg.BLOCK_STATUS and "NOT_BETTER_THAN_MARKET" in out["reason"]
    assert out["estimate_p"] == 0.6
    nfl = thp.apply_cfb_market_gate(dict(priced), "NFL", "TEAM_TOTALS")
    assert nfl["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"


def test_f1_recalibration_fit_on_fbs_vs_fbs():
    c = fm.CFB_OPP_MODEL
    assert c["recal_fit_population"] == "FBS_VS_FBS_2024"
    m = mg.load_metrics()
    assert abs(m["oos_2025_fbs_vs_fbs_mean_margin_error"]) < 0.5


def test_ruling_recorded():
    import pathlib
    txt = (pathlib.Path(__file__).resolve().parents[1] / "GROK_RULINGS.md").read_text()
    assert "2026-10-23i" in txt
