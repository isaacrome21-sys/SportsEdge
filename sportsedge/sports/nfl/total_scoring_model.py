"""NFL totals: PIT-safe opponent-adjusted team scoring-rate model (Lane 2).

Replaces the ``22_PTS_PER_TEAM_PLUS_MARGIN_FORM_ONLY`` league prior as the
*projection* for NFL totals. Each club carries an offense rating (points
scored above league mean) and a defense rating (points allowed above league
mean). Ratings are updated only AFTER a game is projected (walk-forward),
regressed toward zero between seasons, and combined with a home-field split,
a league scoring level that drifts with past results, and roof/wind
adjustments. Pace is not modelled separately (no free play-by-play is
committed); a team's scoring rate already embeds its pace.

RESEARCH-ONLY. ``pricing_status`` fails closed: this model may create edges
only when a committed chronological out-of-sample receipt shows it beats the
closing market (n >= 300, whole 95% CI of Brier(model) - Brier(market) < 0).
No wagering, staking or order placement of any kind.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MODEL_ID = "nfl_total_opp_adj_scoring_rate_v1"
RECEIPT_PATH = Path(__file__).with_name("NFL_TOTAL_SCORING_MODEL_BACKTEST_V1.json")
MIN_TEST_N = 300

DEFAULT_PARAMS = {
    "mu0": 22.0,        # starting league points/team only; drifts with data
    "k": 0.08,          # rating learning rate
    "k_mu": 0.01,       # league-level drift rate
    "carry": 0.6,       # between-season regression toward 0
    "hfa": 1.8,         # home minus away points
    "dome": 1.0,        # total points added for dome/closed roof
    "wind_per_mph": 0.15,  # total points removed per mph above 10
    "sigma": 13.5,      # SD of actual total about projection
}


def environment_adjustment(game, params):
    adj = 0.0
    if str(game.get("roof") or "").lower() in ("dome", "closed"):
        adj += params["dome"]
    wind = game.get("wind")
    try:
        wind = float(wind)
    except (TypeError, ValueError):
        wind = None
    if wind is not None and not math.isnan(wind) and wind > 10:
        adj -= params["wind_per_mph"] * (wind - 10)
    return adj


def walk_forward(games, params):
    """Project every game using only games before it (input must be chronological)."""
    off, dfn = {}, {}
    mu = params["mu0"]
    season = None
    out = []
    for g in games:
        if season is not None and g["season"] != season:
            for d in (off, dfn):
                for t in d:
                    d[t] *= params["carry"]
        season = g["season"]
        h, a = g["home_team"], g["away_team"]
        env = environment_adjustment(g, params) / 2.0
        ph = mu + params["hfa"] / 2 + off.get(h, 0.0) + dfn.get(a, 0.0) + env
        pa = mu - params["hfa"] / 2 + off.get(a, 0.0) + dfn.get(h, 0.0) + env
        out.append({**g, "proj_home": ph, "proj_away": pa, "proj_total": ph + pa})
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None or (isinstance(hs, float) and math.isnan(hs)):
            continue
        eh, ea = hs - ph, as_ - pa
        off[h] = off.get(h, 0.0) + params["k"] * eh
        dfn[a] = dfn.get(a, 0.0) + params["k"] * eh
        off[a] = off.get(a, 0.0) + params["k"] * ea
        dfn[h] = dfn.get(h, 0.0) + params["k"] * ea
        mu += params["k_mu"] * (eh + ea) / 2
    return out


def _cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def total_probabilities(proj_total, line, sigma):
    """Push-aware over/under probability with a continuity-corrected normal."""
    if float(line).is_integer():
        p_under = _cdf((line - 0.5 - proj_total) / sigma)
        p_over = 1 - _cdf((line + 0.5 - proj_total) / sigma)
        return {"p_over": p_over, "p_under": p_under, "p_push": 1 - p_over - p_under}
    p_over = 1 - _cdf((line - proj_total) / sigma)
    return {"p_over": p_over, "p_under": 1 - p_over, "p_push": 0.0}


def load_backtest_receipt(path=RECEIPT_PATH):
    return json.loads(Path(path).read_text())


def pricing_status(receipt):
    """Fail-closed gate. Edges only with a passing, adequately sized OOS receipt."""
    ok = (isinstance(receipt, dict) and receipt.get("passes") is True
          and int(receipt.get("n_test") or 0) >= MIN_TEST_N
          and isinstance(receipt.get("brier_diff_ci95"), (list, tuple))
          and float(receipt["brier_diff_ci95"][1]) < 0)
    if ok:
        return {"status": "RESEARCH_MODEL_BEATS_CLOSE_UNVALIDATED_FORWARD",
                "may_create_edges": True, "model_id": MODEL_ID}
    return {"status": "WATCH_NFL_TOTAL_MODEL_DOES_NOT_BEAT_CLOSE",
            "may_create_edges": False, "model_id": MODEL_ID,
            "reason": "NFL_TOTAL_SCORING_MODEL_OOS_BACKTEST_NOT_PASSED"}
