"""Risk overlay for deployed MLB game-market candidates.

This module does not alter Model_P and does not use sportsbook data as a model
feature.  It is a downstream wager-selection safety gate used while MONEYLINE
has only aggregate holdout calibration evidence and no validated probability-
tail / market-disagreement evidence.

Temporary policy, predeclared 2026-08-13:
* all game-market bets require at least 2.5 percentage points of raw edge;
* side bets whose underlying ML is +175 or longer are PASS until heavy-dog
  tail validation exists;
* +100 through +174 underdogs need 5.0pp edge and 10% EV, while model/market
  disagreement above 7.5pp is treated as unvalidated rather than celebrated;
* at most one ML/RL side position per game can be official;
* accepted underdog side bets are capped at 1.5% bankroll Kelly guidance.

The thresholds are safety constraints, not a claim that favorites are inherently
better bets.  They prevent the production card from exploiting an unvalidated
region of the current model.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

RISK_GATE_VERSION = "GAME_RISK_GUARD_V1_20260813"
GLOBAL_MIN_EDGE = 0.025
HEAVY_DOG_ML_ODDS = 175
DOG_MIN_EDGE = 0.050
DOG_MIN_EV = 0.10
DOG_MAX_UNVALIDATED_EDGE = 0.075
DOG_KELLY_CAP = 0.015
SIDE_MARKETS = {"MONEYLINE", "RUN_LINE"}


def _copy(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["risk_gate_version"] = RISK_GATE_VERSION
    out.setdefault("risk_gate_reason", "PASS_THROUGH")
    out.setdefault("pre_risk_gate_status", out.get("bet_status"))
    return out


def _pass(row: dict[str, Any], reason: str) -> None:
    row["bet_status"] = "PASS"
    row["risk_gate_reason"] = reason
    row["kelly_fraction"] = 0.0


def apply_game_risk_guard(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Apply downstream risk controls without mutating input rows.

    RUN_LINE side risk is classified using the same selection's MONEYLINE price
    from the same game.  If that pairing is absent, an otherwise-official RL bet
    fails closed because SportsEdge cannot know whether it is a heavy-underdog
    exposure.
    """
    out = [_copy(r) for r in rows]

    ml_price: dict[tuple[str, str], float] = {}
    for r in out:
        if r.get("market") != "MONEYLINE":
            continue
        try:
            key = (str(r["game_id"]), str(r["selection"]))
            price = float(r["american_odds"])
        except Exception:
            continue
        ml_price[key] = price

    for r in out:
        if r.get("bet_status") != "OFFICIAL_BET" or r.get("market") not in SIDE_MARKETS:
            continue
        key = (str(r.get("game_id")), str(r.get("selection")))
        underlying = ml_price.get(key)
        if r.get("market") == "MONEYLINE" and underlying is None:
            try:
                underlying = float(r["american_odds"])
            except Exception:
                underlying = None
        r["underlying_moneyline_odds"] = underlying

        if underlying is None:
            _pass(r, "UNDERLYING_ML_PRICE_MISSING_FOR_SIDE_RISK")
            continue

        if underlying >= HEAVY_DOG_ML_ODDS:
            _pass(r, "HEAVY_DOG_SIDE_UNVALIDATED")
            continue

        if underlying >= 100:
            try:
                edge = float(r["edge"])
                ev = float(r["ev_per_dollar"])
            except Exception:
                _pass(r, "UNDERDOG_RISK_METRICS_MISSING")
                continue
            if edge > DOG_MAX_UNVALIDATED_EDGE:
                _pass(r, "UNDERDOG_MARKET_DISAGREEMENT_UNVALIDATED")
                continue
            if edge < DOG_MIN_EDGE or ev < DOG_MIN_EV:
                _pass(r, "UNDERDOG_EDGE_BUFFER_NOT_MET")
                continue
            r["kelly_fraction"] = min(float(r.get("kelly_fraction") or 0.0), DOG_KELLY_CAP)
            r["risk_gate_reason"] = "UNDERDOG_BUFFER_MET"
        else:
            r["risk_gate_reason"] = "SIDE_RISK_OK"

    # Never stack correlated ML/RL exposure in the same game.  When the same
    # underdog qualifies in both markets, prefer the run line (lower outcome
    # variance).  For a favorite, prefer the moneyline.  Remaining tie-breaks
    # use larger edge then EV, deterministically.
    by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in out:
        if r.get("bet_status") == "OFFICIAL_BET" and r.get("market") in SIDE_MARKETS:
            by_game[str(r.get("game_id"))].append(r)

    for _gid, candidates in by_game.items():
        if len(candidates) <= 1:
            continue

        def rank(r: dict[str, Any]) -> tuple[float, float, float, str, str]:
            underlying = r.get("underlying_moneyline_odds")
            try:
                dog = float(underlying) >= 100
            except Exception:
                dog = False
            preferred_market = "RUN_LINE" if dog else "MONEYLINE"
            preference = 1.0 if r.get("market") == preferred_market else 0.0
            return (
                preference,
                float(r.get("edge") or 0.0),
                float(r.get("ev_per_dollar") or 0.0),
                str(r.get("selection")),
                str(r.get("market")),
            )

        keep = max(candidates, key=rank)
        keep["risk_gate_reason"] = (
            keep.get("risk_gate_reason", "PASS_THROUGH") + ";GAME_SIDE_EXPOSURE_SELECTED"
        )
        for r in candidates:
            if r is keep:
                continue
            _pass(r, "CORRELATED_SIDE_EXPOSURE_SUPPRESSED")

    return out
