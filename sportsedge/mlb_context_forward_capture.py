"""Forward PIT capture ledger for MLB context-model training evidence.

Creates immutable, price-blind training rows from the same public pregame
context bundle used by serving. It intentionally does not backfill context.
"""
from __future__ import annotations
from hashlib import sha256
import json
from typing import Any, Mapping
from .mlb_context_model_features import context_model_features

CAPTURE_VERSION="mlb_context_forward_capture_v1"

def capture_training_row(bundle: Mapping[str,Any], *, game_date: str, first_pitch_utc: str, captured_at_utc: str) -> dict[str,Any]:
    if not game_date or not first_pitch_utc or not captured_at_utc:
        raise ValueError("capture timestamps required")
    if captured_at_utc >= first_pitch_utc:
        raise ValueError("context capture must be strictly pregame")
    model=context_model_features(bundle)
    row={
      "capture_version":CAPTURE_VERSION,"game_pk":bundle.get("game_pk"),"game_date":game_date,
      "first_pitch_utc":first_pitch_utc,"captured_at_utc":captured_at_utc,
      "pit_strict":True,"contains_sportsbook_prices":False,
      "feature_schema_version":model["schema_version"],"feature_sha256":model["feature_sha256"],
      "features":model["features"],"eligibility":model["eligibility"],
    }
    raw=json.dumps(row,sort_keys=True,separators=(",",":"),default=str).encode()
    row["capture_sha256"]=sha256(raw).hexdigest()
    return row

