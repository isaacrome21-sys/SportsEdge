#!/usr/bin/env python3
"""Acquire the frozen 2015-2025 reconstructed CFB selection inputs.

CFBD supplies games, FBS membership, venue metadata, and advanced metrics. Historical
weather is reconstructed from CFBD venue coordinates plus Open-Meteo ERA5 reanalysis
because CFBD's paid weather endpoint is not required by the frozen selection contract.

Raw provider responses are written only to caller-selected private cache paths. Public
attestations contain request/response hashes and governance state, never raw rows or
exact account/quota values.

This script never fits or evaluates a candidate and creates no Model_P, Truth Gate,
promotion, eligibility, staking, OFFICIAL, evidence-clock, PIT, or backfill authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.source import normalize_advanced_team_metrics
from sportsedge.sports.cfb.venue_coordinates import try_venue_coordinates, venue_indexes as shared_venue_indexes

CONFIG = ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json"
CFBD_BASE = "https://api.collegefootballdata.com"
WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"


class CFBAcquisitionError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_authority() -> dict[str, bool]:
    return {
        "attempt_consumed": False,
        "evaluation_performed": False,
        "historical_pit_created": False,
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "eligibility_changed": False,
        "official_authority": False,
        "backfill": False,
    }
