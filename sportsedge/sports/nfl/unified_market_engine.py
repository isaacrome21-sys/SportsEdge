"""Unified NFL research market engine.

One frozen score distribution is the source of truth for game markets and for
the sampled score paths that drive QB/RB/WR prop workloads.  Sportsbook lines
enter only at the final pricing step; player-role inputs remain market blind.

This is a research challenger.  It does not change the frozen Attempt-9 owner,
does not claim the discrete-v2 holdout passed, and grants no Truth-Gate,
OFFICIAL, promotion, or staking authority.
"""
from __future__ import annotations

from bisect import bisect_left
from math import isfinite
import random
from typing import Any, Mapping, Sequence

from sportsedge.nfl_coherent_team_props import simulate_team_on_game_paths
from sportsedge.nfl_coherent_team_scoring import simulate_coherent_team_scoring_paths
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError
from sportsedge.nfl_score_td_composition import (
    NflScoreTdCompositionError,
    attach_team_tds_to_score_paths,
)
from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior
from sportsedge.sports.nfl.discrete_v2 import (
    load_freeze,
    means_from_attempt9,
    score_grid,
)

SCHEMA = "SPORTSEDGE_NFL_UNIFIED_RESEARCH_MARKET_ENGINE_V1"
SCORE_PATH_COUPLING = "UNIFIED_NFL_SCORE_PATH_PACE_ONLY_V1"
PACE_EXPONENT = 0.35
PACE_MIN = 0.75
PACE_MAX = 1.25

GAME_MARKETS = frozenset({"moneyline", "spread", "total", "team_total"})
QB_PROP_MARKETS = frozenset({
    "pass_attempts", "completions", "passing_yards", "pass_tds",
    "interceptions", "rush_attempts", "rushing_yards", "anytime_tds",
})
SKILL_PROP_MARKETS = frozenset({
    "rush_attempts", "rushing_yards", "receptions", "receiving_yards",
    "rush_receiving_yards", "receiving_tds", "rushing_tds", "anytime_tds",
})
TD_PROP_MARKETS = frozenset({
    "pass_tds", "receiving_tds", "rushing_tds", "anytime_tds",
})


class UnifiedNflModelError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise UnifiedNflModelError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise UnifiedNflModelError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise UnifiedNflModelError(f"{field}:NONFINITE")
    return out


def _probability_row(*, wins: float, losses: float, pushes: float) -> dict[str, Any]:
    total = wins + losses + pushes
    if total <= 0:
        raise UnifiedNflModelError("EMPTY_PROBABILITY_MASS")
    p_win = wins / total
    p_loss = losses / total
    p_push = pushes / total
    no_push = p_win + p_loss
    conditional = p_win / no_push if no_push > 0 else None
    fair = None
    if conditional is not None and 0.0 < conditional < 1.0:
        fair = (
            -100.0 * conditional / (1.0 - conditional)
            if conditional >= 0.5
            else 100.0 * (1.0 - conditional) / conditional
        )
    return {
        "estimate_p": p_win,
        "loss_p": p_loss,
        "push_p": p_push,
        "conditional_win_probability": conditional,
        "fair_american": fair,
    }


def _grid_mass(
    grid: Sequence[Sequence[float]],
    predicate,
) -> tuple[float, float, float]:
    win = loss = push = 0.0
    for home, row in enumerate(grid):
        for away, probability in enumerate(row):
            verdict = predicate(home, away)
            if verdict > 0:
                win += probability
            elif verdict < 0:
                loss += probability
            else:
                push += probability
    return win, loss, push


def price_game_market(
    grid: Sequence[Sequence[float]],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Price one game contract directly from the frozen score grid."""
    market = str(request.get("market") or "").strip().lower()
    selection = str(request.get("selection") or "").strip().lower()
    if market not in GAME_MARKETS:
        raise UnifiedNflModelError("GAME_MARKET_UNSUPPORTED")

    if market == "moneyline":
        if selection not in {"home", "away"}:
            raise UnifiedNflModelError("MONEYLINE_SELECTION_INVALID")

        def verdict(home: int, away: int) -> int:
            if home == away:
                return 0
            home_won = home > away
            selected_won = home_won if selection == "home" else not home_won
            return 1 if selected_won else -1

        line = None
    elif market == "spread":
        if selection not in {"home", "away"}:
            raise UnifiedNflModelError("SPREAD_SELECTION_INVALID")
        line = _num(request.get("line"), "line")

        def verdict(home: int, away: int) -> int:
            home_result = (home - away) + line
            if abs(home_result) <= 1e-12:
                return 0
            home_cover = home_result > 0
            selected_cover = home_cover if selection == "home" else not home_cover
            return 1 if selected_cover else -1

    elif market == "total":
        if selection not in {"over", "under"}:
            raise UnifiedNflModelError("TOTAL_SELECTION_INVALID")
        line = _num(request.get("line"), "line")

        def verdict(home: int, away: int) -> int:
            result = (home + away) - line
            if abs(result) <= 1e-12:
                return 0
            over = result > 0
            selected = over if selection == "over" else not over
            return 1 if selected else -1

    else:
        if selection not in {"over", "under"}:
            raise UnifiedNflModelError("TEAM_TOTAL_SELECTION_INVALID")
        side = str(request.get("team") or "").strip().lower()
        if side not in {"home", "away"}:
            raise UnifiedNflModelError("TEAM_TOTAL_SIDE_INVALID")
        line = _num(request.get("line"), "line")

        def verdict(home: int, away: int) -> int:
            score = home if side == "home" else away
            result = score - line
            if abs(result) <= 1e-12:
                return 0
            over = result > 0
            selected = over if selection == "over" else not over
            return 1 if selected else -1

    wins, losses, pushes = _grid_mass(grid, verdict)
    return {
        "market": market,
        "selection": selection,
        "team": request.get("team"),
        "line": line,
        **_probability_row(wins=wins, losses=losses, pushes=pushes),
        "status": "PRICED_RESEARCH",
    }


def _flat_grid(
    grid: Sequence[Sequence[float]],
) -> tuple[list[tuple[int, int]], list[float]]:
    outcomes: list[tuple[int, int]] = []
    cumulative: list[float] = []
    running = 0.0
    for home, row in enumerate(grid):
        for away, probability in enumerate(row):
            p = _num(probability, "score_probability")
            if p < 0:
                raise UnifiedNflModelError("NEGATIVE_SCORE_PROBABILITY")
            if p == 0:
                continue
            running += p
            outcomes.append((home, away))
            cumulative.append(running)
    if not outcomes or running <= 0:
        raise UnifiedNflModelError("SCORE_GRID_EMPTY")
    cumulative[-1] = 1.0
    return outcomes, cumulative


def sample_score_paths(
    grid: Sequence[Sequence[float]],
    *,
    n_sims: int,
    seed: int,
) -> list[dict[str, Any]]:
    if isinstance(n_sims, bool) or not isinstance(n_sims, int) or n_sims <= 0:
        raise UnifiedNflModelError("N_SIMS_POSITIVE_INTEGER_REQUIRED")
    outcomes, cumulative = _flat_grid(grid)
    rng = random.Random(int(seed))
    rows: list[dict[str, Any]] = []
    for simulation_id in range(n_sims):
        draw = rng.random()
        index = min(bisect_left(cumulative, draw), len(outcomes) - 1)
        home, away = outcomes[index]
        rows.append({
            "simulation_id": simulation_id,
            "home_score": home,
            "away_score": away,
        })
    return rows


def _pace_multiplier(path_total: float, expected_total: float) -> float:
    """Damped score-path coupling; never changes pass/rush mix.

    This keeps player volume correlated with the sampled scoring environment
    without inventing an unfitted lead/trail pass-vs-rush response.
    """
    baseline = max(1.0, expected_total)
    observed = max(1.0, path_total)
    value = (observed / baseline) ** PACE_EXPONENT
    return min(PACE_MAX, max(PACE_MIN, value))


def _team_states(
    score_paths: Sequence[Mapping[str, Any]],
    *,
    side: str,
    expected_total: float,
    pass_td_share: float | None = None,
) -> list[dict[str, Any]]:
    side = str(side).lower()
    if side not in {"home", "away"}:
        raise UnifiedNflModelError("TEAM_SIDE_INVALID")
    out: list[dict[str, Any]] = []
    for path in score_paths:
        home = int(path["home_score"])
        away = int(path["away_score"])
        pace = _pace_multiplier(home + away, expected_total)
        state: dict[str, Any] = {
            "script_source": SCORE_PATH_COUPLING,
            "pass_multiplier": pace,
            "rush_multiplier": pace,
        }
        td_key = f"{side}_team_tds"
        if td_key in path:
            state["team_tds"] = int(path[td_key])
            if pass_td_share is None:
                raise UnifiedNflModelError("PASS_TD_SHARE_REQUIRED_FOR_TD_PROPS")
            share = _num(pass_td_share, "pass_td_share")
            if not 0.0 <= share <= 1.0:
                raise UnifiedNflModelError("PASS_TD_SHARE_OUT_OF_RANGE")
            state["pass_td_share"] = share
        out.append(state)
    return out


def _player_name(payload: Mapping[str, Any]) -> str:
    name = str(payload.get("player") or "").strip()
    if not name:
        raise UnifiedNflModelError("PLAYER_IDENTITY_REQUIRED")
    return name


def _team_contract(team_model: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    if not isinstance(team_model, Mapping):
        raise UnifiedNflModelError("TEAM_MODEL_REQUIRED")
    qb = team_model.get("qb")
    skills = team_model.get("skill_players")
    if not isinstance(qb, Mapping):
        raise UnifiedNflModelError("TEAM_QB_REQUIRED")
    if not isinstance(skills, Sequence) or isinstance(skills, (str, bytes, bytearray)) or not skills:
        raise UnifiedNflModelError("TEAM_SKILL_PLAYERS_REQUIRED")
    skill_rows = [row for row in skills if isinstance(row, Mapping)]
    if len(skill_rows) != len(skills):
        raise UnifiedNflModelError("TEAM_SKILL_PLAYER_OBJECT_REQUIRED")
    qb_name = _player_name(qb)
    names = [_player_name(row) for row in skill_rows]
    if qb_name in names or len(set(names)) != len(names):
        raise UnifiedNflModelError("TEAM_PLAYER_IDENTITY_DUPLICATE")
    return qb, skill_rows


def _team_needs_td(requests: Sequence[Mapping[str, Any]], side: str) -> bool:
    for request in requests:
        if str(request.get("team") or "").strip().lower() != side:
            continue
        if str(request.get("market") or "").strip().lower() in TD_PROP_MARKETS:
            return True
    return False


def _simulate_team(
    *,
    side: str,
    team_model: Mapping[str, Any] | None,
    score_paths: Sequence[Mapping[str, Any]],
    expected_total: float,
    needs_td: bool,
    seed: int,
) -> list[dict[str, Any]]:
    qb, skills = _team_contract(team_model)
    states = _team_states(
        score_paths,
        side=side,
        expected_total=expected_total,
        pass_td_share=team_model.get("pass_td_share") if needs_td else None,
    )
    if needs_td:
        return simulate_coherent_team_scoring_paths(qb, skills, states, seed=seed)
    return simulate_team_on_game_paths(qb, skills, states, seed=seed)


def _find_player_draws(
    team_paths: Sequence[Mapping[str, Any]],
    *,
    qb_name: str,
    player: str,
    market: str,
    td_paths: bool,
) -> list[Mapping[str, Any]]:
    if player == qb_name:
        if market not in QB_PROP_MARKETS:
            raise UnifiedNflModelError("QB_PROP_MARKET_UNSUPPORTED")
        return [path["qb"] for path in team_paths]

    if market not in SKILL_PROP_MARKETS:
        raise UnifiedNflModelError("SKILL_PROP_MARKET_UNSUPPORTED")
    bucket = "players" if td_paths else "receivers"
    out: list[Mapping[str, Any]] = []
    for path in team_paths:
        players = path.get(bucket)
        if not isinstance(players, Mapping) or player not in players:
            raise UnifiedNflModelError("PROP_PLAYER_NOT_IN_TEAM_MODEL")
        out.append(players[player])
    return out


def price_prop_market(
    draws: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    market = str(request.get("market") or "").strip().lower()
    selection = str(request.get("selection") or "").strip().lower()
    player = str(request.get("player") or "").strip()
    if not player:
        raise UnifiedNflModelError("PROP_PLAYER_REQUIRED")
    if selection not in {"over", "under"}:
        raise UnifiedNflModelError("PROP_SELECTION_INVALID")
    line = _num(request.get("line"), "line")
    if not draws:
        raise UnifiedNflModelError("PROP_DRAWS_EMPTY")
    win = loss = push = 0
    for draw in draws:
        if market not in draw:
            raise UnifiedNflModelError("PROP_MARKET_MISSING_FROM_DRAW")
        value = _num(draw[market], market)
        if abs(value - line) <= 1e-12:
            push += 1
        else:
            over = value > line
            selected = over if selection == "over" else not over
            if selected:
                win += 1
            else:
                loss += 1
    return {
        "market": market,
        "selection": selection,
        "player": player,
        "team": request.get("team"),
        "line": line,
        **_probability_row(wins=win, losses=loss, pushes=push),
        "status": "PRICED_RESEARCH",
    }


def run_unified_nfl_model(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    attempt9_margin: float,
    attempt9_total: float,
    game_markets: Sequence[Mapping[str, Any]] = (),
    prop_markets: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: ScoringCompositionPrior | None = None,
    n_sims: int = 20000,
    seed: int = 21,
) -> dict[str, Any]:
    """Run one coherent research surface for game markets and QB/RB/WR props."""
    margin = _num(attempt9_margin, "attempt9_margin")
    total = _num(attempt9_total, "attempt9_total")
    if total <= 0:
        raise UnifiedNflModelError("ATTEMPT9_TOTAL_POSITIVE_REQUIRED")
    if not str(game_id).strip() or not str(home_team).strip() or not str(away_team).strip():
        raise UnifiedNflModelError("GAME_IDENTITY_REQUIRED")
    if str(home_team).strip().upper() == str(away_team).strip().upper():
        raise UnifiedNflModelError("GAME_TEAM_IDENTITY_COLLISION")

    freeze = load_freeze()
    means = means_from_attempt9(margin, total)
    grid = score_grid(means["mean_home"], means["mean_away"], freeze)
    sampled = sample_score_paths(grid, n_sims=n_sims, seed=seed)

    game_rows: list[dict[str, Any]] = []
    for request in game_markets:
        try:
            game_rows.append(price_game_market(grid, request))
        except (UnifiedNflModelError, KeyError, TypeError, ValueError) as exc:
            game_rows.append({
                "market": request.get("market") if isinstance(request, Mapping) else None,
                "selection": request.get("selection") if isinstance(request, Mapping) else None,
                "line": request.get("line") if isinstance(request, Mapping) else None,
                "status": "NO_MODEL",
                "reason": str(exc),
            })

    prop_requests = [request for request in prop_markets if isinstance(request, Mapping)]
    home_needs_td = _team_needs_td(prop_requests, "home")
    away_needs_td = _team_needs_td(prop_requests, "away")
    any_td = home_needs_td or away_needs_td
    td_path_error: str | None = None
    score_paths = sampled
    if any_td:
        if scoring_prior is None:
            td_path_error = "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS"
        else:
            try:
                score_paths = attach_team_tds_to_score_paths(
                    sampled,
                    prior=scoring_prior,
                    seed=int(seed) ^ 0x71D,
                )
            except (NflScoreTdCompositionError, ValueError, TypeError) as exc:
                td_path_error = str(exc)

    team_paths: dict[str, list[dict[str, Any]]] = {}
    team_errors: dict[str, str] = {}
    for side, model, needs_td, side_seed in (
        ("home", home_model, home_needs_td, int(seed) ^ 0x484F4D45),
        ("away", away_model, away_needs_td, int(seed) ^ 0x41574159),
    ):
        if not any(str(request.get("team") or "").lower() == side for request in prop_requests):
            continue
        if needs_td and td_path_error is not None:
            # Non-TD props for this team can still be produced from the same score
            # paths; TD requests will fail separately below.
            needs_td_for_sim = False
        else:
            needs_td_for_sim = needs_td
        try:
            team_paths[side] = _simulate_team(
                side=side,
                team_model=model,
                score_paths=score_paths if needs_td_for_sim else sampled,
                expected_total=total,
                needs_td=needs_td_for_sim,
                seed=side_seed,
            )
        except (UnifiedNflModelError, NflPropSimulationError, KeyError, TypeError, ValueError) as exc:
            team_errors[side] = str(exc)

    prop_rows: list[dict[str, Any]] = []
    for request in prop_requests:
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
            prop_rows.append({**base, "status": "NO_MODEL", "reason": "PROP_TEAM_SIDE_REQUIRED"})
            continue
        if market in TD_PROP_MARKETS and td_path_error is not None:
            prop_rows.append({**base, "status": "NO_MODEL", "reason": td_path_error})
            continue
        if side in team_errors:
            prop_rows.append({**base, "status": "NO_MODEL", "reason": team_errors[side]})
            continue
        try:
            team_model = home_model if side == "home" else away_model
            qb, _skills = _team_contract(team_model)
            qb_name = _player_name(qb)
            td_paths = (home_needs_td if side == "home" else away_needs_td) and td_path_error is None
            draws = _find_player_draws(
                team_paths[side],
                qb_name=qb_name,
                player=player,
                market=market,
                td_paths=td_paths,
            )
            prop_rows.append(price_prop_market(draws, request))
        except (UnifiedNflModelError, NflPropSimulationError, KeyError, TypeError, ValueError) as exc:
            prop_rows.append({**base, "status": "NO_MODEL", "reason": str(exc)})

    return {
        "schema": SCHEMA,
        "game_id": str(game_id),
        "home_team": str(home_team),
        "away_team": str(away_team),
        "attempt9_raw": {"margin": margin, "total": total},
        "score_means": means,
        "score_distribution": {
            "family": freeze["family"],
            "freeze_sha256": freeze["artifact_sha256"],
            "sampled_paths": n_sims,
            "seed": int(seed),
        },
        "workload_coupling": {
            "identity": SCORE_PATH_COUPLING,
            "pace_exponent": PACE_EXPONENT,
            "pace_bounds": [PACE_MIN, PACE_MAX],
            "lead_trail_pass_rush_adjustment": False,
            "note": "Sampled score total moves overall workload only; pass/rush mix remains unchanged until a fitted script layer earns use.",
        },
        "game_markets": game_rows,
        "prop_markets": prop_rows,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "changes_attempt9_owner": False,
            "discrete_v2_holdout_pass_claimed": False,
            "truth_gate_authority": False,
            "official_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }


__all__ = [
    "GAME_MARKETS",
    "QB_PROP_MARKETS",
    "SKILL_PROP_MARKETS",
    "TD_PROP_MARKETS",
    "UnifiedNflModelError",
    "price_game_market",
    "price_prop_market",
    "run_unified_nfl_model",
    "sample_score_paths",
]
