"""Full-game total-runs distribution and the Total Runs 3-Way read-out.

This is the FULL_GAME generalization of sportsedge.period_distribution,
built for the DraftKings "Total Runs (3-Way)" market (Over / Exactly /
Under at an integer line; enumerated in the Oct 13 2026 DraftKings
catalog capture, CATALOG_MLB.md full-game list, and in the inspected
menu census as GAME_TOTAL_3_WAY, group "game", period FULL_GAME, form
BAND).

The construction is identical in kind to the F3/F7 period machinery:
each team's full-game scoring marginal is an equal blend of its own
runs-for empirical PMF and the opponent's runs-allowed empirical PMF
from actual strictly-prior completed games, optionally smoothed toward
a strictly-prior league team-runs PMF (m30, the F5/period recipe). The
two marginals form one joint (away, home) full-game score state; the
3-way read-out marginalizes it to the game total and splits the mass
into the market's three settlement cells: total above the line (OVER),
total exactly on the line (EXACTLY), total below the line (UNDER).

A 3-way bet never pushes: every final total settles exactly one
selection as a win and the other two as losses. The read-out therefore
reports push_probability 0.0 by construction and carries the EXACTLY
cell as its own probability. Read-out stabilization uses the same
Jeffreys settlement-mass posterior as the F5/period read-outs, with
the exactly mass in the third settlement category.

The period and F5 modules are deliberately NOT modified: their
distribution SHA identities are byte-sensitive for existing consumers.
This module carries its own version strings.

Research only: nothing here validates, promotes or prices anything.
Eligibility is governed by the deployment registry, consulted by the
binding layer (sportsedge.mlb_game_total_quote_binding).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_empirical_bayes import posterior_settlement_mass
from .source_lineage import canonical_json_sha256

GAME_TOTAL_3WAY_MARKET = "GAME_TOTAL_3_WAY"
GAME_TOTAL_3WAY_MARKETS = frozenset({GAME_TOTAL_3WAY_MARKET})
THREE_WAY_SIDES = ("OVER", "EXACTLY", "UNDER")
MIN_HISTORY_GAMES = 10
LEAGUE_PRIOR_STRENGTH = 30
MIN_LEAGUE_HALVES = 200


def distribution_version(*, league_prior_strength: int = LEAGUE_PRIOR_STRENGTH) -> str:
    if league_prior_strength == LEAGUE_PRIOR_STRENGTH:
        return "mlb_game_total_empirical_state_v1_m30_league_prior_full_game"
    return "mlb_game_total_empirical_state_v1_candidate_full_game"


def readout_version() -> str:
    return "mlb_game_total_3way_readout_v1_jeffreys"


class GameTotalDistributionError(ValueError):
    pass


@dataclass(frozen=True)
class GameTotalDistribution:
    away_history_games: int
    home_history_games: int
    joint_score_pmf: dict[str, float]
    distribution_sha256: str
    distribution_version: str


@dataclass(frozen=True)
class GameTotalReadout:
    market: str
    line: float
    side: str
    probability: float
    exactly_probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str


def _count_pool(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GameTotalDistributionError(f"{field} must be a sequence")
    if len(value) < MIN_HISTORY_GAMES:
        raise GameTotalDistributionError(
            f"{field} requires at least {MIN_HISTORY_GAMES} strictly-prior games"
        )
    out: list[int] = []
    for index, raw in enumerate(value):
        if isinstance(raw, bool):
            raise GameTotalDistributionError(f"{field}[{index}] must be integer >= 0")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise GameTotalDistributionError(f"{field}[{index}] must be integer >= 0") from exc
        if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
            raise GameTotalDistributionError(f"{field}[{index}] must be integer >= 0")
        out.append(int(numeric))
    return tuple(out)


def _empirical_pmf(values: tuple[int, ...]) -> dict[int, float]:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    n = len(values)
    return {key: count / n for key, count in counts.items()}


def _league_pmf(value: Any) -> dict[int, float]:
    if not isinstance(value, Mapping) or not value:
        raise GameTotalDistributionError("league_game_pmf must be a non-empty mapping")
    out: dict[int, float] = {}
    total = 0.0
    for raw_key, raw_p in value.items():
        try:
            key = int(raw_key)
            probability = float(raw_p)
        except (TypeError, ValueError) as exc:
            raise GameTotalDistributionError("league_game_pmf contains invalid state") from exc
        if key < 0 or not isfinite(probability) or probability < 0:
            raise GameTotalDistributionError("league_game_pmf contains invalid probability")
        out[key] = out.get(key, 0.0) + probability
        total += probability
    if abs(total - 1.0) > 1e-9:
        raise GameTotalDistributionError("league_game_pmf does not conserve probability")
    return out


def _smoothed_pmf(values: tuple[int, ...], league: Mapping[int, float]) -> dict[int, float]:
    counts: dict[int, float] = {}
    for value in values:
        counts[value] = counts.get(value, 0.0) + 1.0
    keys = set(counts) | set(league)
    denom = float(len(values) + LEAGUE_PRIOR_STRENGTH)
    out = {
        key: (counts.get(key, 0.0) + LEAGUE_PRIOR_STRENGTH * float(league.get(key, 0.0))) / denom
        for key in keys
    }
    if abs(sum(out.values()) - 1.0) > 1e-12:
        raise GameTotalDistributionError("smoothed game marginal does not conserve probability")
    return out


def _blend(left: dict[int, float], right: dict[int, float]) -> dict[int, float]:
    keys = set(left) | set(right)
    out = {key: 0.5 * left.get(key, 0.0) + 0.5 * right.get(key, 0.0) for key in keys}
    if abs(sum(out.values()) - 1.0) > 1e-12:
        raise GameTotalDistributionError("blended game marginal does not conserve probability")
    return out


def build_game_total_distribution(
    features: Mapping[str, Any],
    *,
    league_prior_strength: int = 0,
) -> GameTotalDistribution:
    """Build the joint full-game score state for one matchup.

    Feature arrays are strictly-prior FULL-GAME runs (final scores of
    completed games): away_game_runs_for / away_game_runs_against /
    home_game_runs_for / home_game_runs_against, plus, when the m30
    league prior is requested, league_game_pmf / league_prior_halves /
    league_prior_strength. No period state is scaled up to a full game;
    only actual final scores enter.
    """
    if not isinstance(features, Mapping):
        raise GameTotalDistributionError("game total features must be an object")
    away_for = _count_pool(features.get("away_game_runs_for"), "away_game_runs_for")
    away_against = _count_pool(features.get("away_game_runs_against"), "away_game_runs_against")
    home_for = _count_pool(features.get("home_game_runs_for"), "home_game_runs_for")
    home_against = _count_pool(features.get("home_game_runs_against"), "home_game_runs_against")
    if len(away_for) != len(away_against):
        raise GameTotalDistributionError("away game history arrays must align")
    if len(home_for) != len(home_against):
        raise GameTotalDistributionError("home game history arrays must align")
    if league_prior_strength not in {0, LEAGUE_PRIOR_STRENGTH}:
        raise GameTotalDistributionError("unsupported league prior strength")
    league_halves = 0
    league: dict[int, float] | None = None
    if league_prior_strength == LEAGUE_PRIOR_STRENGTH:
        try:
            league_halves = int(features.get("league_prior_halves"))
            league_strength = int(features.get("league_prior_strength"))
        except (TypeError, ValueError) as exc:
            raise GameTotalDistributionError("league prior identity fields required") from exc
        if league_halves < MIN_LEAGUE_HALVES:
            raise GameTotalDistributionError(
                f"league prior requires at least {MIN_LEAGUE_HALVES} team-halves"
            )
        if league_strength != LEAGUE_PRIOR_STRENGTH:
            raise GameTotalDistributionError("league prior strength drift")
        league = _league_pmf(features.get("league_game_pmf"))
        away_for_pmf = _smoothed_pmf(away_for, league)
        home_against_pmf = _smoothed_pmf(home_against, league)
        home_for_pmf = _smoothed_pmf(home_for, league)
        away_against_pmf = _smoothed_pmf(away_against, league)
    else:
        away_for_pmf = _empirical_pmf(away_for)
        home_against_pmf = _empirical_pmf(home_against)
        home_for_pmf = _empirical_pmf(home_for)
        away_against_pmf = _empirical_pmf(away_against)

    away_scoring = _blend(away_for_pmf, home_against_pmf)
    home_scoring = _blend(home_for_pmf, away_against_pmf)
    joint: dict[str, float] = {}
    for away_runs, away_p in sorted(away_scoring.items()):
        for home_runs, home_p in sorted(home_scoring.items()):
            joint[f"{away_runs},{home_runs}"] = away_p * home_p
    if abs(sum(joint.values()) - 1.0) > 1e-12:
        raise GameTotalDistributionError("game joint score PMF does not conserve probability")

    version = distribution_version(league_prior_strength=league_prior_strength)
    digest_payload: dict[str, Any] = {
        "version": version,
        "period": "FULL_GAME",
        "blend_policy": "equal_offense_opponent_allowed_empirical_marginals",
        "joint_score_pmf": joint,
    }
    if league_prior_strength == LEAGUE_PRIOR_STRENGTH:
        digest_payload["blend_policy"] = (
            "equal_offense_opponent_allowed_m30_league_smoothed_marginals")
        digest_payload["league_prior_strength"] = LEAGUE_PRIOR_STRENGTH
        digest_payload["league_prior_halves"] = int(league_halves)
        digest_payload["league_game_pmf"] = {
            str(k): float(v) for k, v in sorted(league.items())}
    digest = canonical_json_sha256(digest_payload)
    return GameTotalDistribution(
        away_history_games=len(away_for),
        home_history_games=len(home_for),
        joint_score_pmf=joint,
        distribution_sha256=digest,
        distribution_version=version,
    )


def _states(distribution: GameTotalDistribution):
    total = 0.0
    rows: list[tuple[int, int, float]] = []
    for key, raw_p in distribution.joint_score_pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away_runs = int(away_text)
            home_runs = int(home_text)
            probability = float(raw_p)
        except (TypeError, ValueError) as exc:
            raise GameTotalDistributionError("invalid game joint score state") from exc
        if away_runs < 0 or home_runs < 0 or not isfinite(probability) or probability < 0:
            raise GameTotalDistributionError("invalid game joint score state")
        total += probability
        rows.append((away_runs, home_runs, probability))
    if abs(total - 1.0) > 1e-12:
        raise GameTotalDistributionError("game joint score PMF does not conserve probability")
    return tuple(rows)


def _integer_line(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise GameTotalDistributionError("3-way total line must be a non-negative integer")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise GameTotalDistributionError("3-way total line must be a non-negative integer") from exc
    if not isfinite(out) or out < 0 or out != int(out):
        raise GameTotalDistributionError(
            "3-way total line must be a non-negative integer: the EXACTLY "
            "settlement cell exists only when the final total can land "
            "exactly on the line")
    return out


def read_game_total_probability(
    distribution: GameTotalDistribution,
    *,
    market: str,
    line: Any,
    side: str,
) -> GameTotalReadout:
    """Read one selection of the Total Runs 3-Way at an integer line.

    The three settlement cells partition the total: OVER wins strictly
    above the line, EXACTLY wins on the line, UNDER wins strictly
    below. No cell pushes, so push_probability is exactly 0.0 and the
    EXACTLY cell is reported as its own probability.
    """
    if not isinstance(distribution, GameTotalDistribution):
        raise GameTotalDistributionError("distribution must be GameTotalDistribution")
    market = str(market or "").upper()
    if market != GAME_TOTAL_3WAY_MARKET:
        raise GameTotalDistributionError(f"unsupported game total market: {market}")
    side = str(side or "").upper()
    if side not in THREE_WAY_SIDES:
        raise GameTotalDistributionError(
            f"3-way total side must be one of {THREE_WAY_SIDES}, got {side!r}")
    resolved_line = _integer_line(line)
    rows = _states(distribution)
    over_mass = sum(p for away, home, p in rows if away + home > resolved_line)
    exactly_mass = sum(p for away, home, p in rows if away + home == int(resolved_line))
    under_mass = sum(p for away, home, p in rows if away + home < resolved_line)
    if over_mass < -1e-12 or exactly_mass < -1e-12 or under_mass < -1e-12 \
            or over_mass + exactly_mass + under_mass > 1.0 + 1e-9:
        raise GameTotalDistributionError("3-way total readout probability mass invalid")

    # Same Jeffreys stabilization discipline as the F5/period readouts:
    # the score state is built from only 10-30 prior games per club, so
    # a sparse empirical state cannot manufacture near-certainty. The
    # exactly mass occupies the posterior's third settlement category;
    # unlike a two-way total, it is a real outcome here, not a push.
    posterior = posterior_settlement_mass(
        over_mass=float(over_mass),
        under_mass=float(under_mass),
        push_mass=float(exactly_mass),
        effective_n=float(min(distribution.away_history_games,
                              distribution.home_history_games)),
        has_push=True,
    )
    by_side = {
        "OVER": float(posterior["p_over"]),
        "UNDER": float(posterior["p_under"]),
        "EXACTLY": float(posterior["p_push"]),
    }
    probability = by_side[side]
    exactly_probability = by_side["EXACTLY"]

    version = readout_version()
    readout_sha = canonical_json_sha256({
        "version": version,
        "distribution_sha256": distribution.distribution_sha256,
        "market": market,
        "line": resolved_line,
        "side": side,
        "probability": float(probability),
        "exactly_probability": float(exactly_probability),
        "push_probability": 0.0,
        "raw_over_mass": float(over_mass),
        "raw_exactly_mass": float(exactly_mass),
        "raw_under_mass": float(under_mass),
        "posterior_prior": posterior["prior"],
        "effective_history_games": float(min(distribution.away_history_games,
                                             distribution.home_history_games)),
    })
    return GameTotalReadout(
        market=market,
        line=resolved_line,
        side=side,
        probability=float(probability),
        exactly_probability=float(exactly_probability),
        push_probability=0.0,
        distribution_sha256=distribution.distribution_sha256,
        readout_sha256=readout_sha,
        readout_version=version,
    )
