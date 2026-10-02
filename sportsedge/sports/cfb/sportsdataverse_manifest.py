"""Deterministic provenance manifest for reconstructed SportsDataverse CFB history."""
from __future__ import annotations
import hashlib, json
from typing import Any, Mapping, Sequence

MANIFEST_SCHEMA="CFB_SPORTSDATAVERSE_RECONSTRUCTED_MANIFEST_V1"
SOURCE_IDENTITY="SPORTSDATAVERSE_ESPN_CFB_ADV_V1|RECONSTRUCTED_PRIOR_WEEK_V1"


def canonical_sha256(value: Any) -> str:
    payload=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def build_manifest(*, season:int, target_week:int, datasets:Mapping[str,Sequence[Mapping[str,Any]]], feature_names:Sequence[str]) -> dict[str,Any]:
    if season >= 2026:
        raise ValueError("CFB_SDV_MANIFEST_2026_OUTCOMES_PROHIBITED")
    dataset_hashes={}
    row_counts={}
    for name in sorted(datasets):
        rows=sorted((dict(r) for r in datasets[name]),key=lambda r:canonical_sha256(r))
        dataset_hashes[name]=canonical_sha256(rows)
        row_counts[name]=len(rows)
    core={
        "schema":MANIFEST_SCHEMA,
        "source_identity":SOURCE_IDENTITY,
        "classification":"RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "season":season,
        "target_week":target_week,
        "through_week":target_week-1,
        "temporal_rule":"WEEK_LT_TARGET_WEEK",
        "datasets_sha256":dataset_hashes,
        "row_counts":row_counts,
        "feature_names":list(feature_names),
        "market_features_used":False,
        "pit_evidence":False,
        "model_p_authority":False,
        "promotion_authority":False,
        "official_authority":False,
    }
    return {**core,"manifest_sha256":canonical_sha256(core)}
