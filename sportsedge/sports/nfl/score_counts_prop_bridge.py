"""Player-prop bridge from NFL_SCORE_COUNTS_G1 score paths.

The score-count candidate owns the game score environment. Existing PIT-safe
player role models own player workload/efficiency. This module couples them
without using sportsbook lines to create either model distribution.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.nfl_coherent_team_props import simulate_team_on_game_paths
from sportsedge.nfl_coherent_team_scoring import simulate_coherent_team_scoring_paths
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError
from sportsedge.nfl_score_td_composition import (
    NflScoreTdCompositionError,
    attach_team_tds_to_score_paths,
)
from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior
from sportsedge.sports.nfl.score_counts_market_bridge import (
    score_count_component_paths,
    score_count_paths,
    score_count_prediction_game,
)
from sportsedge.sports.nfl.unified_market_engine import (
    QB_PROP_MARKETS,
    SKILL_PROP_MARKETS,
    TD_PROP_MARKETS,
    price_prop_market,
)

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_PROP_BRIDGE_V1"
SCRIPT_SOURCE = "NFL_SCORE_COUNTS_G1_SCORE_PATH_PACE_V1"
PACE_EXPONENT = 0.35
PACE_MIN = 0.75
PACE_MAX = 1.25


class ScoreCountPropBridgeError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ScoreCountPropBridgeError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountPropBridgeError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise ScoreCountPropBridgeError(f"{field}:NONFINITE")
    return out


def _name(row: Mapping[str, Any]) -> str:
    value = str(row.get("player") or "").strip()
    if not value:
        raise ScoreCountPropBridgeError("PLAYER_IDENTITY_REQUIRED")
    return value


def _team_contract(team_model: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    if not isinstance(team_model, Mapping):
        raise ScoreCountPropBridgeError("TEAM_MODEL_REQUIRED")
    qb = team_model.get("qb")
    skills = team_model.get("skill_players")
    if not isinstance(qb, Mapping):
        raise ScoreCountPropBridgeError("TEAM_QB_REQUIRED")
    if not isinstance(skills, Sequence) or isinstance(skills, (str, bytes, bytearray)) or not skills:
        raise ScoreCountPropBridgeError("TEAM_SKILL_PLAYERS_REQUIRED")
    skill_rows = [row for row in skills if isinstance(row, Mapping)]
    if len(skill_rows) != len(skills):
        raise ScoreCountPropBridgeError("TEAM_SKILL_PLAYER_OBJECT_REQUIRED")
    qb_name = _name(qb)
    names = [_name(row) for row in skill_rows]
    if qb_name in names or len(names) != len(set(names)):
        raise ScoreCountPropBridgeError("TEAM_PLAYER_IDENTITY_DUPLICATE")
    return qb, skill_rows


def _stabilized_volume_value(row: Mapping[str, Any], key: str) -> float:
    """Mirror the frozen V1 volume shrinkage for one field, permitting signed YPR."""
    prior = row.get("role_prior")
    trailing = row.get("trailing") or {}
    if not isinstance(prior, Mapping) or not isinstance(trailing, Mapping):
        raise ScoreCountPropBridgeError("ROLE_OBJECT_REQUIRED")
    if key not in prior:
        raise ScoreCountPropBridgeError(f"ROLE_PRIOR_MISSING:{key}")
    p = _num(prior[key], key)
    o = p if key not in trailing else _num(trailing[key], key)
    n = max(0.0, _num(row.get("sample_size", 0), "sample_size"))
    strength = 8.0
    return (strength * p + n * o) / (strength + n)


def _regularize_nonpositive_receiving_efficiency(
    team_model: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]]]:
    """Repair only isolated nonpositive receiver YPR before frozen shared V1 runs.

    The source/model payload is copied.  Signed receiving efficiency is evaluated
    with the same volume shrinkage as the frozen shared role layer, but no global
    shared-model contract is changed.  If at least one receiver has a positive
    expectation, isolated nonpositive receivers inherit the catch-weighted
    positive team pool.  If the whole pool is unusable, no value is invented and
    the downstream team simulation still fails closed.
    """
    if not isinstance(team_model, Mapping):
        return team_model, []
    model = deepcopy(dict(team_model))
    skills = model.get("skill_players")
    if not isinstance(skills, Sequence) or isinstance(skills, (str, bytes, bytearray)):
        return model, []

    rows = [row for row in skills if isinstance(row, Mapping)]
    positive: list[tuple[float, float]] = []
    stabilized: dict[str, tuple[float, float]] = {}
    for row in rows:
        player = _name(row)
        ypr = _stabilized_volume_value(row, "receiving_yards_per_reception")
        targets = max(0.0, _stabilized_volume_value(row, "targets"))
        catch_rate = _stabilized_volume_value(row, "catch_rate")
        if catch_rate < 0 or catch_rate > 1:
            raise ScoreCountPropBridgeError(f"ROLE_VALUE_INVALID:catch_rate:{player}")
        catches = targets * catch_rate
        stabilized[player] = (ypr, catches)
        if ypr > 0:
            positive.append((ypr, max(catches, 1e-6)))

    if not positive:
        return model, []

    denom = sum(weight for _, weight in positive)
    fallback = sum(value * weight for value, weight in positive) / denom
    if not isfinite(fallback) or fallback <= 0:
        return model, []

    adjusted: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for raw in rows:
        row = deepcopy(dict(raw))
        player = _name(row)
        ypr, catches = stabilized[player]
        if ypr <= 0:
            prior = dict(row.get("role_prior") or {})
            trailing = dict(row.get("trailing") or {})
            prior["receiving_yards_per_reception"] = fallback
            if "receiving_yards_per_reception" in trailing:
                trailing["receiving_yards_per_reception"] = fallback
            row["role_prior"] = prior
            row["trailing"] = trailing
            audit.append({
                "player": player,
                "observed_stabilized_ypr": ypr,
                "expected_catches_weight": catches,
                "replacement_ypr": fallback,
                "method": "CATCH_WEIGHTED_POSITIVE_TEAM_POOL",
            })
        adjusted.append(row)
    model["skill_players"] = adjusted
    return model, audit


def _pace(path_total: float, expected_total: float) -> float:
    baseline = max(1.0, expected_total)
    observed = max(1.0, path_total)
    value = (observed / baseline) ** PACE_EXPONENT
    return min(PACE_MAX, max(PACE_MIN, value))


def _states(
    paths: Sequence[Mapping[str, Any]],
    *,
    side: str,
    expected_total: float,
    pass_td_share: float | None = None,
    include_tds: bool = False,
) -> list[dict[str, Any]]:
    if side not in {"home", "away"}:
        raise ScoreCountPropBridgeError("TEAM_SIDE_INVALID")
    out: list[dict[str, Any]] = []
    for path in paths:
        home = int(path["home_score"])
        away = int(path["away_score"])
        pace = _pace(home + away, expected_total)
        state: dict[str, Any] = {
            "script_source": SCRIPT_SOURCE,
            "pass_multiplier": pace,
            "rush_multiplier": pace,
        }
        if include_tds:
            td_key = f"{side}_team_tds"
            if td_key not in path:
                raise ScoreCountPropBridgeError("DIRECT_TD_PATH_REQUIRED")
            if pass_td_share is None:
                raise ScoreCountPropBridgeError("PASS_TD_SHARE_REQUIRED_FOR_TD_PROPS")
            share = _num(pass_td_share, "pass_td_share")
            if not 0.0 <= share <= 1.0:
                raise ScoreCountPropBridgeError("PASS_TD_SHARE_OUT_OF_RANGE")
            state["team_tds"] = int(path[td_key])
            state["pass_td_share"] = share
        out.append(state)
    return out


def _needs_td(requests: Sequence[Mapping[str, Any]], side: str) -> bool:
    return any(
        str(row.get("team") or "").strip().lower() == side
        and str(row.get("market") or "").strip().lower() in TD_PROP_MARKETS
        for row in requests
    )


def _needs_non_td(requests: Sequence[Mapping[str, Any]], side: str) -> bool:
    return any(
        str(row.get("team") or "").strip().lower() == side
        and str(row.get("market") or "").strip().lower() not in TD_PROP_MARKETS
        for row in requests
    )


def _find_draws(
    team_paths: Sequence[Mapping[str, Any]],
    *,
    qb_name: str,
    player: str,
    market: str,
    scoring_paths: bool,
) -> list[Mapping[str, Any]]:
    if player == qb_name:
        if market not in QB_PROP_MARKETS:
            raise ScoreCountPropBridgeError("QB_PROP_MARKET_UNSUPPORTED")
        return [row["qb"] for row in team_paths]
    if market not in SKILL_PROP_MARKETS:
        raise ScoreCountPropBridgeError("SKILL_PROP_MARKET_UNSUPPORTED")
    bucket = "players" if scoring_paths else "receivers"
    out: list[Mapping[str, Any]] = []
    for row in team_paths:
        players = row.get(bucket)
        if not isinstance(players, Mapping) or player not in players:
            raise ScoreCountPropBridgeError("PROP_PLAYER_NOT_IN_TEAM_MODEL")
        out.append(players[player])
    return out


def price_score_count_props_from_paths(
    *,
    game_id: str,
    score_paths: Sequence[Mapping[str, Any]],
    prop_requests: Sequence[Mapping[str, Any]],
    home_model: Mapping[str, Any] | None,
    away_model: Mapping[str, Any] | None,
    scoring_prior: ScoringCompositionPrior | None = None,
    seed: int = 21,
) -> dict[str, Any]:
    if not score_paths:
        raise ScoreCountPropBridgeError("SCORE_PATHS_REQUIRED")
    requests = [dict(row) for row in prop_requests if isinstance(row, Mapping)]
    if len(requests) != len(prop_requests):
        raise ScoreCountPropBridgeError("PROP_REQUEST_OBJECT_REQUIRED")

    totals = [_num(row["home_score"], "home_score") + _num(row["away_score"], "away_score") for row in score_paths]
    expected_total = sum(totals) / len(totals)

    home_needs_td = _needs_td(requests, "home")
    away_needs_td = _needs_td(requests, "away")
    td_error: str | None = None
    td_paths: Sequence[Mapping[str, Any]] = score_paths
    if home_needs_td or away_needs_td:
        direct_flags = [
            "home_team_tds" in row and "away_team_tds" in row
            for row in score_paths
        ]
        if any(direct_flags) and not all(direct_flags):
            td_error = "DIRECT_TD_PATHS_INCOMPLETE"
        elif direct_flags and all(direct_flags):
            td_paths = score_paths
        elif scoring_prior is None:
            td_error = "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS"
        else:
            try:
                td_paths = attach_team_tds_to_score_paths(
                    score_paths,
                    prior=scoring_prior,
                    seed=int(seed) ^ 0x71D,
                )
            except (NflScoreTdCompositionError, ValueError, TypeError) as exc:
                td_error = str(exc)

    team_paths: dict[str, list[dict[str, Any]]] = {}
    team_scoring: dict[str, bool] = {}
    team_errors: dict[str, str] = {}
    team_models: dict[str, Mapping[str, Any] | None] = {}
    efficiency_regularization: dict[str, list[dict[str, Any]]] = {}
    for side, model, needs_td, side_seed in (
        ("home", home_model, home_needs_td, int(seed) ^ 0x484F4D45),
        ("away", away_model, away_needs_td, int(seed) ^ 0x41574159),
    ):
        if not any(str(row.get("team") or "").strip().lower() == side for row in requests):
            continue
        if needs_td and td_error is not None and not _needs_non_td(requests, side):
            # Every request for this side is already locally unpriceable for a
            # TD-path prerequisite. Do not manufacture a broader team failure.
            continue
        try:
            model, regularization = _regularize_nonpositive_receiving_efficiency(model)
            team_models[side] = model
            efficiency_regularization[side] = regularization
            qb, skills = _team_contract(model)
            use_scoring = bool(needs_td and td_error is None)
            states = _states(
                td_paths if use_scoring else score_paths,
                side=side,
                expected_total=expected_total,
                pass_td_share=model.get("pass_td_share") if use_scoring else None,
                include_tds=use_scoring,
            )
            if use_scoring:
                team_paths[side] = simulate_coherent_team_scoring_paths(
                    qb, skills, states, seed=side_seed
                )
            else:
                team_paths[side] = simulate_team_on_game_paths(
                    qb, skills, states, seed=side_seed
                )
            team_scoring[side] = use_scoring
        except (
            ScoreCountPropBridgeError,
            NflPropSimulationError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            team_errors[side] = str(exc)

    # A two-team player-prop board is one simulation product. If either
    # requested team cannot be simulated, do not let the surviving side create
    # a mechanically one-sided card.
    prop_board_error: str | None = None
    if team_errors:
        detail = ";".join(
            f"{side}={team_errors[side]}" for side in sorted(team_errors)
        )
        prop_board_error = f"GAME_PROP_SIMULATION_INCOMPLETE:{detail}"

    rows: list[dict[str, Any]] = []
    for request in requests:
        side = str(request.get("team") or "").strip().lower()
        market = str(request.get("market") or "").strip().lower()
        player = str(request.get("player") or "").strip()
        base = {
            "market": market or None,
            "selection": request.get("selection"),
            "player": player or None,
            "team": side or None,
            "line": request.get("line"),
        }
        if side not in {"home", "away"}:
            rows.append({**base, "status": "NO_MODEL", "reason": "PROP_TEAM_SIDE_REQUIRED"})
            continue
        if prop_board_error is not None:
            rows.append({**base, "status": "NO_MODEL", "reason": prop_board_error})
            continue
        if market in TD_PROP_MARKETS and td_error is not None:
            rows.append({**base, "status": "NO_MODEL", "reason": td_error})
            continue
        if side in team_errors:
            rows.append({**base, "status": "NO_MODEL", "reason": team_errors[side]})
            continue
        try:
            model = team_models.get(side)
            if model is None:
                model = home_model if side == "home" else away_model
            qb, _skills = _team_contract(model)
            draws = _find_draws(
                team_paths[side],
                qb_name=_name(qb),
                player=player,
                market=market,
                scoring_paths=team_scoring[side],
            )
            rows.append(price_prop_market(draws, request))
        except (
            ScoreCountPropBridgeError,
            NflPropSimulationError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            rows.append({**base, "status": "NO_MODEL", "reason": str(exc)})

    return {
        "schema": SCHEMA,
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "game_id": str(game_id),
        "score_path_count": len(score_paths),
        "expected_total_from_score_paths": expected_total,
        "prop_markets": rows,
        "prop_board_status": (
            "NOT_REQUIRED"
            if not requests
            else "NO_MODEL"
            if prop_board_error is not None
            else "AVAILABLE"
        ),
        "prop_board_error": prop_board_error,
        "team_simulation_errors": dict(sorted(team_errors.items())),
        "receiving_efficiency_regularization": {
            side: rows
            for side, rows in sorted(efficiency_regularization.items())
            if rows
        },
        "market_data_used_to_create_score_distribution": False,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": True,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }


def price_score_count_prop_markets(
    prediction: Mapping[str, Any],
    *,
    game_id: str,
    prop_requests: Sequence[Mapping[str, Any]],
    home_model: Mapping[str, Any] | None,
    away_model: Mapping[str, Any] | None,
    scoring_prior: ScoringCompositionPrior | None = None,
    seed: int = 21,
) -> dict[str, Any]:
    game = score_count_prediction_game(prediction, game_id)
    if game.get("joint_score_td_distribution") is not None:
        paths = score_count_component_paths(game)
    else:
        paths = score_count_paths(game)
    out = price_score_count_props_from_paths(
        game_id=game_id,
        score_paths=paths,
        prop_requests=prop_requests,
        home_model=home_model,
        away_model=away_model,
        scoring_prior=scoring_prior,
        seed=seed,
    )
    out["fit_artifact_sha256"] = prediction.get("fit_artifact_sha256")
    out["prediction_sha256"] = prediction.get("prediction_sha256")
    out["joint_score_distribution_sha256"] = game.get("joint_score_distribution_sha256")
    return out


__all__ = [
    "SCHEMA",
    "ScoreCountPropBridgeError",
    "price_score_count_prop_markets",
    "price_score_count_props_from_paths",
]
