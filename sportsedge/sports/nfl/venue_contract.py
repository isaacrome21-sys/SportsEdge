"""NFL venue contract (NFL_VENUE_POLICY_V1).

Venue support produces a price. It never authorizes a bet. Truth Gate
status is decided separately (see sportsedge/core/card_status.py).

Standard library only. No repo imports, so it can be wired into the M2
live-feature path wherever that lives.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = "HOME"
NEUTRAL_DOMESTIC = "NEUTRAL_DOMESTIC"
NEUTRAL_INTERNATIONAL = "NEUTRAL_INTERNATIONAL"
POLICY_ID = "NFL_VENUE_POLICY_V1"

TEAM_TZ = {
    "ARI": "America/Phoenix", "ATL": "America/New_York", "BAL": "America/New_York",
    "BUF": "America/New_York", "CAR": "America/New_York", "CHI": "America/Chicago",
    "CIN": "America/New_York", "CLE": "America/New_York", "DAL": "America/Chicago",
    "DEN": "America/Denver", "DET": "America/Detroit", "GB": "America/Chicago",
    "HOU": "America/Chicago", "IND": "America/Indiana/Indianapolis",
    "JAX": "America/New_York", "KC": "America/Chicago", "LA": "America/Los_Angeles",
    "LAR": "America/Los_Angeles", "LAC": "America/Los_Angeles", "LV": "America/Los_Angeles",
    "MIA": "America/New_York", "MIN": "America/Chicago", "NE": "America/New_York",
    "NO": "America/Chicago", "NYG": "America/New_York", "NYJ": "America/New_York",
    "PHI": "America/New_York", "PIT": "America/New_York", "SEA": "America/Los_Angeles",
    "SF": "America/Los_Angeles", "TB": "America/New_York", "TEN": "America/Chicago",
    "WAS": "America/New_York",
}

VENUE_PROFILE_FIELDS = ("country", "tz", "roof", "surface")


class VenueContractError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def load_policy(path) -> dict:
    raw = Path(path).read_bytes()
    policy = json.loads(raw)
    if policy.get("policy_id") != POLICY_ID:
        raise VenueContractError("VENUE_POLICY_ID_MISMATCH", str(policy.get("policy_id")))
    policy["_sha256"] = hashlib.sha256(raw).hexdigest()
    return policy


def _parse_utc(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise VenueContractError("KICKOFF_INVALID", str(value)) from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise VenueContractError("KICKOFF_TIMEZONE_MISSING", str(value))
    return dt


def classify_venue(game: dict) -> str:
    """Uses schedule fields only. Never inferred from home_team."""
    neutral = game.get("neutral_site")
    country = game.get("venue_country")
    if neutral is None:
        raise VenueContractError("VENUE_CLASS_UNRESOLVED", "neutral_site missing")
    if not isinstance(neutral, bool):
        raise VenueContractError("VENUE_CLASS_UNRESOLVED", "neutral_site must be true/false")
    if not neutral:
        if country and str(country).upper() != "US":
            raise VenueContractError("VENUE_CLASS_INCONSISTENT", "non-neutral game outside US")
        return HOME
    if not country:
        raise VenueContractError("VENUE_CLASS_UNRESOLVED", "venue_country missing for neutral site")
    return NEUTRAL_DOMESTIC if str(country).upper() == "US" else NEUTRAL_INTERNATIONAL


def tz_shift_hours(team: str, venue_tz: str, kickoff_utc, wrap: int = 12) -> float:
    """Signed venue-minus-home UTC offset at kickoff, wrapped to (-wrap, wrap]."""
    zone = TEAM_TZ.get(team)
    if zone is None:
        raise VenueContractError("TRAVEL_TEAM_TZ_UNKNOWN", team)
    if wrap <= 0:
        raise VenueContractError("TRAVEL_TZ_WRAP_INVALID", str(wrap))
    kickoff = _parse_utc(kickoff_utc)
    try:
        home_off = kickoff.astimezone(ZoneInfo(zone)).utcoffset()
        venue_off = kickoff.astimezone(ZoneInfo(venue_tz)).utcoffset()
    except Exception as exc:
        raise VenueContractError("VENUE_TIMEZONE_INVALID", venue_tz) from exc
    if home_off is None or venue_off is None:
        raise VenueContractError("VENUE_TIMEZONE_INVALID", venue_tz)
    shift = (venue_off - home_off).total_seconds() / 3600.0
    span = 2 * wrap
    while shift > wrap:
        shift -= span
    while shift <= -wrap:
        shift += span
    return shift


def travel_differential(home_team: str, away_team: str, venue_tz: str, kickoff_utc, wrap: int = 12) -> dict:
    home_shift = tz_shift_hours(home_team, venue_tz, kickoff_utc, wrap)
    away_shift = tz_shift_hours(away_team, venue_tz, kickoff_utc, wrap)
    return {
        "home_tz_shift_hours": home_shift,
        "away_tz_shift_hours": away_shift,
        "tz_shift_abs_differential": abs(home_shift) - abs(away_shift),
    }


def evaluate_venue_gate(game: dict, m2_hfa_prior: float, policy: dict) -> dict:
    """Returns the venue decision for one game. priceable=False means no Model_P."""
    out = {
        "policy_id": policy.get("policy_id"),
        "policy_sha256": policy.get("_sha256"),
        "venue_class": None,
        "governed_hfa": None,
        "sensitivity_band": None,
        "travel": None,
        "venue_profile": None,
        "ledger_segment": None,
        "in_primary_confirmation_test": False,
        "blockers": [],
        "priceable": False,
    }
    try:
        prior = float(m2_hfa_prior)
    except (TypeError, ValueError):
        out["blockers"].append("M2_HFA_PRIOR_INVALID")
        return out
    if prior < 0:
        out["blockers"].append("M2_HFA_PRIOR_INVALID")
        return out

    try:
        venue_class = classify_venue(game)
    except VenueContractError as exc:
        out["blockers"].append(exc.code)
        return out

    out["venue_class"] = venue_class
    segment = policy.get("ledger_segments", {}).get(venue_class)
    if not segment:
        out["blockers"].append("VENUE_POLICY_SEGMENT_MISSING")
        return out
    out["ledger_segment"] = segment
    out["in_primary_confirmation_test"] = segment in policy.get("primary_confirmation_test_segments", [])

    if venue_class == HOME:
        out["governed_hfa"] = prior
        out["priceable"] = True
        return out

    try:
        kickoff = _parse_utc(game.get("kickoff_utc"))
        effective = _parse_utc(policy.get("effective_from_kickoff_utc"))
    except VenueContractError as exc:
        out["blockers"].append(exc.code)
        return out
    if kickoff < effective:
        out["blockers"].append("VENUE_POLICY_NOT_EFFECTIVE")
        return out

    profile = policy.get("venues", {}).get(game.get("venue_id") or "")
    if profile is None or any(not profile.get(f) for f in VENUE_PROFILE_FIELDS):
        out["blockers"].append("ENVIRONMENT_PROFILE_MISSING")
        return out
    if str(profile["country"]).upper() != str(game.get("venue_country", "")).upper():
        out["blockers"].append("VENUE_COUNTRY_MISMATCH")
        return out
    out["venue_profile"] = profile
    if str(profile["roof"]).lower() == "outdoors" and not game.get("weather_observed_at"):
        out["blockers"].append("ENVIRONMENT_WEATHER_MISSING")

    try:
        out["travel"] = travel_differential(
            game.get("home_team"), game.get("away_team"), profile["tz"], kickoff,
            int(policy.get("travel", {}).get("tz_shift_wrap_hours", 0)),
        )
    except (VenueContractError, TypeError, ValueError) as exc:
        out["blockers"].append(exc.code if isinstance(exc, VenueContractError) else "TRAVEL_POLICY_INVALID")

    try:
        governed = float(policy["neutral_hfa_points"])
        residual = float(policy["sensitivity"]["designated_home_residual_share"]) * prior
    except (KeyError, TypeError, ValueError):
        out["blockers"].append("VENUE_HFA_POLICY_INVALID")
        return out
    out["governed_hfa"] = governed
    out["sensitivity_band"] = (governed, residual)
    out["priceable"] = not out["blockers"]
    return out


def venue_sensitivity_check(price_at_hfa, band: tuple, novig_p: float) -> dict:
    """price_at_hfa(hfa) -> Model_P for the side being evaluated, on the same
    non-push conditional basis as novig_p. The governed price is band[0]."""
    lo, hi = band
    p_lo, p_hi = float(price_at_hfa(lo)), float(price_at_hfa(hi))
    for p in (p_lo, p_hi, novig_p):
        if not 0.0 < p < 1.0:
            raise VenueContractError("PROBABILITY_OUT_OF_RANGE", str(p))
    e_lo, e_hi = p_lo - novig_p, p_hi - novig_p
    flipped = (e_lo > 0) != (e_hi > 0)
    return {
        "governed_model_p": p_lo,
        "model_p_at_band": (p_lo, p_hi),
        "edge_at_band": (e_lo, e_hi),
        "blocker": "VENUE_SENSITIVITY" if flipped else None,
    }
