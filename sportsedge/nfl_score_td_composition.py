"""Attach empirically fitted team-TD counts to existing NFL final-score paths.

A final football score does not uniquely identify touchdown count.  This module
therefore never uses score // 7 and never invents scoring-composition weights.
Sampling requires a PIT-safe ScoringCompositionPrior fitted upstream from
completed historical scoring events.  Scores absent from that fitted prior fail
closed rather than borrowing an undocumented fallback.
"""
from __future__ import annotations

import random
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior

FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american", "odds", "market_no_vig_p", "edge_probability_points",
    "ev_per_dollar", "fair_american", "sportsbook_probability",
})


class NflScoreTdCompositionError(ValueError):
    pass


def _score(row: Mapping[str, Any], key: str) -> int:
    if FORBIDDEN_MARKET_KEYS.intersection(row):
        raise NflScoreTdCompositionError("MARKET_INPUT_FORBIDDEN")
    raw = row.get(key)
    if isinstance(raw, bool):
        raise NflScoreTdCompositionError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise NflScoreTdCompositionError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED") from exc
    if not isfinite(value) or value < 0 or value != int(value):
        raise NflScoreTdCompositionError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    return int(value)


def feasible_scoring_compositions(score: int) -> list[tuple[int, int, int, int, int]]:
    """Return (TD, PAT, two-point, FG, safety) tuples that exactly make score."""
    if isinstance(score, bool) or not isinstance(score, int) or score < 0:
        raise NflScoreTdCompositionError("SCORE_NONNEGATIVE_INTEGER_REQUIRED")
    out: list[tuple[int, int, int, int, int]] = []
    for td in range(score // 6 + 1):
        for pat in range(td + 1):
            for two in range(td - pat + 1):
                subtotal = 6 * td + pat + 2 * two
                if subtotal > score:
                    continue
                rem = score - subtotal
                for safety in range(rem // 2 + 1):
                    left = rem - 2 * safety
                    if left % 3 == 0:
                        out.append((td, pat, two, left // 3, safety))
    if not out:
        raise NflScoreTdCompositionError(f"NO_FEASIBLE_SCORING_COMPOSITION:{score}")
    return out


def _empirical_choices(
    score: int, prior: ScoringCompositionPrior
) -> tuple[list[tuple[int, int, int, int, int]], list[int]]:
    if not isinstance(prior, ScoringCompositionPrior) or prior.training_rows <= 0:
        raise NflScoreTdCompositionError("FITTED_SCORING_PRIOR_REQUIRED")
    counts = prior.counts_by_score.get(score)
    if not counts:
        raise NflScoreTdCompositionError(f"FITTED_SCORE_COMPOSITION_MISSING:{score}")
    feasible = set(feasible_scoring_compositions(score))
    choices: list[tuple[int, int, int, int, int]] = []
    weights: list[int] = []
    for composition, raw_count in counts.items():
        if composition not in feasible:
            raise NflScoreTdCompositionError(
                f"FITTED_SCORE_COMPOSITION_INVALID:{score}:{composition}"
            )
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
            raise NflScoreTdCompositionError("FITTED_SCORE_COUNT_POSITIVE_INTEGER_REQUIRED")
        choices.append(composition)
        weights.append(raw_count)
    return choices, weights


def sample_td_count(
    score: int, *, prior: ScoringCompositionPrior, rng: random.Random
) -> int:
    """Sample TD count only from observed, PIT-safe exact-score compositions."""
    choices, weights = _empirical_choices(score, prior)
    return rng.choices(choices, weights=weights, k=1)[0][0]


def attach_team_tds_to_score_paths(
    simulation_rows: Sequence[Mapping[str, Any]],
    *,
    prior: ScoringCompositionPrior,
    seed: int = 21,
) -> list[dict[str, Any]]:
    """Preserve score paths and attach empirical home/away TD opportunities."""
    if not simulation_rows:
        raise NflScoreTdCompositionError("SIMULATION_ROWS_EMPTY")
    rng = random.Random(int(seed))
    out: list[dict[str, Any]] = []
    for row in simulation_rows:
        if not isinstance(row, Mapping):
            raise NflScoreTdCompositionError("SIMULATION_ROW_OBJECT_REQUIRED")
        home = _score(row, "home_score")
        away = _score(row, "away_score")
        item = dict(row)
        item["home_team_tds"] = sample_td_count(home, prior=prior, rng=rng)
        item["away_team_tds"] = sample_td_count(away, prior=prior, rng=rng)
        out.append(item)
    return out


def team_game_states(
    rows: Sequence[Mapping[str, Any]], *, team: str
) -> list[dict[str, Any]]:
    """Expose the exact shared states consumed by downstream TD allocators."""
    side = str(team).strip().lower()
    if side not in {"home", "away"}:
        raise NflScoreTdCompositionError("TEAM_SIDE_REQUIRED")
    other = "away" if side == "home" else "home"
    out = []
    for row in rows:
        own = _score(row, f"{side}_score")
        opp = _score(row, f"{other}_score")
        raw_tds = row.get(f"{side}_team_tds")
        if isinstance(raw_tds, bool):
            raise NflScoreTdCompositionError("TEAM_TDS_INTEGER_REQUIRED")
        try:
            tds = int(raw_tds)
        except (TypeError, ValueError) as exc:
            raise NflScoreTdCompositionError("TEAM_TDS_INTEGER_REQUIRED") from exc
        if tds < 0 or raw_tds != tds:
            raise NflScoreTdCompositionError("TEAM_TDS_INTEGER_REQUIRED")
        out.append({
            "team_margin": own - opp,
            "team_tds": tds,
            "pace_multiplier": row.get("pace_multiplier", 1.0),
        })
    return out
