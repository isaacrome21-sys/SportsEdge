"""MLB home-run prop model (full-game) from free Statcast data — research only.

Isaac's named priority prop market. Inputs (all free, all verified):
  - Batter power vs pitcher handedness: HR/PA, barrel%, exit velo from
    Statcast pitch-level data, split by pitcher hand (p_throws).
  - Regressed platoon splits (Derek Carty / THE BAT): RHB splits regress
    toward the league-average platoon split with a 2,200 PA prior, LHB with
    a 1,000 PA prior. Power splits >> contact: the model ALWAYS uses the
    matchup-specific (platoon) rate, never a blended overall rate.
  - Pitcher HR suppression: HR allowed per PA faced from Statcast
    (the Statcast-sourced equivalent of Isaac's "pitcher HR/9 allowed";
    the factor pipeline may substitute a box-score HR/9-derived rate via
    ``pitcher_hr_pa_against_override``), shrunk toward league average.
  - COMPONENT park HR factor (not aggregate): consumed from Phase 2's
    ``data/component_park_factors_2022_2024.json`` (schema
    SPORTSEDGE_COMPONENT_PARK_FACTORS_V1, teams["<name>"]["HR"]["pf"]) by
    contract — this module never recomputes park factors. Missing file or
    missing team -> BLOCKED, never a neutral 1.0 default.

Model (Poisson-ish):
    lambda = pa_expected * batter_regressed_hr_pa(matchup)
             * pitcher_hr_factor * park_hr_pf
    P(>=1 HR) = 1 - exp(-lambda);  P(>=2 HR) = 1 - exp(-lambda)*(1+lambda)
  Multiplicative log-linear form; every component is surfaced in the output
  for audit. Percentile projections (p10/p50/p90 of the HR count) are emitted
  for card rendering via the shared ``attach_prop_percentiles`` helper.

Fail-closed (BLOCKED with explicit reason, never a point estimate on
defaults): missing pitcher handedness, missing park HR component, unverified
lineup / insufficient batter history.

Entry point::

    hr_prop_projection(
        *, batter_id, batter_hand, pitcher_id, pitcher_hand,
        home_team_name, pitch_rows, park_hr_factors,
        pa_expected=4.2, min_batter_pa=50,
        pitcher_hr_pa_against_override=None,
    ) -> dict

Research only. No betting authority. Must beat the naive batter-HR-rate
baseline out-of-sample (Brier + log-loss) before production use.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Iterable, Mapping, Sequence

from .mlb_savant_features import (
    SavantFeatureError,
    attach_prop_percentiles,  # noqa: F401  (re-exported for card wiring)
    poisson_quantiles,
)

HR_SCHEMA_VERSION = "mlb_hr_prop_v1_2026-10-11"
PARK_FACTORS_SCHEMA = "SPORTSEDGE_COMPONENT_PARK_FACTORS_V1"

# Carty (THE BAT): PA prior for regressing platoon splits toward the
# league-average platoon split. Power splits stabilize at these volumes.
PLATOON_PRIOR_PA = {"R": 2200, "L": 1000, "S": 1000}  # S declared, Carty-sourced R/L
MIN_BATTER_PA = 50            # minimum train PA for a priced HR prop
MIN_PITCHER_BF = 150          # minimum batters faced for pitcher HR factor
PITCHER_SHRINK_BF = 300       # DECLARED prior strength (BF) shrinking pitcher
                              # HR factor toward 1.0
DEFAULT_PA_EXPECTED = 4.2     # DECLARED full-game PA expectation (overridable)


class HRPropError(ValueError):
    """HR prop model error; message is an HR_* code."""


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# ---------------------------------------------------------------------------
# Component 1: batter platoon power splits from pitch-level Statcast
# ---------------------------------------------------------------------------

def batter_platoon_power(pitch_rows: Iterable[Mapping[str, str]],
                         batter_id: str | int) -> dict[str, Any]:
    """HR/PA, barrel%, exit velo, xwOBA for one batter vs LHP and vs RHP.

    Split by pitcher hand (p_throws) — the platoon matchup. Only Statcast
    columns are used.
    """
    bid = str(batter_id)
    splits = {
        "L": {"pa": 0, "hr": 0, "barrels": 0, "bbe": 0,
              "ev_sum": 0.0, "ev_n": 0, "xwoba_sum": 0.0, "xwoba_n": 0},
        "R": {"pa": 0, "hr": 0, "barrels": 0, "bbe": 0,
              "ev_sum": 0.0, "ev_n": 0, "xwoba_sum": 0.0, "xwoba_n": 0},
    }
    stands = {}
    for row in pitch_rows:
        if str(row.get("batter")) != bid:
            continue
        hand = str(row.get("p_throws") or "").strip().upper()
        if hand not in ("L", "R"):
            continue
        s = splits[hand]
        stand = str(row.get("stand") or "").strip().upper()
        if stand in ("L", "R", "S"):
            stands[stand] = stands.get(stand, 0) + 1
        event = str(row.get("events") or "").strip()
        launch_speed = _finite(row.get("launch_speed"))
        if launch_speed is not None:
            s["bbe"] += 1
            s["ev_sum"] += launch_speed
            s["ev_n"] += 1
            if launch_speed >= 95.0:
                pass  # hard-hit counted implicitly via ev distribution
            if str(row.get("launch_speed_angle") or "").strip() == "6":
                s["barrels"] += 1
        xw = _finite(row.get("estimated_woba_using_speedangle"))
        if xw is not None:
            s["xwoba_sum"] += xw
            s["xwoba_n"] += 1
        if event:
            s["pa"] += 1
            if event == "home_run":
                s["hr"] += 1
    total_pa = splits["L"]["pa"] + splits["R"]["pa"]
    if total_pa < MIN_BATTER_PA:
        return {"status": "MISSING",
                "reason": f"HR_BATTER_HISTORY_INSUFFICIENT:pa={total_pa}",
                "entity_id": bid}
    bats = max(stands, key=stands.get) if stands else None
    out = {"status": "AVAILABLE", "entity_id": bid, "bats": bats,
           "pa_total": total_pa, "schema_version": HR_SCHEMA_VERSION}
    for hand, s in splits.items():
        pa = s["pa"]
        out[f"vs_{hand}"] = {
            "pa": pa,
            "hr": s["hr"],
            "hr_per_pa": round(s["hr"] / pa, 6) if pa else None,
            "barrel_rate": round(s["barrels"] / s["bbe"], 6) if s["bbe"] else None,
            "avg_exit_velocity": (round(s["ev_sum"] / s["ev_n"], 2)
                                  if s["ev_n"] else None),
            "xwoba": (round(s["xwoba_sum"] / s["xwoba_n"], 4)
                      if s["xwoba_n"] else None),
        }
    return out


def league_platoon_hr_rates(pitch_rows: Iterable[Mapping[str, str]]
                            ) -> dict[str, Any]:
    """League HR/PA by (batter_hand, pitcher_hand) matchup — the regression target.

    Batter hand from ``stand`` (mode per batter); pitcher hand from p_throws.
    """
    # Per-batter stand mode.
    batter_stands: dict[str, dict[str, int]] = {}
    rows = list(pitch_rows)
    for row in rows:
        stand = str(row.get("stand") or "").strip().upper()
        if stand in ("L", "R", "S"):
            cell = batter_stands.setdefault(str(row.get("batter")), {})
            cell[stand] = cell.get(stand, 0) + 1
    batter_hand = {b: max(v, key=v.get) for b, v in batter_stands.items()}
    agg: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        event = str(row.get("events") or "").strip()
        if not event:
            continue
        bh = batter_hand.get(str(row.get("batter")))
        ph = str(row.get("p_throws") or "").strip().upper()
        if bh not in ("L", "R", "S") or ph not in ("L", "R"):
            continue
        cell = agg.setdefault((bh, ph), [0, 0])
        cell[0] += 1
        if event == "home_run":
            cell[1] += 1
    out = {}
    for (bh, ph), (pa, hr) in agg.items():
        if pa >= 500:  # stable league estimate only
            out[f"{bh}v{ph}"] = {"pa": pa, "hr": hr,
                                 "hr_per_pa": round(hr / pa, 6)}
    if not out:
        return {"status": "MISSING", "reason": "HR_LEAGUE_PLATOON_RATES_UNVERIFIED"}
    return {"status": "AVAILABLE", "matchups": out}


def regressed_platoon_hr_rate(platoon: Mapping[str, Any],
                              pitcher_hand: str,
                              league_matchups: Mapping[str, Any],
                              batter_hand_override: str | None = None
                              ) -> dict[str, Any]:
    """Empirical-Bayes HR/PA for the platoon matchup.

    regressed = (obs_hr + prior_pa * lg_rate) / (obs_pa + prior_pa),
    prior_pa = 2200 (RHB) / 1000 (LHB) per Carty, lg_rate = league HR/PA for
    the (batter_hand, pitcher_hand) matchup. Power splits are ALWAYS
    matchup-specific (power splits >> contact).
    """
    if not isinstance(platoon, Mapping) or platoon.get("status") != "AVAILABLE":
        return {"status": "BLOCKED",
                "reason": "HR_BATTER_SPLITS_UNAVAILABLE"}
    ph = str(pitcher_hand or "").strip().upper()
    if ph not in ("L", "R"):
        return {"status": "BLOCKED", "reason": "HR_PITCHER_HAND_UNVERIFIED"}
    bh = (str(batter_hand_override or "").strip().upper()
          or str(platoon.get("bats") or "").strip().upper())
    if bh not in ("L", "R", "S"):
        return {"status": "BLOCKED", "reason": "HR_BATTER_HAND_UNVERIFIED"}
    split = platoon.get(f"vs_{ph}")
    if not isinstance(split, Mapping):
        return {"status": "BLOCKED", "reason": "HR_PLATOON_SPLIT_MISSING"}
    obs_pa = int(split.get("pa") or 0)
    obs_hr = int(split.get("hr") or 0)
    lg = league_matchups.get(f"{bh}v{ph}") if isinstance(
        league_matchups, Mapping) else None
    if not isinstance(lg, Mapping) or _finite(lg.get("hr_per_pa")) is None:
        return {"status": "BLOCKED",
                "reason": f"HR_LEAGUE_PLATOON_RATE_MISSING:{bh}v{ph}"}
    lg_rate = float(lg["hr_per_pa"])
    prior_pa = PLATOON_PRIOR_PA[bh]
    rate = (obs_hr + prior_pa * lg_rate) / (obs_pa + prior_pa)
    return {"status": "AVAILABLE",
            "regressed_hr_per_pa": round(rate, 6),
            "matchup": f"{bh}v{ph}",
            "obs_pa": obs_pa, "obs_hr": obs_hr,
            "prior_pa": prior_pa, "league_hr_per_pa": lg_rate}


# ---------------------------------------------------------------------------
# Component 2: pitcher HR suppression (Statcast-sourced)
# ---------------------------------------------------------------------------

def pitcher_hr_factor(pitch_rows: Iterable[Mapping[str, str]],
                      pitcher_id: str | int,
                      league_hr_per_pa: float) -> dict[str, Any]:
    """Pitcher HR-allowed factor: (HR/PA faced / league HR/PA), shrunk to 1.0.

    The Statcast-sourced equivalent of HR/9 allowed. Shrunk with a declared
    300-BF prior toward neutral; the shrinkage is surfaced, never silent.
    """
    lg = _finite(league_hr_per_pa)
    if lg is None or lg <= 0:
        return {"status": "BLOCKED", "reason": "HR_LEAGUE_RATE_UNVERIFIED"}
    pid = str(pitcher_id)
    pa = hr = 0
    for row in pitch_rows:
        if str(row.get("pitcher")) != pid:
            continue
        event = str(row.get("events") or "").strip()
        if not event:
            continue
        pa += 1
        if event == "home_run":
            hr += 1
    if pa < MIN_PITCHER_BF:
        return {"status": "MISSING",
                "reason": f"HR_PITCHER_SAMPLE_TOO_SMALL:bf={pa}",
                "entity_id": pid}
    raw = (hr / pa) / lg
    shrunk = (pa * raw + PITCHER_SHRINK_BF * 1.0) / (pa + PITCHER_SHRINK_BF)
    return {"status": "AVAILABLE", "entity_id": pid,
            "batters_faced": pa, "hr_allowed": hr,
            "raw_factor": round(raw, 4),
            "factor": round(shrunk, 4),
            "shrink_prior_bf": PITCHER_SHRINK_BF}


# ---------------------------------------------------------------------------
# Component 3: component park HR factor (Phase 2 artifact, by contract)
# ---------------------------------------------------------------------------

def load_component_park_hr(source: str | Mapping[str, Any]) -> dict[str, float]:
    """Load the HR component from Phase 2's component park factors artifact.

    ``source``: path to the JSON or an already-parsed mapping. Validates the
    schema; raises HRPropError on anything unexpected (fail-closed: the model
    never runs on a neutral 1.0 default).
    """
    if isinstance(source, str):
        if not os.path.exists(source):
            raise HRPropError("HR_PARK_FACTORS_FILE_MISSING")
        try:
            with open(source, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError) as exc:
            raise HRPropError("HR_PARK_FACTORS_UNREADABLE") from exc
    elif isinstance(source, Mapping):
        payload = source
    else:
        raise HRPropError("HR_PARK_FACTORS_SOURCE_INVALID")
    if not isinstance(payload, Mapping):
        raise HRPropError("HR_PARK_FACTORS_MALFORMED")
    if payload.get("schema") != PARK_FACTORS_SCHEMA:
        raise HRPropError(
            f"HR_PARK_FACTORS_SCHEMA_UNEXPECTED:{payload.get('schema')}")
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        raise HRPropError("HR_PARK_FACTORS_TEAMS_MISSING")
    out: dict[str, float] = {}
    for name, entry in teams.items():
        if not isinstance(entry, Mapping):
            continue
        hr = entry.get("HR")
        if not isinstance(hr, Mapping):
            continue
        pf = _finite(hr.get("pf"))
        if pf is None or pf <= 0:
            continue
        out[str(name)] = pf
    if not out:
        raise HRPropError("HR_PARK_FACTORS_EMPTY")
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def hr_prop_projection(*, batter_id: str | int,
                       batter_hand: str | None,
                       pitcher_id: str | int,
                       pitcher_hand: str | None,
                       home_team_name: str,
                       pitch_rows: Sequence[Mapping[str, str]],
                       park_hr_factors: Mapping[str, float] | None,
                       league_matchups: Mapping[str, Any] | None = None,
                       league_hr_per_pa: float | None = None,
                       pa_expected: float = DEFAULT_PA_EXPECTED,
                       pitcher_hr_pa_against_override: float | None = None
                       ) -> dict[str, Any]:
    """Price a full-game batter HR prop (P(>=1 HR), P(>=2 HR)).

    Parameters
    ----------
    batter_id / pitcher_id: MLBAM ids (verified upstream — unverified
        identity must be blocked before calling).
    batter_hand: "L"/"R"/"S" (from verified roster/stand data; None ->
        BLOCKED).
    pitcher_hand: "L"/"R" (verified probable-starter handedness; None ->
        BLOCKED with HR_PITCHER_HAND_UNVERIFIED).
    home_team_name: e.g. "Los Angeles Dodgers" (must match a key in
        ``park_hr_factors``; missing -> BLOCKED).
    pitch_rows: train-window Statcast pitch rows (strictly prior to the game).
    park_hr_factors: mapping team name -> HR component factor (from
        load_component_park_hr). None/missing team -> BLOCKED.
    league_matchups / league_hr_per_pa: precomputed league rates (computed
        from the same train window when omitted).
    pa_expected: full-game PA expectation (declared default 4.2).
    pitcher_hr_pa_against_override: optional box-score HR/9-derived
        HR-per-PA-against to substitute for the Statcast computation.

    Returns {"status": "AVAILABLE", ...} with p_ge1_hr, p_ge2_hr, lambda_hr,
    percentiles (p10/p50/p90), components and coverage_audit; or
    {"status": "BLOCKED", "reason": <HR_* code>} — never a point estimate on
    defaults.
    """
    bid = str(batter_id)
    ph = str(pitcher_hand or "").strip().upper()
    if ph not in ("L", "R"):
        return {"status": "BLOCKED", "reason": "HR_PITCHER_HAND_UNVERIFIED",
                "entity_id": bid}
    if not isinstance(park_hr_factors, Mapping):
        return {"status": "BLOCKED", "reason": "HR_PARK_FACTORS_NOT_SUPPLIED",
                "entity_id": bid}
    pf = _finite(park_hr_factors.get(str(home_team_name or "")))
    if pf is None or pf <= 0:
        return {"status": "BLOCKED",
                "reason": f"HR_PARK_FACTOR_MISSING:{home_team_name}",
                "entity_id": bid}
    pa_exp = _finite(pa_expected)
    if pa_exp is None or pa_exp <= 0:
        return {"status": "BLOCKED", "reason": "HR_PA_EXPECTED_INVALID",
                "entity_id": bid}

    rows = list(pitch_rows)
    platoon = batter_platoon_power(rows, bid)
    if platoon.get("status") != "AVAILABLE":
        return {"status": "BLOCKED", "reason": platoon.get("reason"),
                "entity_id": bid}
    if league_matchups is None:
        lgm = league_platoon_hr_rates(rows)
        league_matchups = lgm.get("matchups") if lgm.get(
            "status") == "AVAILABLE" else None
    reg = regressed_platoon_hr_rate(platoon, ph, league_matchups or {},
                                    batter_hand_override=batter_hand)
    if reg.get("status") != "AVAILABLE":
        return {"status": "BLOCKED", "reason": reg.get("reason"),
                "entity_id": bid}

    # League HR/PA (for the pitcher factor denominator).
    lg_pa = league_hr_per_pa
    if lg_pa is None:
        tot_pa = tot_hr = 0
        for row in rows:
            event = str(row.get("events") or "").strip()
            if event:
                tot_pa += 1
                if event == "home_run":
                    tot_hr += 1
        lg_pa = tot_hr / tot_pa if tot_pa else None
    if pitcher_hr_pa_against_override is not None:
        ov = _finite(pitcher_hr_pa_against_override)
        lgf = _finite(lg_pa)
        if ov is None or ov < 0 or lgf is None or lgf <= 0:
            return {"status": "BLOCKED",
                    "reason": "HR_PITCHER_OVERRIDE_UNVERIFIED",
                    "entity_id": bid}
        raw = ov / lgf
        pit_factor = raw  # pipeline-supplied; surfaced as-is
        pit_detail = {"status": "AVAILABLE", "source": "pipeline_override",
                      "factor": round(raw, 4)}
    else:
        pit_detail = pitcher_hr_factor(rows, pitcher_id, lg_pa or 0)
        if pit_detail.get("status") != "AVAILABLE":
            return {"status": "BLOCKED", "reason": pit_detail.get("reason"),
                    "entity_id": bid}
        pit_factor = float(pit_detail["factor"])

    lam = pa_exp * float(reg["regressed_hr_per_pa"]) * pit_factor * float(pf)
    if not math.isfinite(lam) or lam < 0:
        return {"status": "BLOCKED", "reason": "HR_LAMBDA_INVALID",
                "entity_id": bid}
    p_ge1 = 1.0 - math.exp(-lam)
    p_ge2 = 1.0 - math.exp(-lam) * (1.0 + lam)
    percentiles = poisson_quantiles(lam) if lam > 0 else {"p10": 0, "p50": 0,
                                                          "p90": 0}
    components = {
        "batter_regressed_hr_per_pa": reg["regressed_hr_per_pa"],
        "matchup": reg["matchup"],
        "matchup_obs_pa": reg["obs_pa"],
        "matchup_obs_hr": reg["obs_hr"],
        "platoon_prior_pa": reg["prior_pa"],
        "pitcher_hr_factor": round(pit_factor, 4),
        "pitcher_hr_factor_detail": pit_detail,
        "park_hr_pf": round(float(pf), 4),
        "park_team": str(home_team_name),
        "pa_expected": pa_exp,
    }
    return {
        "status": "AVAILABLE",
        "entity_id": bid,
        "lambda_hr": round(lam, 4),
        "p_ge1_hr": round(p_ge1, 4),
        "p_ge2_hr": round(p_ge2, 4),
        "percentiles": percentiles,
        # Card-renderable block (shared helper keys on market):
        "BATTER_HRS": {"mean": round(lam, 4), "percentiles": percentiles},
        "components": components,
        "coverage_audit": {
            "verified_used": ["hr_batter_platoon_power", "hr_pitcher_suppression",
                              "hr_park_component", "hr_platoon_regression"],
            "missing": [],
        },
        "engine": "mlb_hr_prop_v1",
        "schema_version": HR_SCHEMA_VERSION,
        "research_only": True,
    }


__all__ = [
    "HR_SCHEMA_VERSION",
    "HRPropError",
    "batter_platoon_power",
    "league_platoon_hr_rates",
    "regressed_platoon_hr_rate",
    "pitcher_hr_factor",
    "load_component_park_hr",
    "hr_prop_projection",
    "attach_prop_percentiles",
]
