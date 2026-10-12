"""Documented per-sport parameters for the SportsEdge team-rating foundation.

Every number below is DECLARED, not fitted: each entry carries a `source`
string naming where it came from. Parameters that have never been validated
against historical outcomes are marked status ``DECLARED_UNVALIDATED`` and
must pass the backtest harness (Isaac's bar: chronological out-of-sample vs
the existing model AND a market baseline) before entering production pricing.

Conventions
-----------
* Rating scale: 1500 average, 400-point logistic scale (standard Elo).
* A rating is a NEUTRAL-SITE team-quality estimate. Home-field advantage,
  rest, and travel are NOT folded into the rating; they are separate
  declared adjustment layers in ``sportsedge.ratings.layers``.
* ``elo_per_point`` converts a rating differential into an expected score
  margin: ``expected_margin_pts = (rating_home - rating_away) / elo_per_point``.
  These are declared linear scalings, not fitted regressions.
"""
from __future__ import annotations

from typing import Any, Mapping

SPORTS = ("NFL", "CFB", "NBA", "MLB")


def _param(value: Any, source: str, status: str) -> dict[str, Any]:
    return {"value": value, "source": source, "status": status}


#: Core Elo dynamics, per sport.
ELO: dict[str, dict[str, dict[str, Any]]] = {
    "NFL": {
        # 538's published NFL Elo used K=20 for the regular update.
        "k": _param(20.0, "538 NFL Elo methodology (published K=20)",
                    "DECLARED_ADOPTED"),
        "init": _param(1500.0, "Elo convention", "DECLARED_CONVENTION"),
        "scale": _param(400.0, "Elo convention", "DECLARED_CONVENTION"),
        # Declared NFL-equivalent points per Elo unit: a 100-Elo gap is
        # roughly a 4-point favorite. Declared, unfitted.
        "elo_per_point": _param(25.0, "declared: 100 Elo ~= 4 pts (NFL)",
                                "DECLARED_UNVALIDATED"),
        # Typical full-game margin sd; only used to normalize margins into
        # NFL-scale units for the MOV multiplier. Free_models PRIORS value.
        "margin_sd": _param(13.7, "free_models PRIORS NFL sd_margin",
                            "DECLARED_ADOPTED"),
    },
    "CFB": {
        # Wider skill gaps + more blowouts than the NFL; slightly higher K.
        "k": _param(25.0, "declared: CFB needs faster adaptation than NFL",
                    "DECLARED_UNVALIDATED"),
        "init": _param(1500.0, "Elo convention", "DECLARED_CONVENTION"),
        "scale": _param(400.0, "Elo convention", "DECLARED_CONVENTION"),
        "elo_per_point": _param(28.0, "declared: 100 Elo ~= 3.6 pts (CFB)",
                                "DECLARED_UNVALIDATED"),
        "margin_sd": _param(19.0, "free_models PRIORS CFB sd_margin",
                            "DECLARED_ADOPTED"),
    },
    "NBA": {
        # 538's published NBA Elo used K=20.
        "k": _param(20.0, "538 NBA Elo methodology (published K=20)",
                    "DECLARED_ADOPTED"),
        "init": _param(1500.0, "Elo convention", "DECLARED_CONVENTION"),
        "scale": _param(400.0, "Elo convention", "DECLARED_CONVENTION"),
        "elo_per_point": _param(20.0, "declared: 100 Elo ~= 5 pts (NBA)",
                                "DECLARED_UNVALIDATED"),
        "margin_sd": _param(12.5, "free_models PRIORS NBA sd_margin",
                            "DECLARED_ADOPTED"),
    },
    "MLB": {
        # 162-game season: per-game information is small; low K.
        "k": _param(8.0, "declared: MLB's long season needs slow adaptation",
                    "DECLARED_UNVALIDATED"),
        "init": _param(1500.0, "Elo convention", "DECLARED_CONVENTION"),
        "scale": _param(400.0, "Elo convention", "DECLARED_CONVENTION"),
        # Runs are scarce; a 100-Elo gap is roughly a 1.1-run favorite.
        "elo_per_point": _param(90.0, "declared: 100 Elo ~= 1.1 runs (MLB)",
                                "DECLARED_UNVALIDATED"),
        "margin_sd": _param(3.4, "declared: typical MLB run-margin sd",
                            "DECLARED_UNVALIDATED"),
    },
}

#: How much a new season's starting rating regresses toward the mean.
#: Declared carryover convention (538 regresses toward the mean each season).
SEASON_REGRESS = _param(
    0.33,
    "declared carryover convention: new season keeps 67% of prior rating",
    "DECLARED_UNVALIDATED",
)

#: Season label boundaries: (sport -> month the season's games start counting
#: toward the NEXT season label). E.g. NFL games from September belong to the
#: season of that calendar year.
SEASON_START_MONTH = {"NFL": 9, "CFB": 8, "NBA": 10, "MLB": 4}

#: Margin-of-victory multiplier: FiveThirtyEight's published NFL formula
#:   mult = ((mov + 3) ** 0.8) / (7.45 + 0.006 * |pre_diff|)
#: Margins and pre-game rating diffs are first normalized into NFL-scale
#: units via each sport's margin_sd, so the formula's NFL-calibrated
#: constants apply uniformly. The +3 / 0.8 / 7.45 / 0.006 constants are
#: 538's published values, not SportsEdge inventions.
MOV_FORMULA = _param(
    "((mov_nfl + 3) ** 0.8) / (7.45 + 0.006 * abs(diff_nfl))",
    "538 NFL Elo methodology (published MOV multiplier)",
    "DECLARED_ADOPTED",
)


def get(sport: str, name: str) -> Any:
    """Return the raw value of a named parameter for a sport."""
    sport = str(sport or "").upper().strip()
    if sport not in ELO:
        raise KeyError("RATINGS_SPORT_UNSUPPORTED:" + sport)
    entry = ELO[sport].get(name)
    if entry is None:
        raise KeyError(f"RATINGS_PARAM_UNKNOWN:{sport}:{name}")
    return entry["value"]


def describe(sport: str, name: str) -> Mapping[str, Any]:
    """Return the full parameter record (value + source + status)."""
    sport = str(sport or "").upper().strip()
    if sport not in ELO:
        raise KeyError("RATINGS_SPORT_UNSUPPORTED:" + sport)
    entry = ELO[sport].get(name)
    if entry is None:
        raise KeyError(f"RATINGS_PARAM_UNKNOWN:{sport}:{name}")
    return dict(entry)


def audit_table() -> list[dict[str, Any]]:
    """Every parameter with its source and validation status (for cards)."""
    rows = []
    for sport in SPORTS:
        for name, entry in ELO[sport].items():
            rows.append({"sport": sport, "param": name, **entry})
    rows.append({"sport": "ALL", "param": "season_regress",
                 **SEASON_REGRESS})
    rows.append({"sport": "ALL", "param": "mov_formula", **MOV_FORMULA})
    return rows
