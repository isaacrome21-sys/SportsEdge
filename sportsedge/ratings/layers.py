"""Declared adjustment layers applied when score means are built.

Architecture rule (from the adopted critique): HFA, rest, and travel are
DECLARED SEPARATE adjustment layers. They are never buried inside the Elo
rating (ratings are neutral-site quality) and never silently merged into a
mean. Every layer carries its own documented parameter and source, and the
mean builder returns a factor-coverage audit listing each layer's status.

Layer statuses:
* ``DECLARED_LEGACY``      — value already in production use (free_models PRIORS).
* ``DECLARED_UNVALIDATED`` — declared value, not yet harness-validated.
* ``NOT_WIRED``            — interface declared; parameter pending Phase 2
  validation. The layer returns 0.0 and says so in the audit.

Phase 2 factors (bullpen workload, QB/pitcher participation, weather
interactions, park factors, rest/travel coefficients) plug in here as new
``AdjustmentLayer`` constructors with harness-gated parameters. The mean
builder does not need to change; only the layer list grows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

from . import params

# Legacy home-field points already declared in free_models PRIORS
# (base, sd_total, sd_margin, hfa) — adopted as-is, not refitted.
_HFA_POINTS = {
    "NFL": {"value": 1.5, "source": "free_models PRIORS NFL hfa", "status": "DECLARED_LEGACY"},
    "CFB": {"value": 2.5, "source": "free_models PRIORS CFB hfa", "status": "DECLARED_LEGACY"},
    "NBA": {"value": 2.0, "source": "free_models PRIORS NBA hfa", "status": "DECLARED_LEGACY"},
    "MLB": {"value": 0.20, "source": "free_models PRIORS MLB hfa", "status": "DECLARED_LEGACY"},
}


@dataclass(frozen=True)
class AdjustmentLayer:
    """One declared adjustment applied symmetrically to the two means.

    ``home_pts``/``away_pts`` are points added to the home/away score mean.
    ``status`` is one of DECLARED_LEGACY / DECLARED_UNVALIDATED / NOT_WIRED.
    """
    name: str
    home_pts: float
    away_pts: float
    parameter: str
    source: str
    status: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def audit_row(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "home_pts": round(self.home_pts, 3),
            "away_pts": round(self.away_pts, 3),
            "parameter": self.parameter,
            "source": self.source,
            "status": self.status,
            "detail": dict(self.detail),
        }


def hfa_layer(sport: str, *, neutral_site: bool = False) -> AdjustmentLayer:
    """Home-field advantage as a declared separate layer.

    Matches production convention: the HFA point total is split +hfa/2 to
    the home mean and -hfa/2 to the away mean (same as free_models).
    """
    sport = str(sport or "").upper().strip()
    if sport not in _HFA_POINTS:
        raise ValueError("LAYERS_SPORT_UNSUPPORTED:" + sport)
    spec = _HFA_POINTS[sport]
    hfa = 0.0 if neutral_site else float(spec["value"])
    return AdjustmentLayer(
        name="home_field_advantage",
        home_pts=hfa / 2, away_pts=-hfa / 2,
        parameter=f"hfa_points={spec['value']}",
        source=spec["source"] + ("; neutral_site=0" if neutral_site else ""),
        status=spec["status"],
        detail={"neutral_site": neutral_site},
    )


def rest_layer(sport: str, *, home_rest_days: Optional[float] = None,
               away_rest_days: Optional[float] = None) -> AdjustmentLayer:
    """Rest differential layer.

    INTERFACE DECLARED, PARAMETER NOT WIRED: no rest coefficient has passed
    the harness, so this layer returns 0.0 and reports NOT_WIRED with the
    reason. Phase 2 (free factors) declares and validates the coefficient
    here. Passing rest days is still recorded in the audit detail so the
    coverage gap is visible on every card.
    """
    sport = str(sport or "").upper().strip()
    if sport not in params.SPORTS:
        raise ValueError("LAYERS_SPORT_UNSUPPORTED:" + sport)
    return AdjustmentLayer(
        name="rest_differential",
        home_pts=0.0, away_pts=0.0,
        parameter="rest_points_per_day=TBD",
        source="not yet declared — Phase 2 free-factors, harness-gated",
        status="NOT_WIRED",
        detail={"home_rest_days": home_rest_days,
                "away_rest_days": away_rest_days,
                "reason": "no rest coefficient has passed the backtest harness"},
    )


def travel_layer(sport: str, *, away_travel_miles: Optional[float] = None,
                 timezone_shift_hours: Optional[float] = None) -> AdjustmentLayer:
    """Travel layer.

    INTERFACE DECLARED, PARAMETER NOT WIRED: no travel coefficient has
    passed the harness. Returns 0.0 with NOT_WIRED status and a reason.
    Phase 2 declares and validates the coefficient here.
    """
    sport = str(sport or "").upper().strip()
    if sport not in params.SPORTS:
        raise ValueError("LAYERS_SPORT_UNSUPPORTED:" + sport)
    return AdjustmentLayer(
        name="travel",
        home_pts=0.0, away_pts=0.0,
        parameter="travel_points_per_mile=TBD",
        source="not yet declared — Phase 2 free-factors, harness-gated",
        status="NOT_WIRED",
        detail={"away_travel_miles": away_travel_miles,
                "timezone_shift_hours": timezone_shift_hours,
                "reason": "no travel coefficient has passed the backtest harness"},
    )


#: Default layers applied by ``build_means`` when the caller does not
#: supply its own layer list.
DEFAULT_LAYERS: tuple[Callable[..., AdjustmentLayer], ...] = (
    hfa_layer, rest_layer, travel_layer,
)


def build_means(sport: str, *, base_mean: float,
                home_strength_pts: float, away_strength_pts: float,
                layers: Optional[list[AdjustmentLayer]] = None,
                neutral_site: bool = False,
                **layer_kwargs: Any) -> dict[str, Any]:
    """Build home/away score means from declared components.

    Components are kept explicit — nothing is buried:

    * ``base_mean``: league scoring prior (e.g. free_models PRIORS base).
    * ``home_strength_pts`` / ``away_strength_pts``: neutral-site team
      strength in points above average (from the Elo rating).
    * ``layers``: declared adjustment layers (HFA / rest / travel / future
      Phase 2 factors). Defaults to ``DEFAULT_LAYERS``; the HFA layer
      receives ``neutral_site`` when that kwarg is set.

    Returns home_mean, away_mean, and a factor-coverage audit listing every
    component with its source and status. Missing critical layers are
    reported in the audit, never silently priced.
    """
    sport = str(sport or "").upper().strip()
    if sport not in params.SPORTS:
        raise ValueError("LAYERS_SPORT_UNSUPPORTED:" + sport)

    if layers is None:
        layers = []
        for ctor in DEFAULT_LAYERS:
            if ctor is hfa_layer:
                layers.append(ctor(sport, neutral_site=neutral_site))
            else:
                layers.append(ctor(sport, **{
                    k: v for k, v in layer_kwargs.items()
                    if k in _layer_kw(ctor)}))

    home_mean = base_mean + home_strength_pts
    away_mean = base_mean + away_strength_pts
    for layer in layers:
        home_mean += layer.home_pts
        away_mean += layer.away_pts

    audit = [
        {"layer": "league_prior", "home_pts": base_mean, "away_pts": base_mean,
         "parameter": f"base_mean={base_mean}", "source": "caller-supplied prior",
         "status": "DECLARED_LEGACY",
         "detail": {"note": "free_models PRIORS base when wired via adapter"}},
        {"layer": "team_strength_elo", "home_pts": round(home_strength_pts, 3),
         "away_pts": round(away_strength_pts, 3),
         "parameter": "elo_per_point (see params.describe)",
         "source": "sportsedge.ratings EloTracker (neutral-site)",
         "status": "DECLARED_UNVALIDATED",
         "detail": {"note": "harness verdict required before production use"}},
    ]
    audit.extend(layer.audit_row() for layer in layers)

    missing = [a["layer"] for a in audit if a["status"] == "NOT_WIRED"]
    return {
        "home_mean": home_mean,
        "away_mean": away_mean,
        "factor_audit": audit,
        "layers_not_wired": missing,
        "research_only": True,
    }


def _layer_kw(ctor: Callable[..., AdjustmentLayer]) -> set[str]:
    if ctor is rest_layer:
        return {"home_rest_days", "away_rest_days"}
    if ctor is travel_layer:
        return {"away_travel_miles", "timezone_shift_hours"}
    return set()
