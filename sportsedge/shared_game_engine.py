"""Stage 1 shared V7 game-distribution engine session.

One immutable V7 score distribution is simulated per distinct pregame game state and
then reused for MONEYLINE, RUN_LINE, TOTALS, and TEAM_TOTALS read-outs. Sportsbook
proposition line/side and selected team never enter the stochastic distribution
identity.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Mapping

from .game_distribution_readout import read_game_probability
from .source_lineage import canonical_json_sha256
from .v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    DEFAULT_FIRST_INNING_DISPERSION_R,
    DEFAULT_FIRST_INNING_SHARE,
    V7_DISTRIBUTION_VERSION,
    GameDistribution,
    simulate_game_distribution,
)

STAGE1_GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})
V8_PRIMARY_GAME_DEFAULT_SIMULATIONS = 100000
V8_PRIMARY_GAME_MIN_SIMULATIONS = 100000


class SharedGameEngineError(ValueError):
    pass


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise SharedGameEngineError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SharedGameEngineError(f"{name} must be numeric") from exc
    if not isfinite(out) or out <= 0:
        raise SharedGameEngineError(f"{name} must be finite and > 0")
    return out


def _simulation_count(value: Any, *, minimum: int = V8_PRIMARY_GAME_MIN_SIMULATIONS) -> int:
    if isinstance(value, bool):
        raise SharedGameEngineError(f"simulations must be integer >= {minimum}")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise SharedGameEngineError(f"simulations must be integer >= {minimum}") from exc
    if out < minimum:
        raise SharedGameEngineError(f"simulations must be integer >= {minimum}")
    return out


def score_distribution_sha256(distribution: GameDistribution) -> str:
    """Hash only the reusable final-score distribution, not any sportsbook read-out."""
    if not isinstance(distribution, GameDistribution):
        raise SharedGameEngineError("distribution must be GameDistribution")
    return canonical_json_sha256({
        "version": V7_DISTRIBUTION_VERSION,
        "simulations": int(distribution.simulations),
        "seed_policy": str(distribution.seed_policy),
        "joint_score_pmf": distribution.joint_score_pmf,
    })


def build_shared_game_engine_session(
    *,
    simulator: Callable[..., GameDistribution] = simulate_game_distribution,
    _minimum_simulations_for_test: int | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Return one per-card engine closure with an internal distribution cache.

    Production always enforces the frozen V8 100k path floor. A lower minimum is
    available only when a non-production simulator is injected by tests; the
    canonical registry never supplies this escape hatch.
    """
    minimum_simulations = V8_PRIMARY_GAME_MIN_SIMULATIONS
    if _minimum_simulations_for_test is not None:
        if simulator is simulate_game_distribution:
            raise SharedGameEngineError("test simulation floor override requires injected simulator")
        if isinstance(_minimum_simulations_for_test, bool) or int(_minimum_simulations_for_test) < 1000:
            raise SharedGameEngineError("test simulation floor override must be >= 1000")
        minimum_simulations = int(_minimum_simulations_for_test)

    cache: dict[str, tuple[GameDistribution, str]] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        market = str(model_input.get("market", "")).upper()
        if market not in STAGE1_GAME_MARKETS:
            raise SharedGameEngineError(f"unsupported Stage 1 game market: {market}")

        game_id = str(model_input.get("game_id", ""))
        if not game_id:
            raise SharedGameEngineError("game_id required")
        away_mean = _finite_positive(model_input.get("away_mean_runs"), "away_mean_runs")
        home_mean = _finite_positive(model_input.get("home_mean_runs"), "home_mean_runs")
        simulations = _simulation_count(
            model_input.get("simulations", V8_PRIMARY_GAME_DEFAULT_SIMULATIONS),
            minimum=minimum_simulations,
        )
        feature_source_hash = model_input.get("feature_source_hash")

        stochastic_identity = {
            "engine": V7_DISTRIBUTION_VERSION,
            "game_id": game_id,
            "away_mean_runs": away_mean,
            "home_mean_runs": home_mean,
            "feature_source_hash": feature_source_hash,
        }
        game_build_hash = canonical_json_sha256(stochastic_identity)
        model_input_hash = canonical_json_sha256({
            **stochastic_identity,
            "simulations": simulations,
        })

        cached = cache.get(model_input_hash)
        if cached is None:
            distribution = simulator(
                away_mean_runs=away_mean,
                home_mean_runs=home_mean,
                total_line=0.0,
                simulations=simulations,
                build_hash=game_build_hash,
                first_inning_share=DEFAULT_FIRST_INNING_SHARE,
                first_inning_dispersion_r=DEFAULT_FIRST_INNING_DISPERSION_R,
                extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
            )
            distribution_sha256 = score_distribution_sha256(distribution)
            cache[model_input_hash] = (distribution, distribution_sha256)
        else:
            distribution, distribution_sha256 = cached

        readout = read_game_probability(
            {
                "joint_score_pmf": distribution.joint_score_pmf,
                "result_sha256": distribution_sha256,
            },
            market=market,
            line=model_input.get("line"),
            side=str(model_input.get("side", "")),
            team_side=model_input.get("team_side"),
        )
        return {
            "game_id": model_input.get("game_id"),
            "market": model_input.get("market"),
            "entity_id": model_input.get("entity_id"),
            "line": model_input.get("line"),
            "side": model_input.get("side"),
            "model_p": readout.probability,
            "push_p": readout.push_probability,
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution_sha256,
            "readout_sha256": readout.readout_sha256,
            "readout_version": readout.readout_version,
            "engine_version": V7_DISTRIBUTION_VERSION,
            "seed_policy": distribution.seed_policy,
            "mc_paths": distribution.simulations,
        }

    return engine
