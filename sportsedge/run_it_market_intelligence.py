"""RUN IT Layer-B market-intelligence provenance contract.

This module has no Model_P, Truth Gate, promotion, staking, or OFFICIAL
authority. Its job is to keep exploratory RUN IT context rows comparable when
market-intelligence policy changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import re

POLICY_VERSION = "RUN_IT_MARKET_INTELLIGENCE_V2"
POLICY_STATUS = "UNMERGED"
CONTEXT_HIERARCHY_ID = "RUN_IT_CONTEXT_MARKET_ROLE_V2"
BENCHMARK_HIERARCHY_ID = "CORE_MARKET_BENCHMARK_V1"
FROZEN_BENCHMARK_ORDER = ("PINNACLE", "DRAFTKINGS", "FANDUEL", "BETMGM", "CAESARS")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class RunItPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class SourcedMarketRole:
    book: str
    role: str
    source_id: str
    classification_version: str
    as_of_utc: str

    def validate(self) -> None:
        if self.role not in {"MARKET_MAKER", "SOFT_BOOK", "UNCLASSIFIED"}:
            raise RunItPolicyError("unknown market-role classification")
        if not self.book or not self.source_id or not self.classification_version or not self.as_of_utc:
            raise RunItPolicyError("market-role classification requires book/source/version/as_of provenance")
        if self.role != "UNCLASSIFIED" and self.source_id.upper() in {"ASSERTED", "ASSUMED", "SHARP"}:
            raise RunItPolicyError("market role must be sourced, not asserted")


def validate_hierarchy_contract(*, context_hierarchy_id: str, benchmark_hierarchy_id: str,
                                benchmark_order: tuple[str, ...]) -> None:
    if context_hierarchy_id == benchmark_hierarchy_id:
        raise RunItPolicyError("context and benchmark hierarchies must use distinct namespaces")
    if context_hierarchy_id != CONTEXT_HIERARCHY_ID:
        raise RunItPolicyError("unexpected RUN IT context hierarchy id")
    if benchmark_hierarchy_id != BENCHMARK_HIERARCHY_ID:
        raise RunItPolicyError("unexpected frozen benchmark hierarchy id")
    if tuple(benchmark_order) != FROZEN_BENCHMARK_ORDER:
        raise RunItPolicyError("frozen benchmark hierarchy reordered")


def stamp_run_it_row(row: Mapping[str, Any], *, working_commit_sha: str,
                     policy_status: str = POLICY_STATUS) -> dict[str, Any]:
    """Return a provenance-stamped Layer-B row.

    The working SHA is deliberately mandatory. V1 and V2 observations can then
    be partitioned later instead of being silently pooled into one ledger.
    """
    if not _SHA40.fullmatch(str(working_commit_sha or "")):
        raise RunItPolicyError("RUN IT row requires exact 40-char working commit SHA")
    if policy_status != POLICY_STATUS:
        raise RunItPolicyError("V2 working policy must remain stamped UNMERGED")

    out = dict(row)
    reserved = {
        "policy_version": POLICY_VERSION,
        "policy_status": POLICY_STATUS,
        "policy_commit_sha": working_commit_sha,
        "context_hierarchy_id": CONTEXT_HIERARCHY_ID,
        "benchmark_hierarchy_id": BENCHMARK_HIERARCHY_ID,
        "model_p_authority": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "official_authority": False,
    }
    for key, value in reserved.items():
        if key in out and out[key] != value:
            raise RunItPolicyError(f"caller attempted to override reserved RUN IT field: {key}")
        out[key] = value
    return out


def assert_footer_unchanged(*, rendered_footer: str, frozen_footer: str) -> None:
    """Fail closed on any footer drift caused by model-groundwork changes."""
    if rendered_footer != frozen_footer:
        raise RunItPolicyError("RUN IT footer drifted from frozen text")
