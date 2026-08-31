"""PIT-safe candidate scanner for MLB home-run research.

This module is intentionally NOT a predictive Model_P engine and MUST NOT be used
for Truth Gate certification. It ranks research candidates whose recent contact
quality may be stronger than recent HR results, so the existing SportsEdge HR
model can decide whether the market price is wrong.

No sportsbook odds, public picks, ticket splits, handle splits, or promo signals
may enter the contact score. Price and promo data are attached only after a player
has been identified as a baseball candidate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

SCANNER_VERSION = "mlb_hr_regression_scanner_v1"

BANNED_CONTACT_KEYS = {
    "american_odds",
    "decimal_odds",
    "sportsbook_price",
    "implied_probability",
    "market_probability",
    "ticket_pct",
    "tickets_pct",
    "handle_pct",
    "money_pct",
    "public_pct",
    "promo_value",
    "bonus_bet_value",
}


class HRRegressionScannerError(ValueError):
    pass


def _num(row: Mapping[str, Any], key: str, *, lo: float | None = None, hi: float | None = None) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HRRegressionScannerError(f"missing_or_invalid:{key}") from exc
    if not isfinite(value):
        raise HRRegressionScannerError(f"non_finite:{key}")
    if lo is not None and value < lo:
        raise HRRegressionScannerError(f"below_min:{key}")
    if hi is not None and value > hi:
        raise HRRegressionScannerError(f"above_max:{key}")
    return value


def _iso_utc(value: Any, key: str) -> datetime:
    if not isinstance(value, str):
        raise HRRegressionScannerError(f"missing_or_invalid:{key}")
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HRRegressionScannerError(f"missing_or_invalid:{key}") from exc
    if dt.tzinfo is None:
        raise HRRegressionScannerError(f"timezone_required:{key}")
    return dt.astimezone(timezone.utc)


def _reject_market_leakage(contact: Mapping[str, Any]) -> None:
    leaked = sorted(k for k in contact if str(k).lower() in BANNED_CONTACT_KEYS)
    if leaked:
        raise HRRegressionScannerError("market_data_in_contact_features:" + ",".join(leaked))


@dataclass(frozen=True)
class HRRegressionCandidate:
    player_id: str
    game_id: str
    as_of: str
    scanner_version: str
    score: float
    reasons: tuple[str, ...]
    recent_bbe: int
    recent_hr: int
    barrel_pct: float
    hard_hit_pct: float
    avg_ev: float
    xslg: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "game_id": self.game_id,
            "as_of": self.as_of,
            "scanner_version": self.scanner_version,
            "score": self.score,
            "reasons": list(self.reasons),
            "recent_bbe": self.recent_bbe,
            "recent_hr": self.recent_hr,
            "barrel_pct": self.barrel_pct,
            "hard_hit_pct": self.hard_hit_pct,
            "avg_ev": self.avg_ev,
            "xslg": self.xslg,
            "governance": "CANDIDATE_GENERATION_ONLY_NOT_MODEL_P",
        }


def scan_hr_regression_candidate(contact: Mapping[str, Any]) -> HRRegressionCandidate:
    """Return a research candidate from price-independent contact data.

    Required fields are timestamped so same-day/post-start leakage fails closed.
    Thresholds are candidate-generation heuristics only; they are not promotion
    thresholds and must be forward-tested before any predictive use.
    """
    _reject_market_leakage(contact)

    player_id = str(contact.get("player_id", "")).strip()
    game_id = str(contact.get("game_id", "")).strip()
    if not player_id or not game_id:
        raise HRRegressionScannerError("player_id_and_game_id_required")

    as_of_dt = _iso_utc(contact.get("as_of"), "as_of")
    first_pitch_dt = _iso_utc(contact.get("first_pitch"), "first_pitch")
    if as_of_dt >= first_pitch_dt:
        raise HRRegressionScannerError("CONTACT_DATA_NOT_PREGAME")

    recent_bbe = int(_num(contact, "recent_bbe", lo=1))
    recent_hr = int(_num(contact, "recent_hr", lo=0))
    barrel_pct = _num(contact, "barrel_pct", lo=0.0, hi=100.0)
    hard_hit_pct = _num(contact, "hard_hit_pct", lo=0.0, hi=100.0)
    avg_ev = _num(contact, "avg_ev", lo=50.0, hi=130.0)
    xslg = _num(contact, "xslg", lo=0.0, hi=2.0)

    reasons: list[str] = []
    score = 0.0

    # Conservative heuristics chosen only to identify players worth running
    # through the existing HR probability model. Recent HR scarcity is a
    # tiebreaking research condition, not an assertion that a player is "due".
    if recent_bbe >= 15:
        score += 1.0
        reasons.append("recent_bbe_sample")
    if barrel_pct >= 10.0:
        score += 2.0
        reasons.append("elevated_barrel_rate")
    if hard_hit_pct >= 45.0:
        score += 1.5
        reasons.append("elevated_hard_hit_rate")
    if avg_ev >= 90.0:
        score += 1.0
        reasons.append("strong_exit_velocity")
    if xslg >= 0.450:
        score += 1.5
        reasons.append("strong_expected_slugging")
    if recent_hr <= 1 and (barrel_pct >= 10.0 or hard_hit_pct >= 45.0):
        score += 1.0
        reasons.append("contact_quality_exceeds_recent_hr_results")

    return HRRegressionCandidate(
        player_id=player_id,
        game_id=game_id,
        as_of=as_of_dt.isoformat(),
        scanner_version=SCANNER_VERSION,
        score=round(score, 3),
        reasons=tuple(reasons),
        recent_bbe=recent_bbe,
        recent_hr=recent_hr,
        barrel_pct=barrel_pct,
        hard_hit_pct=hard_hit_pct,
        avg_ev=avg_ev,
        xslg=xslg,
    )


def shortlist_hr_regression_candidates(rows: list[Mapping[str, Any]], *, min_score: float = 5.0) -> list[dict[str, Any]]:
    if min_score < 0 or not isfinite(float(min_score)):
        raise HRRegressionScannerError("invalid_min_score")
    candidates = [scan_hr_regression_candidate(row) for row in rows]
    kept = [c for c in candidates if c.score >= float(min_score)]
    kept.sort(key=lambda c: (-c.score, c.player_id))
    return [c.as_dict() for c in kept]
