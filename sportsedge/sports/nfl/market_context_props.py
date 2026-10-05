"""NFL player-prop runner with sportsbook game context, not a game-edge model.

The failed V2K game-model search means the sportsbook spread/total are treated as
context only. Player probabilities still come from the existing PIT-safe role/usage
simulation. This surface intentionally produces no side/total edge rows.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .unified_run_it import run_unified_nfl_run_it

SCHEMA = "SPORTSEDGE_NFL_MARKET_CONTEXT_PROP_RUN_IT_V1"


class MarketContextPropError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise MarketContextPropError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketContextPropError(f"{field}:NUMERIC_REQUIRED") from exc
    if not (-200.0 < out < 200.0):
        raise MarketContextPropError(f"{field}:OUT_OF_RANGE")
    return out


def run_market_context_props(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    home_spread: float,
    game_total: float,
    prop_quotes: Sequence[Mapping[str, Any]] = (),
    td_quotes: Sequence[Mapping[str, Any]] = (),
    qualification_snapshots: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: Any = None,
    as_of: Any,
    executable_book: str = "draftkings",
    n_sims: int = 20000,
    seed: int = 21,
) -> dict[str, Any]:
    """Price NFL player props from a market-anchored game environment.

    home_spread uses normal sportsbook display convention: a home favorite is
    negative (for example -3.5). The simulation expects home scoring margin,
    so the environment margin is minus home_spread.
    """
    spread = _num(home_spread, "home_spread")
    total = _num(game_total, "game_total")
    if total <= 0:
        raise MarketContextPropError("game_total:POSITIVE_REQUIRED")

    fair_home_margin = -spread
    out = run_unified_nfl_run_it(
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        attempt9_margin=fair_home_margin,
        attempt9_total=total,
        game_quotes=(),
        prop_quotes=prop_quotes,
        td_quotes=td_quotes,
        qualification_snapshots=qualification_snapshots,
        home_model=home_model,
        away_model=away_model,
        scoring_prior=scoring_prior,
        as_of=as_of,
        edge_floor=1.0,
        executable_book=executable_book,
        n_sims=n_sims,
        seed=seed,
    )

    model = dict(out.get("model") or {})
    model.pop("attempt9_raw", None)
    model["score_context"] = {
        "source": "SPORTSBOOK_MARKET_CENTER_CONTEXT_ONLY",
        "home_spread": spread,
        "fair_home_margin": fair_home_margin,
        "game_total": total,
        "creates_game_market_edge": False,
    }
    out["schema"] = SCHEMA
    out["model"] = model
    out["game_card"] = {
        "status": "DISABLED_GAME_EDGE_MODEL_FAILED",
        "picks": [],
        "reason": "V2K_DEVELOPMENT_BUDGET_EXHAUSTED_NO_PASS",
    }
    out["market_environment"] = dict(model["score_context"])
    out["authority"] = {
        "research_only": True,
        "creates_game_market_edge": False,
        "creates_model_p": False,
        "truth_gate_authority": False,
        "official_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
    }
    return out


__all__ = ["MarketContextPropError", "SCHEMA", "run_market_context_props"]
