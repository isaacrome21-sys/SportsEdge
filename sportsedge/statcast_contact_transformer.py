"""Frozen expected-contact transformer for SportsEdge Statcast V5.

The transformer is trained only on raw exit velocity/launch angle and realized
contact outcomes from the predeclared training period. It never consumes Savant's
retrospectively generated expected-stat columns.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

TRANSFORMER_VERSION = "SPORTSEDGE_FROZEN_CONTACT_V1"
TRAIN_YEARS = (2021, 2022, 2023)
INPUT_FEATURES = ("launch_speed", "launch_angle")

class ContactTransformerError(ValueError):
    pass

@dataclass
class FrozenContactTransformer:
    hit_model: Any
    value_model: Any
    version: str = TRANSFORMER_VERSION
    train_years: tuple[int, ...] = TRAIN_YEARS
    input_features: tuple[str, ...] = INPUT_FEATURES

    def predict_hit_probability(self, X: Sequence[Sequence[float]]) -> np.ndarray:
        arr = _validate_X(X)
        out = np.asarray(self.hit_model.predict_proba(arr)[:, 1], dtype=float)
        if np.any(~np.isfinite(out)) or np.any((out < 0) | (out > 1)):
            raise ContactTransformerError("CONTACT_HIT_PROBABILITY_INVALID")
        return out

    def predict_contact_value(self, X: Sequence[Sequence[float]]) -> np.ndarray:
        arr = _validate_X(X)
        out = np.asarray(self.value_model.predict(arr), dtype=float)
        if np.any(~np.isfinite(out)):
            raise ContactTransformerError("CONTACT_VALUE_INVALID")
        return np.clip(out, 0.0, 2.0)

    def manifest(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "train_years": list(self.train_years),
            "input_features": list(self.input_features),
            "uses_savant_expected_stats": False,
            "hit_model": type(self.hit_model).__name__,
            "value_model": type(self.value_model).__name__,
        }

    def manifest_sha256(self) -> str:
        raw = json.dumps(self.manifest(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def _validate_X(X: Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(X, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) == 0:
        raise ContactTransformerError("CONTACT_FEATURE_MATRIX_INVALID")
    if np.any(~np.isfinite(arr)):
        raise ContactTransformerError("CONTACT_FEATURE_NONFINITE")
    return arr


def fit_frozen_contact_transformer(X: Sequence[Sequence[float]], y_hit: Sequence[int], y_value: Sequence[float]) -> FrozenContactTransformer:
    arr = _validate_X(X)
    hit = np.asarray(y_hit, dtype=int); val = np.asarray(y_value, dtype=float)
    if len(hit) != len(arr) or len(val) != len(arr):
        raise ContactTransformerError("CONTACT_TARGET_LENGTH_MISMATCH")
    if len(arr) < 1000:
        raise ContactTransformerError("CONTACT_TRAINING_SAMPLE_TOO_SMALL")
    if set(np.unique(hit)) - {0, 1}:
        raise ContactTransformerError("CONTACT_HIT_TARGET_INVALID")
    if np.any(~np.isfinite(val)) or np.any((val < 0) | (val > 2.0)):
        raise ContactTransformerError("CONTACT_VALUE_TARGET_INVALID")
    hit_model = HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=220, max_leaf_nodes=31,
        min_samples_leaf=100, l2_regularization=2.0, random_state=5101,
    )
    value_model = HistGradientBoostingRegressor(
        loss="squared_error", learning_rate=0.05, max_iter=220, max_leaf_nodes=31,
        min_samples_leaf=100, l2_regularization=2.0, random_state=5102,
    )
    hit_model.fit(arr, hit); value_model.fit(arr, val)
    return FrozenContactTransformer(hit_model=hit_model, value_model=value_model)
