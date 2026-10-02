"""Price every MLB side, total, team total, and player prop from the live registry.

This is an engineering proof, not evidence promotion. F5 stays on
grok/mlb/f5-card. Binary first-HR and pitcher-win stay on their dedicated
sessions and are not coerced into count markets.
"""
from __future__ import annotations

from typing import Any

from sportsedge.engine_registry import engine_registry
from sportsedge.hitter_joint_engine import HITTER_MARKETS
from sportsedge.pitcher_joint_engine import PITCHER_MARKETS

SIDE_TOTAL_MARKETS = ("MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS")
SIMULATIONS = 100000


def _hitter_pool() -> list[dict[str, int]]:
    row = {
        "plate_appearances": 4,
        "hits": 1,
        "singles": 1,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "total_bases": 1,
        "rbi": 1,
        "runs": 1,
        "stolen_bases": 0,
        "walks": 1,
        "strikeouts": 1,
        "extra_base_hits": 0,
    }
    return [dict(row) for _ in range(10)]


def _pitcher_pool() -> list[dict[str, int]]:
    row = {
        "strikeouts": 6,
        "outs": 18,
        "earned_runs": 2,
        "hits_allowed": 5,
        "walks_allowed": 1,
    }
    return [dict(row) for _ in range(5)]


def _side_total_input(market: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "game_id": "proof-game",
        "entity_id": "game",
        "market": market,
        "away_mean_runs": 4.1,
        "home_mean_runs": 4.4,
        "simulations": SIMULATIONS,
    }
    if market == "MONEYLINE":
        row.update(line=0.0, side="HOME")
    elif market == "RUN_LINE":
        row.update(line=-1.5, side="HOME")
    elif market == "TOTALS":
        row.update(line=8.5, side="OVER")
    else:
        row.update(line=4.5, side="OVER", team_side="HOME", entity_id="home")
    return row


def _prop_input(market: str) -> dict[str, Any]:
    if market == "HOME_RUNS":
        # Registry keeps the measured generic baseline for HOME_RUNS.
        return {
            "game_id": "proof-game",
            "entity_id": "hitter-1",
            "market": market,
            "line": 0.5,
            "side": "OVER",
            "expected_count": 0.35,
        }
    if market in HITTER_MARKETS:
        return {
            "game_id": "proof-game",
            "entity_id": "hitter-1",
            "market": market,
            "line": 0.5,
            "side": "OVER",
            "features": {"history_pool": _hitter_pool()},
        }
    if market.startswith("EITHER_PITCHER_"):
        return {
            "game_id": "proof-game",
            "entity_id": "sp-a|sp-b",
            "market": market,
            "line": 0.5 if market != "EITHER_PITCHER_ER" else 1.5,
            "side": "OVER",
            "features": {
                "pitcher_a_history": _pitcher_pool(),
                "pitcher_b_history": _pitcher_pool(),
            },
        }
    line = 17.5 if market == "PITCHER_OUTS" else 0.5
    if market == "PITCHER_ER":
        line = 1.5
    return {
        "game_id": "proof-game",
        "entity_id": "sp-1",
        "market": market,
        "line": line,
        "side": "OVER",
        "features": {"history_pool": _pitcher_pool()},
    }


def price_props_side_totals() -> dict[str, dict[str, Any]]:
    """Return a probability for every side, total, team total, and prop."""
    registry = engine_registry()
    markets = list(SIDE_TOTAL_MARKETS) + sorted(HITTER_MARKETS | PITCHER_MARKETS)
    missing = [market for market in markets if market not in registry]
    if missing:
        raise RuntimeError(f"registry missing props/side/totals: {missing}")
    out: dict[str, dict[str, Any]] = {}
    for market in markets:
        payload = _side_total_input(market) if market in SIDE_TOTAL_MARKETS else _prop_input(market)
        priced = registry[market](payload)
        model_p = priced.get("model_p")
        if not isinstance(model_p, (int, float)):
            raise RuntimeError(f"{market} did not return model_p")
        if not 0.0 <= float(model_p) <= 1.0:
            raise RuntimeError(f"{market} model_p outside [0,1]: {model_p}")
        out[market] = {
            "market": market,
            "model_p": float(model_p),
            "push_p": float(priced.get("push_p") or 0.0),
            "engine_version": priced.get("engine_version"),
            "authority": "RESEARCH_READOUT_NOT_OFFICIAL",
        }
    return out
