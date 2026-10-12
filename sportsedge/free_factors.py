"""Free verifiable factors for SportsEdge pricing.

Every factor here obeys Isaac's standing bar:
  - public verified data only (MLB StatsAPI, ESPN, Open-Meteo);
  - NO Odds API, no market prices invented;
  - fail closed with explicit reason codes;
  - research-only, no betting authority;
  - no factor enters production pricing until it improves chronological
    out-of-sample performance vs the existing model in the backtest
    harness (sportsedge/backtest). CONDITIONAL_PASS (market baseline
    missing) is labeled as such and never presented as validated.

Factor registry (source -> pricing use):
  1. MLB park factors ......... MLB StatsAPI-derived table (2022-2024,
     regressed); scales both teams' run means for TOTALS/ML/SPREAD.
  2. Rest / travel ............. ESPN team schedules (days rest) + venue
     geography (travel miles, timezone jumps); declared bounded formulas
     adjust NFL/CFB means.
  3. Weather thresholds ........ Open-Meteo forecast/archive
     (wind_speed_10m, wind_direction_10m, precipitation_probability) +
     MLB StatsAPI venue azimuth/coords; declared explicit cutoffs adjust
     totals. Indoor venues verified -> no adjustment.
  4. NFL/CFB key numbers ....... empirical final-margin frequencies from
     ESPN scoreboards (2020-2023 NFL, 2021-2023 CFB) blended with the
     normal-model push estimate; push-aware SPREAD/TOTAL pricing.
  5. MLB umpire ................ NOT_WIRED: historical assignments exist in
     StatsAPI boxscores but no stable free pregame source exists.

Explicitly NOT_WIRED (never attempted): news speed, motivation spots,
officiating tendencies, Statcast, Next Gen Stats, NBA props.
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# 1. MLB park factors
# ---------------------------------------------------------------------------
# Derived 2026-10-11 from MLB StatsAPI official schedule data (free, public,
# no key) by scripts/derive_mlb_park_factors.py --seasons 2022,2023,2024.
# Formula: pf = 1 + (home_rpg/road_rpg - 1) * home_games/(home_games + 162),
# where *_rpg counts runs scored AND allowed. 100 = neutral would be 1.00.
# Re-derive with the script when a new season completes; do not hand-edit.
PARK_FACTOR_SOURCE = "MLB StatsAPI official schedule (free, public, no key)"
PARK_FACTOR_SEASONS = (2022, 2023, 2024)
PARK_FACTOR_DERIVATION = "scripts/derive_mlb_park_factors.py"
PARK_FACTOR_MAX_SEASON = 2025  # table applies through this season, then STALE

PARK_FACTORS: dict[str, float] = {
    'Arizona Diamondbacks': 0.9747,
    'Athletics': 0.9613,  # Oakland Coliseum (2022-24); blocked for 2025+ via PARK_CHANGES
    'Atlanta Braves': 0.9663,
    'Baltimore Orioles': 0.9772,
    'Boston Red Sox': 1.0692,
    'Chicago Cubs': 0.9657,
    'Chicago White Sox': 1.007,
    'Cincinnati Reds': 1.0526,
    'Cleveland Guardians': 0.9921,
    'Colorado Rockies': 1.1614,
    'Detroit Tigers': 1.025,
    'Houston Astros': 0.99,
    'Kansas City Royals': 1.0466,
    'Los Angeles Angels': 1.017,
    'Los Angeles Dodgers': 0.9522,
    'Miami Marlins': 1.0755,
    'Milwaukee Brewers': 0.9891,
    'Minnesota Twins': 0.9796,
    'New York Mets': 0.9579,
    'New York Yankees': 1.0216,
    'Philadelphia Phillies': 1.0095,
    'Pittsburgh Pirates': 1.0271,
    'San Diego Padres': 0.9551,
    'San Francisco Giants': 0.9672,
    'Seattle Mariners': 0.9171,
    'St. Louis Cardinals': 0.9767,
    'Tampa Bay Rays': 0.9625,  # Tropicana Field (2022-24); blocked for 2025+ via PARK_CHANGES
    'Texas Rangers': 1.0038,
    'Toronto Blue Jays': 0.9968,
    'Washington Nationals': 1.0261,
}
# Re-derived 2026-10-11 after fixing a derivation bug: the StatsAPI schedule
# endpoint ignores the `team=` query parameter (verified by direct test), so
# the first table counted every non-home game as a "road" game, polluting
# the road sample with other teams' games. Corrected: full-season schedules
# fetched, games grouped by team locally. See scripts/derive_mlb_park_factors.py.
# Teams that changed home parks after the table's seasons. The table's park
# no longer applies -> fail closed (MISSING), never approximate.
PARK_CHANGES: dict[str, int] = {
    # team -> first season in the new park
    "Athletics": 2025,        # Oakland Coliseum -> Sutter Health Park (Sacramento)
    "Tampa Bay Rays": 2025,   # Tropicana Field -> Steinbrenner Field (outdoor)
}


def park_factor_for(home_team: str, season: int) -> tuple[float | None, str, str]:
    """Return (factor, status, detail) for a home team + season.

    Fail-closed: unknown team, stale table, or post-move team -> (None,
    <REASON>, <detail>) and the caller must not apply any park adjustment.
    """
    name = str(home_team or "").strip()
    try:
        season = int(season)
    except (TypeError, ValueError):
        return None, "PARK_FACTOR_SEASON_UNVERIFIED", "season not an integer"
    if not name:
        return None, "PARK_FACTOR_TEAM_UNVERIFIED", "empty home team name"
    if season > PARK_FACTOR_MAX_SEASON:
        return None, "PARK_FACTOR_STALE", (
            f"table covers {PARK_FACTOR_SEASONS[0]}-{PARK_FACTOR_SEASONS[-1]}; "
            f"season {season} needs re-derivation via {PARK_FACTOR_DERIVATION}")
    moved = PARK_CHANGES.get(name)
    if moved is not None and season >= moved:
        return None, "PARK_FACTOR_TEAM_PARK_CHANGED", (
            f"{name} changed home parks starting {moved}; table park no longer applies")
    pf = PARK_FACTORS.get(name)
    if pf is None:
        return None, "PARK_FACTOR_TEAM_UNKNOWN", f"no table entry for {name!r}"
    return pf, "PARK_FACTOR_VERIFIED", (
        f"runs park factor {pf:.4f} from {PARK_FACTOR_SOURCE} "
        f"{PARK_FACTOR_SEASONS[0]}-{PARK_FACTOR_SEASONS[-1]}")


def park_runs_scale(pf: float) -> float:
    """Declared scaling of both teams' expected runs for a park factor.

    Half-strength blend toward neutral (1.0): a measured factor is an
    estimate, not truth, so production applies 50% of the deviation,
    bounded to [+/-8%]. Declared prior, NOT a fitted coefficient.
    """
    return max(0.92, min(1.08, 1.0 + 0.5 * (float(pf) - 1.0)))


# ---------------------------------------------------------------------------
# 2. Rest / travel (NFL, CFB)
# ---------------------------------------------------------------------------
# Source: ESPN public team schedule API (free, public, no key) for days rest
# and previous-game venue; venue geography from Open-Meteo geocoding of the
# ESPN venue city (static geography, cached) or MLB-StatsAPI-style static
# tables. Formulas are declared bounded priors, NOT fitted coefficients.
REST_POINTS_PER_DAY = 0.10
REST_MARGIN_CAP = 1.0
TRAVEL_FREE_MILES = 500.0
TRAVEL_POINTS_PER_500MI = 0.10
TRAVEL_DISTANCE_CAP = 0.6
TRAVEL_POINTS_PER_EXTRA_TZ = 0.15
TRAVEL_TZ_CAP = 0.45
TRAVEL_TOTAL_CAP = 1.0


def rest_margin_adjustment(home_rest_days: float | None,
                           away_rest_days: float | None) -> tuple[float, str, str]:
    """Declared rest-differential adjustment, added to the HOME margin.

    +0.10 points per day of rest differential, bounded to +/-1.0.
    Either side unverified -> (0.0, REST_UNVERIFIED, ...) fail-closed.
    """
    if home_rest_days is None or away_rest_days is None:
        return 0.0, "REST_UNVERIFIED", "rest days missing for a side"
    try:
        home_d, away_d = float(home_rest_days), float(away_rest_days)
    except (TypeError, ValueError):
        return 0.0, "REST_UNVERIFIED", "rest days non-numeric"
    if not (math.isfinite(home_d) and math.isfinite(away_d)):
        return 0.0, "REST_UNVERIFIED", "rest days non-finite"
    if home_d < 0 or away_d < 0:
        # Contradictory: a team cannot have played its last game in the future.
        return 0.0, "REST_UNVERIFIED", "negative rest days (contradictory input)"
    diff = home_d - away_d
    adj = max(-REST_MARGIN_CAP, min(REST_MARGIN_CAP, REST_POINTS_PER_DAY * diff))
    return adj, "REST_VERIFIED_APPLIED", (
        f"rest differential {diff:+.1f}d -> {adj:+.2f} pts home margin "
        f"(declared {REST_POINTS_PER_DAY}/day, cap {REST_MARGIN_CAP})")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles. Declared formula."""
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def timezone_jumps(lon_from: float, lon_to: float) -> int:
    """Declared timezone jumps from longitude difference (15 deg ~= 1 hour)."""
    return int(round(abs(float(lon_to) - float(lon_from)) / 15.0))


def travel_margin_adjustment(miles: float | None, tz_jumps: int | None,
                             traveler: str = "AWAY") -> tuple[float, str, str]:
    """Declared travel-burden adjustment, added to the TRAVELER's mean (<= 0).

    -0.10 pts per 500 miles beyond the first 500 (cap -0.6), plus -0.15 per
    timezone jump beyond the first (cap -0.45); total bounded [-1.0, 0].
    Unverifiable geography -> (0.0, TRAVEL_UNVERIFIED, ...) fail-closed.
    """
    traveler = str(traveler or "AWAY").upper()
    if traveler not in ("HOME", "AWAY"):
        return 0.0, "TRAVEL_UNVERIFIED", "traveler side invalid"
    try:
        miles = float(miles) if miles is not None else None
        tz = int(tz_jumps) if tz_jumps is not None else None
    except (TypeError, ValueError):
        return 0.0, "TRAVEL_UNVERIFIED", "travel inputs non-numeric"
    if miles is None or tz is None or not math.isfinite(miles) or miles < 0 or tz < 0:
        return 0.0, "TRAVEL_UNVERIFIED", "travel distance/timezone unverified"
    dist = -min(TRAVEL_DISTANCE_CAP,
                TRAVEL_POINTS_PER_500MI * max(0.0, miles - TRAVEL_FREE_MILES) / 500.0)
    tzp = -min(TRAVEL_TZ_CAP, TRAVEL_POINTS_PER_EXTRA_TZ * max(0, tz - 1))
    adj = max(-TRAVEL_TOTAL_CAP, dist + tzp)
    return adj, "TRAVEL_VERIFIED_APPLIED", (
        f"{miles:.0f} mi, {tz} tz jumps -> {adj:+.2f} pts to {traveler} mean "
        f"(declared, capped {TRAVEL_TOTAL_CAP})")


# Static NFL team geography: Open-Meteo geocoding of the ESPN venue
# city per team (2026-10-11; static geography), ATL hand-verified
# (geocoder returned Atlanta, MI), LAC shares SoFi with LAR.
# Source: https://geocoding-api.open-meteo.com (free, public, no key).
NFL_TEAM_GEO: dict[str, tuple[float, float]] = {
    'ARI': (33.5386, -112.186),  # Glendale, AZ
    'ATL': (33.749, -84.388),  # Atlanta, GA
    'BAL': (39.2904, -76.6122),  # Baltimore, MD
    'BUF': (42.7676, -78.7439),  # Orchard Park, NY
    'CAR': (35.2271, -80.8431),  # Charlotte, NC
    'CHI': (41.85, -87.65),  # Chicago, IL
    'CIN': (39.1271, -84.5144),  # Cincinnati, OH
    'CLE': (41.4995, -81.6954),  # Cleveland, OH
    'DAL': (32.7357, -97.1081),  # Arlington, TX
    'DEN': (39.7392, -104.9847),  # Denver, CO
    'DET': (42.3314, -83.0457),  # Detroit, MI
    'GB': (44.5192, -88.0198),  # Green Bay, WI
    'HOU': (29.7633, -95.3633),  # Houston, TX
    'IND': (39.7684, -86.158),  # Indianapolis, IN
    'JAX': (30.3322, -81.6556),  # Jacksonville, FL
    'KC': (39.0997, -94.5786),  # Kansas City, MO
    'LAC': (33.962, -118.353),  # Inglewood, CA
    'LAR': (33.9617, -118.3531),  # Inglewood, CA
    'LV': (36.175, -115.1372),  # Las Vegas, NV
    'MIA': (25.942, -80.2456),  # Miami Gardens, FL
    'MIN': (44.98, -93.2638),  # Minneapolis, MN
    'NE': (42.0654, -71.2478),  # Foxborough, MA
    'NO': (29.9547, -90.0751),  # New Orleans, LA
    'NYG': (40.834, -74.0971),  # East Rutherford, NJ
    'NYJ': (40.834, -74.0971),  # East Rutherford, NJ
    'PHI': (39.9524, -75.1636),  # Philadelphia, PA
    'PIT': (40.4406, -79.9959),  # Pittsburgh, PA
    'SEA': (47.6062, -122.3321),  # Seattle, WA
    'SF': (37.3541, -121.9552),  # Santa Clara, CA
    'TB': (27.9475, -82.4584),  # Tampa, FL
    'TEN': (36.1659, -86.7844),  # Nashville, TN
    'WSH': (38.934, -76.8966),  # Landover, MD
}


# ---------------------------------------------------------------------------
# 3. Weather thresholds
# ---------------------------------------------------------------------------
# Sources:
#   - Open-Meteo forecast/archive API docs: wind_speed_10m (mph),
#     wind_direction_10m (meteorological degrees, direction wind comes FROM),
#     precipitation_probability (%). Free, public, no key.
#   - MLB StatsAPI venues?hydrate=location: azimuthAngle (field azimuth,
#     home-plate-to-center-field degrees), defaultCoordinates, roofType.
#     Free, public, no key.
# Thresholds below are DECLARED priors (explicit cutoffs), not fitted or
# learned coefficients. Each is gated on backtest-harness validation.
WEATHER_SOURCE = "Open-Meteo API + MLB StatsAPI venue azimuth/coords"
# MLB wind-out/in buckets (mph of outfield-directed component)
MLB_WIND_OUT_STRONG = 12.0
MLB_WIND_OUT_MODERATE = 8.0
MLB_WIND_OUT_STRONG_ADJ = 0.50
MLB_WIND_OUT_MODERATE_ADJ = 0.25
MLB_PRECIP_STRONG = 70.0
MLB_PRECIP_ADJ = -0.30
MLB_WEATHER_CAP = 1.0
# NFL/CFB wind/precip buckets (mph sustained)
FOOTBALL_WIND_STRONG = 20.0
FOOTBALL_WIND_MODERATE = 15.0
FOOTBALL_WIND_STRONG_ADJ = -1.50
FOOTBALL_WIND_MODERATE_ADJ = -0.75
FOOTBALL_PRECIP_STRONG = 70.0
FOOTBALL_PRECIP_ADJ = -0.75
FOOTBALL_WEATHER_CAP = 2.0


def wind_out_component_mph(wind_speed_mph: float, wind_from_degrees: float,
                           field_azimuth_degrees: float) -> float:
    """Project meteorological wind onto the home-plate-to-outfield axis.

    Same math as sportsedge.mlb_environment_derived.stadium_wind_components_mph,
    reimplemented here so this module stays dependency-free. Positive = blowing
    out toward the outfield; negative = blowing in toward home plate.
    """
    speed = float(wind_speed_mph)
    if speed < 0 or not math.isfinite(speed):
        raise ValueError("WIND_SPEED_INVALID")
    wind_from = float(wind_from_degrees) % 360.0
    azimuth = float(field_azimuth_degrees) % 360.0
    out_from = (azimuth + 180.0) % 360.0
    return speed * math.cos(math.radians(wind_from - out_from))


def weather_total_adjustment(*, sport: str, wind_speed_mph: float | None,
                             wind_from_degrees: float | None = None,
                             field_azimuth_degrees: float | None = None,
                             precip_probability_pct: float | None = None,
                             indoor: bool | None = None) -> tuple[float, str, str]:
    """Declared weather adjustment, added to the game TOTAL (split evenly).

    Returns (runs_or_points, status, detail). Any unverifiable input ->
    (0.0, WEATHER_UNVERIFIED, ...) fail-closed. Verified indoor ->
    (0.0, VERIFIED_INDOOR, ...).
    """
    sport = str(sport or "").upper()
    if indoor is True:
        return 0.0, "VERIFIED_INDOOR", "venue verified indoor; no weather effect"
    if sport not in ("MLB", "NFL", "CFB"):
        return 0.0, "WEATHER_NOT_APPLICABLE", f"no weather model for {sport}"
    try:
        wind = float(wind_speed_mph) if wind_speed_mph is not None else None
        precip = (float(precip_probability_pct)
                  if precip_probability_pct is not None else None)
    except (TypeError, ValueError):
        return 0.0, "WEATHER_UNVERIFIED", "wind/precip non-numeric"
    if wind is None or not math.isfinite(wind) or wind < 0:
        return 0.0, "WEATHER_UNVERIFIED", "wind speed unverified"
    if precip is not None and (not math.isfinite(precip) or precip < 0
                               or precip > 100):
        # Probability outside [0,100] is contradictory data (red-team fix).
        return 0.0, "WEATHER_UNVERIFIED", "precip probability invalid"
    adj = 0.0
    notes: list[str] = []
    if sport == "MLB":
        signed_out = None
        if wind_from_degrees is not None and field_azimuth_degrees is not None:
            try:
                signed_out = wind_out_component_mph(wind, wind_from_degrees,
                                                    field_azimuth_degrees)
            except (ValueError, TypeError):
                signed_out = None
        if signed_out is None:
            return 0.0, "WEATHER_UNVERIFIED", (
                "MLB wind direction/azimuth unverified; speed-only not used")
        if signed_out >= MLB_WIND_OUT_STRONG:
            adj += MLB_WIND_OUT_STRONG_ADJ
            notes.append(f"wind out {signed_out:.0f}mph>=+{MLB_WIND_OUT_STRONG:g}")
        elif signed_out >= MLB_WIND_OUT_MODERATE:
            adj += MLB_WIND_OUT_MODERATE_ADJ
            notes.append(f"wind out {signed_out:.0f}mph>=+{MLB_WIND_OUT_MODERATE:g}")
        elif signed_out <= -MLB_WIND_OUT_STRONG:
            adj -= MLB_WIND_OUT_STRONG_ADJ
            notes.append(f"wind in {signed_out:.0f}mph<=-{MLB_WIND_OUT_STRONG:g}")
        elif signed_out <= -MLB_WIND_OUT_MODERATE:
            adj -= MLB_WIND_OUT_MODERATE_ADJ
            notes.append(f"wind in {signed_out:.0f}mph<=-{MLB_WIND_OUT_MODERATE:g}")
        if precip is not None and precip >= MLB_PRECIP_STRONG:
            adj += MLB_PRECIP_ADJ
            notes.append(f"precip {precip:.0f}%>=70")
        adj = max(-MLB_WEATHER_CAP, min(MLB_WEATHER_CAP, adj))
    else:
        if wind >= FOOTBALL_WIND_STRONG:
            adj += FOOTBALL_WIND_STRONG_ADJ
            notes.append(f"wind {wind:.0f}mph>={FOOTBALL_WIND_STRONG:g}")
        elif wind >= FOOTBALL_WIND_MODERATE:
            adj += FOOTBALL_WIND_MODERATE_ADJ
            notes.append(f"wind {wind:.0f}mph>={FOOTBALL_WIND_MODERATE:g}")
        if precip is not None and precip >= FOOTBALL_PRECIP_STRONG:
            adj += FOOTBALL_PRECIP_ADJ
            notes.append(f"precip {precip:.0f}%>=70")
        adj = max(-FOOTBALL_WEATHER_CAP, min(FOOTBALL_WEATHER_CAP, adj))
    status = "WEATHER_THRESHOLDS_VERIFIED_APPLIED" if notes else "WEATHER_CALM_NO_EFFECT"
    detail = ("; ".join(notes) if notes else "all conditions below declared thresholds")
    detail += f" [{WEATHER_SOURCE}]"
    return adj, status, detail


# ---------------------------------------------------------------------------
# 4. NFL/CFB key numbers (empirical push model)
# ---------------------------------------------------------------------------
# Source: ESPN public scoreboard API (free, public, no key), derived by
# scripts/derive_key_number_table.py. NFL seasons 2020-2023, CFB 2021-2023.
# P(|home margin| == k), k = 0..40. Filled in after derivation runs.
KEY_NUMBER_SOURCE = "ESPN public scoreboard API (free, public, no key)"
KEY_NUMBER_SEASONS = {"NFL": (2020, 2021, 2022, 2023), "CFB": (2021, 2022, 2023)}
KEY_MARGIN_FREQUENCIES: dict[str, dict[int, float]] = {
    'NFL': {
        0: 0.003584,
        1: 0.045699,
        2: 0.047491,
        3: 0.151434,
        4: 0.051971,
        5: 0.041219,
        6: 0.066308,
        7: 0.076165,
        8: 0.048387,
        9: 0.020609,
        10: 0.051075,
        11: 0.022401,
        12: 0.019713,
        13: 0.012545,
        14: 0.055556,
        15: 0.018817,
        16: 0.020609,
        17: 0.03405,
        18: 0.022401,
        19: 0.010753,
        20: 0.020609,
        21: 0.016129,
        22: 0.008961,
        23: 0.018817,
        24: 0.018817,
        25: 0.010753,
        26: 0.015233,
        27: 0.006272,
        28: 0.014337,
        29: 0.00448,
        30: 0.00448,
        31: 0.008961,
        32: 0.003584,
        34: 0.003584,
        35: 0.008065,
        37: 0.00448,
        38: 0.001792,
        39: 0.000896,
        40: 0.00448,
    },
    'CFB': {
        1: 0.026672,
        2: 0.030776,
        3: 0.095199,
        4: 0.031596,
        5: 0.019286,
        6: 0.030365,
        7: 0.080837,
        8: 0.027082,
        9: 0.015593,
        10: 0.043086,
        11: 0.018055,
        12: 0.013541,
        13: 0.018876,
        14: 0.041444,
        15: 0.015593,
        16: 0.008617,
        17: 0.038982,
        18: 0.022569,
        19: 0.01149,
        20: 0.017234,
        21: 0.038572,
        22: 0.009848,
        23: 0.014362,
        24: 0.026672,
        25: 0.015593,
        26: 0.011079,
        27: 0.016003,
        28: 0.031186,
        29: 0.009848,
        30: 0.008207,
        31: 0.025031,
        32: 0.013952,
        33: 0.007796,
        34: 0.014362,
        35: 0.015593,
        36: 0.004103,
        37: 0.009027,
        38: 0.015593,
        39: 0.008207,
        40: 0.003693,
    },
}

KEY_NUMBER_MAX_LINE = 40  # empirical table support


def key_number_push_probability(sport: str, line: float | None,
                                normal_push: float) -> tuple[float, str, str]:
    """Blend the normal-model push estimate with the empirical key-number rate.

    Declared blend: push = 0.5 * empirical + 0.5 * normal, for integer lines
    within table support. Non-integer lines or missing table -> normal model
    unchanged (PUSH_AWARE_ONLY). Returns (push_p, status, detail).
    """
    sport = str(sport or "").upper()
    try:
        base = max(0.0, min(1.0, float(normal_push)))
    except (TypeError, ValueError):
        return 0.0, "KEY_NUMBER_PUSH_INVALID", "normal push non-numeric"
    if line is None:
        return base, "KEY_NUMBER_NOT_APPLICABLE", "no line (ML market)"
    try:
        line_f = float(line)
    except (TypeError, ValueError):
        return base, "KEY_NUMBER_PUSH_INVALID", "line non-numeric"
    if not math.isfinite(line_f):
        # NaN/inf line: fail closed to the normal push (found by red-team).
        return base, "KEY_NUMBER_PUSH_INVALID", "line non-finite"
    freq = KEY_MARGIN_FREQUENCIES.get(sport) or {}
    k = int(round(abs(line_f)))
    if not freq or abs(line_f - round(line_f)) > 1e-9 or k > KEY_NUMBER_MAX_LINE:
        return base, "PUSH_AWARE_ONLY", (
            "integer key-number table unavailable for this line; normal push kept")
    empirical = freq.get(k)
    if empirical is None:
        return base, "PUSH_AWARE_ONLY", "no empirical rate at this key number"
    blended = 0.5 * empirical + 0.5 * base
    return blended, "KEY_NUMBER_PUSH_VERIFIED", (
        f"|line|={k}: empirical push {empirical:.4f} blended 50/50 with "
        f"normal {base:.4f} -> {blended:.4f} [{KEY_NUMBER_SOURCE}]")


def apply_key_push(win: float, push_normal: float, loss: float,
                   push_new: float) -> tuple[float, float, float]:
    """Rescale (win, loss) to the new push probability, preserving win:loss ratio."""
    win, loss = float(win), float(loss)
    denom = 1.0 - float(push_normal)
    if denom <= 0:
        scale = 0.0
    else:
        scale = max(0.0, (1.0 - float(push_new)) / denom)
    win_new = max(0.0, min(1.0, win * scale))
    loss_new = max(0.0, min(1.0, loss * scale))
    push_new = max(0.0, min(1.0, float(push_new)))
    return win_new, push_new, loss_new


# ---------------------------------------------------------------------------
# 5. MLB umpire — NOT_WIRED
# ---------------------------------------------------------------------------
UMPIRE_FACTOR_STATUS = "NOT_WIRED"
UMPIRE_NOT_WIRED_REASON = (
    "Historical home-plate umpire assignments are verifiable in MLB StatsAPI "
    "boxscores (officials[].officialType == 'Home Plate'), but MLB publishes "
    "no stable free pregame umpire-assignment feed; assignments are announced "
    "day-of via press release. Without a verifiable pregame source the factor "
    "cannot enter pregame pricing. Fails closed by design. "
    "2026-10-11 probe (docs/umpscorecards_probe.md): umpscorecards.com's "
    "frontend data path is Patreon-gated (no keyless API; 4-request probe, "
    "fixture in tests/fixtures/umpscorecards_probe_20261011.json) -> still no "
    "stable free source. ABS challenge system (2026) structurally shrinks the "
    "umpire effect; factor stays MISSING until the harness proves a residual.")


# ---------------------------------------------------------------------------
# Registry + validation verdicts
# ---------------------------------------------------------------------------
# validation verdicts are filled by scripts/validate_free_factors.py runs:
#   PASS / CONDITIONAL_PASS / FAIL / NOT_RUN, plus a one-line summary.
FACTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "mlb_park_factors": {
        "source": PARK_FACTOR_SOURCE,
        "derivation": PARK_FACTOR_DERIVATION,
        "wired": False,
        "validation": "FAIL",
        "validation_note": "Brier 0.2387->0.2423 (worse); LL improved. Re-validated after fixing team= derivation bug. NOT wired.",
    },
    "rest_travel": {
        "source": "ESPN public team schedule API + Open-Meteo geocoding (static geography)",
        "wired": True,
        "validation": "CONDITIONAL_PASS",
        "validation_note": "Rest: Brier 0.24673->0.24645. Travel: 0.24673->0.24661. Rest wired (rest_margin_adj); travel interface defined, venue extraction pending.",
    },
    "weather_thresholds": {
        "source": WEATHER_SOURCE,
        "wired": False,
        "validation": "FAIL",
        "validation_note": ("2026-10-11: declared wind/precip thresholds FAIL "
                            "vs legacy heuristic OOS (MLB Jun-Aug 2025 totals, "
                            "n=11575; Brier 0.2320->0.2321, LL 0.7120->0.7093). "
                            "NOT wired. Harness validated the wind leg only: "
                            "ERA5 archive serves no precipitation_probability "
                            "(verified all-nulls)."),
    },
    "key_numbers": {
        "source": KEY_NUMBER_SOURCE,
        "derivation": "scripts/derive_key_number_table.py",
        "wired": True,
        "validation": "CONDITIONAL_PASS",
        "validation_note": "NFL push: Brier 0.1166->0.1096. CFB push: 0.0642->0.0623. Wired with labels.",
    },
    "mlb_umpire": {
        "source": "none stable pregame (historical only: MLB StatsAPI boxscore officials)",
        "wired": False,
        "validation": "NOT_WIRED",
        "validation_note": UMPIRE_NOT_WIRED_REASON,
    },
    # Explicitly out of scope; never attempted.
    "news_speed": {"wired": False, "validation": "NOT_WIRED",
                   "validation_note": "Out of scope: no verifiable free pregame source."},
    "motivation_spots": {"wired": False, "validation": "NOT_WIRED",
                         "validation_note": "Out of scope: subjective, no verifiable free source."},
    "officiating_tendencies": {"wired": False, "validation": "NOT_WIRED",
                               "validation_note": "Out of scope: no verifiable free pregame source."},
}


# ---------------------------------------------------------------------------
# 6. Injury / participation (NFL, CFB)
# ---------------------------------------------------------------------------
# Source: ESPN injuries API (free, public, no key), team-group identity
# verified exactly as in artifacts/free_models.py injury_points.
# VALIDATION STATUS: NOT_VALIDATABLE via the backtest harness -- ESPN
# publishes no archived point-in-time injury feed (the ?dates= parameter is
# ignored; verified 2026-10-11), so the production rule cannot be scored
# out-of-sample. An ORACLE ablation (post-game boxscore QB1-out labels)
# sizes the declared coefficient; it is INFORMATIONAL, not a gate pass.
# Production status stays HEURISTIC_NOT_VALIDATED, fail-closed.
QB_OUT_ADJUSTMENT = {"NFL": -2.5, "CFB": -3.0}  # declared pts to team's mean
# NOTE: when QB_OUT_VERIFIED_APPLIED fires, production must NOT also apply
# the generic injury_points QB 1.5 component (no double-count).


def qb_out_adjustment(sport: str, verified: bool,
                      qb_name: str | None = None) -> tuple[float, str, str]:
    """Declared QB-out adjustment, added to the affected TEAM's mean.

    Verified (team-identity-checked ESPN out/doubtful QB) -> declared
    points; anything else -> (0.0, QB_STATUS_NOT_VERIFIED, ...) fail-closed.
    Backup quality is NEVER invented: the adjustment is a conservative
    declared team-level effect, not a backup-QB rating.
    """
    sport = str(sport or "").upper()
    if not verified:
        return 0.0, "QB_STATUS_NOT_VERIFIED", (
            "no team-verified QB out/doubtful report; no adjustment")
    adj = QB_OUT_ADJUSTMENT.get(sport)
    if adj is None:
        return 0.0, "QB_OUT_NOT_APPLICABLE", f"no declared QB value for {sport}"
    who = f" ({qb_name})" if qb_name else ""
    return adj, "QB_OUT_VERIFIED_APPLIED", (
        f"verified QB out/doubtful{who} -> {adj:+.1f} pts to team mean "
        f"(declared, fail-closed; backup quality NOT invented)")


# ---------------------------------------------------------------------------
# 7. MLB starting pitcher
# ---------------------------------------------------------------------------
# Source: MLB StatsAPI schedule hydrate=probablePitcher (free, public) for
# the probable starter; pitcher game logs (people/{id}/stats?stats=gameLog)
# for ERA over starts strictly before as_of. Declared formula, NOT fitted.
PITCHER_LEAGUE_AVG_ERA = 4.20
PITCHER_ERA_POINTS_PER_RUN = 0.40
PITCHER_ADJ_CAP = 1.2
PITCHER_MIN_STARTS = 5


def pitcher_quality_adjustment(era_prior: float | None,
                               n_starts: int) -> tuple[float, str, str]:
    """Declared pitcher adjustment, added to the OPPONENT's run mean.

    +0.40 runs per point of ERA above 4.20 (cap +/-1.2). Fewer than 5 prior
    starts -> (0.0, PITCHER_HISTORY_INSUFFICIENT, ...) fail-closed.
    """
    try:
        n = int(n_starts)
    except (TypeError, ValueError):
        n = 0
    if era_prior is None or n < PITCHER_MIN_STARTS:
        return 0.0, "PITCHER_HISTORY_INSUFFICIENT", (
            f"only {n} prior starts (< {PITCHER_MIN_STARTS}); no adjustment")
    try:
        era = float(era_prior)
    except (TypeError, ValueError):
        return 0.0, "PITCHER_HISTORY_INSUFFICIENT", "ERA non-numeric"
    if not math.isfinite(era) or era < 0:
        return 0.0, "PITCHER_HISTORY_INSUFFICIENT", "ERA invalid"
    adj = max(-PITCHER_ADJ_CAP,
              min(PITCHER_ADJ_CAP, PITCHER_ERA_POINTS_PER_RUN * (era - PITCHER_LEAGUE_AVG_ERA)))
    return adj, "PITCHER_VERIFIED_APPLIED", (
        f"ERA {era:.2f} over {n} starts vs lg avg {PITCHER_LEAGUE_AVG_ERA} "
        f"-> {adj:+.2f} runs to opponent mean (declared)")


# ---------------------------------------------------------------------------
# 8. MLB bullpen workload
# ---------------------------------------------------------------------------
# Source: MLB StatsAPI boxscores (free, public): bullpen pitches =
# team total pitches minus starter pitches, summed over the trailing 3
# calendar days. Declared thresholds, NOT fitted.
BULLPEN_TAXED_PITCHES = 170
BULLPEN_ELEVATED_PITCHES = 130
BULLPEN_TAXED_ADJ = 0.40
BULLPEN_ELEVATED_ADJ = 0.25


def bullpen_workload_adjustment(trailing_3d_pitches: float | None,
                                n_games: int = 0) -> tuple[float, str, str]:
    """Declared bullpen-fatigue adjustment, added to the OPPONENT's run mean.

    >=170 trailing-3d bullpen pitches -> +0.40; >=130 -> +0.25; else 0.
    Unverifiable workload -> (0.0, BULLPEN_WORKLOAD_UNVERIFIED, ...) fail-closed.
    """
    if trailing_3d_pitches is None or n_games <= 0:
        return 0.0, "BULLPEN_WORKLOAD_UNVERIFIED", (
            "trailing bullpen workload unverifiable; no adjustment")
    try:
        p = float(trailing_3d_pitches)
    except (TypeError, ValueError):
        return 0.0, "BULLPEN_WORKLOAD_UNVERIFIED", "pitches non-numeric"
    if not math.isfinite(p) or p < 0:
        return 0.0, "BULLPEN_WORKLOAD_UNVERIFIED", "pitches invalid"
    if p >= BULLPEN_TAXED_PITCHES:
        adj = BULLPEN_TAXED_ADJ
        note = f"taxed ({p:.0f} >= {BULLPEN_TAXED_PITCHES})"
    elif p >= BULLPEN_ELEVATED_PITCHES:
        adj = BULLPEN_ELEVATED_ADJ
        note = f"elevated ({p:.0f} >= {BULLPEN_ELEVATED_PITCHES})"
    else:
        return 0.0, "BULLPEN_OK", f"{p:.0f} trailing-3d bullpen pitches; no fatigue flag"
    return adj, "BULLPEN_TAXED_APPLIED", (
        f"{note} over {n_games} games -> +{adj:.2f} runs to opponent mean (declared)")


# ---------------------------------------------------------------------------
# 9. Backups / depth -- verifiability assessment
# ---------------------------------------------------------------------------
# WHO is out is verifiable (ESPN injuries, team-identity-checked). Backup
# QUALITY has no verifiable free measure: no free source publishes
# backup-specific ratings, and inventing one from vibes is prohibited.
# Therefore this factor contributes NO numeric adjustment by design; the
# audit reports who's out (verified) and marks backup quality NOT_INVENTED
# / MISSING with this reason. The team-level declared adjustments above
# (QB-out, injury_points) are the only participation effects.
BACKUP_QUALITY_STATUS = "NOT_INVENTED"
BACKUP_QUALITY_REASON = (
    "Who is out is verifiable via ESPN injuries (team-identity-checked); no "
    "free source publishes backup-quality ratings, so none is invented. "
    "Team-level declared adjustments (QB-out, injury_points) are the only "
    "participation effects; per-backup ratings stay MISSING by design.")


# ---------------------------------------------------------------------------
# 10. MLB rotation: starter days-rest / rotation spot
# ---------------------------------------------------------------------------
# Source: MLB StatsAPI pitcher game logs (free, public): days since the
# probable starter's last start, strictly before as_of. Declared short-rest
# penalty only; no declared long-rest or rotation-order effect (insufficient
# basis). Fail closed when unverifiable.
ROTATION_SHORT_REST_DAYS = 4
ROTATION_SHORT_REST_ADJ = 0.50


def rotation_rest_adjustment(days_rest: float | None) -> tuple[float, str, str]:
    """Declared short-rest penalty, added to the OPPONENT's run mean.

    Starter on <4 days rest -> +0.50 runs to opponent. Anything else
    verified -> 0. Unverifiable -> (0.0, ROTATION_REST_UNVERIFIED, ...).
    """
    if days_rest is None:
        return 0.0, "ROTATION_REST_UNVERIFIED", (
            "days since last start unverifiable; no adjustment")
    try:
        d = float(days_rest)
    except (TypeError, ValueError):
        return 0.0, "ROTATION_REST_UNVERIFIED", "days rest non-numeric"
    if not math.isfinite(d) or d < 0:
        return 0.0, "ROTATION_REST_UNVERIFIED", "days rest invalid"
    if d < ROTATION_SHORT_REST_DAYS:
        return ROTATION_SHORT_REST_ADJ, "ROTATION_SHORT_REST_APPLIED", (
            f"starter on {d:.0f} days rest (< {ROTATION_SHORT_REST_DAYS}) "
            f"-> +{ROTATION_SHORT_REST_ADJ:.2f} runs to opponent mean (declared)")
    return 0.0, "ROTATION_REST_OK", f"starter on {d:.0f} days rest; no penalty"


# ---------------------------------------------------------------------------
# Ingestion entry points (for the Phase 8 pre-pricing stage in run_it_full.py)
# ---------------------------------------------------------------------------
# Every entry point returns a dict:
#   {"factor": str, "kind": "add"|"scale"|"push"|"none",
#    "target": "TOTAL"|"HOME_MARGIN"|"HOME_MEAN"|"AWAY_MEAN"|"OPPONENT_MEAN"|None,
#    "value": float | tuple | None, "status": str, "detail": str,
#    "source": str, "verified": bool}
# Application rules for the ingestion stage:
#   add/TOTAL        -> home_mean += v/2; away_mean += v/2
#   add/HOME_MARGIN  -> home_mean += v/2; away_mean -= v/2
#   add/HOME_MEAN or AWAY_MEAN -> direct
#   add/OPPONENT_MEAN (needs "side": "home"|"away") -> the other team's mean += v
#   scale/BOTH_MEANS -> home_mean *= v; away_mean *= v
#   push             -> value is (win, push, loss) replacing the base triple
#   none             -> no pricing effect; status/detail are audit-only
# verified=False or status not in the entry point's APPLIED set -> the
# ingestion stage MUST NOT apply any pricing effect (fail closed).

def _entry(factor, kind, target, value, status, detail, source, applied_statuses):
    return {
        "factor": factor, "kind": kind, "target": target, "value": value,
        "status": status, "detail": detail, "source": source,
        "verified": status in applied_statuses,
        "applied_statuses": list(applied_statuses),
    }


def ingest_mlb_park(home_team_name: str, season: int) -> dict:
    """Park-factor scale for both teams' run means. Signature:
    ingest_mlb_park(home_team_name: str, season: int) -> entry dict."""
    pf, status, detail = park_factor_for(home_team_name, season)
    ok = {"PARK_FACTOR_VERIFIED"}
    return _entry("mlb_park_factors", "scale" if status in ok else "none",
                  "BOTH_MEANS", park_runs_scale(pf) if status in ok else None,
                  status, detail, PARK_FACTOR_SOURCE, ok)


def ingest_rest(sport: str, home_rest_days, away_rest_days) -> dict:
    """Rest-differential margin adjustment. Signature:
    ingest_rest(sport: str, home_rest_days, away_rest_days) -> entry dict."""
    adj, status, detail = rest_margin_adjustment(home_rest_days, away_rest_days)
    ok = {"REST_VERIFIED_APPLIED"}
    return _entry("rest_travel", "add" if status in ok else "none",
                  "HOME_MARGIN", adj if status in ok else 0.0,
                  status, detail,
                  "ESPN public team schedule API (free, public, no key)", ok)


def ingest_travel(sport: str, traveler_side: str, miles, tz_jumps) -> dict:
    """Travel-burden adjustment to the traveler's mean. Signature:
    ingest_travel(sport: str, traveler_side: str, miles, tz_jumps) -> entry dict."""
    adj, status, detail = travel_margin_adjustment(miles, tz_jumps,
                                                  traveler=traveler_side)
    ok = {"TRAVEL_VERIFIED_APPLIED"}
    target = (traveler_side.upper() + "_MEAN") if status in ok else None
    return _entry("rest_travel", "add" if status in ok else "none",
                  target, adj if status in ok else 0.0,
                  status, detail,
                  "ESPN venue geography + Open-Meteo geocoding (static)", ok)


def ingest_weather(sport: str, wind_speed_mph, wind_from_degrees=None,
                   field_azimuth_degrees=None, precip_probability_pct=None,
                   indoor=None) -> dict:
    """Declared weather total adjustment. Signature:
    ingest_weather(sport, wind_speed_mph, wind_from_degrees=None,
                   field_azimuth_degrees=None, precip_probability_pct=None,
                   indoor=None) -> entry dict.

    Harness verdict 2026-10-11: the declared wind/precip thresholds FAILED
    vs the legacy production heuristic OOS (docs/validation_reports/
    weather.json; Brier 0.2320->0.2321). WEATHER_THRESHOLDS_VALIDATED is
    False -> this entry is AUDIT-ONLY until a future validation passes.
    """
    adj, status, detail = weather_total_adjustment(
        sport=sport, wind_speed_mph=wind_speed_mph,
        wind_from_degrees=wind_from_degrees,
        field_azimuth_degrees=field_azimuth_degrees,
        precip_probability_pct=precip_probability_pct, indoor=indoor)
    if not WEATHER_THRESHOLDS_VALIDATED:
        detail += (" [NOT_WIRED: declared thresholds FAILED harness "
                   "validation 2026-10-11 vs legacy heuristic; audit only]")
        return _entry("weather_thresholds", "none", None, 0.0,
                      status, detail, WEATHER_SOURCE, set())
    ok = {"WEATHER_THRESHOLDS_VERIFIED_APPLIED", "WEATHER_CALM_NO_EFFECT"}
    return _entry("weather_thresholds", "add" if status in ok else "none",
                  "TOTAL", adj if status in ok else 0.0,
                  status, detail, WEATHER_SOURCE, ok)


def ingest_key_numbers(sport: str, market: str, line, win: float, push: float,
                       loss: float) -> dict:
    """Key-number push blend. Signature:
    ingest_key_numbers(sport, market, line, win, push, loss) -> entry dict
    with value=(win, push, loss). Only for SPREAD/TOTAL integer lines."""
    market = str(market or "").upper()
    if market not in ("SPREAD", "TOTAL"):
        return _entry("key_numbers", "none", None, None,
                      "KEY_NUMBER_NOT_APPLICABLE",
                      "key-number push only applies to SPREAD/TOTAL",
                      KEY_NUMBER_SOURCE, set())
    new_push, status, detail = key_number_push_probability(sport, line, push)
    ok = {"KEY_NUMBER_PUSH_VERIFIED", "PUSH_AWARE_ONLY"}
    if status not in ok:
        # Fail closed: audit-only, no pricing effect (red-team hardening).
        return _entry("key_numbers", "none", None, None,
                      status, detail, KEY_NUMBER_SOURCE, ok)
    win2, push2, loss2 = apply_key_push(win, push, loss, new_push)
    return _entry("key_numbers", "push", None, (win2, push2, loss2),
                  status, detail, KEY_NUMBER_SOURCE, ok)


def ingest_mlb_pitcher(side: str, probable_pitcher_name, era_prior,
                       n_starts: int) -> dict:
    """Starting-pitcher quality adjustment to the OPPONENT's mean. Signature:
    ingest_mlb_pitcher(side: str, probable_pitcher_name, era_prior,
                       n_starts: int) -> entry dict. side is the pitcher's team."""
    adj, status, detail = pitcher_quality_adjustment(era_prior, n_starts)
    ok = {"PITCHER_VERIFIED_APPLIED"}
    entry = _entry("starting_pitcher", "add" if status in ok else "none",
                   "OPPONENT_MEAN", adj if status in ok else 0.0,
                   status, detail,
                   "MLB StatsAPI probablePitcher + game logs (free, public)", ok)
    entry["side"] = str(side or "").lower()
    entry["pitcher"] = str(probable_pitcher_name or "")
    return entry


def ingest_mlb_bullpen(side: str, trailing_3d_pitches, n_games: int) -> dict:
    """Bullpen-workload adjustment to the OPPONENT's mean. Signature:
    ingest_mlb_bullpen(side: str, trailing_3d_pitches, n_games: int)
    -> entry dict. side is the bullpen's team."""
    adj, status, detail = bullpen_workload_adjustment(trailing_3d_pitches, n_games)
    ok = {"BULLPEN_TAXED_APPLIED", "BULLPEN_OK"}
    entry = _entry("bullpen_workload", "add" if status in ok else "none",
                   "OPPONENT_MEAN", adj if status in ok else 0.0,
                   status, detail,
                   "MLB StatsAPI boxscores (free, public)", ok)
    entry["side"] = str(side or "").lower()
    return entry


def ingest_mlb_rotation(side: str, days_rest) -> dict:
    """Rotation short-rest penalty to the OPPONENT's mean. Signature:
    ingest_mlb_rotation(side: str, days_rest) -> entry dict."""
    adj, status, detail = rotation_rest_adjustment(days_rest)
    ok = {"ROTATION_SHORT_REST_APPLIED", "ROTATION_REST_OK"}
    entry = _entry("rotation", "add" if status in ok else "none",
                   "OPPONENT_MEAN", adj if status in ok else 0.0,
                   status, detail,
                   "MLB StatsAPI pitcher game logs (free, public)", ok)
    entry["side"] = str(side or "").lower()
    return entry


def ingest_participation(sport: str, team_side: str, qb_out_verified: bool,
                         qb_name: str | None = None) -> dict:
    """QB-out participation adjustment to the team's mean. Signature:
    ingest_participation(sport: str, team_side: str, qb_out_verified: bool,
                         qb_name: str | None = None) -> entry dict.
    qb_out_verified must come from team-identity-checked ESPN out/doubtful
    data; never from rumors. Backup quality is NOT invented."""
    adj, status, detail = qb_out_adjustment(sport, qb_out_verified, qb_name)
    ok = {"QB_OUT_VERIFIED_APPLIED"}
    target = (str(team_side or "").upper() + "_MEAN") if status in ok else None
    return _entry("injury_participation", "add" if status in ok else "none",
                  target, adj if status in ok else 0.0,
                  status, detail,
                  "ESPN injuries API, team-identity-verified (free, public)", ok)


def umpire_entry() -> dict:
    """MLB umpire factor: NOT_WIRED by design (no stable free pregame source)."""
    return _entry("mlb_umpire", "none", None, None, UMPIRE_FACTOR_STATUS,
                  UMPIRE_NOT_WIRED_REASON,
                  "none stable pregame (historical only: MLB StatsAPI boxscore)",
                  set())


INGEST_ENTRY_POINTS = {
    "mlb_park_factors": "ingest_mlb_park(home_team_name: str, season: int)",
    "rest": "ingest_rest(sport: str, home_rest_days, away_rest_days)",
    "travel": "ingest_travel(sport: str, traveler_side: str, miles, tz_jumps)",
    "weather": ("ingest_weather(sport: str, wind_speed_mph, wind_from_degrees=None, "
                "field_azimuth_degrees=None, precip_probability_pct=None, indoor=None)"),
    "key_numbers": "ingest_key_numbers(sport: str, market: str, line, win: float, push: float, loss: float)",
    "starting_pitcher": "ingest_mlb_pitcher(side: str, probable_pitcher_name, era_prior, n_starts: int)",
    "bullpen_workload": "ingest_mlb_bullpen(side: str, trailing_3d_pitches, n_games: int)",
    "rotation": "ingest_mlb_rotation(side: str, days_rest)",
    "injury_participation": "ingest_participation(sport: str, team_side: str, qb_out_verified: bool, qb_name: str | None = None)",
    "mlb_umpire": "umpire_entry()  # NOT_WIRED",
}



# ---------------------------------------------------------------------------
# 11. Team strength: SRS (opponent-adjusted) ratings -- backlog UNIVERSAL
# ---------------------------------------------------------------------------
# Source: game scores from ESPN scoreboards / MLB StatsAPI (free, public).
# Simple Rating System: rating_i = mean(mov_i) + mean(ratings of opponents),
# solved iteratively, mean-centered. Declared (not fitted): 100 iterations,
# recency half-life 45 days (weight 0.5^((as_of - game)/45d)).
SRS_ITERATIONS = 100
SRS_RECENCY_HALF_LIFE_DAYS = 45.0


def srs_ratings(games: list[tuple[str, str, float, float]]) -> dict[str, float]:
    """games: (home_team, away_team, home_mov, days_ago). Returns team->SRS."""
    teams = sorted({t for g in games for t in g[:2]})
    if not teams:
        return {}
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    r = [0.0] * n
    weights = [0.5 ** (max(0.0, float(g[3])) / SRS_RECENCY_HALF_LIFE_DAYS)
               for g in games]
    for _ in range(SRS_ITERATIONS):
        num = [0.0] * n
        den = [0.0] * n
        for (h, a, mov, _), w in zip(games, weights):
            i, j = idx[h], idx[a]
            num[i] += w * (mov + r[j])
            den[i] += w
            num[j] += w * (-mov + r[i])
            den[j] += w
        r = [num[i] / den[i] if den[i] > 0 else 0.0 for i in range(n)]
    mean = sum(r) / n
    return {t: r[idx[t]] - mean for t in teams}


def srs_predicted_margin(srs: dict[str, float], home_team: str,
                         away_team: str, league_hfa: float) -> tuple[float | None, str]:
    """Predicted home margin from SRS + league HFA. Missing team -> (None, reason)."""
    if home_team not in srs or away_team not in srs:
        return None, "SRS_TEAM_UNRATED"
    try:
        return (srs[home_team] - srs[away_team] + float(league_hfa)), "SRS_VERIFIED"
    except (TypeError, ValueError):
        return None, "SRS_HFA_INVALID"


# ---------------------------------------------------------------------------
# 12. Venue-specific HFA -- backlog UNIVERSAL
# ---------------------------------------------------------------------------
# Source: same game scores. team_home_edge = mean(home mov) - mean(away mov)
# from the team's perspective; shrunk toward the league-average edge with
# n/(n+30) (declared shrinkage). Needs >=8 home and >=8 road games.
VENUE_HFA_SHRINK_GAMES = 30
VENUE_HFA_MIN_GAMES = 8


def venue_hfa_delta(home_movs: list[float], road_movs: list[float],
                    league_home_edge: float) -> tuple[float, str, str]:
    """Extra home-field edge for a team vs the league average (margin points).

    home_movs/road_movs: the team's margins from its own perspective.
    Returns (delta, status, detail); delta is added to the home margin when
    this team is home. Fail closed when unverified.
    """
    try:
        league_home_edge = float(league_home_edge)
    except (TypeError, ValueError):
        return 0.0, "VENUE_HFA_UNVERIFIED", "league edge non-numeric"
    if len(home_movs) < VENUE_HFA_MIN_GAMES or len(road_movs) < VENUE_HFA_MIN_GAMES:
        return 0.0, "VENUE_HFA_UNVERIFIED", (
            f"only {len(home_movs)}H/{len(road_movs)}R games "
            f"(<{VENUE_HFA_MIN_GAMES}); no venue edge")
    team_edge = sum(home_movs) / len(home_movs) - sum(road_movs) / len(road_movs)
    n = len(home_movs)
    shrunk = (league_home_edge + (team_edge - league_home_edge)
              * n / (n + VENUE_HFA_SHRINK_GAMES))
    delta = shrunk - league_home_edge
    return delta, "VENUE_HFA_VERIFIED", (
        f"team home edge {team_edge:+.2f} vs league {league_home_edge:+.2f} "
        f"(n={n}, shrunk) -> {delta:+.2f} pts home margin (declared)")


# ---------------------------------------------------------------------------
# 13. Pace / tempo (NFL) -- backlog UNIVERSAL/NFL
# ---------------------------------------------------------------------------
# Source: ESPN NFL game summaries, boxscore team statistic
# "totalOffensivePlays" (free, public). Declared: each play above/below the
# season-to-date league average shifts the total by 0.12 points (bounded).
PACE_POINTS_PER_PLAY = 0.12
PACE_TOTAL_CAP = 1.5


def pace_total_adjustment(home_plays_pg: float | None,
                          away_plays_pg: float | None,
                          league_avg_plays_pg: float | None) -> tuple[float, str, str]:
    """Declared pace adjustment, added to the game TOTAL (split evenly)."""
    try:
        hp = float(home_plays_pg) if home_plays_pg is not None else None
        ap = float(away_plays_pg) if away_plays_pg is not None else None
        lg = float(league_avg_plays_pg) if league_avg_plays_pg is not None else None
    except (TypeError, ValueError):
        return 0.0, "PACE_UNVERIFIED", "pace inputs non-numeric"
    if hp is None or ap is None or lg is None:
        return 0.0, "PACE_UNVERIFIED", "pace missing for a side or league"
    if not all(math.isfinite(x) and x > 0 for x in (hp, ap, lg)):
        return 0.0, "PACE_UNVERIFIED", "pace inputs invalid"
    adj = max(-PACE_TOTAL_CAP,
              min(PACE_TOTAL_CAP, PACE_POINTS_PER_PLAY * ((hp + ap) / 2 - lg)))
    return adj, "PACE_VERIFIED_APPLIED", (
        f"pace {hp:.1f}/{ap:.1f} vs lg {lg:.1f} plays/g -> {adj:+.2f} total "
        f"(declared {PACE_POINTS_PER_PLAY}/play, cap {PACE_TOTAL_CAP})")


# ---------------------------------------------------------------------------
# 14. Turnover differential, REGRESSED (NFL) -- backlog NFL
# ---------------------------------------------------------------------------
# Source: ESPN NFL summaries, "turnovers" team statistic (free, public).
# Turnovers are high-luck: past turnover margin is regressed 70% toward zero
# and the NON-repeating luck is REMOVED from the team's rating-implied mean
# (declared 4.0 points per net turnover). This subtracts luck; it does not
# add a new signal.
TURNOVER_POINTS_EACH = 4.0
TURNOVER_REPEAT = 0.30  # 30% of past TO margin treated as repeating skill
TURNOVER_ADJ_CAP = 2.0


def turnover_luck_adjustment(to_diff_per_game: float | None) -> tuple[float, str, str]:
    """Remove non-repeating turnover luck from a TEAM's mean.

    to_diff_per_game = (takeaways - giveaways)/game over the trailing window.
    adj = -(1-0.30) * 4.0 * to_diff_pg, bounded +/-2.0. Positive past luck
    REDUCES the team's mean. Fail closed when unverified.
    """
    if to_diff_per_game is None:
        return 0.0, "TURNOVER_UNVERIFIED", "turnover differential unverifiable"
    try:
        d = float(to_diff_per_game)
    except (TypeError, ValueError):
        return 0.0, "TURNOVER_UNVERIFIED", "turnover differential non-numeric"
    if not math.isfinite(d):
        return 0.0, "TURNOVER_UNVERIFIED", "turnover differential non-finite"
    adj = max(-TURNOVER_ADJ_CAP,
              min(TURNOVER_ADJ_CAP, -(1 - TURNOVER_REPEAT) * TURNOVER_POINTS_EACH * d))
    return adj, "TURNOVER_REGRESSED_APPLIED", (
        f"TO diff {d:+.2f}/g, {TURNOVER_REPEAT:.0%} repeats -> {adj:+.2f} pts "
        f"to team mean (luck removed, declared {TURNOVER_POINTS_EACH}/TO)")


# ---------------------------------------------------------------------------
# 15. MLB starter FIP (in addition to ERA/WHIP) -- backlog MLB
# ---------------------------------------------------------------------------
# Source: MLB StatsAPI pitcher game logs (free, public). FIP from prior
# starts only: (13*HR + 3*(BB+HBP) - 2*K)/IP + 3.10 (declared constant).
FIP_CONSTANT = 3.10
FIP_POINTS_PER_RUN = 0.35
FIP_AVG = 4.10


def fip_from_gamelog(starts: list[dict]) -> tuple[float | None, int]:
    """starts: list of {"HR","BB","HBP","SO","IP"} from prior starts.

    Returns (FIP, n_starts). IP may use .1/.2 baseball notation.
    """
    tot_hr = tot_bb = tot_hbp = tot_k = tot_ip = 0.0
    n = 0
    for s in starts:
        try:
            ip_raw = str(s.get("IP") or "0")
            if "." in ip_raw:
                whole, frac = ip_raw.split(".")
                ip = float(whole) + {"0": 0.0, "1": 1 / 3, "2": 2 / 3}[frac]
            else:
                ip = float(ip_raw)
            hr = float(s.get("HR") or 0)
            bb = float(s.get("BB") or 0)
            hbp = float(s.get("HBP") or 0)
            k = float(s.get("SO") or s.get("K") or 0)
        except (TypeError, ValueError, KeyError):
            continue
        if ip <= 0:
            continue
        tot_hr += hr
        tot_bb += bb
        tot_hbp += hbp
        tot_k += k
        tot_ip += ip
        n += 1
    if n == 0 or tot_ip <= 0:
        return None, 0
    fip = (13 * tot_hr + 3 * (tot_bb + tot_hbp) - 2 * tot_k) / tot_ip + FIP_CONSTANT
    return fip, n


def pitcher_fip_adjustment(fip_prior: float | None,
                           n_starts: int) -> tuple[float, str, str]:
    """Declared FIP adjustment, added to the OPPONENT's run mean."""
    try:
        n = int(n_starts)
    except (TypeError, ValueError):
        n = 0
    if fip_prior is None or n < PITCHER_MIN_STARTS:
        return 0.0, "PITCHER_FIP_HISTORY_INSUFFICIENT", (
            f"only {n} prior starts (< {PITCHER_MIN_STARTS}); no adjustment")
    try:
        fip = float(fip_prior)
    except (TypeError, ValueError):
        return 0.0, "PITCHER_FIP_HISTORY_INSUFFICIENT", "FIP non-numeric"
    if not math.isfinite(fip) or fip < 0:
        return 0.0, "PITCHER_FIP_HISTORY_INSUFFICIENT", "FIP invalid"
    adj = max(-PITCHER_ADJ_CAP,
              min(PITCHER_ADJ_CAP, FIP_POINTS_PER_RUN * (fip - FIP_AVG)))
    return adj, "PITCHER_FIP_VERIFIED_APPLIED", (
        f"FIP {fip:.2f} over {n} starts vs avg {FIP_AVG} "
        f"-> {adj:+.2f} runs to opponent mean (declared)")


# ---------------------------------------------------------------------------
# Backlog ingest entry points (same contract as section above)
# ---------------------------------------------------------------------------

def ingest_srs_margin(srs_table: dict, home_team: str, away_team: str,
                      league_hfa: float) -> dict:
    """Opponent-adjusted predicted home margin. Signature:
    ingest_srs_margin(srs_table: dict, home_team: str, away_team: str,
                      league_hfa: float) -> entry dict (kind=margin)."""
    margin, status = srs_predicted_margin(srs_table, home_team, away_team,
                                          league_hfa)
    ok = {"SRS_VERIFIED"}
    return _entry("team_strength_srs", "margin" if status in ok else "none",
                  "HOME_MARGIN", margin, status,
                  f"SRS predicted home margin {margin:+.2f}" if status in ok else status,
                  "ESPN/StatsAPI game scores (free, public)", ok)


def ingest_venue_hfa(home_movs: list[float], road_movs: list[float],
                     league_home_edge: float) -> dict:
    """Venue-specific HFA delta. Signature:
    ingest_venue_hfa(home_movs: list[float], road_movs: list[float],
                     league_home_edge: float) -> entry dict."""
    delta, status, detail = venue_hfa_delta(home_movs, road_movs, league_home_edge)
    ok = {"VENUE_HFA_VERIFIED"}
    return _entry("venue_hfa", "add" if status in ok else "none",
                  "HOME_MARGIN", delta if status in ok else 0.0,
                  status, detail,
                  "ESPN/StatsAPI game scores (free, public)", ok)


def ingest_pace(home_plays_pg, away_plays_pg, league_avg_plays_pg) -> dict:
    """Pace total adjustment. Signature:
    ingest_pace(home_plays_pg, away_plays_pg, league_avg_plays_pg) -> entry dict."""
    adj, status, detail = pace_total_adjustment(home_plays_pg, away_plays_pg,
                                                league_avg_plays_pg)
    ok = {"PACE_VERIFIED_APPLIED"}
    return _entry("pace", "add" if status in ok else "none",
                  "TOTAL", adj if status in ok else 0.0,
                  status, detail,
                  "ESPN NFL summaries totalOffensivePlays (free, public)", ok)


def ingest_turnovers(to_diff_per_game, team_side: str) -> dict:
    """Regressed turnover-luck removal from a team's mean. Signature:
    ingest_turnovers(to_diff_per_game, team_side: str) -> entry dict."""
    adj, status, detail = turnover_luck_adjustment(to_diff_per_game)
    ok = {"TURNOVER_REGRESSED_APPLIED"}
    target = (str(team_side or "").upper() + "_MEAN") if status in ok else None
    return _entry("turnover_regressed", "add" if status in ok else "none",
                  target, adj if status in ok else 0.0,
                  status, detail,
                  "ESPN NFL summaries turnovers (free, public)", ok)


def ingest_mlb_pitcher_fip(side: str, probable_pitcher_name, fip_prior,
                           n_starts: int) -> dict:
    """FIP-based pitcher adjustment to the OPPONENT's mean. Signature:
    ingest_mlb_pitcher_fip(side: str, probable_pitcher_name, fip_prior,
                           n_starts: int) -> entry dict."""
    adj, status, detail = pitcher_fip_adjustment(fip_prior, n_starts)
    ok = {"PITCHER_FIP_VERIFIED_APPLIED"}
    entry = _entry("starting_pitcher_fip", "add" if status in ok else "none",
                   "OPPONENT_MEAN", adj if status in ok else 0.0,
                   status, detail,
                   "MLB StatsAPI game logs (free, public)", ok)
    entry["side"] = str(side or "").lower()
    entry["pitcher"] = str(probable_pitcher_name or "")
    return entry


INGEST_ENTRY_POINTS.update({
    "team_strength_srs": "ingest_srs_margin(srs_table: dict, home_team: str, away_team: str, league_hfa: float)",
    "venue_hfa": "ingest_venue_hfa(home_movs: list[float], road_movs: list[float], league_home_edge: float)",
    "pace": "ingest_pace(home_plays_pg, away_plays_pg, league_avg_plays_pg)",
    "turnover_regressed": "ingest_turnovers(to_diff_per_game, team_side: str)",
    "starting_pitcher_fip": "ingest_mlb_pitcher_fip(side: str, probable_pitcher_name, fip_prior, n_starts: int)",
})

FACTOR_REGISTRY.update({
    "team_strength_srs": {
        "source": "ESPN/StatsAPI game scores (free, public, no key)",
        "wired": False, "validation": "CONDITIONAL_PASS",
        "validation_note": "NFL: Brier 0.24913->0.23254 (large). Wiring deferred to Elo-foundation agent; interface ingest_srs_margin defined.",
    },
    "venue_hfa": {
        "source": "ESPN/StatsAPI game scores (free, public, no key)",
        "wired": False, "validation": "FAIL",
        "validation_note": "Brier improved 0.2491->0.2479 but log-loss worsened 0.6914->0.6934. NOT wired.",
    },
    "pace": {
        "source": "ESPN NFL summaries totalOffensivePlays (free, public)",
        "wired": False, "validation": "FAIL",
        "validation_note": "Brier 0.2430->0.2488, LL 0.6952->0.6961 (both worsened). NOT wired.",
    },
    "turnover_regressed": {
        "source": "ESPN NFL summaries turnovers (free, public)",
        "wired": False, "validation": "NOT_RUN", "validation_note": "",
    },
    "starting_pitcher_fip": {
        "source": "MLB StatsAPI pitcher game logs (free, public)",
        "wired": False, "validation": "NOT_RUN", "validation_note": "",
    },
    "injury_participation": {
        "source": "ESPN injuries API (free, public); NO archived point-in-time feed",
        "wired": False, "validation": "NOT_VALIDATABLE",
        "validation_note": ("ESPN publishes no archived injury feed (?dates= ignored, "
                            "verified 2026-10-11); production rule stays "
                            "HEURISTIC_NOT_VALIDATED, fail-closed. Oracle QB-out "
                            "ablation sizes the declared coefficient (informational)."),
    },
    "starting_pitcher": {
        "source": "MLB StatsAPI probablePitcher + game logs (free, public)",
        "wired": False, "validation": "NOT_RUN", "validation_note": "",
    },
    "bullpen_workload": {
        "source": "MLB StatsAPI boxscores (free, public)",
        "wired": False, "validation": "NOT_RUN", "validation_note": "",
    },
    "rotation": {
        "source": "MLB StatsAPI pitcher game logs (free, public)",
        "wired": False, "validation": "NOT_RUN", "validation_note": "",
    },
    "backups_depth": {
        "source": "none verifiable for backup quality",
        "wired": False, "validation": "NOT_WIRED",
        "validation_note": BACKUP_QUALITY_REASON,
    },
    # Backlog guardrails (non-negotiable per Isaac).
    "market_odds_as_features": {
        "source": "REJECTED", "wired": False, "validation": "NOT_WIRED",
        "validation_note": ("Market-blind discipline: market prices are never model "
                            "features; they appear only as the harness evaluation "
                            "baseline when archived prices exist."),
    },
    "nhl_soccer": {
        "source": "OUT_OF_SCOPE", "wired": False, "validation": "NOT_WIRED",
        "validation_note": "Our sports are NFL/CFB/MLB/NBA/CBB; NHL/Soccer out of scope.",
    },
    "motivation_coaching_news": {
        "source": "none verifiable", "wired": False, "validation": "NOT_WIRED",
        "validation_note": "Motivation spots, coaching tendencies, news speed: no verifiable free source; never attempted.",
    },
    "nba_factors": {
        "source": "QUEUED_FOR_PHASE_5", "wired": False, "validation": "NOT_RUN",
        "validation_note": ("ORtg/DRtg/net, pace, Four Factors, rest/altitude/travel, "
                            "lineups/usage: queued for the NBA phase (season tips "
                            "~Oct 20, 2026); harness has no NBA outcomes module yet."),
    },
    "nfl_epa": {
        "source": "nflverse (Phase 3 tracking-data standard)",
        "wired": False, "validation": "NOT_RUN",
        "validation_note": ("EPA/play, CPOE, success rate need play-by-play; nflverse "
                            "pipeline is Phase 3's mandate. Attempted opportunistically "
                            "in Phase 2 if the pipeline proves free+stable."),
    },
    "mlb_wrc_plus": {
        "source": "QUEUED", "wired": False, "validation": "NOT_RUN",
        "validation_note": "Opponent-adjusted offense (wRC+ proxy) needs batting game logs; queued behind pitcher/bullpen validation.",
    },
    "mlb_platoon_splits": {
        "source": "QUEUED", "wired": False, "validation": "NOT_RUN",
        "validation_note": "Platoon splits need handedness game logs; queued.",
    },
})


# ---------------------------------------------------------------------------
# 16. NFL EPA/play via nflverse -- backlog NFL
# ---------------------------------------------------------------------------
# Source: nflverse play_by_play CSVs, GitHub releases
# (https://github.com/nflverse/nflverse-data/releases/tag/pbp). Free, public,
# no key, no infrastructure for Isaac to run (bulk CSV download + aggregate).
# Team strength = trailing-8-week offensive EPA/play minus defensive EPA/play
# allowed (raw, not opponent-adjusted -- opponent-adjusted EPA is queued).
# Declared conversion: predicted home margin =
#   EPA_MARGIN_PER_UNIT * (strength_home - strength_away) + league_hfa.
EPA_SOURCE = ("nflverse play_by_play CSVs, GitHub releases "
              "(https://github.com/nflverse/nflverse-data/releases/tag/pbp)")
EPA_MARGIN_PER_UNIT = 55.0
EPA_TRAIL_WEEKS = 8
EPA_MIN_WEEKS = 4


def epa_predicted_margin(home_strength: float | None,
                         away_strength: float | None,
                         league_hfa: float = 1.5) -> tuple[float | None, str]:
    """Predicted home margin from trailing EPA strengths. Missing -> (None, reason)."""
    if home_strength is None or away_strength is None:
        return None, "EPA_STRENGTH_UNVERIFIED"
    try:
        sh, sa = float(home_strength), float(away_strength)
    except (TypeError, ValueError):
        return None, "EPA_STRENGTH_UNVERIFIED"
    if not (math.isfinite(sh) and math.isfinite(sa)):
        return None, "EPA_STRENGTH_UNVERIFIED"
    margin = EPA_MARGIN_PER_UNIT * (sh - sa) + float(league_hfa)
    return margin, "EPA_VERIFIED"


def ingest_epa_margin(home_strength, away_strength,
                      league_hfa: float = 1.5) -> dict:
    """EPA predicted home margin. Signature:
    ingest_epa_margin(home_strength, away_strength, league_hfa=1.5) -> entry dict."""
    margin, status = epa_predicted_margin(home_strength, away_strength, league_hfa)
    ok = {"EPA_VERIFIED"}
    return _entry("nfl_epa", "margin" if status in ok else "none",
                  "HOME_MARGIN", margin, status,
                  f"EPA predicted home margin {margin:+.2f}" if status in ok else status,
                  EPA_SOURCE, ok)


INGEST_ENTRY_POINTS["nfl_epa"] = (
    "ingest_epa_margin(home_strength, away_strength, league_hfa=1.5)")
FACTOR_REGISTRY["nfl_epa"].update({
    "validation": "NOT_RUN",
    "validation_note": "EPA/play via nflverse validated in Phase 2 harness run.",
})


# ---------------------------------------------------------------------------
# 17. Poisson time-decay for recency weighting -- backlog/frameworks note
# ---------------------------------------------------------------------------
# Adapted from the Dixon-Coles time-decay idea (soccer-specific parts
# skipped): recent games carry more weight in form windows via exponential
# decay. Our poisson() in artifacts/free_models.py is unchanged; the decay
# applies to the game weights feeding ratings/form means.
# Declared half-lives (not fitted): MLB 30d (daily games), NFL 45d (~6 games),
# CFB 30d, NBA 30d. Harness-gated vs the no-decay (equal-weighted) version.
TIME_DECAY_HALF_LIFE_DAYS = {"MLB": 30.0, "NFL": 45.0, "CFB": 30.0, "NBA": 30.0}


def time_decay_weight(days_ago: float, half_life_days: float) -> float:
    """Exponential recency weight: 0.5^(days_ago / half_life).

    Dixon-Coles style decay. days_ago < 0 (future game) is contradictory ->
    raises ValueError so callers fail closed loudly.
    """
    try:
        t = float(days_ago)
        hl = float(half_life_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("TIME_DECAY_INPUT_NON_NUMERIC") from exc
    if not (math.isfinite(t) and math.isfinite(hl)) or hl <= 0:
        raise ValueError("TIME_DECAY_INPUT_INVALID")
    if t < 0:
        raise ValueError("TIME_DECAY_NEGATIVE_AGE")
    return 0.5 ** (t / hl)


def decay_weighted_mean(values_with_age: list[tuple[float, float]],
                        half_life_days: float) -> tuple[float | None, str]:
    """Time-decay-weighted mean of [(value, days_ago)]. Empty -> (None, reason)."""
    if not values_with_age:
        return None, "TIME_DECAY_NO_GAMES"
    try:
        hl = float(half_life_days)
    except (TypeError, ValueError):
        return None, "TIME_DECAY_HALF_LIFE_INVALID"
    num = den = 0.0
    for value, days_ago in values_with_age:
        try:
            w = time_decay_weight(days_ago, hl)
            v = float(value)
        except (ValueError, TypeError):
            return None, "TIME_DECAY_VALUE_INVALID"
        if not math.isfinite(v):
            return None, "TIME_DECAY_VALUE_INVALID"
        num += w * v
        den += w
    if den <= 0:
        return None, "TIME_DECAY_NO_WEIGHT"
    return num / den, "TIME_DECAY_VERIFIED"


def ingest_time_decay(values_with_age: list[tuple[float, float]],
                      sport: str) -> dict:
    """Decay-weighted form mean. Signature:
    ingest_time_decay(values_with_age: list[tuple[float, float]], sport: str)
    -> entry dict. values_with_age = [(margin, days_ago)]."""
    sport = str(sport or "").upper()
    hl = TIME_DECAY_HALF_LIFE_DAYS.get(sport)
    if hl is None:
        return _entry("time_decay", "none", None, None,
                      "TIME_DECAY_NOT_APPLICABLE",
                      f"no declared half-life for {sport}",
                      "Dixon-Coles adapted decay (declared half-lives)", set())
    mean, status = decay_weighted_mean(values_with_age, hl)
    ok = {"TIME_DECAY_VERIFIED"}
    return _entry("time_decay", "none", None, mean,
                  status,
                  f"decay-weighted mean {mean:.3f} (half-life {hl:g}d)" if status in ok else status,
                  "Dixon-Coles adapted decay (declared half-lives)", ok)


INGEST_ENTRY_POINTS["time_decay"] = (
    "ingest_time_decay(values_with_age: list[tuple[float, float]], sport: str)")
FACTOR_REGISTRY["time_decay"] = {
    "source": "Dixon-Coles adapted exponential decay (declared half-lives)",
    "wired": False, "validation": "CONDITIONAL_PASS",
    "validation_note": "NFL: Brier 0.24673->0.24380, LL 0.69355->0.68539. Wiring: rating construction input for Elo agent.",
}


# ---------------------------------------------------------------------------
# 18. Weather interaction terms -- architecture critique adoption
# ---------------------------------------------------------------------------
# Beyond base thresholds: wind x passing (NFL) and temp/humidity x park (MLB).
# Declared formulas, documented below. Any unverifiable input -> fail closed
# (0.0, WEATHER_INTERACTION_UNVERIFIED, ...). Verified indoor -> no effect.
#
# NFL wind x passing: wind degrades the passing game more than the run game,
# so the total-suppression from wind scales with how pass-heavy the matchup
# is. Declared scale: base_wind_adj * (0.5 + combined_pass_rate), where
# combined_pass_rate in [0,1] is the mean of the two teams' pass rates
# (pass attempts / (pass attempts + rush attempts), trailing, from nflverse).
# League-average pass rate ~0.59 -> scale ~1.09; run-heavy ~0.45 -> ~0.95.
# If pass rate is unverified, the interaction is NOT applied (fail closed);
# the base wind threshold effect stands on its own.
#
# MLB temp/humidity x park: warm air is less dense -> ball carries farther.
# Declared: +0.025 runs per degF above 70F (capped +/-0.75), symmetric below
# 70F down to 50F. High humidity (>=70%) in heat (>=75F) amplifies x1.25
# (declared). Park interaction: multiplied by the runs park factor when
# verified (hitter parks amplify carry effects; pitcher parks mute them).
# Capped at +/-1.0 runs total. Sources: declared priors consistent with
# published temperature/HR literature direction; coefficients are declared,
# not fitted, and harness-gated.
# Harness verdicts 2026-10-11 (docs/validation_reports/weather*.json):
# - weather (declared wind/precip thresholds): FAIL vs the legacy production
#   heuristic OOS (MLB Jun-Aug 2025 totals; Brier 0.2320->0.2321) ->
#   WEATHER_THRESHOLDS_VALIDATED = False; ingest_weather stays audit-only.
# - weather_interaction_legacy (temp/humidity x park stacked on the legacy
#   heuristic): CONDITIONAL_PASS, MLB only (Brier 0.2320->0.2312, LL
#   0.7120->0.6985). The xpark multiplier leg was fail-closed OFF in that
#   run (2025 -> PARK_FACTOR_STALE), so it stays disabled until separately
#   validated. NFL wind x pass rate: NOT_RUN -> not wired.
WEATHER_THRESHOLDS_VALIDATED = False
WEATHER_INTERACTION_VALIDATED_SPORTS = frozenset({"MLB"})
WEATHER_INTERACTION_PARK_LEG_VALIDATED = False


def weather_interaction_adjustment(*, sport: str, temp_f=None,
                                   humidity_pct=None, park_factor=None,
                                   pass_rate=None, base_wind_adj: float = 0.0,
                                   indoor: bool | None = None
                                   ) -> tuple[float, str, str]:
    sport = str(sport or "").upper()
    if indoor is True:
        return 0.0, "VERIFIED_INDOOR", "venue verified indoor; no interaction"
    if sport == "NFL":
        if pass_rate is None:
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                "combined pass rate unverified; wind-x-passing not applied")
        try:
            pr = float(pass_rate)
        except (TypeError, ValueError):
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", "pass rate non-numeric"
        if not math.isfinite(pr) or not 0.0 <= pr <= 1.0:
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                "pass rate outside [0,1]")
        try:
            base = float(base_wind_adj)
        except (TypeError, ValueError):
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                "base wind adjustment non-numeric")
        if not math.isfinite(base):
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                "base wind adjustment invalid")
        scale = 0.5 + pr
        adj = max(-4.0, min(0.0, base * scale)) if base <= 0 else 0.0
        return adj, "WEATHER_INTERACTION_VERIFIED", (
            f"wind x pass_rate: base {base:+.2f} x {scale:.2f} (pr={pr:.2f})")
    if sport == "MLB":
        try:
            t = float(temp_f) if temp_f is not None else None
            h = (float(humidity_pct)
                 if humidity_pct is not None else None)
        except (TypeError, ValueError):
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                "temp/humidity non-numeric")
        if t is None or not math.isfinite(t):
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                "temperature unverified; temp-x-park not applied")
        if not -20.0 <= t <= 120.0:
            return 0.0, "WEATHER_INTERACTION_UNVERIFIED", (
                f"temperature {t:.0f}F outside plausible range")
        temp_adj = max(-0.75, min(0.75, 0.025 * (t - 70.0)))
        detail = f"temp {t:.0f}F -> {temp_adj:+.2f} runs"
        if (h is not None and math.isfinite(h) and 0.0 <= h <= 100.0
                and h >= 70.0 and t >= 75.0):
            temp_adj *= 1.25
            detail += f"; humidity {h:.0f}% amplifies x1.25"
        if park_factor is not None:
            try:
                pf = float(park_factor)
            except (TypeError, ValueError):
                pf = None
            if pf is not None and math.isfinite(pf) and 0.8 < pf < 1.3:
                temp_adj *= pf
                detail += f"; park {pf:.3f} interaction"
        temp_adj = max(-1.0, min(1.0, temp_adj))
        return temp_adj, "WEATHER_INTERACTION_VERIFIED", detail
    return 0.0, "WEATHER_NOT_APPLICABLE", f"no interaction model for {sport}"


def ingest_weather_interaction(sport: str, **kwargs) -> dict:
    """Weather interaction adjustment. Signature:
    ingest_weather_interaction(sport: str, temp_f=None, humidity_pct=None,
        park_factor=None, pass_rate=None, base_wind_adj=0.0, indoor=None)
    -> entry dict.

    Harness-gated (2026-10-11): only the MLB temp/humidity leg earned
    CONDITIONAL_PASS (weather_interaction_legacy). The xpark multiplier leg
    and the NFL wind x pass-rate leg are NOT validated -> forced off /
    audit-only here. Target is TOTAL to match the harness application
    (total adjustment split evenly across both means).
    """
    sport_up = str(sport or "").upper()
    if not WEATHER_INTERACTION_PARK_LEG_VALIDATED:
        kwargs = dict(kwargs, park_factor=None)
    adj, status, detail = weather_interaction_adjustment(
        sport=sport, **kwargs)
    validated = (status == "WEATHER_INTERACTION_VERIFIED"
                 and sport_up in WEATHER_INTERACTION_VALIDATED_SPORTS)
    if not validated:
        detail += " [NOT_WIRED: interaction not harness-validated for " \
                  f"{sport_up}; audit only]"
        return _entry("weather_interactions", "none", None, 0.0,
                      status, detail,
                      "weather interaction terms (wind x passing, temp x park)",
                      set())
    ok = {"WEATHER_INTERACTION_VERIFIED"}
    return _entry("weather_interactions", "add", "TOTAL", adj,
                  status, detail,
                  "weather interaction terms (temp/humidity, MLB; "
                  "CONDITIONAL_PASS 2026-10-11, research-only)", ok)


INGEST_ENTRY_POINTS["weather_interaction"] = (
    "ingest_weather_interaction(sport: str, temp_f=None, humidity_pct=None, "
    "park_factor=None, pass_rate=None, base_wind_adj=0.0, indoor=None)")
FACTOR_REGISTRY["weather_interactions"] = {
    "source": ("declared interaction priors: NFL wind x pass rate "
               "(nflverse), MLB temp/humidity x park factor"),
    "wired": True,
    "validation": "CONDITIONAL_PASS",
    "validation_note": ("2026-10-11: MLB temp/humidity leg (+0.025 runs/degF "
                        "from 70F, humidity x1.25) CONDITIONAL_PASS stacked "
                        "on the legacy heuristic "
                        "(docs/validation_reports/weather_interaction_legacy.json: "
                        "Brier 0.2320->0.2312, LL 0.7120->0.6985, n=11575). "
                        "Wired LABELED via ingest_weather_interaction "
                        "(target TOTAL, research-only). NOT wired: the xpark "
                        "multiplier leg (fail-closed off in the run), the "
                        "NFL wind x pass-rate leg (NOT_RUN), and the declared "
                        "wind/precip thresholds (FAILED vs legacy)."),
}


# ---------------------------------------------------------------------------
# 19. Component park factors (Derek Carty / THE BAT pattern)
# ---------------------------------------------------------------------------
# REPLACES the aggregate-runs park factor. Components computed SEPARATELY
# from Retrosheet play-by-play (free event files):
#   1B, 2B, 3B, HR, BB (incl HBP), K
# Method: road-weight (team home rate vs road rate per component) +
# regress-by-noisiness with declared per-component PA constants.
# Source: data/component_park_factors_2022_2024.json
# Derivation: scripts/derive_component_park_factors.py
# Keyed by 2022-2024 team name. A's/Rays 2025+ fail closed (park changes).
COMPONENT_PARK_FACTORS: dict[str, dict[str, float]] = {
    'Arizona Diamondbacks': {'1B': 1.0485, '2B': 1.0851, '3B': 1.2322, 'HR': 0.8911, 'BB': 1.0018, 'K': 0.9382},
    'Atlanta Braves': {'1B': 1.0167, '2B': 0.9976, '3B': 1.1623, 'HR': 0.9709, 'BB': 1.0568, 'K': 1.0319},
    'Baltimore Orioles': {'1B': 1.0278, '2B': 0.9369, '3B': 0.9674, 'HR': 0.9621, 'BB': 0.9831, 'K': 0.9709},
    'Boston Red Sox': {'1B': 1.0506, '2B': 1.1332, '3B': 1.0964, 'HR': 1.0158, 'BB': 0.9954, 'K': 0.9867},
    'Chicago Cubs': {'1B': 1.0237, '2B': 0.9217, '3B': 1.1159, 'HR': 1.0086, 'BB': 1.0124, 'K': 1.0013},
    'Chicago White Sox': {'1B': 1.0004, '2B': 0.9451, '3B': 0.893, 'HR': 0.9987, 'BB': 1.0339, 'K': 0.936},
    'Cincinnati Reds': {'1B': 0.9902, '2B': 0.9823, '3B': 0.877, 'HR': 1.2119, 'BB': 1.0542, 'K': 0.99},
    'Cleveland Guardians': {'1B': 0.9955, '2B': 1.0348, '3B': 0.9186, 'HR': 0.9388, 'BB': 1.0563, 'K': 0.9841},
    'Colorado Rockies': {'1B': 1.1027, '2B': 1.1409, '3B': 1.3165, 'HR': 1.2273, 'BB': 1.0634, 'K': 0.8839},
    'Detroit Tigers': {'1B': 1.0238, '2B': 0.9589, '3B': 1.0882, 'HR': 0.9651, 'BB': 1.0373, 'K': 0.9485},
    'Houston Astros': {'1B': 0.9854, '2B': 1.0319, '3B': 1.0396, 'HR': 1.0389, 'BB': 1.04, 'K': 0.9653},
    'Kansas City Royals': {'1B': 1.0777, '2B': 1.1298, '3B': 1.2025, 'HR': 0.9773, 'BB': 1.035, 'K': 0.8551},
    'Los Angeles Angels': {'1B': 0.9634, '2B': 0.9769, '3B': 1.0636, 'HR': 1.1591, 'BB': 1.0087, 'K': 1.0141},
    'Los Angeles Dodgers': {'1B': 0.9878, '2B': 0.9467, '3B': 0.9215, 'HR': 1.1293, 'BB': 0.975, 'K': 0.9704},
    'Miami Marlins': {'1B': 1.0167, '2B': 1.0698, '3B': 1.1582, 'HR': 1.0186, 'BB': 1.0617, 'K': 0.9328},
    'Milwaukee Brewers': {'1B': 0.949, '2B': 0.9735, '3B': 0.9906, 'HR': 1.0855, 'BB': 1.0606, 'K': 1.0696},
    'Minnesota Twins': {'1B': 1.0047, '2B': 1.0912, '3B': 1.0853, 'HR': 1.0761, 'BB': 1.0117, 'K': 0.9827},
    'New York Mets': {'1B': 0.9432, '2B': 0.9494, '3B': 0.9325, 'HR': 1.058, 'BB': 1.123, 'K': 1.0049},
    'New York Yankees': {'1B': 0.9483, '2B': 0.9574, '3B': 0.8428, 'HR': 1.1233, 'BB': 1.0449, 'K': 0.9847},
    'Oakland Athletics': {'1B': 0.9698, '2B': 1.0265, '3B': 1.1831, 'HR': 0.8672, 'BB': 0.9942, 'K': 0.9634},
    'Philadelphia Phillies': {'1B': 0.9958, '2B': 0.9898, '3B': 1.0316, 'HR': 1.1271, 'BB': 1.0579, 'K': 0.9459},
    'Pittsburgh Pirates': {'1B': 1.0285, '2B': 1.0734, '3B': 0.9624, 'HR': 0.923, 'BB': 1.0285, 'K': 0.9126},
    'San Diego Padres': {'1B': 0.9714, '2B': 0.9241, '3B': 0.8875, 'HR': 1.1145, 'BB': 0.985, 'K': 1.0109},
    'San Francisco Giants': {'1B': 1.0416, '2B': 1.08, '3B': 1.2128, 'HR': 0.8815, 'BB': 0.9619, 'K': 0.9294},
    'Seattle Mariners': {'1B': 0.9687, '2B': 0.9454, '3B': 0.8952, 'HR': 0.9646, 'BB': 1.0267, 'K': 1.0448},
    'St. Louis Cardinals': {'1B': 1.0227, '2B': 0.9513, '3B': 0.9876, 'HR': 1.0031, 'BB': 1.0532, 'K': 0.9157},
    'Tampa Bay Rays': {'1B': 0.9677, '2B': 1.0113, '3B': 1.1461, 'HR': 0.9907, 'BB': 1.0335, 'K': 1.0059},
    'Texas Rangers': {'1B': 0.9742, '2B': 1.0595, '3B': 0.9678, 'HR': 1.1675, 'BB': 1.0488, 'K': 0.9812},
    'Toronto Blue Jays': {'1B': 0.9749, '2B': 1.024, '3B': 0.8657, 'HR': 1.0148, 'BB': 0.9742, 'K': 0.9936},
    'Washington Nationals': {'1B': 1.009, '2B': 0.9593, '3B': 1.0184, 'HR': 1.1214, 'BB': 0.9736, 'K': 0.9532},
}
COMPONENT_PARK_SOURCE = "Retrosheet play-by-play event files (free)"
COMPONENT_PARK_SEASONS = (2022, 2023, 2024)


def component_park_factor_for(home_team: str, season: int,
                              component: str) -> tuple[float | None, str, str]:
    """Component park factor (1B/2B/3B/HR/BB/K). Fail-closed like the
    aggregate version. Replaces aggregate runs park factor per Carty."""
    name = str(home_team or "").strip()
    comp = str(component or "").upper()
    if comp not in ("1B", "2B", "3B", "HR", "BB", "K"):
        return None, "COMPONENT_PARK_INVALID", f"unknown component {component!r}"
    try:
        season = int(season)
    except (TypeError, ValueError):
        return None, "PARK_FACTOR_SEASON_UNVERIFIED", "season not an integer"
    if not name:
        return None, "PARK_FACTOR_TEAM_UNVERIFIED", "empty home team name"
    if season > PARK_FACTOR_MAX_SEASON:
        return None, "PARK_FACTOR_STALE", (
            f"table covers 2022-2024; season {season} needs re-derivation")
    moved = PARK_CHANGES.get(name)
    if moved is not None and season >= moved:
        return None, "PARK_FACTOR_TEAM_PARK_CHANGED", (
            f"{name} changed home parks starting {moved}")
    # Map 2025 "Athletics" to the Oakland table entry (blocked by PARK_CHANGES
    # anyway for 2025+; this keeps pre-2025 lookups working).
    key = "Oakland Athletics" if name == "Athletics" else name
    team_table = COMPONENT_PARK_FACTORS.get(key)
    if team_table is None:
        return None, "PARK_FACTOR_TEAM_UNKNOWN", f"no table entry for {name!r}"
    pf = team_table.get(comp)
    if pf is None:
        return None, "COMPONENT_PARK_MISSING", f"no {comp} factor for {name!r}"
    return pf, "COMPONENT_PARK_VERIFIED", (
        f"{comp} park factor {pf:.4f} from {COMPONENT_PARK_SOURCE} 2022-2024")


# ---------------------------------------------------------------------------
# 20. Stabilization points & regression-by-noisiness (Carty / THE BAT)
# ---------------------------------------------------------------------------
# Declared stabilization points (PA or BF threshold where the stat becomes
# more signal than noise). From sabermetric research (Russell Carleton /
# Baseball Prospectus). These ARE the declared recency-weighting spec:
# regression-by-noisiness per component, not one blanket decay.
STABILIZATION_PA = {
    # Batting (plate appearances)
    "K%": 60,      # strikeout rate stabilizes fastest
    "BB%": 120,    # walk rate
    "GB%": 80,     # groundball rate
    "FB%": 80,     # flyball rate
    "LD%": 80,     # line drive rate
    "ISO": 160,    # isolated power
    "BABIP": 650,  # batting avg on balls in play: very noisy
    "AVG": 500,    # batting average
    "OBP": 500,    # on-base percentage
    "SLG": 500,    # slugging
    "wOBA": 500,   # weighted on-base average
    # Pitching (batters faced)
    "K%_pitch": 70,
    "BB%_pitch": 170,
    "HR%_pitch": 300,  # HR rate: noisy
    "GB%_pitch": 100,
}
# Platoon split regression (Carty): heavily regress observed splits.
# RHB: regress to ~2,200 PA of league average; LHB: ~1,000 PA.
# Power splits >> contact splits (power platoon effect is real; contact is noise).
PLATOON_REGRESS_PA = {"RHB": 2200, "LHB": 1000}


def regress_stat(observed: float, sample_pa: float, league_avg: float,
                 stabilization_pa: float) -> tuple[float | None, str]:
    """Regress an observed rate toward league average by noisiness.

    regressed = (observed * pa + league_avg * stab) / (pa + stab)
    Returns (value, status). Fail-closed on invalid inputs.
    """
    try:
        obs = float(observed)
        pa = float(sample_pa)
        lg = float(league_avg)
        stab = float(stabilization_pa)
    except (TypeError, ValueError):
        return None, "REGRESS_INPUT_NON_NUMERIC"
    if not all(math.isfinite(x) for x in (obs, pa, lg, stab)):
        return None, "REGRESS_INPUT_INVALID"
    if pa < 0 or stab <= 0:
        return None, "REGRESS_INPUT_INVALID"
    if pa == 0:
        return lg, "REGRESSED_TO_LEAGUE_AVG"
    val = (obs * pa + lg * stab) / (pa + stab)
    return val, "REGRESSED_VERIFIED"


def regress_platoon_split(observed_split: float, split_pa: float,
                          batter_hand: str, league_avg_split: float = 0.0
                          ) -> tuple[float | None, str]:
    """Regress an observed platoon split (e.g., wOBA vs LHP - vs RHP).

    Carty: RHB regress to 2,200 PA of league avg; LHB to 1,000 PA.
    Raw splits are noise that manufactures fake edges — never use unregressed.
    """
    hand = str(batter_hand or "").upper()
    if hand in ("R", "RIGHT", "RHB"):
        reg_pa = PLATOON_REGRESS_PA["RHB"]
    elif hand in ("L", "LEFT", "LHB"):
        reg_pa = PLATOON_REGRESS_PA["LHB"]
    elif hand in ("S", "SWITCH", "BOTH"):
        # Switch hitters: use the smaller (LHB) regression; splits are
        # less meaningful. Documented choice.
        reg_pa = PLATOON_REGRESS_PA["LHB"]
    else:
        return None, "PLATOON_HAND_UNKNOWN"
    return regress_stat(observed_split, split_pa, league_avg_split, reg_pa)


def ingest_component_park(home_team: str, season: int,
                          component: str) -> dict:
    """Component park factor entry. Signature:
    ingest_component_park(home_team: str, season: int, component: str)
    -> entry dict. Replaces ingest_mlb_park (aggregate)."""
    pf, status, detail = component_park_factor_for(home_team, season, component)
    ok = {"COMPONENT_PARK_VERIFIED"}
    return _entry("component_park", "none", None, pf, status, detail,
                  f"{COMPONENT_PARK_SOURCE} 2022-2024", ok)


def ingest_platoon(batter_hand: str, observed_split: float, split_pa: float,
                   league_avg_split: float = 0.0) -> dict:
    """Regressed platoon split entry. Signature:
    ingest_platoon(batter_hand: str, observed_split: float, split_pa: float,
                   league_avg_split: float = 0.0) -> entry dict."""
    val, status = regress_platoon_split(observed_split, split_pa,
                                        batter_hand, league_avg_split)
    ok = {"REGRESSED_VERIFIED", "REGRESSED_TO_LEAGUE_AVG"}
    return _entry("platoon_split", "none", None, val, status,
                  f"regressed platoon split {val:.4f}" if val is not None else status,
                  "Carty regressed platoon (RHB 2200 PA / LHB 1000 PA)", ok)


INGEST_ENTRY_POINTS["component_park"] = (
    "ingest_component_park(home_team: str, season: int, component: str)")
INGEST_ENTRY_POINTS["platoon"] = (
    "ingest_platoon(batter_hand: str, observed_split: float, split_pa: float, "
    "league_avg_split: float = 0.0)")
FACTOR_REGISTRY["component_park"] = {
    "source": "Retrosheet play-by-play (free); Carty component method",
    "wired": False, "validation": "NOT_RUN", "validation_note": "",
}
FACTOR_REGISTRY["platoon_split"] = {
    "source": "Carty regressed platoon (RHB 2200 PA / LHB 1000 PA)",
    "wired": False, "validation": "NOT_RUN", "validation_note": "",
}
# Umpire zone effects and catcher framing: MISSING until proven stable
# out-of-sample in the harness. Validation path: derive umpire K/BB
# deltas from Retrosheet (umpire IDs in info records), test stability
# across seasons in walk-forward. Do not wire on reputation.
FACTOR_REGISTRY["umpire_zone"] = {
    "source": "Retrosheet umpire IDs (info records) — stability TBD",
    "wired": False, "validation": "NOT_WIRED",
    "validation_note": ("MISSING until proven stable OOS: umpire K/BB effects "
                        "must validate across seasons before wiring. "
                        "2026-10-11: umpscorecards.com probed (see "
                        "docs/umpscorecards_probe.md) -- frontend API is "
                        "Patreon-gated, no keyless stable path; plus MLB's "
                        "2026 ABS challenge system structurally shrinks the "
                        "effect. No further investment until harness shows "
                        "a residual."),
}
FACTOR_REGISTRY["catcher_framing"] = {
    "source": "TBD — stability TBD",
    "wired": False, "validation": "NOT_WIRED",
    "validation_note": ("MISSING until proven stable OOS: catcher framing "
                        "must validate before wiring."),
}
