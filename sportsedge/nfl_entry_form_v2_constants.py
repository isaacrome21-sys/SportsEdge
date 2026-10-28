"""Constants for NFL_ENTRY_FORM_V2.

This is the build-stage form of the constants file PREREG_DRAFT §7.4
requires the freeze to pin: "Any number not in this file does not exist
in the construction." Every value below cites the section it comes from.
STATUS: DRAFT — NOT FROZEN. The fitted values are the build-stage fit
(fitted ONCE on pooled 2020-2025 design data by
``research/nfl_entry_form_v2_20261028/fit_constants.py``; provenance in
``fitted_constants.json`` beside it). At a freeze, the fit is re-run and
re-pinned on the exact frozen head and the freeze record governs
(PREREG_DRAFT §3: "the freeze fit governs").
"""

from __future__ import annotations

CONSTRUCTION_ID = "NFL_ENTRY_FORM_V2"
CONSTANTS_ID = "EF_V2_CONSTANTS_BUILD_20261028"
STATUS = "DRAFT — NOT FROZEN"

# --- EPA core structure (DESIGN §4.1; PREREG_DRAFT §7.4) -------------------
PRIOR_PLAYS = 250.0            # season EPA shrinkage prior, plays (§4.1/§7.4)
FORM_PRIOR_PLAYS = 150.0       # last-4 form shrink toward season rate (§4.1/§7.4)
FORM_WINDOW_GAMES = 4          # "Last-4-games rates" (§4.1)
CARRY_TEAM = 0.30              # prior-season carry, team EPA sums (§4.1/§7.4)
CARRY_QB = 0.50                # prior-season carry, QB EPA sums (§7.4)
PRIOR_QB_ATTEMPTS = 200.0      # QB EPA shrinkage prior, attempts (§7.4)
# QB delta is expressed per 36 attempts in the design record's reference
# implementation (design_screen.py, qb_delta) — the screen program that
# DESIGN §4.2's feature set is defined by.
QB_DELTA_ATTEMPT_SCALE = 36.0
MIN_PRIOR_REG_GAMES = 3        # eligibility: both teams, in-season (§4.1/§3)
PACE_DEFAULT = 62.0            # pace fallback before any game is ingested
                               # (design_screen.py RateBook.rates)
PACE_LEAGUE_REFERENCE = 124.0  # pace-deviation center, both teams combined
                               # (design_screen.py: y_pace_dev = y_pace - 124)

# --- Veto-path context feature shape (DESIGN §4.2; design_screen.py) -------
WIND_THRESHOLD_MPH = 12.0      # wind term: -max(0, wind - 12) x outdoor
COLD_THRESHOLD_F = 32.0        # cold term: -max(0, 32 - temp) / 10 x outdoor
COLD_SCALE = 10.0

# --- Pick rule (PREREG_DRAFT §3) -------------------------------------------
DISTANCE_GATE = 3.0            # |d| >= 3.0
PROBABILITY_GATE = 0.545       # p_raw >= 0.545
PRICE_CAP = -165               # picked-side DK price >= -165 (owner's cap)
SIGMA_FLOOR = 12.5             # per-market sigma floor (§3/§7.4)

# --- Fitted once on pooled 2020-2025 design data (build-stage fit) ---------
# Core mapping (DESIGN §4.1 spec B): margin ~ EPA margin + form divergence;
# total ~ EPA total + form divergence. The SPREAD intercept is the fitted
# home-field constant (DESIGN §4.1: "Home-field advantage is a single
# fitted constant").
CORE_FIT = {
    "SPREAD": {"intercept": 1.815740331071083,
               "epa_margin": 0.25732346527512767,
               "form_divergence": -0.03423383579171986},
    "TOTAL": {"intercept": 45.7744180510264,
              "epa_total": 0.11994016396891266,
              "form_divergence": 0.05602314211235785},
}
# Veto path (DESIGN §4.2): OLS on the market residual from the frozen
# context set. Sign veto only; never added to the projection.
RESIDUAL_FIT = {
    "SPREAD": {"intercept": 0.3209959989876865,
               "form_divergence": -0.0019959586730060367,
               "qb_home": -0.015127771241296412,
               "qb_away": -0.007256052362978923,
               "rest": 0.046685837155063276},
    "TOTAL": {"intercept": 1.0645555882323183,
              "form_divergence": 0.04772094528587417,
              "pace_deviation": -0.00044526821542872376,
              "wind": 0.34157472359635094,
              "cold": 1.8271630676898325},
}
# Per-market sigma of the core fit's design residuals, floor applied
# (PREREG_DRAFT §3). SIGMA_FIT_RAW preserves the pre-floor values for the
# record. Design-stage walk-forward values were margin 14.40 / totals
# 13.95 (PREREG_DRAFT §3); the values below are this build's pooled fit.
SIGMA_FIT_RAW = {"SPREAD": 14.034734387117979, "TOTAL": 13.736836529512287}
SIGMA_FIT = {"SPREAD": 14.034734387117979, "TOTAL": 13.736836529512287}

FIT_PROVENANCE = {
    "fit": "pooled OLS on all eligible 2020-2025 design rows, fitted once",
    "n_eligible_rows": 1327,
    "design_stage_walkforward_sigma": {"SPREAD": 14.40, "TOTAL": 13.95},
    "record": "research/nfl_entry_form_v2_20261028/fitted_constants.json",
}
