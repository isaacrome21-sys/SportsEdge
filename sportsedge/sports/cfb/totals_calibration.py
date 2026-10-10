"""Frozen CFB totals calibration layer.

Intercept + scale applied to the model's projected total after the raw
score means (or after MC distribution mean) and before pricing. Margin
(spread/ML) path is left unchanged. Coefficients are frozen in
config/cfb_totals_calibration_v1.json; the file SHA is stamped on every card.
No market data enters Model_P.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Tuple

ROOT = Path(__file__).resolve().parents[3]
CAL_PATH = ROOT / "config" / "cfb_totals_calibration_v1.json"

_CACHE: dict | None = None


def load_totals_calibration() -> dict:
    """Load and SHA-stamp the frozen calibration coefficients."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    raw = CAL_PATH.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    if data.get("schema") != "CFB_TOTALS_CALIBRATION_V1":
        raise ValueError("CFB_TOTALS_CALIBRATION_SCHEMA_INVALID")
    data = dict(data)
    data["sha256"] = sha
    _CACHE = data
    return data


def apply_totals_calibration(
    raw_home: float,
    raw_away: float,
    cal: Mapping | None = None,
) -> Tuple[float, float]:
    """Return calibrated (home, away) means that preserve the raw margin.

    calibrated_total = intercept + scale * (raw_home + raw_away)
    delta = calibrated_total - raw_total
    home_cal = raw_home + delta / 2
    away_cal = raw_away + delta / 2
    """
    if cal is None:
        cal = load_totals_calibration()
    raw_total = float(raw_home) + float(raw_away)
    cal_total = float(cal["intercept"]) + float(cal["scale"]) * raw_total
    delta = cal_total - raw_total
    return raw_home + delta / 2.0, raw_away + delta / 2.0
