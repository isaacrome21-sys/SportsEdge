"""Per-market CFB candidate gate (ruling 2026-10-23i).

Every CFB market (spread, total, moneyline, halves, team totals, and the
t272 fallback composition) is blocked from candidate status until its
RECORDED 2025 out-of-sample Brier beats the closing no-vig market with a
95% CI: the upper bound of mean(model Brier - market Brier) must be < 0.
Metrics come only from docs/cfb_market_gate_metrics_20261023i.json, which
scripts/cfb_calibration/backtest_opponent_ratings.py writes. The pass/fail
is computed here from those numbers; no stored flag can make a market pass.
Blocked markets keep their research numbers. SCREEN / NOT_VALIDATED.
"""
import json
import pathlib

RULING = "2026-10-23i"
BLOCK_STATUS = "WATCH_CFB_NOT_BETTER_THAN_MARKET"
METRICS_PATH = pathlib.Path(__file__).resolve().parents[3] / "docs" / "cfb_market_gate_metrics_20261023i.json"


def load_metrics():
    try:
        return json.loads(METRICS_PATH.read_text())
    except (OSError, ValueError):
        return {"ruling": RULING, "markets": {}}


def gate(sport, market_key):
    if str(sport).upper() != "CFB":
        return {"allowed": True, "reason": None}
    e = (load_metrics().get("markets") or {}).get(market_key)
    if not e or not isinstance(e.get("diff_ci95"), list) or len(e["diff_ci95"]) != 2:
        return {"allowed": False, "ruling": RULING, "metrics": None,
                "reason": f"NOT_BETTER_THAN_MARKET:{market_key}:NO_RECORDED_OOS_2025_METRICS"}
    lo, hi = e["diff_ci95"]
    ok = hi < 0
    return {"allowed": ok, "ruling": RULING, "metrics": dict(e),
            "reason": None if ok else
            (f"NOT_BETTER_THAN_MARKET:{market_key}:OOS2025_BRIER_{e.get('model_brier')}"
             f"_VS_NO_VIG_{e.get('market_no_vig_brier')}_DIFF_CI95_{lo}_{hi}")}


def market_key(market, cfb_opp_adjusted):
    m = str(market).upper()
    if cfb_opp_adjusted and m in {"SPREAD", "TOTAL", "ML"}:
        return "OPP:" + m
    if m in {"SPREAD", "TOTAL", "ML"}:
        return "T272:" + m
    return m
