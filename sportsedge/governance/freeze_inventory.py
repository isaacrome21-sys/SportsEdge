from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

CLASSIFICATIONS = frozenset(
    {"ACTIVE", "INCOMPLETE_BLOCKED", "SUPERSEDED", "REVOKED", "NON_AUTHORITATIVE"}
)

CANDIDATE_TOKENS = (
    "freeze",
    "prereg",
    "ledger",
    "admission",
    "activation",
    "evaluation_boundary",
    "evidence_policy",
    "selection_policy",
    "cron_policy",
    "promotion_evidence",
    "truth_gate",
)


class FreezeInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateClassification:
    path: str
    rule_id: str
    classification: str
    bundle_id: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "rule_id": self.rule_id,
            "classification": self.classification,
            "bundle_id": self.bundle_id,
            "reason": self.reason,
        }


def is_candidate(path: str) -> bool:
    normalized = str(path).replace("\\", "/")
    if not normalized.startswith("config/"):
        return False
    suffix = Path(normalized).suffix.lower()
    if suffix not in {".json", ".md", ".yml", ".yaml"}:
        return False
    name = Path(normalized).name.lower()
    return any(token in name for token in CANDIDATE_TOKENS)


def discover_candidates(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(path).replace("\\", "/") for path in paths if is_candidate(str(path))}))


def _matches(path: str, rule: Mapping[str, Any]) -> bool:
    exact = {str(value) for value in rule.get("exact") or ()}
    prefixes = tuple(str(value) for value in rule.get("prefixes") or ())
    suffixes = tuple(str(value) for value in rule.get("suffixes") or ())
    return path in exact or any(path.startswith(prefix) for prefix in prefixes) or any(
        path.endswith(suffix) for suffix in suffixes
    )


def classify_candidate(path: str, inventory: Mapping[str, Any]) -> CandidateClassification:
    matches = [rule for rule in inventory.get("rules") or () if _matches(path, rule)]
    if not matches:
        raise FreezeInventoryError(f"FREEZE_CANDIDATE_UNCLASSIFIED:{path}")
    if len(matches) != 1:
        ids = ",".join(str(rule.get("rule_id")) for rule in matches)
        raise FreezeInventoryError(f"FREEZE_CANDIDATE_AMBIGUOUS:{path}:{ids}")
    rule = matches[0]
    classification = str(rule.get("classification") or "")
    if classification not in CLASSIFICATIONS:
        raise FreezeInventoryError(
            f"FREEZE_CLASSIFICATION_INVALID:{path}:{classification}"
        )
    bundle_id = rule.get("bundle_id")
    if classification == "ACTIVE" and not bundle_id:
        raise FreezeInventoryError(f"ACTIVE_FREEZE_BUNDLE_ID_REQUIRED:{path}")
    if classification != "ACTIVE" and bundle_id:
        raise FreezeInventoryError(
            f"NONACTIVE_FREEZE_BUNDLE_ID_FORBIDDEN:{path}:{classification}"
        )
    reason = str(rule.get("reason") or "").strip()
    if not reason:
        raise FreezeInventoryError(f"FREEZE_CLASSIFICATION_REASON_REQUIRED:{path}")
    return CandidateClassification(
        path=path,
        rule_id=str(rule.get("rule_id") or ""),
        classification=classification,
        bundle_id=str(bundle_id) if bundle_id else None,
        reason=reason,
    )


def audit_inventory(
    *,
    paths: Iterable[str],
    inventory: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    if inventory.get("schema") != "SPORTSEDGE_FREEZE_INVENTORY_V1":
        raise FreezeInventoryError("FREEZE_INVENTORY_SCHEMA_INVALID")
    candidates = discover_candidates(paths)
    classifications = [classify_candidate(path, inventory) for path in candidates]

    active_bundle_ids = {row.bundle_id for row in classifications if row.classification == "ACTIVE"}
    registry_bundle_ids = {str(row.get("bundle_id")) for row in registry.get("bundles") or ()}
    missing_registry = sorted(str(value) for value in active_bundle_ids - registry_bundle_ids)
    if missing_registry:
        raise FreezeInventoryError(
            "ACTIVE_FREEZE_BUNDLE_MISSING_FROM_RECONCILIATION:" + ",".join(missing_registry)
        )

    # A reconciliation bundle that has no explicit ACTIVE inventory record is also
    # unsafe: it may be a stale hand-maintained scope that no current freeze owns.
    orphan_registry = sorted(registry_bundle_ids - {str(value) for value in active_bundle_ids})
    allowed_structural = {
        str(value) for value in inventory.get("structural_registry_bundles") or ()
    }
    unexplained = sorted(set(orphan_registry) - allowed_structural)
    if unexplained:
        raise FreezeInventoryError(
            "RECONCILIATION_BUNDLE_WITHOUT_ACTIVE_INVENTORY:" + ",".join(unexplained)
        )

    counts = {name: 0 for name in sorted(CLASSIFICATIONS)}
    for row in classifications:
        counts[row.classification] += 1
    return {
        "schema": "SPORTSEDGE_FREEZE_INVENTORY_AUDIT_V1",
        "candidate_count": len(candidates),
        "classification_counts": counts,
        "candidates": [row.as_dict() for row in classifications],
        "active_bundle_ids": sorted(str(value) for value in active_bundle_ids),
        "registry_bundle_ids": sorted(registry_bundle_ids),
        "complete": True,
    }


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
