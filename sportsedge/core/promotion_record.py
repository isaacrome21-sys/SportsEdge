"""Independent market-family promotion records.

A market or prop family cannot inherit OFFICIAL status from another family merely
because it shares a model, sport, or simulator. Every OFFICIAL state points to its own
policy/evidence bundle.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from string import hexdigits


class PromotionRecordError(ValueError):
    pass


def _sha(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in hexdigits.lower() for ch in text):
        raise PromotionRecordError(f"{field}:SHA256_REQUIRED")
    return text


@dataclass(frozen=True)
class MarketPromotionRecord:
    sport: str
    market_family: str
    status: str
    truth_gate_policy_id: str
    policy_bundle_sha: str
    evidence_bundle_sha: str
    model_bundle_sha: str
    effective_at: str
    supersedes_record_sha: str | None = None

    def validate(self) -> "MarketPromotionRecord":
        if not self.sport or not self.market_family or not self.truth_gate_policy_id or not self.effective_at:
            raise PromotionRecordError("PROMOTION_RECORD_IDENTITY_REQUIRED")
        if self.status not in {"EXPERIMENTAL", "EVIDENCE_INCOMPLETE", "OFFICIAL", "REVOKED"}:
            raise PromotionRecordError("PROMOTION_RECORD_STATUS_INVALID")
        for field in ("policy_bundle_sha", "evidence_bundle_sha", "model_bundle_sha"):
            _sha(getattr(self, field), field)
        if self.supersedes_record_sha is not None:
            _sha(self.supersedes_record_sha, "supersedes_record_sha")
        return self

    def content_hash(self) -> str:
        self.validate()
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def assert_no_certification_inheritance(
    source: MarketPromotionRecord,
    target_market_family: str,
) -> None:
    source.validate()
    target = str(target_market_family).strip()
    if not target:
        raise PromotionRecordError("TARGET_MARKET_FAMILY_REQUIRED")
    if target != source.market_family:
        raise PromotionRecordError(
            f"CERTIFICATION_INHERITANCE_FORBIDDEN:{source.market_family}->{target}"
        )
