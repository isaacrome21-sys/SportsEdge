"""NFL venue contract (NFL_VENUE_POLICY_V1).

Venue support produces a price. It never authorizes a bet. Promotion status is
decided separately. This module is standard-library only so it can sit on the
M2 live-feature boundary without creating a parallel model path.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    try:
        policy = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VenueContractError("VENUE_POLICY_INVALID_JSON") from exc
    if policy.get("policy_id") != POLICY_ID:
        raise VenueContractError("VENUE_POLICY_ID_MISMATCH", str(policy.get("policy_id")))
    policy["_sha256"] = hashlib.sha256(raw).hexdigest()
    return policy


def _parse_utc(value) -> datetime:
    try:
        if isinstance(value, datetime):
            dt = value
        elif value in (None, ""):
            raise ValueError("missing")
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise VenueContractError("KICKOFF_TIME_INVALID", str(value)) from exc
    if dt.tzinfo is None:
        raise VenueContractError("KICKOFF_TIMEZONE_MISSING", str(value))
    return dt


def classify_venue(game: dict) -> str:
    """Classify only from schedule/venue fields; never infer neutral status from teams."""
    neutral = game.get("neutral_site")
    country = game.get("venue_country")
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
    if isinstance(wrap, bool) or not isinstance(wrap, int) or wrap <= 0:
        raise VenueContractError("TRAVEL_WRAP_INVALID", str(wrap))
    zone = TEAM_TZ.get(str(team or "").upper())
    if zone is None:
        raise VenueContractError("TRAVEL_TEAM_TZ_UNKNOWN", str(team))
    kickoff = _parse_utc(kickoff_utc)
    try:
        home_off = kickoff.astimezone(ZoneInfo(zone)).utcoffset()
        venue_off = kickoff.astimezone(ZoneInfo(str(venue_tz))).utcoffset()
    except ZoneInfoNotFoundError as exc:
        raise VenueContractError("VENUE_TIMEZONE_UNKNOWN", str(venue_tz)) from exc
    if home_off is None or venue_off is None:
        raise VenueContractError("VENUE_TIMEZONE_OFFSET_MISSING")
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
    """Return the venue decision. priceable=False means this gate cannot supply Model_P."""
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
    if (
        isinstance(m2_hfa_prior, bool)
        or not isinstance(m2_hfa_prior, (int, float))
        or not math.isfinite(float(m2_hfa_prior))
        or float(m2_hfa_prior) < 0
    ):
        out["blockers"].append("M2_HFA_PRIOR_INVALID")
        return out
    try:
        venue_class = classify_venue(game)
        out["venue_class"] = venue_class
        segment = policy.get("ledger_segments", {}).get(venue_class)
        if not segment:
            raise VenueContractError("VENUE_LEDGER_SEGMENT_MISSING", venue_class)
        out["ledger_segment"] = segment
        out["in_primary_confirmation_test"] = segment in policy.get("primary_confirmation_test_segments", [])

        if venue_class == HOME:
            out["governed_hfa"] = float(m2_hfa_prior)
            out["priceable"] = True
            return out

        kickoff = _parse_utc(game.get("kickoff_utc"))
        effective = _parse_utc(policy.get("effective_from_kickoff_utc"))
        if kickoff < effective:
            out["blockers"].append("VENUE_POLICY_NOT_EFFECTIVE")
            return out

        venues = policy.get("venues")
        if not isinstance(venues, dict):
            raise VenueContractError("VENUE_POLICY_VENUES_MISSING")
        profile = venues.get(game.get("venue_id") or "")
        if not isinstance(profile, dict) or any(not profile.get(f) for f in VENUE_PROFILE_FIELDS):
            out["blockers"].append("ENVIRONMENT_PROFILE_MISSING")
            return out
        if str(profile["country"]).upper() != str(game.get("venue_country", "")).upper():
            out["blockers"].append("VENUE_COUNTRY_MISMATCH")
            return out
        out["venue_profile"] = dict(profile)
        if profile["roof"] == "outdoors" and not game.get("weather_observed_at"):
            out["blockers"].append("ENVIRONMENT_WEATHER_MISSING")

        travel = policy.get("travel") or {}
        out["travel"] = travel_differential(
            game.get("home_team"), game.get("away_team"), profile["tz"], kickoff,
            int(travel.get("tz_shift_wrap_hours", 0)),
        )
        governed = float(policy["neutral_hfa_points"])
        residual = float(policy["sensitivity"]["designated_home_residual_share"]) * float(m2_hfa_prior)
        if not all(math.isfinite(x) for x in (governed, residual)):
            raise VenueContractError("VENUE_SENSITIVITY_POLICY_INVALID")
        out["governed_hfa"] = governed
        out["sensitivity_band"] = (governed, residual)
        out["priceable"] = not out["blockers"]
        return out
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, VenueContractError):
            out["blockers"].append(exc.code)
        else:
            out["blockers"].append("VENUE_POLICY_INVALID")
        out["priceable"] = False
        return out


def venue_sensitivity_check(price_at_hfa, band: tuple, novig_p: float) -> dict:
    try:
        lo, hi = band
        p_lo, p_hi = float(price_at_hfa(lo)), float(price_at_hfa(hi))
        market_p = float(novig_p)
    except (TypeError, ValueError) as exc:
        raise VenueContractError("VENUE_SENSITIVITY_INPUT_INVALID") from exc
    for p in (p_lo, p_hi, market_p):
        if not math.isfinite(p) or not 0.0 < p < 1.0:
            raise VenueContractError("PROBABILITY_OUT_OF_RANGE", str(p))
    e_lo, e_hi = p_lo - market_p, p_hi - market_p
    flipped = (e_lo > 0) != (e_hi > 0)
    return {
        "governed_model_p": p_lo,
        "model_p_at_band": (p_lo, p_hi),
        "edge_at_band": (e_lo, e_hi),
        "blocker": "VENUE_SENSITIVITY" if flipped else None,
    }
