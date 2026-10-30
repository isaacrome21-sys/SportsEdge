"""Attach plausible team-TD counts to existing NFL final-score simulation paths.

This closes a coherence gap between Game Picks-style score distributions and the
Touchdown Picks-style role allocator.  A final football score does not uniquely
identify touchdown count (field goals, PATs, two-point tries and safeties matter),
so this module never uses the invalid ``score // 7`` shortcut.  Instead it
enumerates feasible scoring decompositions and samples one deterministically.

The idea adapts the disclosed MySpariEdge/Spari Edge product separation supplied
by the user: game environment/scoring paths first, TD role/workload second, and
sportsbook economics only downstream.  The composition weights below are
transparent engineering defaults, not claimed proprietary Spari Edge weights.
"""
from __future__ import annotations

import random
from math import isfinite
from typing import Any, Mapping, Sequence

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
    # Bounds are exact and deliberately small for football-sized scores.
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


def _weight(c: tuple[int, int, int, int, int]) -> float:
    td, pat, two, fg, safety = c
    # Prefer ordinary TD+PAT and FG scoring while retaining nonzero support for
    # two-point tries and safeties. These are engineering priors, not fitted rates.
    missed_pat = max(0, td - pat - two)
    return (1.0 ** td) * (0.92 ** pat) * (0.12 ** two) * (0.55 ** fg) * (0.04 ** safety) * (0.08 ** missed_pat)


def sample_td_count(score: int, *, rng: random.Random) -> int:
    choices = feasible_scoring_compositions(score)
    weights = [_weight(c) for c in choices]
    return rng.choices(choices, weights=weights, k=1)[0][0]


def attach_team_tds_to_score_paths(
    simulation_rows: Sequence[Mapping[str, Any]], *, seed: int = 21
) -> list[dict[str, Any]]:
    """Preserve score paths and attach home/away TD opportunities one-for-one."""
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
        item["home_team_tds"] = sample_td_count(home, rng=rng)
        item["away_team_tds"] = sample_td_count(away, rng=rng)
        out.append(item)
    return out


def team_game_states(
    rows: Sequence[Mapping[str, Any]], *, team: str
) -> list[dict[str, Any]]:
    """Expose the exact shared states consumed by prop/TD allocators."""
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
        out.append({"team_margin": own - opp, "team_tds": tds, "pace_multiplier": row.get("pace_multiplier", 1.0)})
    return out
