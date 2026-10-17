"""Quote-bound residual research adapter outside the frozen unified RUN IT surface.

The existing unified_run_it.py, nfl_unified_phone.py and unified_market_engine.py
remain byte-for-byte frozen. This adapter feeds market-anchored score means into
that same joint-score and workload simulation, never its raw absolute game p
into the wagering rails. No paired quotes => fail closed.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.ask_sims import AskSimsError, ask_unified_score_sims
from sportsedge.nfl_run_it import run_it_market_anchored
from sportsedge.sports.nfl.unified_market_engine import run_unified_nfl_model


class UnifiedResidualResearchError(ValueError):
    pass


def run_unified_residual_research(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    raw_margin: float,
    raw_total: float,
    paired_game_quotes: Sequence[Mapping[str, Any]],
    game_start_ts: str,
    as_of: str,
    executable_book: str = "draftkings",
    prop_requests: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: Any = None,
    n_sims: int = 20000,
    seed: int = 21,
    ask_sims_questions: Sequence[Mapping[str, Any]] = (),
    ask_sims_aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Single executable-book residual pricing, coherent game/prop distribution.

    Existing run_unified_nfl_model is used unchanged. Game bets remain DISABLED:
    only research probability/edge rows leave this adapter.
    """
    if not paired_game_quotes:
        raise UnifiedResidualResearchError("PAIRED_GAME_QUOTES_REQUIRED")
    quotes = [q for q in paired_game_quotes
              if str(q.get("book") or q.get("book_key") or "").casefold() ==
              str(executable_book).casefold()]
    if not quotes:
        raise UnifiedResidualResearchError("EXECUTABLE_PAIRED_BOOK_REQUIRED")
    if any(str(q.get("game_id")) != str(game_id) or
           str(q.get("home")) != str(home_team) or
           str(q.get("away")) != str(away_team) for q in quotes):
        raise UnifiedResidualResearchError("GAME_IDENTITY_MISMATCH")
    card = run_it_market_anchored(
        quotes,
        {game_id: {"margin": raw_margin, "total": raw_total,
                   "commence_time": game_start_ts}},
        as_of=as_of,
    )
    if len(card["games"]) != 1 or not card["games"][0]["market_anchored_research_prices"]:
        raise UnifiedResidualResearchError("ONE_PRICED_GAME_REQUIRED")
    fair = card["games"][0]["market_anchored_research_prices"]
    margin = float(fair[0]["fair_margin"])
    total = float(fair[0]["fair_total"])
    # Same immutable discrete score shape and joint paths as the frozen
    # runtime; no game probabilities from its absolute score grid are used.
    engine = run_unified_nfl_model(
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        attempt9_margin=margin,
        attempt9_total=total,
        game_markets=(),
        prop_markets=prop_requests,
        home_model=home_model,
        away_model=away_model,
        scoring_prior=scoring_prior,
        n_sims=n_sims,
        seed=seed,
    )
    asked_sims = []
    # Query exactly the same recorded frozen game score paths; book odds are
    # caller supplied and never treated as quote receipts or betting authority.
    if not isinstance(ask_sims_questions, (list, tuple)) or len(ask_sims_questions) > 40:
        raise AskSimsError("ASK_SIMS_REQUEST_BATCH_INVALID")
    for request in ask_sims_questions:
        if not isinstance(request, Mapping) or not isinstance(request.get("question"), (str, dict)):
            raise AskSimsError("ASK_SIMS_REQUEST_INVALID")
        asked_sims.append(ask_unified_score_sims(
            engine, request["question"], home_team=home_team, away_team=away_team,
            aliases=ask_sims_aliases, price_american=request.get("price_american"),
        ))
    return {
        "schema": "SPORTSEDGE_NFL_UNIFIED_RESIDUAL_RESEARCH_V1",
        "game_id": game_id,
        "score_distribution": engine["score_distribution"],
        "score_means": engine["score_means"],
        "workload_coupling": engine["workload_coupling"],
        "prop_markets": engine["prop_markets"],
        "asked_sims": asked_sims,
        "game_markets": fair,
        "market_anchored_residual": {
            "fair_margin": margin, "fair_total": total,
            "raw_margin": raw_margin, "raw_total": raw_total,
        },
        "validated_markets": [],
        "picks": [],
        "authority": {
            "research_only": True,
            "game_market_edge_disabled": True,
            "creates_model_p": False, "official_authority": False,
            "promotion_authority": False, "staking_authority": False,
            "forward_clv_status": "PENDING",
        },
    }
