"""MLB game / team Total Hits: first-class intake, truthful NO_ENGINE.

DraftKings hangs a full-game Total Hits market and per-team Team
Total Hits markets (Oct 13 2026 DraftKings catalog capture,
CATALOG_MLB.md: "Total Hits O/U 14.5 (game)", "Team Total Hits per
team O/U 7.5"; the #2272 inspected-menu census carries them as
GAME_TOTAL_HITS and TEAM_TOTAL_HITS, group "game", period FULL_GAME,
forms TWO_SIDED + ALTERNATE). Until now those names resolved nowhere
on the canonical path: a captured row fell through prop routing to the
generic NO_VERIFIED_MODEL_FOR_THIS_MARKET death. This module gives
the two families first-class intake names and truthful named terminal
states. It prices NOTHING, deliberately, for two distinct reasons:

GAME_TOTAL_HITS -- TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED (NO_ENGINE).
  No joint game-hits distribution exists in the repo, and none can be
  constructed honestly from the components that do exist. The
  per-batter empirical machinery prices INDIVIDUAL batters from their
  own game logs; a game total is the sum over both lineups (18+
  batters), whose hit counts are NOT independent -- they share the
  opposing starting pitcher and bullpen, the park, the weather, and
  the game's plate-appearance total (itself driven by the score).
  Multiplying nine per-batter marginals together (an independence
  convolution) would fabricate a distribution whose variance is
  systematically wrong in the direction of false confidence. A valid
  construction requires a dependence treatment that has never been
  built or measured here: e.g. a game-level empirical state (per-game
  total hits from verified linescores -- the data exists in
  mlb_first_inning_data's game_hits pools) blended per team with an
  explicit, harness-tested dependence model, then validated
  chronologically against the naive baseline AND the market. Until
  that construction exists and passes the harness, the family is a
  named NO_ENGINE refusal, not a fake engine.

TEAM_TOTAL_HITS -- TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL (NO_ENGINE).
  Here a candidate construction DOES exist and has been measured:
  the team-rate Poisson in mlb_first_inning_model.price_team_hits,
  blended from verified StatsAPI linescore team-hit pools
  (mlb_first_inning_data.prior_pools game_hits_for / game_hits_against).
  The repo's recorded out-of-sample harness verdict for that model is
  FAIL -- it does not beat the naive baseline -- and the phone
  first-inning lane already records TEAM_HITS as IN_BUILD_HARNESS_FAIL
  and emits no probabilities for it. Wiring DraftKings team-total-hits
  rows to price through a measured-failed model would contradict the
  harness-first standard (every factor must prove chronological
  out-of-sample improvement before it prices). The refusal names the
  verdict; a future construction that passes the harness replaces it
  through the normal validation path, not by relabeling.

Row-shape discipline mirrors the P0 team-totals intake contract:
malformed rows refuse by name (side, line, team identity) and NEVER
reach the family gate disguised as well-formed rows; a stated team is
never silently overridden by team_side; the confirmed-lineup gate is
not the blocker here and is not claimed to be -- these families
refuse upstream of any lineup question because no admissible
distribution exists at all.

Research only. No betting authority, no staking, no order placement.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

TOTAL_HITS_VERSION = "MLB_TOTAL_HITS_REFUSAL_V1"

GAME_TOTAL_HITS = "GAME_TOTAL_HITS"
TEAM_TOTAL_HITS = "TEAM_TOTAL_HITS"
TOTAL_HITS_MARKETS = frozenset({GAME_TOTAL_HITS, TEAM_TOTAL_HITS})

# Canonical intake spellings -> canonical market, when the name alone
# decides. TOTAL_HITS is decided by row context (see
# canonical_total_hits_market): DraftKings' board label is "Total
# Hits" for the game market and "Team Total Hits" for the team market,
# so a bare TOTAL_HITS row carrying team identity is the team market.
_TOTAL_HITS_NAME_MARKETS = {
    "GAME_TOTAL_HITS": GAME_TOTAL_HITS,
    "GAME_HITS": GAME_TOTAL_HITS,
    "TOTAL_GAME_HITS": GAME_TOTAL_HITS,
    "TEAM_TOTAL_HITS": TEAM_TOTAL_HITS,
    "TEAM_HITS_TOTAL": TEAM_TOTAL_HITS,
    "TOTAL_TEAM_HITS": TEAM_TOTAL_HITS,
}

# --- terminal family gates -------------------------------------------
TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED = "TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED"
TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL = "TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL"

# --- malformed-row refusals (P0-style, named) -------------------------
TOTAL_HITS_SIDE_INVALID = "TOTAL_HITS_SIDE_INVALID"
TOTAL_HITS_LINE_INVALID = "TOTAL_HITS_LINE_INVALID"
GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED = "GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED"
TEAM_TOTAL_HITS_TEAM_REQUIRED = "TEAM_TOTAL_HITS_TEAM_REQUIRED"
TEAM_TOTAL_HITS_TEAM_SIDE_INVALID = "TEAM_TOTAL_HITS_TEAM_SIDE_INVALID"
TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT = "TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT"

BLOCKER_BY_REASON = {
    TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED: "NO_ENGINE",
    TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL: "NO_ENGINE",
    TOTAL_HITS_SIDE_INVALID: "NO_QUOTE",
    TOTAL_HITS_LINE_INVALID: "NO_QUOTE",
    GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED: "NO_QUOTE",
    TEAM_TOTAL_HITS_TEAM_REQUIRED: "NO_QUOTE",
    TEAM_TOTAL_HITS_TEAM_SIDE_INVALID: "NO_QUOTE",
    TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT: "NO_QUOTE",
}

_DETAIL_BY_REASON = {
    TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED: (
        "no joint game total-hits distribution is constructed: the "
        "per-batter empirical marginals cannot be convolved without a "
        "cross-batter dependence model (shared opposing pitcher, park, "
        "game plate-appearance total) that has never been built or "
        "measured; an independence convolution would fabricate the "
        "distribution's variance. See the design note in "
        "sportsedge/mlb_total_hits.py."),
    TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL: (
        "the one constructed candidate (team-rate Poisson over "
        "verified linescore team-hit pools, "
        "mlb_first_inning_model.price_team_hits) carries a recorded "
        "out-of-sample harness verdict of FAIL against the naive "
        "baseline (mlb_phone_first_inning_pricing records TEAM_HITS "
        "as IN_BUILD_HARNESS_FAIL and emits no probabilities); a "
        "measured-failed model does not price."),
}


def _norm_name(value: Any) -> str:
    return " ".join(
        str(value or "").strip().lower().replace(".", "").split())


def _has_team_identity(row: Mapping[str, Any]) -> bool:
    return bool(
        str(row.get("team_side") or "").strip()
        or str(row.get("team") or "").strip()
        or row.get("team_id") not in (None, "")
    )


def normalize_total_hits_market_name(market: Any) -> str | None:
    """Name-only canonicalization (no row context): TOTAL_HITS and
    its game spellings resolve to the game market; explicit team
    spellings to the team market."""
    name = str(market or "").strip().upper()
    if name == "TOTAL_HITS":
        return GAME_TOTAL_HITS
    return _TOTAL_HITS_NAME_MARKETS.get(name)


def canonical_total_hits_market(row: Mapping[str, Any]) -> str | None:
    """The canonical Total Hits market for an intake row, else None.

    A bare TOTAL_HITS row carrying team identity is the team market
    (DraftKings' game board label is "Total Hits"; the per-team board
    is "Team Total Hits"); without team identity it is the game
    market. Explicit names decide by name alone.
    """
    name = str(row.get("market") or "").strip().upper()
    if name == "TOTAL_HITS":
        return TEAM_TOTAL_HITS if _has_team_identity(row) else GAME_TOTAL_HITS
    return _TOTAL_HITS_NAME_MARKETS.get(name)


def is_total_hits_row(row: Mapping[str, Any]) -> bool:
    return canonical_total_hits_market(row) is not None


def _refusal_row(row: Mapping[str, Any], *, market: str, code: str,
                 detail: str) -> dict[str, Any]:
    blocker = BLOCKER_BY_REASON[code]
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": f"{blocker}: {code} — {detail}"[:400],
        "blocker": blocker,
        "blocker_detail": detail,
        "total_hits_reason": code,
        "coverage_market": market,
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }


def _validate_row_shape(row: Mapping[str, Any], market: str) -> str | None:
    """Named refusal code for a malformed row, else None.

    Mirrors the P0 team-totals intake contract's discipline: identity
    signals are resolved or refused by name, never guessed and never
    silently overridden.
    """
    side = str(row.get("side") or row.get("selection") or "").strip().upper()
    if side not in ("OVER", "UNDER"):
        return TOTAL_HITS_SIDE_INVALID
    line_raw = row.get("line")
    try:
        line = float(line_raw)
    except (TypeError, ValueError):
        return TOTAL_HITS_LINE_INVALID
    if not isfinite(line) or line < 0:
        return TOTAL_HITS_LINE_INVALID

    if market == GAME_TOTAL_HITS:
        if _has_team_identity(row):
            return GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED
        return None

    # TEAM_TOTAL_HITS identity resolution.
    team_side_raw = str(row.get("team_side") or "").strip().upper()
    team_name = str(row.get("team") or "").strip()
    team_id = row.get("team_id")
    has_id = team_id not in (None, "")
    if not team_side_raw and not team_name and not has_id:
        return TEAM_TOTAL_HITS_TEAM_REQUIRED
    if team_side_raw and team_side_raw not in ("HOME", "AWAY"):
        # A team NAME in the team_side field is resolvable; anything
        # else is a corrupt identity signal and refuses by name.
        named = _norm_name(team_side_raw)
        candidates = {
            _norm_name(row.get("away")), _norm_name(row.get("home"))}
        if named not in candidates:
            return TEAM_TOTAL_HITS_TEAM_SIDE_INVALID
    if team_side_raw in ("HOME", "AWAY") and team_name:
        expected = row.get("home") if team_side_raw == "HOME" else row.get("away")
        if _norm_name(team_name) != _norm_name(expected):
            return TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT
    return None


def phone_total_hits_rows(rows: Sequence[Mapping[str, Any]], *, now=None
                          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonical-card stage for Total Hits rows: refuse truthfully.

    Every input row returns exactly one card row. Well-formed rows
    terminate at their family's named NO_ENGINE gate; malformed rows
    terminate at their named intake refusal. No row can carry a price,
    a probability, or an EV -- there is no pricing path in this stage
    by construction.
    """
    rows = list(rows)
    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in rows:
        market = canonical_total_hits_market(row)
        if market is None:
            # Defensive: the router only sends Total Hits rows here.
            code = TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED
            results.append(_refusal_row(
                row, market=GAME_TOTAL_HITS, code=code,
                detail=_DETAIL_BY_REASON[code]))
            counts[code] = counts.get(code, 0) + 1
            continue
        shape_code = _validate_row_shape(row, market)
        if shape_code is not None:
            detail = {
                TOTAL_HITS_SIDE_INVALID:
                    "Total Hits selections must be OVER or UNDER",
                TOTAL_HITS_LINE_INVALID:
                    "Total Hits requires a finite numeric line >= 0",
                GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED:
                    "a game Total Hits row carrying team identity is "
                    "contradictory (the team market is TEAM_TOTAL_HITS)",
                TEAM_TOTAL_HITS_TEAM_REQUIRED:
                    "a team Total Hits row names no team (team_side, "
                    "team or team_id required)",
                TEAM_TOTAL_HITS_TEAM_SIDE_INVALID:
                    "team_side is neither HOME/AWAY nor resolvable to "
                    "either team in the fixture",
                TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT:
                    "the stated team contradicts team_side; a stated "
                    "team is never silently overridden",
            }[shape_code]
            results.append(_refusal_row(
                row, market=market, code=shape_code, detail=detail))
            counts[shape_code] = counts.get(shape_code, 0) + 1
            continue
        code = (TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED
                if market == GAME_TOTAL_HITS
                else TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL)
        results.append(_refusal_row(
            row, market=market, code=code, detail=_DETAIL_BY_REASON[code]))
        counts[code] = counts.get(code, 0) + 1
    receipts = [{
        "source": TOTAL_HITS_VERSION,
        "status": "TOTAL_HITS_REFUSAL_ACTIVE_NO_ENGINE",
        "rows": len(results),
        "outcome_counts": counts,
    }]
    return results, receipts
