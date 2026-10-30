"""NFL_SCORE_COUNTS_G2 attempt 2 - model form v2 (IMPLEMENTATION ONLY).

Implements the model form frozen for design in
``~/workspace/sportsedge/g2_attempt2_preregistration_20261013/PREREGISTRATION.md``
(SHA-256 bb35cafcdc34ed2d39632ebf564af2de0879daa8e4bdc90434789aa684555a70),
under owner ruling J1 + K3 (issue #2131, Oct 13 2026):

* C1: FG leg rebuilt - decayed-PIT band shares/conversion rates (0.85
  recursion), opportunity model on 12 features (attempt-1 10 + own/opponent
  FG attempt volume).
* C2: negative-binomial dispersion on the offensive-TD and made-FG draws,
  per-leg theta selected by training-window expanding-season CV.
* C3: rare-score EB prior strength selected per fold by training-window CV
  from {25, 100, 400, LEAGUE_ONLY}.
* C4: alpha grid restored to the heritage/SPEC grid {0.1, 1, 10, 100, 1000}.
* C5b/K3: fitted key-mass component (preregistration section 4) - estimated
  inside each training fold from training games only, applied to the
  full-game PMF only, skeleton preserved.

EXECUTION STATUS: attempt 2 is NOT authorized and NOT spent (owner NO-GO for
execution, Oct 13 2026). This module contains model mathematics only; the
governed runner (scripts/run_nfl_score_counts_g2_attempt2.py) refuses to run
by construction. Nothing here reads real game data, touches any holdout, or
creates model probability for any card. Research only; authority block all
false, exactly as attempt 1.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
from math import exp, inf, lgamma, log
from typing import Any, Mapping, Sequence

import numpy as np

from sportsedge.sports.nfl.score_counts_g1 import (
    FEATURE_NAMES,
    PoissonRidge,
    choose_alpha as heritage_choose_alpha,
    fit_poisson_ridge as heritage_fit_poisson_ridge,
    predict_mean as heritage_predict_mean,
)

FAMILY = "NFL_SCORE_COUNTS_G2"
ATTEMPT_NUMBER = 2
ATTEMPT_BUDGET = 3

ROOT_SEED_LITERAL_V2 = "SportsEdge|NFL_SCORE_COUNTS_G2|ATTEMPT_2|ROOT_SEED"
ROOT_SEED_SHA256_V2 = sha256(ROOT_SEED_LITERAL_V2.encode("utf-8")).hexdigest()
ROOT_SEED_UINT64_V2 = int.from_bytes(
    sha256(ROOT_SEED_LITERAL_V2.encode("utf-8")).digest()[:8], "little")

PATHS_PER_GAME = 50000
MIN_PATHS_FOR_SCORED_OUTPUT = 10000
VALIDATION_SEASONS = (2021, 2022, 2023, 2024, 2025)
DEVELOPMENT_SEASONS = tuple(range(2018, 2026))

ALPHA_GRID_V2 = (0.1, 1.0, 10.0, 100.0, 1000.0)
ALPHA_GRID_V1_TRUNCATED = (0.1, 1.0, 10.0, 100.0)
SIGMA_GRID = (0.0, 0.10, 0.20, 0.30)
THETA_GRID = (5.0, 10.0, 20.0, 50.0, 200.0, inf)
RARE_PRIOR_GRID: tuple = (25.0, 100.0, 400.0, "LEAGUE_ONLY")
RARE_PRIOR_DEFAULT = 25.0

FG_BANDS = ((0, 29), (30, 39), (40, 49), (50, 59), (60, None))
FG_BAND_PRIOR_ATTEMPTS = 25.0
DECAY = 0.85
LOOKBACK_GAMES = 8

FG_OPPORTUNITY_FEATURES_V1 = (
    "fg_rz_trips_per_game",
    "fg_drives35_per_game",
    "fg_drives25_per_game",
    "opp_fg_rz_trips_allowed_per_game",
    "opp_fg_drives35_allowed_per_game",
    "opp_fg_drives25_allowed_per_game",
    "off_plays_per_game",
    "off_turnover_rate",
    "opp_takeaway_rate",
    "home_indicator",
)
FG_OPPORTUNITY_FEATURES_V2 = FG_OPPORTUNITY_FEATURES_V1 + (
    "fg_attempts_per_game",
    "opp_fg_attempts_allowed_per_game",
)

# K3 key-mass component (preregistration section 4.2, frozen).
K3_KEYS = (-7, -3, 3, 7)
K3_WINDOWS = {-7: (-9, -8, -6, -5), -3: (-4, -2, -1), 3: (1, 2, 4), 7: (5, 6, 8, 9)}
K3_LAMBDA_MAX = 0.50


class ScoreCountsG2V2Error(ValueError):
    """Raised for frozen-contract violations inside the v2 implementation."""


class ZeroModelRow(ScoreCountsG2V2Error):
    """ZERO_MODEL_ROW semantics (preregistration sections 2.1/2.3): the row
    cannot be priced because no league context exists."""


@dataclass(frozen=True)
class ModelFormConfig:
    """Switches that reduce v2 to the attempt-1 model form (spec-gated).

    The attempt-2 root seed is NOT switched: section 2.1 freezes a new root
    seed for attempt separation, so pathwise equality with attempt 1 is
    impossible by design; equivalence holds for the pre-simulation
    quantities (shares, rates, means, selections) under V1_COMPAT_CONFIG.
    """
    decayed_fg_shares: bool = True
    alpha_grid: tuple = ALPHA_GRID_V2
    theta_grid: tuple = THETA_GRID
    rare_prior_mode: str = "CV"          # or "FIXED" with rare_prior_fixed
    rare_prior_fixed: float = RARE_PRIOR_DEFAULT
    k3_enabled: bool = True
    opportunity_features: tuple = FG_OPPORTUNITY_FEATURES_V2


V2_CONFIG = ModelFormConfig()
V1_COMPAT_CONFIG = ModelFormConfig(
    decayed_fg_shares=False,
    alpha_grid=ALPHA_GRID_V1_TRUNCATED,
    theta_grid=(inf,),
    rare_prior_mode="FIXED",
    rare_prior_fixed=RARE_PRIOR_DEFAULT,
    k3_enabled=False,
    opportunity_features=FG_OPPORTUNITY_FEATURES_V1,
)


def child_seed_v2(game_id: str, *, root_seed: int = ROOT_SEED_UINT64_V2) -> int:
    gid = str(game_id or "").strip()
    if not gid:
        raise ScoreCountsG2V2Error("GAME_ID_REQUIRED")
    digest = sha256(f"{root_seed}:{gid}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def rng_for_v2(game_id: str, stream: str, *, root_seed: int = ROOT_SEED_UINT64_V2):
    seed = child_seed_v2(f"{game_id}|{stream}", root_seed=root_seed)
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed)))


def poisson_deviance(y: np.ndarray, mu: np.ndarray) -> float:
    mu = np.clip(np.asarray(mu, dtype=float), 1e-12, None)
    y = np.asarray(y, dtype=float)
    term = np.where(y > 0, y * np.log(y / mu) - (y - mu), mu)
    return float(2.0 * np.mean(term))


def poisson_logpmf(y: float, lam: float) -> float:
    lam = max(float(lam), 1e-12)
    return float(y * log(lam) - lam - lgamma(y + 1.0))


# ---------------------------------------------------------------------------
# Poisson ridge for non-heritage feature sets (attempt-1 G2 fitter semantics,
# carried verbatim: G1's fitter validates names against its frozen allowlist,
# so new feature sets need this equivalent estimator).
# ---------------------------------------------------------------------------

def _matrix(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> np.ndarray:
    out = []
    for idx, row in enumerate(rows):
        vals = []
        for name in feature_names:
            value = row.get(name)
            if value in (None, ""):
                raise ScoreCountsG2V2Error(f"row[{idx}].{name}:REQUIRED")
            vals.append(float(value))
        out.append(vals)
    return np.asarray(out, dtype=float)


def _target(rows: Sequence[Mapping[str, Any]], field: str) -> np.ndarray:
    vals = []
    for idx, row in enumerate(rows):
        value = float(row.get(field))
        if value < 0 or abs(value - round(value)) > 1e-9:
            raise ScoreCountsG2V2Error(f"row[{idx}].{field}:NONNEGATIVE_INTEGER_REQUIRED")
        vals.append(value)
    return np.asarray(vals, dtype=float)


def fit_poisson_ridge_v2(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    alpha: float,
    feature_names: Sequence[str],
    max_iter: int = 100,
    tol: float = 1e-10,
) -> PoissonRidge:
    x_raw = _matrix(rows, feature_names)
    y = _target(rows, target)
    mean = np.mean(x_raw, axis=0)
    scale = np.std(x_raw, axis=0, ddof=0)
    scale = np.where(scale < 1e-9, 1.0, scale)
    x = (x_raw - mean) / scale
    design = np.column_stack([np.ones(x.shape[0]), x])
    beta = np.zeros(design.shape[1], dtype=float)
    beta[0] = log(max(float(np.mean(y)), 1e-6))
    penalty = np.zeros(design.shape[1], dtype=float)
    penalty[1:] = float(alpha)
    for _ in range(max_iter):
        eta = np.clip(design @ beta, -20.0, 20.0)
        mu = np.exp(eta)
        grad = design.T @ (mu - y) + penalty * beta
        hess = design.T @ (design * mu[:, None]) + np.diag(penalty)
        hess += np.eye(hess.shape[0]) * 1e-10
        step = np.linalg.solve(hess, grad)
        beta_next = beta - step
        if float(np.max(np.abs(beta_next - beta))) <= tol:
            beta = beta_next
            break
        beta = beta_next
    return PoissonRidge(
        target=str(target),
        alpha=float(alpha),
        feature_names=tuple(str(n) for n in feature_names),
        mean=tuple(float(v) for v in mean),
        scale=tuple(float(v) for v in scale),
        intercept=float(beta[0]),
        coefficients=tuple(float(v) for v in beta[1:]),
    )


def predict_mean_v2(model: PoissonRidge, row: Mapping[str, Any]) -> float:
    x = np.asarray([float(row[name]) for name in model.feature_names], dtype=float)
    mean = np.asarray(model.mean, dtype=float)
    scale = np.asarray(model.scale, dtype=float)
    beta = np.asarray(model.coefficients, dtype=float)
    eta = float(model.intercept + ((x - mean) / scale) @ beta)
    return float(exp(max(-20.0, min(20.0, eta))))


def choose_alpha_v2(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    feature_names: Sequence[str],
    alphas: Sequence[float] = ALPHA_GRID_V2,
) -> tuple[float, dict[float, float]]:
    """Expanding-season CV on mean Poisson deviance (attempt-1 semantics);
    ties break to the smaller alpha (min by (score, alpha))."""
    seasons = sorted({int(r["season"]) for r in rows})
    if len(seasons) < 3:
        raise ScoreCountsG2V2Error("AT_LEAST_THREE_DEVELOPMENT_SEASONS_REQUIRED")
    scores: dict[float, list[float]] = {float(a): [] for a in alphas}
    for validation_season in seasons[1:]:
        train = [r for r in rows if int(r["season"]) < validation_season]
        valid = [r for r in rows if int(r["season"]) == validation_season]
        if not train or not valid:
            continue
        y = _target(valid, target)
        for alpha in scores:
            model = fit_poisson_ridge_v2(train, target=target, alpha=alpha,
                                         feature_names=feature_names)
            mu = np.asarray([predict_mean_v2(model, r) for r in valid], dtype=float)
            scores[alpha].append(poisson_deviance(y, mu))
    means = {a: float(np.mean(v)) if v else float("inf") for a, v in scores.items()}
    best = min(means, key=lambda a: (means[a], a))
    return float(best), means


# ---------------------------------------------------------------------------
# FG band accumulators: decayed-PIT (v2, section 2.3) and cumulative
# full-history (attempt-1 semantics, used only under V1_COMPAT_CONFIG).
# A team's accumulator updates once per completed team-game of that team:
# acc <- decay * acc + counts_j (chronological order). League accumulators
# are the elementwise sum over teams of their current accumulators.
# ---------------------------------------------------------------------------

class BandBook:
    def __init__(self, *, decayed: bool, decay: float = DECAY):
        self.decayed = bool(decayed)
        self.decay = float(decay)
        self.team_att: dict[str, list[float]] = defaultdict(lambda: [0.0] * 5)
        self.team_made: dict[str, list[float]] = defaultdict(lambda: [0.0] * 5)

    def snapshot(self, team: str) -> dict[str, list[float]]:
        league_att = [0.0] * 5
        league_made = [0.0] * 5
        for t, att in self.team_att.items():
            made = self.team_made[t]
            for b in range(5):
                league_att[b] += att[b]
                league_made[b] += made[b]
        return {
            "team_attempts": list(self.team_att[str(team)]),
            "team_makes": list(self.team_made[str(team)]),
            "league_attempts": league_att,
            "league_makes": league_made,
        }

    def update(self, team: str, att_band: Sequence[float], made_band: Sequence[float]) -> None:
        team = str(team)
        factor = self.decay if self.decayed else 1.0
        att = self.team_att[team]
        made = self.team_made[team]
        for b in range(5):
            att[b] = factor * att[b] + float(att_band[b])
            made[b] = factor * made[b] + float(made_band[b])


def band_shares_rates_v2(snapshot: Mapping[str, Sequence[float]]) -> tuple[list[float], list[float]]:
    """Decayed-PIT shares/rates (preregistration section 2.3, frozen).

    share_b = (A_b + 25 * league_share_b) / (A_tot + 25);
    rate_b  = (M_b + 25 * league_rate_b) / (A_b + 25).
    Fallbacks: LA_tot = 0 -> ZERO_MODEL_ROW; LA_b = 0 -> league_rate_b is the
    pooled decayed league make rate over all bands.
    """
    team_att = [float(v) for v in snapshot["team_attempts"]]
    team_made = [float(v) for v in snapshot["team_makes"]]
    league_att = [float(v) for v in snapshot["league_attempts"]]
    league_made = [float(v) for v in snapshot["league_makes"]]
    la_tot = sum(league_att)
    if la_tot <= 0:
        raise ZeroModelRow("ZERO_MODEL_ROW:NO_LEAGUE_BAND_CONTEXT")
    a_tot = sum(team_att)
    pooled_rate = sum(league_made) / la_tot
    shares: list[float] = []
    rates: list[float] = []
    for b in range(5):
        league_share = league_att[b] / la_tot
        shares.append((team_att[b] + FG_BAND_PRIOR_ATTEMPTS * league_share)
                      / (a_tot + FG_BAND_PRIOR_ATTEMPTS))
        league_rate = (league_made[b] / league_att[b]) if league_att[b] > 0 else pooled_rate
        rates.append((team_made[b] + FG_BAND_PRIOR_ATTEMPTS * league_rate)
                     / (team_att[b] + FG_BAND_PRIOR_ATTEMPTS))
    return shares, rates


def band_shares_rates_v1(snapshot: Mapping[str, Sequence[float]]) -> tuple[list[float], list[float]]:
    """Attempt-1 formula verbatim (full-history counts; league_share fallback
    0.2, league_rate fallback 0.0). Used only under V1_COMPAT_CONFIG."""
    team_att = [float(v) for v in snapshot["team_attempts"]]
    team_made = [float(v) for v in snapshot["team_makes"]]
    league_att = [float(v) for v in snapshot["league_attempts"]]
    league_made = [float(v) for v in snapshot["league_makes"]]
    total_league = sum(league_att)
    total_team = sum(team_att)
    shares: list[float] = []
    rates: list[float] = []
    for b in range(5):
        league_share = (league_att[b] / total_league) if total_league > 0 else 0.2
        shares.append((team_att[b] + FG_BAND_PRIOR_ATTEMPTS * league_share)
                      / (total_team + FG_BAND_PRIOR_ATTEMPTS))
        league_rate = (league_made[b] / league_att[b]) if league_att[b] > 0 else 0.0
        rates.append((team_made[b] + FG_BAND_PRIOR_ATTEMPTS * league_rate)
                     / (team_att[b] + FG_BAND_PRIOR_ATTEMPTS))
    return shares, rates


def band_snapshot_from_row(row: Mapping[str, Any], *, decayed: bool) -> dict[str, list[float]]:
    prefix = "decayed" if decayed else "pit"
    return {
        "team_attempts": [float(v) for v in row[f"{prefix}_team_band_attempts"]],
        "team_makes": [float(v) for v in row[f"{prefix}_team_band_makes"]],
        "league_attempts": [float(v) for v in row[f"{prefix}_league_band_attempts"]],
        "league_makes": [float(v) for v in row[f"{prefix}_league_band_makes"]],
    }


def band_shares_rates(row: Mapping[str, Any], config: ModelFormConfig) -> tuple[list[float], list[float]]:
    snap = band_snapshot_from_row(row, decayed=config.decayed_fg_shares)
    if config.decayed_fg_shares:
        return band_shares_rates_v2(snap)
    return band_shares_rates_v1(snap)


def row_has_band_context(row: Mapping[str, Any], config: ModelFormConfig) -> bool:
    """False exactly when the row is a ZERO_MODEL_ROW under section 2.3:
    no league band context exists yet (only possible in the development
    window's first kickoff batch). The evaluation driver excludes such
    rows/games from scoring and counts the exclusions; the mathematics
    itself stays fail-closed (band_shares_rates_v2 raises)."""
    snap = band_snapshot_from_row(row, decayed=config.decayed_fg_shares)
    return sum(float(v) for v in snap["league_attempts"]) > 0


def banded_made_fg_mean(opportunity_model: PoissonRidge, row: Mapping[str, Any],
                        config: ModelFormConfig) -> float:
    opportunity = predict_mean_v2(opportunity_model, row)
    shares, rates = band_shares_rates(row, config)
    return float(opportunity * sum(s * r for s, r in zip(shares, rates)))


def banded_made_fg_detail(opportunity_model: PoissonRidge, row: Mapping[str, Any],
                          config: ModelFormConfig) -> dict[str, Any]:
    opportunity = predict_mean_v2(opportunity_model, row)
    shares, rates = band_shares_rates(row, config)
    bands = []
    for b, (lo, hi) in enumerate(FG_BANDS):
        bands.append({
            "band": f"{lo}-{hi}" if hi is not None else f"{lo}+",
            "expected_attempts": float(opportunity * shares[b]),
            "conversion_rate": float(rates[b]),
            "expected_makes": float(opportunity * shares[b] * rates[b]),
        })
    return {"opportunity_mean": float(opportunity), "bands": bands,
            "made_fg_mean": float(sum(b["expected_makes"] for b in bands))}


# ---------------------------------------------------------------------------
# Row enrichment: heritage rows + G2 aggregates -> v2 model rows.
# Ordering discipline is attempt-1's, TIGHTENED at exactly one point per
# preregistration section 2.3 ("kickoff strictly before") and the Oct 13
# audit: games sharing a kickoff timestamp (heritage field game_start_ts,
# required, fail-closed) are batched - every game in a kickoff batch is
# emitted from the pre-batch state and updates apply only after the batch,
# so tied games never contribute to each other's inputs. Attempt 1 updated
# accumulators game-by-game in arrival order. Emits BOTH band snapshots:
# cumulative full-history (pit_*, attempt-1) and decayed (decayed_*, v2).
# Total FG attempts per team-game: agg["fg_attempts_total"] when the
# aggregate carries it (count of field_goal_attempt-flagged rows); otherwise
# derived as distance-evidenced attempts + missing-distance attempts (the
# attempt-1 aggregate's attempt rows all carry field_goal_result).
# ---------------------------------------------------------------------------

def _weighted(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    n = len(values)
    weights = [DECAY ** (n - 1 - i) for i in range(n)]
    return float(sum(w * v for w, v in zip(weights, values)) / sum(weights))


def _agg_total_attempts(agg: Mapping[str, Any]) -> int:
    if agg.get("fg_attempts_total") is not None:
        return int(agg["fg_attempts_total"])
    return int(sum(agg["fg_att_band"])) + int(agg["fg_att_missing_dist"])


def _game_start_ts(pair: Sequence[Mapping[str, Any]], gid: str) -> str:
    """The heritage rows' kickoff field. Required (fail-closed): without a
    kickoff, the strictly-before accumulation rule of section 2.3 cannot be
    enforced."""
    values = {str(r.get("game_start_ts") or "").strip() for r in pair}
    if len(values) != 1 or not next(iter(values)):
        raise ScoreCountsG2V2Error(f"GAME_START_TS_REQUIRED:{gid}")
    return next(iter(values))


def build_g2_rows_v2(
    heritage_rows: Sequence[Mapping[str, Any]],
    g2_agg: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [dict(r) for r in heritage_rows]
    games: list[tuple[str, list[dict[str, Any]]]] = []
    for row in rows:
        gid = str(row["game_id"])
        if games and games[-1][0] == gid:
            games[-1][1].append(row)
        else:
            games.append((gid, [row]))

    hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=LOOKBACK_GAMES))
    decayed_book = BandBook(decayed=True)
    cumulative_book = BandBook(decayed=False)

    def _emit_game(gid: str, pair: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(pair) != 2:
            raise ScoreCountsG2V2Error(f"GAME_PAIR_REQUIRED:{gid}:{len(pair)}")
        enriched: list[dict[str, Any]] = []
        for row in pair:
            team = str(row["team"])
            opp = str(row["opponent"])
            own_hist = list(hist[team])
            opp_hist = list(hist[opp])
            row["fg_rz_trips_per_game"] = _weighted([h["rz_trips"] for h in own_hist])
            row["fg_drives35_per_game"] = _weighted([h["drives35"] for h in own_hist])
            row["fg_drives25_per_game"] = _weighted([h["drives25"] for h in own_hist])
            row["opp_fg_rz_trips_allowed_per_game"] = _weighted([h["def_rz_trips"] for h in opp_hist])
            row["opp_fg_drives35_allowed_per_game"] = _weighted([h["def_drives35"] for h in opp_hist])
            row["opp_fg_drives25_allowed_per_game"] = _weighted([h["def_drives25"] for h in opp_hist])
            row["fg_attempts_per_game"] = _weighted([h["fg_attempts_total"] for h in own_hist])
            row["opp_fg_attempts_allowed_per_game"] = _weighted(
                [h["fg_attempts_allowed"] for h in opp_hist])
            snap_d = decayed_book.snapshot(team)
            snap_c = cumulative_book.snapshot(team)
            row["decayed_team_band_attempts"] = snap_d["team_attempts"]
            row["decayed_team_band_makes"] = snap_d["team_makes"]
            row["decayed_league_band_attempts"] = snap_d["league_attempts"]
            row["decayed_league_band_makes"] = snap_d["league_makes"]
            row["pit_team_band_attempts"] = [int(v) for v in snap_c["team_attempts"]]
            row["pit_team_band_makes"] = [int(v) for v in snap_c["team_makes"]]
            row["pit_league_band_attempts"] = [int(v) for v in snap_c["league_attempts"]]
            row["pit_league_band_makes"] = [int(v) for v in snap_c["league_makes"]]
            for q in (1, 2, 3, 4):
                row[f"q{q}_off_td_per_game"] = _weighted([h["quarters"][q]["off_td"] for h in own_hist])
                row[f"q{q}_off_fg_per_game"] = _weighted([h["quarters"][q]["made_fg"] for h in own_hist])
                row[f"q{q}_def_td_allowed_per_game"] = _weighted(
                    [h["def_quarters"][q]["off_td_allowed"] for h in opp_hist])
                row[f"q{q}_fg_allowed_per_game"] = _weighted(
                    [h["def_quarters"][q]["fg_allowed"] for h in opp_hist])
            agg = g2_agg.get((gid, team))
            if agg is None:
                raise ScoreCountsG2V2Error(f"G2_AGGREGATE_MISSING:{gid}:{team}")
            row["fg_att_band"] = [int(v) for v in agg["fg_att_band"]]
            row["fg_made_band"] = [int(v) for v in agg["fg_made_band"]]
            row["fg_attempts_with_distance"] = int(sum(agg["fg_att_band"]))
            row["fg_attempts_missing_distance"] = int(agg["fg_att_missing_dist"])
            row["fg_makes_missing_distance"] = int(agg["fg_made_missing_dist"])
            row["fg_attempts_total"] = _agg_total_attempts(agg)
            for q in (1, 2, 3, 4):
                qq = agg["quarters"][q]
                row[f"q{q}_off_td"] = int(qq["off_td"])
                row[f"q{q}_made_fg"] = int(qq["made_fg"])
                row[f"q{q}_def_td"] = int(qq["def_td"])
                row[f"q{q}_safeties"] = int(qq["safeties"])
                row[f"q{q}_points"] = int(
                    6 * (qq["off_td"] + qq["def_td"]) + qq["pat"] + 2 * qq["two_pt"]
                    + 3 * qq["made_fg"] + 2 * qq["safeties"])
            enriched.append(row)
        return enriched

    def _apply_updates(gid: str, pair: list[dict[str, Any]]) -> None:
        # Update history + band books only after the whole game is emitted.
        totals = {str(r["team"]): int(r["fg_attempts_total"]) for r in pair}
        for row in pair:
            team = str(row["team"])
            opp = str(row["opponent"])
            agg = g2_agg[(gid, team)]
            entry = dict(agg)
            entry["fg_attempts_total"] = totals[team]
            entry["fg_attempts_allowed"] = totals[opp]
            hist[team].append(entry)
            decayed_book.update(team, agg["fg_att_band"], agg["fg_made_band"])
            cumulative_book.update(team, agg["fg_att_band"], agg["fg_made_band"])

    # Same-kickoff batching (section 2.3 + audit item 1): accumulators
    # include exactly the team-games with kickoff STRICTLY BEFORE the target
    # game's kickoff. Games sharing a kickoff timestamp are all emitted from
    # the pre-batch state and their updates apply only after the whole batch
    # is emitted; the game_id ordering inside a batch is processing order
    # only and never an information flow.
    out: list[dict[str, Any]] = []
    idx = 0
    while idx < len(games):
        ts = _game_start_ts(games[idx][1], games[idx][0])
        batch: list[tuple[str, list[dict[str, Any]]]] = []
        while idx < len(games) and _game_start_ts(games[idx][1], games[idx][0]) == ts:
            batch.append(games[idx])
            idx += 1
        for gid, pair in batch:
            out.extend(_emit_game(gid, pair))
        for gid, pair in batch:
            _apply_updates(gid, pair)
    return out


# ---------------------------------------------------------------------------
# Rare-score legs: PIT empirical-Bayes rates + CV-selected prior (C3).
# Rates are computed from strictly-prior games only: state is seeded by the
# training rows (in order) and each evaluation game is scored before its own
# outcomes enter the state. The prior SELECTION uses training rows only.
# ---------------------------------------------------------------------------

def _pairs(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, list[Mapping[str, Any]]]]:
    games: list[tuple[str, list[Mapping[str, Any]]]] = []
    for row in rows:
        gid = str(row["game_id"])
        if games and games[-1][0] == gid:
            games[-1][1].append(row)
        else:
            games.append((gid, [row]))
    return games


def league_rare_rates(rows: Sequence[Mapping[str, Any]], *,
                      def_field: str = "def_st_touchdowns",
                      saf_field: str = "safeties") -> tuple[float, float]:
    n = len(rows)
    if n == 0:
        return 0.0, 0.0
    def_rate = sum(float(r[def_field]) for r in rows) / n
    saf_rate = sum(float(r[saf_field]) for r in rows) / n
    return float(def_rate), float(saf_rate)


def pit_eb_rates(
    train_rows: Sequence[Mapping[str, Any]],
    eval_rows: Sequence[Mapping[str, Any]],
    *,
    prior: float,
    def_field: str = "def_st_touchdowns",
    saf_field: str = "safeties",
) -> list[tuple[float, float]]:
    """Per-eval-row (def_rate, saf_rate) under EB prior `prior`.

    rate = (team_events + prior * league_rate) / (team_games + prior), with
    league and team counts over strictly-prior team-games (training rows
    first, then earlier evaluation games in chronological order).
    """
    team_events: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    league = [0.0, 0.0, 0.0]  # def events, saf events, team-games

    def _update(row: Mapping[str, Any]) -> None:
        team = str(row["team"])
        d = float(row[def_field])
        s = float(row[saf_field])
        te = team_events[team]
        te[0] += d
        te[1] += s
        te[2] += 1.0
        league[0] += d
        league[1] += s
        league[2] += 1.0

    def _batches(rows: Sequence[Mapping[str, Any]]) -> list[list[tuple[str, list]]]:
        """Consecutive games grouped by kickoff (game_start_ts). Same-kickoff
        games never contribute to each other's rates: rates for a whole batch
        are computed from the pre-batch state, then the batch's outcomes
        update the state. Rows without a kickoff form singleton batches."""
        grouped: list[list[tuple[str, list]]] = []
        last_ts: str | None = None
        for gid, pair in _pairs(rows):
            ts = str(pair[0].get("game_start_ts") or "")
            if grouped and ts and ts == last_ts:
                grouped[-1].append((gid, pair))
            else:
                grouped.append([(gid, pair)])
            last_ts = ts
        return grouped

    for batch in _batches(train_rows):
        for _gid, pair in batch:
            for row in pair:
                _update(row)
    out: list[tuple[float, float]] = []
    for batch in _batches(eval_rows):
        for _gid, pair in batch:
            for row in pair:
                team = str(row["team"])
                te = team_events[team]
                league_def = league[0] / league[2] if league[2] else 0.0
                league_saf = league[1] / league[2] if league[2] else 0.0
                def_rate = (te[0] + prior * league_def) / (te[2] + prior)
                saf_rate = (te[1] + prior * league_saf) / (te[2] + prior)
                out.append((float(def_rate), float(saf_rate)))
        for _gid, pair in batch:
            for row in pair:
                _update(row)
    return out


def select_rare_prior(
    train_rows: Sequence[Mapping[str, Any]],
    config: ModelFormConfig,
) -> tuple[Any, dict[str, float]]:
    """Per-fold prior selection (section 2.4): expanding-season CV inside the
    training window on the rare-event Poisson log score; pooled mean over
    held-out training games; ties break to the LARGER prior (LEAGUE_ONLY
    counts as largest). Selection never touches the validation fold."""
    if config.rare_prior_mode == "FIXED":
        return config.rare_prior_fixed, {}
    seasons = sorted({int(r["season"]) for r in train_rows})
    if len(seasons) < 2:
        raise ScoreCountsG2V2Error("RARE_PRIOR_CV_REQUIRES_TWO_SEASONS")
    totals: dict[Any, list[float]] = {p: [0.0, 0.0] for p in RARE_PRIOR_GRID}  # ll, n
    for vs in seasons[1:]:
        inner_train = [r for r in train_rows if int(r["season"]) < vs]
        inner_valid = [r for r in train_rows if int(r["season"]) == vs]
        if not inner_train or not inner_valid:
            continue
        league_def, league_saf = league_rare_rates(inner_train)
        league_only_lam = league_def + league_saf
        for prior in RARE_PRIOR_GRID:
            if prior == "LEAGUE_ONLY":
                lams = [league_only_lam] * len(inner_valid)
            else:
                rates = pit_eb_rates(inner_train, inner_valid, prior=float(prior))
                lams = [d + s for d, s in rates]
            ll = 0.0
            for row, lam in zip(inner_valid, lams):
                y = float(row["def_st_touchdowns"]) + float(row["safeties"])
                ll += poisson_logpmf(y, lam)
            totals[prior][0] += ll
            totals[prior][1] += len(inner_valid)
    scores = {
        str(p): (v[0] / v[1] if v[1] else float("-inf")) for p, v in totals.items()
    }
    rank = {p: i for i, p in enumerate(RARE_PRIOR_GRID)}
    best = max(RARE_PRIOR_GRID, key=lambda p: (scores[str(p)], rank[p]))
    return best, scores


# ---------------------------------------------------------------------------
# Negative-binomial dispersion (C2, preregistration section 3).
# ---------------------------------------------------------------------------

def nb_logpmf(y: float, mu: float, theta: float) -> float:
    if theta == inf:
        return poisson_logpmf(y, mu)
    mu = max(float(mu), 1e-12)
    theta = float(theta)
    out = (lgamma(y + theta) - lgamma(theta) - lgamma(y + 1.0)
           + theta * log(theta / (theta + mu)))
    if y > 0:
        out += y * log(mu / (theta + mu))
    return float(out)


def draw_count(rng: np.random.Generator, mu: Any, theta: float) -> np.ndarray:
    """NB draw with variance mu + mu^2/theta; theta = inf is exactly the
    attempt-1 Poisson draw (same generator call)."""
    mu_arr = np.asarray(mu, dtype=float)
    if theta == inf:
        return rng.poisson(mu_arr)
    theta = float(theta)
    return rng.negative_binomial(theta, theta / (theta + mu_arr))


def select_theta_cv(
    inner_folds: Sequence[tuple[Sequence[float], Sequence[float]]],
    grid: Sequence[float] = THETA_GRID,
) -> tuple[float, dict[str, float]]:
    """Pooled mean NB log-pmf over held-out training games (section 3);
    ties break to the larger theta (least dispersion)."""
    scores: dict[str, float] = {}
    for theta in grid:
        ll = 0.0
        n = 0
        for mus, ys in inner_folds:
            for mu, y in zip(mus, ys):
                ll += nb_logpmf(float(y), float(mu), float(theta))
                n += 1
        scores[str(theta)] = ll / n if n else float("-inf")
    best = max(grid, key=lambda t: (scores[str(t)], float(t)))
    return float(best), scores


def period_feature_names(quarter: int) -> tuple[str, ...]:
    return (
        f"q{quarter}_off_td_per_game",
        f"q{quarter}_off_fg_per_game",
        f"q{quarter}_def_td_allowed_per_game",
        f"q{quarter}_fg_allowed_per_game",
        "off_plays_per_game",
        "home_indicator",
    )


def _fit_leg_mean(rows: Sequence[Mapping[str, Any]], leg: str,
                  config: ModelFormConfig, alpha: float):
    """Fit one leg's mean model on `rows` at a GIVEN alpha; returns the
    predict function. Alpha selection itself lives in fit_fold_bundle (the
    leg's frozen CV procedure on the full training window)."""
    if leg == "TD":
        model = heritage_fit_poisson_ridge(
            rows, target="offense_touchdowns", alpha=float(alpha),
            feature_names=FEATURE_NAMES)
        return lambda r: heritage_predict_mean(model, r)
    if leg == "FG":
        model = fit_poisson_ridge_v2(
            rows, target="fg_attempts_with_distance", alpha=float(alpha),
            feature_names=config.opportunity_features)
        return lambda r: banded_made_fg_mean(model, r, config)
    if leg.startswith("TD_Q"):
        q = int(leg[-1])
        model = fit_poisson_ridge_v2(rows, target=f"q{q}_off_td",
                                     alpha=float(alpha),
                                     feature_names=period_feature_names(q))
        return lambda r: predict_mean_v2(model, r)
    if leg.startswith("FG_Q"):
        q = int(leg[-1])
        model = fit_poisson_ridge_v2(rows, target=f"q{q}_made_fg",
                                     alpha=float(alpha),
                                     feature_names=period_feature_names(q))
        return lambda r: predict_mean_v2(model, r)
    raise ScoreCountsG2V2Error(f"UNKNOWN_LEG:{leg}")


def _leg_target(leg: str) -> str:
    if leg == "TD":
        return "offense_touchdowns"
    if leg == "FG":
        return "made_field_goals"
    if leg.startswith("TD_Q"):
        return f"q{leg[-1]}_off_td"
    if leg.startswith("FG_Q"):
        return f"q{leg[-1]}_made_fg"
    raise ScoreCountsG2V2Error(f"UNKNOWN_LEG:{leg}")


def select_theta_for_leg(
    train_rows: Sequence[Mapping[str, Any]], leg: str,
    config: ModelFormConfig, *, mean_alpha: float,
) -> tuple[float, dict[str, float]]:
    """Per-fold, per-leg theta by expanding-season CV inside the training
    window only (section 3). The mean fit does not involve theta: inner
    mean models are fit at the leg's training-window alpha (the frozen
    alpha-selection procedure's output for this fold), so the inner
    windows - which can hold fewer than the heritage selector's 3-season
    floor - need no nested alpha selection, and the theta comparison is
    over identical means for every candidate theta."""
    if tuple(config.theta_grid) == (inf,):
        return inf, {}
    seasons = sorted({int(r["season"]) for r in train_rows})
    if len(seasons) < 2:
        raise ScoreCountsG2V2Error("THETA_CV_REQUIRES_TWO_SEASONS")
    target = _leg_target(leg)
    inner_folds: list[tuple[list[float], list[float]]] = []
    for vs in seasons[1:]:
        inner_train = [r for r in train_rows if int(r["season"]) < vs]
        inner_valid = [r for r in train_rows if int(r["season"]) == vs]
        if not inner_train or not inner_valid:
            continue
        predict = _fit_leg_mean(inner_train, leg, config, mean_alpha)
        mus = [predict(r) for r in inner_valid]
        ys = [float(r[target]) for r in inner_valid]
        inner_folds.append((mus, ys))
    return select_theta_cv(inner_folds, config.theta_grid)


# ---------------------------------------------------------------------------
# Simulation. Structure mirrors attempt-1 simulate_full_game /
# simulate_period_game exactly (single shared mean-preserving lognormal
# latent per path; identical draw order), with two preregistered changes:
# the offensive-TD and made-FG draws are negative-binomial with the fitted
# per-leg theta (theta = inf reproduces the attempt-1 Poisson draw through
# the same generator call), and the rare-score rates are supplied by the
# caller (fold-selected prior, section 2.4) instead of read from row fields.
# ---------------------------------------------------------------------------

def _conversions_g2(rng: np.random.Generator, touchdowns: np.ndarray,
                    probabilities: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    pat_p, two_p, no_p = probabilities
    pats = rng.binomial(touchdowns, pat_p)
    remaining = touchdowns - pats
    mass = two_p + no_p
    p_two = 0.0 if mass <= 0 else two_p / mass
    twos = rng.binomial(remaining, p_two)
    return pats.astype(int), twos.astype(int)


def _conversion_probs(row: Mapping[str, Any]) -> tuple[float, float, float]:
    return (
        float(row["conversion_pat_p"]), float(row["conversion_two_p"]),
        float(row["conversion_no_p"]),
    )


def _latent(rng: np.random.Generator, sigma: float, paths: int) -> np.ndarray:
    if sigma == 0.0:
        return np.ones(paths)
    return rng.lognormal(mean=-0.5 * sigma * sigma, sigma=sigma, size=paths)


def simulate_full_game_v2(
    bundle: Mapping[str, Any], *, game_id: str,
    home_row: Mapping[str, Any], away_row: Mapping[str, Any],
    home_rates: tuple[float, float], away_rates: tuple[float, float],
    sigma: float, paths: int = PATHS_PER_GAME,
) -> dict[str, Any]:
    config: ModelFormConfig = bundle["config"]
    rng = rng_for_v2(game_id, "FULL")
    td_model = bundle["td_model"]
    fg_model = bundle["fg_opportunity_model"]
    h_td = heritage_predict_mean(td_model, home_row)
    a_td = heritage_predict_mean(td_model, away_row)
    h_fg = banded_made_fg_mean(fg_model, home_row, config)
    a_fg = banded_made_fg_mean(fg_model, away_row, config)
    latent = _latent(rng, sigma, paths)
    theta_td = float(bundle["thetas"]["TD"])
    theta_fg = float(bundle["thetas"]["FG"])
    h_off = draw_count(rng, h_td * latent, theta_td)
    a_off = draw_count(rng, a_td * latent, theta_td)
    h_fg_n = draw_count(rng, h_fg * latent, theta_fg)
    a_fg_n = draw_count(rng, a_fg * latent, theta_fg)
    h_dst = rng.poisson(float(home_rates[0]), size=paths)
    a_dst = rng.poisson(float(away_rates[0]), size=paths)
    h_saf = rng.poisson(float(home_rates[1]), size=paths)
    a_saf = rng.poisson(float(away_rates[1]), size=paths)
    h_td_tot = h_off + h_dst
    a_td_tot = a_off + a_dst
    h_pat, h_two = _conversions_g2(rng, h_td_tot, _conversion_probs(home_row))
    a_pat, a_two = _conversions_g2(rng, a_td_tot, _conversion_probs(away_row))
    home_score = 6 * h_td_tot + h_pat + 2 * h_two + 3 * h_fg_n + 2 * h_saf
    away_score = 6 * a_td_tot + a_pat + 2 * a_two + 3 * a_fg_n + 2 * a_saf
    return {
        "home_score": home_score, "away_score": away_score,
        "means": {"home_td": h_td, "away_td": a_td, "home_fg": h_fg, "away_fg": a_fg},
    }


def simulate_period_game_v2(
    bundle: Mapping[str, Any], *, game_id: str,
    home_row: Mapping[str, Any], away_row: Mapping[str, Any],
    home_period_rates: Mapping[int, tuple[float, float]],
    away_period_rates: Mapping[int, tuple[float, float]],
    sigma: float, paths: int = PATHS_PER_GAME,
) -> dict[str, Any]:
    """Per-quarter path set on ONE shared latent; halves are quarter sums.
    Period legs use their own fitted thetas (section 2.6 + section 3)."""
    rng = rng_for_v2(game_id, "PERIOD")
    latent = _latent(rng, sigma, paths)
    home_points: dict[int, np.ndarray] = {}
    away_points: dict[int, np.ndarray] = {}
    for q in (1, 2, 3, 4):
        pm = bundle["period"][q]
        theta_td = float(bundle["thetas"][f"TD_Q{q}"])
        theta_fg = float(bundle["thetas"][f"FG_Q{q}"])
        h_td = draw_count(rng, predict_mean_v2(pm["td_model"], home_row) * latent, theta_td)
        a_td = draw_count(rng, predict_mean_v2(pm["td_model"], away_row) * latent, theta_td)
        h_fg = draw_count(rng, predict_mean_v2(pm["fg_model"], home_row) * latent, theta_fg)
        a_fg = draw_count(rng, predict_mean_v2(pm["fg_model"], away_row) * latent, theta_fg)
        h_dst = rng.poisson(float(home_period_rates[q][0]), size=paths)
        a_dst = rng.poisson(float(away_period_rates[q][0]), size=paths)
        h_saf = rng.poisson(float(home_period_rates[q][1]), size=paths)
        a_saf = rng.poisson(float(away_period_rates[q][1]), size=paths)
        h_tot = h_td + h_dst
        a_tot = a_td + a_dst
        h_pat, h_two = _conversions_g2(rng, h_tot, _conversion_probs(home_row))
        a_pat, a_two = _conversions_g2(rng, a_tot, _conversion_probs(away_row))
        home_points[q] = 6 * h_tot + h_pat + 2 * h_two + 3 * h_fg + 2 * h_saf
        away_points[q] = 6 * a_tot + a_pat + 2 * a_two + 3 * a_fg + 2 * a_saf
    return {
        "home_points": home_points, "away_points": away_points,
        "first_half_home": home_points[1] + home_points[2],
        "first_half_away": away_points[1] + away_points[2],
        "second_half_home": home_points[3] + home_points[4],
        "second_half_away": away_points[3] + away_points[4],
    }


# ---------------------------------------------------------------------------
# PMF helpers (attempt-1 semantics verbatim).
# ---------------------------------------------------------------------------

def realized_final_score(row: Mapping[str, Any]) -> int:
    return int(
        6 * (int(row["offense_touchdowns"]) + int(row["def_st_touchdowns"]))
        + int(row["pat_made"]) + 2 * int(row["two_point_made"])
        + 3 * int(row["made_field_goals"]) + 2 * int(row["safeties"])
    )


def game_pairs(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["game_id"])].append(row)
    out = {}
    for gid, pair in grouped.items():
        if len(pair) != 2:
            raise ScoreCountsG2V2Error(f"GAME_PAIR_REQUIRED:{gid}:{len(pair)}")
        home = [r for r in pair if float(r["home_indicator"]) == 1.0]
        away = [r for r in pair if float(r["home_indicator"]) == 0.0]
        if len(home) != 1 or len(away) != 1:
            raise ScoreCountsG2V2Error(f"HOME_AWAY_PAIR_REQUIRED:{gid}")
        out[gid] = (home[0], away[0])
    return out


def pmf_counts(home: np.ndarray, away: np.ndarray) -> dict[tuple[int, int], int]:
    keys, counts = np.unique(
        np.asarray(home, dtype=int) * 1000 + np.asarray(away, dtype=int), return_counts=True
    )
    return {(int(k) // 1000, int(k) % 1000): int(c) for k, c in zip(keys, counts)}


def pmf_from_counts(counts: Mapping[tuple[int, int], int], total: int) -> dict[tuple[int, int], float]:
    if total <= 0:
        raise ScoreCountsG2V2Error("PMF_TOTAL_REQUIRED")
    return {k: v / total for k, v in counts.items()}


def log_score(counts: Mapping[tuple[int, int], int], total: int, realized: tuple[int, int],
              paths: int) -> float:
    p = counts.get(realized, 0) / total if total else 0.0
    floor = 0.5 / paths
    return float(log(max(p, floor)))


def log_score_pmf(pmf: Mapping[tuple[int, int], float], realized: tuple[int, int],
                  paths: int) -> float:
    floor = 0.5 / paths
    return float(log(max(float(pmf.get(realized, 0.0)), floor)))


def randomized_pit(samples: np.ndarray, realized: int, rng: np.random.Generator) -> float:
    below = float(np.mean(samples < realized))
    equal = float(np.mean(samples == realized))
    return below + float(rng.random()) * equal


def joint_distribution_sha256(counts: Mapping[tuple[int, int], int]) -> str:
    import json as _json
    canonical = _json.dumps(
        [[h, a, int(c)] for (h, a), c in sorted(counts.items())],
        separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# K3 fitted key-mass component (preregistration section 4). Estimation uses
# the fold's TRAINING games only: the fold model simulates its own training
# games (skeleton PMFs), and lambda is estimated from those simulations plus
# the training games' realized margins. Application moves mass from each
# key's frozen source window toward the key itself, one-directionally,
# preserving total probability and within-margin composition exactly.
# ---------------------------------------------------------------------------

def margin_law(pmf: Mapping[tuple[int, int], float]) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for (h, a), p in pmf.items():
        out[int(h) - int(a)] += float(p)
    return dict(out)


def estimate_k3_lambdas(
    skeleton_pmfs: Sequence[Mapping[tuple[int, int], float]],
    realized_margins: Sequence[int],
) -> dict[str, Any]:
    if len(skeleton_pmfs) != len(realized_margins) or not skeleton_pmfs:
        raise ScoreCountsG2V2Error("K3_ESTIMATION_INPUTS_REQUIRED")
    laws = [margin_law(p) for p in skeleton_pmfs]
    n = len(laws)
    lambdas: dict[int, float] = {}
    detail: dict[str, Any] = {}
    for k in K3_KEYS:
        s_key = sum(law.get(k, 0.0) for law in laws) / n
        s_win = sum(sum(law.get(m, 0.0) for m in K3_WINDOWS[k]) for law in laws) / n
        r_key = sum(1 for m in realized_margins if int(m) == k) / n
        if s_win <= 0.0:
            lam = 0.0
        else:
            lam = min(max((r_key - s_key) / s_win, 0.0), K3_LAMBDA_MAX)
        lambdas[k] = float(lam)
        detail[str(k)] = {
            "skeleton_mean_key_mass": float(s_key),
            "skeleton_mean_window_mass": float(s_win),
            "realized_key_fraction": float(r_key),
            "lambda": float(lam),
        }
    return {"lambdas": lambdas, "detail": detail, "n_training_games": n}


def apply_k3(
    pmf: Mapping[tuple[int, int], float],
    lambdas: Mapping[int, float],
) -> dict[tuple[int, int], float]:
    """Apply the frozen transfer. Windows and keys are mutually disjoint
    across keys, so per-key transfers do not interact. Corner rule: if the
    skeleton mass at the key is exactly 0 (or the window mass is 0), no
    transfer occurs for that (game, key)."""
    out = {cell: float(p) for cell, p in pmf.items()}
    margins = {cell: cell[0] - cell[1] for cell in out}
    for k in K3_KEYS:
        lam = float(lambdas.get(k, 0.0))
        if lam <= 0.0:
            continue
        window_cells = [c for c in out if margins[c] in K3_WINDOWS[k]]
        key_cells = [c for c in out if margins[c] == k]
        s_win = sum(out[c] for c in window_cells)
        s_key = sum(out[c] for c in key_cells)
        if s_win <= 0.0 or s_key <= 0.0:
            continue
        removed = lam * s_win
        for c in window_cells:
            out[c] = out[c] * (1.0 - lam)
        for c in key_cells:
            out[c] = out[c] + removed * (out[c] / s_key)
    return out


def independent_marginals_pmf(
    pmf: Mapping[tuple[int, int], float],
) -> dict[tuple[int, int], float]:
    """Comparator (ii'): the candidate's own marginals composed independently,
    P(h, a) = P^H(h) * P^A(a). A dependence-value test derived from the
    candidate's own PMF (Amendment 1) - NOT an external benchmark."""
    mh: dict[int, float] = defaultdict(float)
    ma: dict[int, float] = defaultdict(float)
    for (h, a), p in pmf.items():
        mh[int(h)] += float(p)
        ma[int(a)] += float(p)
    return {(h, a): ph * pa for h, ph in mh.items() for a, pa in ma.items()}


# ---------------------------------------------------------------------------
# Fold fitting: every selection (alpha, theta, rare prior) happens inside
# the training window. Sigma follows the attempt-1 placement (heritage OOF
# over the fitted fold models).
# ---------------------------------------------------------------------------

def fit_fold_bundle(
    train_rows: Sequence[Mapping[str, Any]],
    config: ModelFormConfig = V2_CONFIG,
) -> dict[str, Any]:
    train_rows = list(train_rows)
    td_alpha, td_cv = heritage_choose_alpha(
        train_rows, target="offense_touchdowns", alphas=config.alpha_grid,
        feature_names=FEATURE_NAMES)
    td_model = heritage_fit_poisson_ridge(
        train_rows, target="offense_touchdowns", alpha=float(td_alpha),
        feature_names=FEATURE_NAMES)
    fg_alpha, fg_cv = choose_alpha_v2(
        train_rows, target="fg_attempts_with_distance",
        feature_names=config.opportunity_features, alphas=config.alpha_grid)
    fg_model = fit_poisson_ridge_v2(
        train_rows, target="fg_attempts_with_distance", alpha=float(fg_alpha),
        feature_names=config.opportunity_features)
    period: dict[int, dict[str, Any]] = {}
    for q in (1, 2, 3, 4):
        names = period_feature_names(q)
        td_a, _ = choose_alpha_v2(train_rows, target=f"q{q}_off_td",
                                  feature_names=names, alphas=config.alpha_grid)
        fg_a, _ = choose_alpha_v2(train_rows, target=f"q{q}_made_fg",
                                  feature_names=names, alphas=config.alpha_grid)
        period[q] = {
            "td_model": fit_poisson_ridge_v2(train_rows, target=f"q{q}_off_td",
                                             alpha=float(td_a), feature_names=names),
            "fg_model": fit_poisson_ridge_v2(train_rows, target=f"q{q}_made_fg",
                                             alpha=float(fg_a), feature_names=names),
            "td_alpha": float(td_a), "fg_alpha": float(fg_a),
        }
    leg_alphas = {"TD": float(td_alpha), "FG": float(fg_alpha)}
    for q in (1, 2, 3, 4):
        leg_alphas[f"TD_Q{q}"] = period[q]["td_alpha"]
        leg_alphas[f"FG_Q{q}"] = period[q]["fg_alpha"]
    thetas: dict[str, float] = {}
    theta_scores: dict[str, Any] = {}
    for leg in ("TD", "FG", "TD_Q1", "TD_Q2", "TD_Q3", "TD_Q4",
                "FG_Q1", "FG_Q2", "FG_Q3", "FG_Q4"):
        theta, scores = select_theta_for_leg(
            train_rows, leg, config, mean_alpha=leg_alphas[leg])
        thetas[leg] = float(theta)
        theta_scores[leg] = scores
    rare_prior, rare_scores = select_rare_prior(train_rows, config)
    return {
        "config": config,
        "td_model": td_model, "td_alpha": float(td_alpha), "td_cv_scores": td_cv,
        "fg_opportunity_model": fg_model, "fg_alpha": float(fg_alpha),
        "fg_cv_scores": fg_cv,
        "period": period,
        "thetas": thetas, "theta_cv_scores": theta_scores,
        "rare_prior": rare_prior, "rare_cv_scores": rare_scores,
        "train_game_ids": sorted({str(r["game_id"]) for r in train_rows}),
        "train_row_count": len(train_rows),
    }


def fold_rare_rates(
    bundle: Mapping[str, Any],
    train_rows: Sequence[Mapping[str, Any]],
    eval_rows: Sequence[Mapping[str, Any]],
    *,
    def_field: str = "def_st_touchdowns",
    saf_field: str = "safeties",
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(eval_rates, train_rates) under the fold's selected prior, aligned
    with the input row order. LEAGUE_ONLY reduces to the training-window
    league-rate construction itself (the G-RARE baseline construction), so
    the comparison passes by equality when CV selects it (section 2.4)."""
    prior = bundle["rare_prior"]
    if prior == "LEAGUE_ONLY":
        const = league_rare_rates(train_rows, def_field=def_field, saf_field=saf_field)
        return [const] * len(eval_rows), [const] * len(train_rows)
    train_rates = pit_eb_rates((), train_rows, prior=float(prior),
                               def_field=def_field, saf_field=saf_field)
    eval_rates = pit_eb_rates(train_rows, eval_rows, prior=float(prior),
                              def_field=def_field, saf_field=saf_field)
    return eval_rates, train_rates


def select_sigma_oof_v2(
    rows: Sequence[Mapping[str, Any]],
    fold_bundles: Mapping[int, Mapping[str, Any]],
    *,
    validation_seasons: Sequence[int] = VALIDATION_SEASONS,
) -> tuple[float, dict[str, Any]]:
    """Heritage sigma selection (attempt-1 placement and construction):
    OOF residual product vs lognormal-implied covariance, using each fold's
    fitted models on that fold's validation rows; ties to the smaller sigma.
    Under C2 the same selection operates over the NB marginals (the mean
    construction is unchanged).

    SUPERSEDED for attempt 2 by Amendment 2 (owner ruling, Oct 13 2026;
    preregistration section 6 governs): this pooled-across-validation-folds
    placement reads validation rows and is retained only as attempt 1's
    historical construction. The attempt-2 evaluation driver uses
    select_sigma_nested_v2, which reads training rows only."""
    residual_rows: list[dict[str, float]] = []
    for season in validation_seasons:
        bundle = fold_bundles[season]
        config: ModelFormConfig = bundle["config"]
        valid = [r for r in rows if int(r["season"]) == season]
        for gid, (home, away) in sorted(game_pairs(valid).items()):
            h_mu = heritage_predict_mean(bundle["td_model"], home) + banded_made_fg_mean(
                bundle["fg_opportunity_model"], home, config)
            a_mu = heritage_predict_mean(bundle["td_model"], away) + banded_made_fg_mean(
                bundle["fg_opportunity_model"], away, config)
            h_obs = float(home["offense_touchdowns"]) + float(home["made_field_goals"])
            a_obs = float(away["offense_touchdowns"]) + float(away["made_field_goals"])
            residual_rows.append({
                "home_mu": h_mu, "away_mu": a_mu,
                "residual_product": (h_obs - h_mu) * (a_obs - a_mu),
            })
    mse: dict[float, float] = {}
    for sigma in SIGMA_GRID:
        implied_factor = exp(float(sigma) ** 2) - 1.0
        errors = [
            (r["residual_product"] - r["home_mu"] * r["away_mu"] * implied_factor) ** 2
            for r in residual_rows
        ]
        mse[float(sigma)] = float(np.mean(np.asarray(errors, dtype=float)))
    best = min(mse, key=lambda s: (mse[s], s))
    return float(best), {
        "metric": "MSE_RESIDUAL_PRODUCT_VS_LOGNORMAL_IMPLIED_COVARIANCE",
        "sigma_grid": list(SIGMA_GRID),
        "mse_by_sigma": {str(k): mse[k] for k in sorted(mse)},
        "selected_sigma": float(best),
        "oof_game_count": len(residual_rows),
    }


def select_sigma_nested_v2(
    train_rows: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    """Sigma selection under Amendment 2 (preregistration section 2.5 as
    amended; section 6 governs): nested expanding-window selection INSIDE
    one outer fold's training window.

    Inner folds: the inner validation season is each training season after
    the first; inner TD and banded-FG models are refits on the training
    seasons strictly before the inner validation season, at the outer
    fold's selected alphas (the section-3 inner-fit convention — every
    sigma candidate is scored over identical means). The statistic is
    attempt 1's residual-product MSE in the same form (observed residual
    product vs mu_h * mu_a * (exp(sigma^2) - 1)), computed on the inner
    out-of-fold residuals pooled across inner folds; the grid and the
    tie-break to the smaller sigma are unchanged.

    Validation rows are not an input to this function at all: the only
    rows it receives are the outer fold's training rows. Inner games whose
    rows lack band context (ZERO_MODEL_ROW) are excluded from the
    statistic and counted, per the driver's exclude-and-count policy.

    Fail-closed (Amendment 2 section 2.5): a training window with fewer
    than two seasons cannot form an inner fold, and a window whose inner
    folds yield no usable game cannot select — both raise
    ScoreCountsG2V2Error with a SIGMA_SELECTION_* code, which the
    evaluation driver converts to a pre-scoring NOT_RUN. There is no
    fallback to validation data, ever."""
    config: ModelFormConfig = bundle["config"]
    train_rows = list(train_rows)
    seasons = sorted({int(r["season"]) for r in train_rows})
    if len(seasons) < 2:
        raise ScoreCountsG2V2Error(
            "SIGMA_SELECTION_NO_INNER_FOLD: training window seasons "
            f"{seasons} cannot form an inner fold - fail closed "
            "(Amendment 2 section 2.5); no validation-data fallback")
    residual_rows: list[dict[str, float]] = []
    inner_folds: list[dict[str, Any]] = []
    excluded_zero_model = 0
    for inner_season in seasons[1:]:
        inner_train = [r for r in train_rows if int(r["season"]) < inner_season]
        inner_valid = [r for r in train_rows if int(r["season"]) == inner_season]
        td_model = fit_poisson_ridge_v2(
            inner_train, target="offense_touchdowns",
            alpha=float(bundle["td_alpha"]), feature_names=FEATURE_NAMES)
        fg_model = fit_poisson_ridge_v2(
            inner_train, target="fg_attempts_with_distance",
            alpha=float(bundle["fg_alpha"]),
            feature_names=config.opportunity_features)
        n_games = 0
        for gid, (home, away) in sorted(game_pairs(inner_valid).items()):
            if not (row_has_band_context(home, config)
                    and row_has_band_context(away, config)):
                excluded_zero_model += 1
                continue
            h_mu = heritage_predict_mean(td_model, home) + banded_made_fg_mean(
                fg_model, home, config)
            a_mu = heritage_predict_mean(td_model, away) + banded_made_fg_mean(
                fg_model, away, config)
            h_obs = float(home["offense_touchdowns"]) + float(home["made_field_goals"])
            a_obs = float(away["offense_touchdowns"]) + float(away["made_field_goals"])
            residual_rows.append({
                "home_mu": h_mu, "away_mu": a_mu,
                "residual_product": (h_obs - h_mu) * (a_obs - a_mu),
            })
            n_games += 1
        inner_folds.append({
            "inner_validation_season": inner_season,
            "inner_training_seasons": [s for s in seasons if s < inner_season],
            "n_games": n_games,
        })
    if not residual_rows:
        raise ScoreCountsG2V2Error(
            "SIGMA_SELECTION_NO_INNER_GAMES: inner folds formed but no "
            "usable inner game - fail closed (Amendment 2 section 2.5); "
            "no validation-data fallback")
    mse: dict[float, float] = {}
    for sigma in SIGMA_GRID:
        implied_factor = exp(float(sigma) ** 2) - 1.0
        errors = [
            (r["residual_product"] - r["home_mu"] * r["away_mu"] * implied_factor) ** 2
            for r in residual_rows
        ]
        mse[float(sigma)] = float(np.mean(np.asarray(errors, dtype=float)))
    best = min(mse, key=lambda s: (mse[s], s))
    return float(best), {
        "metric": "MSE_RESIDUAL_PRODUCT_VS_LOGNORMAL_IMPLIED_COVARIANCE",
        "selection_rule": "AMENDMENT_2_NESTED_TRAINING_WINDOW_ONLY",
        "sigma_grid": list(SIGMA_GRID),
        "mse_by_sigma": {str(k): mse[k] for k in sorted(mse)},
        "selected_sigma": float(best),
        "oof_game_count": len(residual_rows),
        "inner_folds": inner_folds,
        "inner_games_excluded_zero_model_row": excluded_zero_model,
    }


def fitted_values_digest(bundle: Mapping[str, Any]) -> str:
    """Canonical digest of every fitted value in a fold bundle (model
    parameters, alphas, thetas, rare-prior choice, K3 lambdas when present).
    Used by the leakage-resistance tests: the digest must be bit-identical
    under any permutation/corruption of evaluation-fold outcomes."""
    import dataclasses
    import json as _json

    def _model(m: Any) -> Any:
        return dataclasses.asdict(m) if dataclasses.is_dataclass(m) else str(m)

    payload = {
        "td_alpha": bundle["td_alpha"],
        "fg_alpha": bundle["fg_alpha"],
        "td_model": _model(bundle["td_model"]),
        "fg_model": _model(bundle["fg_opportunity_model"]),
        "period": {
            str(q): {
                "td_alpha": bundle["period"][q]["td_alpha"],
                "fg_alpha": bundle["period"][q]["fg_alpha"],
                "td_model": _model(bundle["period"][q]["td_model"]),
                "fg_model": _model(bundle["period"][q]["fg_model"]),
            } for q in (1, 2, 3, 4)
        },
        "thetas": {k: str(v) for k, v in bundle["thetas"].items()},
        "rare_prior": str(bundle["rare_prior"]),
        "k3_lambdas": (
            {str(k): v for k, v in bundle["k3"]["lambdas"].items()}
            if bundle.get("k3") else None
        ),
    }
    canonical = _json.dumps(payload, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True).encode("utf-8")
    return sha256(canonical).hexdigest()


__all__ = [
    "FAMILY", "ATTEMPT_NUMBER", "ATTEMPT_BUDGET",
    "ROOT_SEED_LITERAL_V2", "ROOT_SEED_SHA256_V2", "ROOT_SEED_UINT64_V2",
    "PATHS_PER_GAME", "MIN_PATHS_FOR_SCORED_OUTPUT", "VALIDATION_SEASONS",
    "DEVELOPMENT_SEASONS", "ALPHA_GRID_V2", "ALPHA_GRID_V1_TRUNCATED",
    "SIGMA_GRID", "THETA_GRID", "RARE_PRIOR_GRID",
    "FG_BANDS", "FG_OPPORTUNITY_FEATURES_V1", "FG_OPPORTUNITY_FEATURES_V2",
    "K3_KEYS", "K3_WINDOWS", "K3_LAMBDA_MAX",
    "ModelFormConfig", "V2_CONFIG", "V1_COMPAT_CONFIG",
    "ScoreCountsG2V2Error", "ZeroModelRow",
    "child_seed_v2", "rng_for_v2", "poisson_deviance", "poisson_logpmf",
    "fit_poisson_ridge_v2", "predict_mean_v2", "choose_alpha_v2",
    "BandBook", "band_shares_rates_v2", "band_shares_rates_v1",
    "band_snapshot_from_row", "band_shares_rates", "row_has_band_context",
    "banded_made_fg_mean",
    "banded_made_fg_detail", "build_g2_rows_v2",
    "league_rare_rates", "pit_eb_rates", "select_rare_prior",
    "nb_logpmf", "draw_count", "select_theta_cv", "select_theta_for_leg",
    "period_feature_names", "simulate_full_game_v2", "simulate_period_game_v2",
    "realized_final_score", "game_pairs", "pmf_counts", "pmf_from_counts",
    "log_score", "log_score_pmf", "randomized_pit", "joint_distribution_sha256",
    "margin_law", "estimate_k3_lambdas", "apply_k3", "independent_marginals_pmf",
    "fit_fold_bundle", "fold_rare_rates", "select_sigma_oof_v2",
    "select_sigma_nested_v2",
    "fitted_values_digest",
]
