"""Research-only evidence attestation: a boolean alone never verifies a market."""
from __future__ import annotations

from datetime import datetime, timezone

from sportsedge.dk_market_coverage_contract import REQUIRED_EVIDENCE


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def review_attestations(evidence: dict, *, cutoff: str) -> dict:
    """Fail closed on missing, unanchored, future or post-cutoff evidence.

    An attestation must identify a source URL and an observed timestamp.
    Source observation is not proof of publication or a verified sports fact.
    """
    boundary = _timestamp(cutoff)
    if boundary is None:
        raise ValueError("INVALID_CUTOFF")
    missing = []
    for field in REQUIRED_EVIDENCE:
        record = evidence.get(field)
        if not isinstance(record, dict) or record.get("verified") is not True:
            missing.append(field)
            continue
        url = record.get("source_url")
        observed = _timestamp(record.get("observed_at"))
        published = _timestamp(record.get("published_at"))
        if not isinstance(url, str) or not url.startswith("https://") or not url[8:]:
            missing.append(field)
        elif observed is None or published is None or published > observed or observed > boundary:
            missing.append(field)
    return {
        "status": "UNVERIFIED" if missing else "EVIDENCE_COMPLETE_REVIEW_REQUIRED",
        "missing_evidence": missing,
        "play_authorized": False,
    }
