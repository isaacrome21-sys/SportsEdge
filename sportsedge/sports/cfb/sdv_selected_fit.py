"""Load the bakeoff-selected PRIOR_CURRENT_BLEND fit. No promotion authority."""
from __future__ import annotations

import json
from pathlib import Path

from .sportsdataverse_candidate_model import NativeScoreModel

DEFAULT_FIT_PATH = Path("config/cfb_sdv_prior_current_blend_fit_v1.json")


def load_selected_sdv_fit(path: str | Path = DEFAULT_FIT_PATH) -> NativeScoreModel:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "CFB_SDV_SELECTED_FAMILY_FIT_V1":
        raise ValueError("CFB_SDV_SELECTED_FIT_SCHEMA_INVALID")
    if payload.get("family") != "PRIOR_CURRENT_BLEND":
        raise ValueError("CFB_SDV_SELECTED_FIT_FAMILY_INVALID")
    return NativeScoreModel(
        family=str(payload["family"]),
        feature_names=tuple(payload["feature_names"]),
        means=tuple(float(x) for x in payload["means"]),
        scales=tuple(float(x) for x in payload["scales"]),
        home_coef=tuple(float(x) for x in payload["home_coef"]),
        away_coef=tuple(float(x) for x in payload["away_coef"]),
        ridge_alpha=float(payload["ridge_alpha"]),
    )
