"""Transparent NFL anytime-TD role model.

Produces an upstream TD estimate from auditable workload/red-zone inputs. The
structure adapts disclosed concepts from the user's MySpariEdge Touchdown Picks
materials (workload, goal-line role, close-range targets, game environment) but
uses no proprietary formula, hidden coefficient, or copied weight.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
import random
from typing import Any, Mapping


class NflTdRoleError(ValueError):
    pass


@dataclass(frozen=True)
class TdRoleEstimate:
    player: str
    game_id: str
    estimate_p: float
    expected_team_tds: float
    rushing_td_share: float
    receiving_td_share: float
    n_sims: int
    seed: int


def _num(row: Mapping[str, Any], key: str, *, low: float = 0.0, high: float | None = None) -> float:
    try:
        x = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise NflTdRoleError(f"TD_ROLE_REQUIRED:{key}") from exc
    if not isfinite(x) or x < low or (high is not None and x > high):
        raise NflTdRoleError(f"TD_ROLE_RANGE:{key}")
    return x


def estimate_anytime_td(payload: Mapping[str, Any], *, n_sims: int = 20_000, seed: int = 21) -> TdRoleEstimate:
    """Estimate P(any TD) from team scoring environment and player scoring shares.

    Inputs are expected to be PIT-safe upstream projections, not post-kickoff
    observations. Goal-line/close-target shares are explicit role features.
    """
    player = str(payload.get("player", "")).strip()
    game_id = str(payload.get("game_id", "")).strip()
    if not player or not game_id:
        raise NflTdRoleError("TD_ROLE_IDENTITY_INCOMPLETE")
    if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
        raise NflTdRoleError("TD_ROLE_N_SIMS_INVALID")

    expected_team_tds = _num(payload, "expected_team_tds", high=10.0)
    rush_share = _num(payload, "rush_share", high=1.0)
    target_share = _num(payload, "target_share", high=1.0)
    goal_line_carry_share = _num(payload, "goal_line_carry_share", high=1.0)
    close_target_share = _num(payload, "close_target_share", high=1.0)
    rush_td_mix = _num(payload, "team_rush_td_mix", high=1.0)
    rec_td_mix = 1.0 - rush_td_mix

    # Transparent role blend: ordinary workload and scoring-zone workload receive
    # equal weight. This is a research assumption to validate, not a fitted truth.
    rushing_td_share = min(1.0, 0.5 * rush_share + 0.5 * goal_line_carry_share)
    receiving_td_share = min(1.0, 0.5 * target_share + 0.5 * close_target_share)

    context = payload.get("context") or {}
    if not isinstance(context, Mapping):
        raise NflTdRoleError("TD_ROLE_CONTEXT_INVALID")
    availability = float(context.get("availability_multiplier", 1.0))
    matchup = float(context.get("matchup_multiplier", 1.0))
    scoring = float(context.get("scoring_environment_multiplier", 1.0))
    for name, value in (("availability_multiplier", availability), ("matchup_multiplier", matchup), ("scoring_environment_multiplier", scoring)):
        if not isfinite(value) or value < 0.0 or value > 2.0:
            raise NflTdRoleError(f"TD_ROLE_CONTEXT_RANGE:{name}")

    player_td_rate = (
        rush_td_mix * rushing_td_share + rec_td_mix * receiving_td_share
    ) * availability * matchup
    team_lambda = expected_team_tds * scoring

    # Simulate team TD count, then allocate each score to the player according to
    # the role-derived rate. Deterministic seed makes repeated RUN IT reproducible.
    rng = random.Random(int(seed))
    hits = 0
    for _ in range(int(n_sims)):
        # Knuth Poisson; team TD means are small in ordinary NFL ranges.
        limit = exp(-team_lambda)
        product = 1.0
        team_tds = -1
        while product > limit:
            team_tds += 1
            product *= rng.random()
        scored = any(rng.random() < player_td_rate for _ in range(max(0, team_tds)))
        hits += int(scored)

    return TdRoleEstimate(
        player=player,
        game_id=game_id,
        estimate_p=hits / float(n_sims),
        expected_team_tds=team_lambda,
        rushing_td_share=rushing_td_share,
        receiving_td_share=receiving_td_share,
        n_sims=int(n_sims),
        seed=int(seed),
    )
