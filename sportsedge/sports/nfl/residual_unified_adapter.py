"""Market-anchored adapter for frozen NFL unified/M2-style joint score research.

Do not edit the frozen distribution engine or any model artifacts. The raw
margin/total MUST be supplied independently from a strictly prior model.
The adapter derives conservative fair home/away means and asks the EXISTING
unified engine to price and simulate the same joint-score path at those means.
No output from this module grants betting, Model_P or promotion authority.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.market_residual_research import (
    price_game_from_pairs,
)
from sportsedge.sports.nfl.unified_market_engine import run_unified_nfl_model


def run_residual_unified_research(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    raw_margin: float,
    raw_total: float,
    paired_markets: Sequence[Mapping[str, Any]],
    observed_at: Any,
    as_of: Any,
    kickoff_at: Any,
    prop_markets: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: Any = None,
    n_sims: int = 20000,
    seed: int = 21,
    model_family: str = "ATTEMPT9_RAW",
) -> dict[str, Any]:
    research = price_game_from_pairs(
        raw_margin=raw_margin, raw_total=raw_total,
        markets=paired_markets, observed_at=observed_at, as_of=as_of,
        kickoff_at=kickoff_at, model_family=model_family,
    )
    center = research["center"]
    requests = []
    for market in research["markets"]:
        for side in market["sides"]:
            request = {"market":market["market"],"selection":side["selection"]}
            if side["line"] is not None:
                request["line"] = side["line"]
            requests.append(request)
    # Frozen engine retains its own score-grid shape, tie/push handling, team
    # scoring and player workload coupling. Only its input location is changed.
    engine = run_unified_nfl_model(
        game_id=game_id,home_team=home_team,away_team=away_team,
        attempt9_margin=center["margin"],attempt9_total=center["total"],
        game_markets=requests,prop_markets=prop_markets,
        home_model=home_model,away_model=away_model,
        scoring_prior=scoring_prior,n_sims=n_sims,seed=seed,
    )
    if not engine["authority"].get("research_only"):
        raise ValueError("RESIDUAL_UNIFIED_RESEARCH_AUTHORITY_REQUIRED")
    return {
        "schema":"NFL_RESIDUAL_UNIFIED_ADAPTER_V1",
        "model_family":model_family,
        "independent_raw":{"margin":float(raw_margin),"total":float(raw_total)},
        "residual":research,
        "engine":engine,
        "authority":{"research_only":True,"model_p":False,"official":False,
                     "promotion":False,"staking":False},
    }


__all__=["run_residual_unified_research"]
