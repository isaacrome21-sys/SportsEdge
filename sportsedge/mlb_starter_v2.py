"""MLB starter component v2 — residual adjustment on defense-blend shell.

Research only until the August one-shot gate passes (see
docs/research/mlb_starter_spec_v2_prelock.md). Constants are frozen to that
pre-lock; do not change them without a new specification and a new window.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping

from .source_lineage import canonical_json_sha256

SPEC_VERSION = "mlb_starter_v2_prelock_20260929"
RESEARCH_LABEL = "NOT_MODEL_P"

# --- Frozen constants (must match mlb_starter_spec_v2_prelock.md) ---
LEAGUE_RA9_PROXY = 4.50
K_GAIN = 1.0
SHRINKAGE_PRIOR_IP = 50.0
DEFAULT_INNINGS_SHARE = 0.55
INNINGS_SHARE_LO = 0.45
INNINGS_SHARE_HI = 0.65
MIN_MEAN_RUNS = 0.05

# FIP-style rate → RA9 weights (a priori; not fit on Aug/Sep 2026)
BB_COEF = 12.0
K_COEF = 9.0
HR_COEF = 15.0

STARTER_IDENTITY_SOURCE = "ACTUAL_STARTER_STAND_IN_NO_PREGAME_PIT_ARCHIVE"

CONSTANTS: dict[str, Any] = {
    "spec_version": SPEC_VERSION,
    "league_ra9_proxy": LEAGUE_RA9_PROXY,
    "k": K_GAIN,
    "shrinkage_prior_ip": SHRINKAGE_PRIOR_IP,
    "default_innings_share": DEFAULT_INNINGS_SHARE,
    "innings_share_clip": [INNINGS_SHARE_LO, INNINGS_SHARE_HI],
    "bb_coef": BB_COEF,
    "k_coef": K_COEF,
    "hr_coef": HR_COEF,
    "min_mean_runs": MIN_MEAN_RUNS,
    "league_rate_window": {"start": "2026-06-01", "end": "2026-07-31"},
    "evaluation_window": {"start": "2026-08-01", "end": "2026-08-31"},
    "starter_identity_source": STARTER_IDENTITY_SOURCE,
}
CONSTANTS_SHA256 = canonical_json_sha256(CONSTANTS)


class StarterV2Error(ValueError):
    pass


@dataclass(frozen=True)
class LeagueRateBaseline:
    k_rate: float
    bb_rate: float
    hr_rate: float
    total_outs: float


@dataclass(frozen=True)
class StarterPeripheralProfile:
    player_id: int
    starts: int
    total_outs: float
    k_rate: float | None
    bb_rate: float | None
    hr_rate: float | None
    mean_outs: float | None
    status: str


def constants_receipt() -> dict[str, Any]:
    return {"constants": dict(CONSTANTS), "constants_sha256": CONSTANTS_SHA256}


def starter_ra9_hat(
    *,
    k_rate: float,
    bb_rate: float,
    hr_rate: float,
    league: LeagueRateBaseline,
) -> float:
    """Fixed FIP-style mapping; no free parameters."""
    for name, value in (
        ("k_rate", k_rate),
        ("bb_rate", bb_rate),
        ("hr_rate", hr_rate),
        ("league.k_rate", league.k_rate),
        ("league.bb_rate", league.bb_rate),
        ("league.hr_rate", league.hr_rate),
    ):
        if not isfinite(value) or value < 0:
            raise StarterV2Error(f"{name} invalid")
    return (
        LEAGUE_RA9_PROXY
        + BB_COEF * (bb_rate - league.bb_rate)
        - K_COEF * (k_rate - league.k_rate)
        + HR_COEF * (hr_rate - league.hr_rate)
    )


def shrink_residual(*, residual: float, observed_ip: float) -> float:
    """Posterior mean of residual toward 0 with prior strength τ IP."""
    if not isfinite(residual):
        raise StarterV2Error("residual invalid")
    if not isfinite(observed_ip) or observed_ip < 0:
        raise StarterV2Error("observed_ip invalid")
    # weight = n / (n + τ); prior mean 0
    return residual * (observed_ip / (observed_ip + SHRINKAGE_PRIOR_IP))


def innings_share(mean_outs: float | None) -> float:
    if mean_outs is None or not isfinite(mean_outs) or mean_outs <= 0:
        return DEFAULT_INNINGS_SHARE
    return max(INNINGS_SHARE_LO, min(INNINGS_SHARE_HI, mean_outs / 27.0))


def adjust_shell_mean(
    *,
    shell: float,
    starter: StarterPeripheralProfile,
    team_runs_against_mean: float,
    league: LeagueRateBaseline,
) -> dict[str, Any]:
    """Apply residual starter effect to one side's defense-blend shell component."""
    if not isfinite(shell) or shell <= 0:
        raise StarterV2Error("shell must be finite and > 0")
    if not isfinite(team_runs_against_mean) or team_runs_against_mean <= 0:
        raise StarterV2Error("team_runs_against_mean invalid")

    if (
        starter.status != "AVAILABLE"
        or starter.k_rate is None
        or starter.bb_rate is None
        or starter.hr_rate is None
        or starter.mean_outs is None
        or starter.total_outs <= 0
    ):
        return {
            "adjusted_mean": float(shell),
            "applied": False,
            "reason": f"STARTER_NEUTRAL:{starter.status}",
            "shell": float(shell),
            "w": 0.0,
            "shrunk_residual": 0.0,
            "fractional": 0.0,
        }

    ra9_hat = starter_ra9_hat(
        k_rate=float(starter.k_rate),
        bb_rate=float(starter.bb_rate),
        hr_rate=float(starter.hr_rate),
        league=league,
    )
    # Team RA per game treated on same RA9 proxy scale as pre-lock.
    team_ra9 = float(team_runs_against_mean) * (9.0 / 9.0)  # already per-game ≈ RA9 units
    residual = ra9_hat - team_ra9
    observed_ip = float(starter.total_outs) / 3.0
    shrunk = shrink_residual(residual=residual, observed_ip=observed_ip)
    w = innings_share(starter.mean_outs)
    fractional = (shrunk / LEAGUE_RA9_PROXY) * K_GAIN
    adjusted = max(MIN_MEAN_RUNS, shell * (1.0 + w * fractional))
    return {
        "adjusted_mean": float(adjusted),
        "applied": True,
        "reason": "APPLIED",
        "shell": float(shell),
        "starter_ra9_hat": float(ra9_hat),
        "team_ra9": float(team_ra9),
        "raw_residual": float(residual),
        "shrunk_residual": float(shrunk),
        "observed_ip": float(observed_ip),
        "w": float(w),
        "fractional": float(fractional),
        "k": K_GAIN,
    }


def defense_blend_shell(*, away_runs_for: float, home_runs_against: float) -> float:
    return 0.5 * float(away_runs_for) + 0.5 * float(home_runs_against)


def starter_v2_means(
    *,
    away_runs_for: float,
    away_runs_against: float,
    home_runs_for: float,
    home_runs_against: float,
    away_starter: StarterPeripheralProfile,
    home_starter: StarterPeripheralProfile,
    league: LeagueRateBaseline,
) -> dict[str, Any]:
    """Build away/home means: defense blend + residual starter on opponent staff."""
    away_shell = defense_blend_shell(away_runs_for=away_runs_for, home_runs_against=home_runs_against)
    home_shell = defense_blend_shell(away_runs_for=home_runs_for, home_runs_against=away_runs_against)

    # Away scoring faces home starter; home scoring faces away starter.
    away_adj = adjust_shell_mean(
        shell=away_shell,
        starter=home_starter,
        team_runs_against_mean=home_runs_against,
        league=league,
    )
    home_adj = adjust_shell_mean(
        shell=home_shell,
        starter=away_starter,
        team_runs_against_mean=away_runs_against,
        league=league,
    )
    return {
        "research_version": SPEC_VERSION,
        "label": RESEARCH_LABEL,
        "promotion_evidence": False,
        "model_p_eligible": False,
        "constants_sha256": CONSTANTS_SHA256,
        "starter_identity_source": STARTER_IDENTITY_SOURCE,
        "starter_identity_pit_verified": False,
        "away_mean_runs": float(away_adj["adjusted_mean"]),
        "home_mean_runs": float(home_adj["adjusted_mean"]),
        "total_mean_runs": float(away_adj["adjusted_mean"] + home_adj["adjusted_mean"]),
        "away_shell": float(away_shell),
        "home_shell": float(home_shell),
        "away_adjustment": away_adj,
        "home_adjustment": home_adj,
        "away_starter": asdict(away_starter),
        "home_starter": asdict(home_starter),
        "league_baseline": asdict(league),
    }


def peripheral_profile_from_start_rows(
    *,
    player_id: int,
    rows: list[Mapping[str, Any]],
    window: int = 12,
    minimum: int = 3,
) -> StarterPeripheralProfile:
    """Build profile from prior start dicts with outs, so, bb, hr keys."""
    starts: list[tuple[float, float, float, float]] = []
    for row in rows:
        try:
            outs = float(row["outs"])
            so = float(row.get("strikeouts", row.get("so", 0)) or 0)
            bb = float(row.get("walks", row.get("bb", 0)) or 0)
            hr = float(row.get("home_runs", row.get("hr", 0)) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if outs <= 0 or so < 0 or bb < 0 or hr < 0:
            continue
        if not all(isfinite(x) for x in (outs, so, bb, hr)):
            continue
        starts.append((outs, so, bb, hr))
    starts = starts[-window:]
    if len(starts) < minimum:
        return StarterPeripheralProfile(int(player_id), len(starts), 0.0, None, None, None, None, "INSUFFICIENT_PRIOR_STARTS")
    total_outs = sum(r[0] for r in starts)
    if total_outs <= 0:
        return StarterPeripheralProfile(int(player_id), len(starts), 0.0, None, None, None, None, "ZERO_PRIOR_OUTS")
    # Rate per out (batters-faced proxy unavailable → per-out rates)
    k_rate = sum(r[1] for r in starts) / total_outs
    bb_rate = sum(r[2] for r in starts) / total_outs
    hr_rate = sum(r[3] for r in starts) / total_outs
    mean_outs = total_outs / len(starts)
    return StarterPeripheralProfile(
        int(player_id),
        len(starts),
        float(total_outs),
        float(k_rate),
        float(bb_rate),
        float(hr_rate),
        float(mean_outs),
        "AVAILABLE",
    )
