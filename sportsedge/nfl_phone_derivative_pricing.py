"""Canonical NFL derivative stage: team totals, periods, alternate lines.

Wires the two orphaned pricers into the canonical RUN IT path:

* ``sportsedge.sports.nfl.team_totals.price_nfl_team_totals`` and
* ``sportsedge.core.simulate.markets.derive_period_markets`` /
  ``derive_alternate_markets``.

Both pricers price ONLY from an independent joint score distribution
(simulation rows with full-game and per-period scores).  The canonical
game engine (``artifacts/free_models``) is analytic and emits no such
distribution, so on the canonical path today every row resolves to a
fail-closed blocked outcome whose reason is the pricer's own guard
(``NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY`` /
``SIMULATION_ROWS_EMPTY``), under the coverage taxonomy blocker
``NO_ENGINE`` (see ``sportsedge/canonical_coverage.py``).

The ``distributions`` argument is the honest seam: a mapping of fixture
key -> simulation rows.  If a canonical stage ever produces a verified
joint score distribution, these rows price through the real pricers
unchanged.  Nothing here fabricates a distribution from free_models
means -- doing so would silently create a new, unvalidated model.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from sportsedge.core.simulate.markets import (
    derive_alternate_markets,
    derive_period_markets,
)
from sportsedge.sports.nfl.team_totals import NFLTeamTotalError, price_nfl_team_totals

TEAM_TOTAL_MARKETS = {"TEAM_TOTALS", "TEAM_TOTAL"}

PERIOD_MARKETS = {
    "FIRST_HALF_MONEYLINE": ("first_half", "MONEYLINE"),
    "FIRST_HALF_SPREAD": ("first_half", "SPREAD"),
    "FIRST_HALF_TOTAL": ("first_half", "TOTAL"),
    "SECOND_HALF_MONEYLINE": ("second_half", "MONEYLINE"),
    "SECOND_HALF_SPREAD": ("second_half", "SPREAD"),
    "SECOND_HALF_TOTAL": ("second_half", "TOTAL"),
    "QUARTER_MONEYLINE": ("quarter", "MONEYLINE"),
    "QUARTER_SPREAD": ("quarter", "SPREAD"),
    "QUARTER_TOTAL": ("quarter", "TOTAL"),
}

ALTERNATE_MARKETS = {"ALTERNATE_SPREAD", "ALTERNATE_TOTAL",
                     "ALT_SPREAD", "ALT_TOTAL"}

# A first-half team total has no pricer of its own: it is a period
# market, so it fails closed on the period guard (SIMULATION_ROWS_EMPTY)
# until a compliant period distribution exists (owner ruling,
# Oct 13, 2026: first-half markets block NO_ENGINE because no compliant
# period distribution is available).
FIRST_HALF_TEAM_TOTAL_MARKETS = {"FIRST_HALF_TEAM_TOTAL"}

DERIVATIVE_MARKETS = (TEAM_TOTAL_MARKETS | set(PERIOD_MARKETS)
                      | ALTERNATE_MARKETS | FIRST_HALF_TEAM_TOTAL_MARKETS)

_DISTRIBUTION_KEYS = ("simulation_rows", "score_paths",
                      "joint_score_distribution")


def fixture_key(away: Any, home: Any) -> tuple[str, str]:
    return (str(away or "").strip().upper(), str(home or "").strip().upper())


def extract_distribution(game_result: Mapping[str, Any] | None):
    """Joint score distribution embedded in a priced game result, if any.

    The canonical analytic game engine emits none today; this seam lets a
    future distribution-producing stage feed the derivative pricers
    without changing this module.
    """
    if not isinstance(game_result, Mapping):
        return None
    for key in _DISTRIBUTION_KEYS:
        rows = game_result.get(key)
        if isinstance(rows, list) and rows:
            return rows
    return None


def _blocked(row: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": reason,
        "blocker": "NO_ENGINE",
        "blocker_detail": (
            "Derivative pricer wired into the canonical path, but it prices "
            "only from an independent joint score distribution; the "
            "canonical analytic game engine emits no simulation paths. "
            "Pricer guard: " + reason),
        "sport": "NFL",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "team": row.get("team"),
        "away_team": row.get("away"), "home_team": row.get("home"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }


def _priced_probabilities(row: Mapping[str, Any], probabilities: Mapping[str, Any],
                          *, pricer: str) -> dict[str, Any]:
    return {
        "status": "PRICED_RESEARCH",
        "reason": None,
        "sport": "NFL",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "team": row.get("team"),
        "away_team": row.get("away"), "home_team": row.get("home"),
        "model_probabilities": dict(probabilities),
        "pricer": pricer,
        "quote_judged": False,
        "quote_judgement_note": (
            "Probabilities come from the derivative pricer over a supplied "
            "joint score distribution; quote judging against the card quote "
            "is not performed by this stage."),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "validated_vs_close": False,
    }


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def phone_nfl_derivative_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    distributions: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]] | None = None,
    now: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve NFL team-total / period / alternate rows through the pricers.

    Returns (evaluated, receipts).  Every row yields exactly one outcome:
    a priced-probability row when a joint score distribution for its
    fixture was supplied (and the pricer's own guards pass), otherwise a
    blocked row naming the pricer's guard.
    """
    distributions = distributions or {}
    # Outcomes are emitted in INPUT order: the canonical runner pairs
    # stage results with intake rows positionally, so grouping (team
    # totals are priced per fixture, below) must not reorder the output.
    outcomes: list[dict[str, Any] | None] = [None] * len(rows)
    receipts: list[dict[str, Any]] = [{
        "stage": "NFL_DERIVATIVE",
        "fixtures_with_distribution": len(distributions),
        "rows": len(rows),
    }] if rows else []

    def distribution_for(row):
        return list(distributions.get(
            fixture_key(row.get("away"), row.get("home")), ()))

    # ---- team totals: the pricer needs both sides' lines together ----
    team_total_rows = [(i, r) for i, r in enumerate(rows)
                       if str(r.get("market") or "").upper()
                       in TEAM_TOTAL_MARKETS]
    fixtures: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = {}
    for idx, row in team_total_rows:
        fixtures.setdefault(fixture_key(row.get("away"), row.get("home")),
                            []).append((idx, row))
    for key, group in fixtures.items():
        dist = list(distributions.get(key, ()))
        home_line = away_line = None
        for _idx, row in group:
            side = str(row.get("side") or row.get("team") or "").upper()
            team = str(row.get("team") or "").upper()
            line = _num(row.get("line"))
            if side == "HOME" or team == key[1]:
                home_line = line if line is not None else home_line
            elif side == "AWAY" or team == key[0]:
                away_line = line if line is not None else away_line
        try:
            if dist and (home_line is None or away_line is None):
                priced = None
                error = "NFL_TEAM_TOTAL_PAIRED_LINE_REQUIRED"
            else:
                priced = price_nfl_team_totals(
                    dist, home_total_line=home_line, away_total_line=away_line)
                error = None
        except NFLTeamTotalError as exc:
            priced, error = None, str(exc)
        except Exception as exc:  # pricer guards are the contract
            priced, error = None, f"NFL_TEAM_TOTAL_PRICER_ERROR:{exc}"
        for idx, row in group:
            if error is not None:
                outcomes[idx] = _blocked(row, reason=error)
            else:
                side = str(row.get("side") or row.get("team") or "").upper()
                team = str(row.get("team") or "").upper()
                which = ("home_team_total" if side == "HOME" or team == key[1]
                         else "away_team_total")
                outcomes[idx] = _priced_probabilities(
                    row, priced[which], pricer="price_nfl_team_totals")

    # ---- periods + alternates: one pricer call per row ----
    for idx, row in enumerate(rows):
        market = str(row.get("market") or "").upper()
        if market in TEAM_TOTAL_MARKETS:
            continue
        if market in FIRST_HALF_TEAM_TOTAL_MARKETS:
            # Period market with no pricer: the period-distribution
            # guard is the named reason (see the set's comment above).
            outcomes[idx] = _blocked(row, reason="SIMULATION_ROWS_EMPTY")
            continue
        dist = distribution_for(row)
        line = _num(row.get("line"))
        if market in PERIOD_MARKETS:
            period, kind = PERIOD_MARKETS[market]
            if period == "quarter":
                quarter = row.get("quarter")
                try:
                    quarter = int(quarter)
                except (TypeError, ValueError):
                    quarter = None
                if quarter not in (1, 2, 3, 4):
                    outcomes[idx] = _blocked(
                        row, reason="QUARTER_UNSPECIFIED")
                    continue
                period = f"q{quarter}"
            try:
                derived = derive_period_markets(
                    dist, period=period,
                    spread_line=line if kind == "SPREAD" and line is not None
                    else 0.0,
                    total_line=line if kind == "TOTAL" else None,
                    include_ot=(row.get("include_ot")
                                if period == "second_half" else None),
                )
                error = None
            except ValueError as exc:
                # The pricers' guard codes ARE the named reasons.
                derived, error = None, str(exc)
            except Exception as exc:
                derived, error = None, f"PERIOD_PRICER_ERROR:{exc}"
            if error is not None:
                outcomes[idx] = _blocked(row, reason=error)
            else:
                key = {"MONEYLINE": "moneyline", "SPREAD": "spread",
                       "TOTAL": "total"}[kind]
                outcomes[idx] = _priced_probabilities(
                    row, derived[key], pricer="derive_period_markets")
        elif market in ALTERNATE_MARKETS:
            try:
                derived = derive_alternate_markets(
                    dist,
                    spread_lines=[line] if market in (
                        "ALTERNATE_SPREAD", "ALT_SPREAD") and line is not None
                    else None,
                    total_lines=[line] if market in (
                        "ALTERNATE_TOTAL", "ALT_TOTAL") and line is not None
                    else None,
                )
                error = None
            except ValueError as exc:
                derived, error = None, str(exc)
            except Exception as exc:
                derived, error = None, f"ALTERNATE_PRICER_ERROR:{exc}"
            if error is not None:
                outcomes[idx] = _blocked(row, reason=error)
            else:
                outcomes[idx] = _priced_probabilities(
                    row, derived, pricer="derive_alternate_markets")
        else:
            outcomes[idx] = _blocked(
                row, reason="NOT_A_DERIVATIVE_MARKET")

    assert all(o is not None for o in outcomes)
    return outcomes, receipts
