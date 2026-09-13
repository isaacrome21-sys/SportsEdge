from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

UTC = timezone.utc


class NetworkAttestationError(ValueError):
    pass


def iso(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NetworkAttestationError("TIMESTAMP_TIMEZONE_REQUIRED")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NetworkAttestationError("TIMESTAMP_MISSING")
    text = value.strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NetworkAttestationError("TIMESTAMP_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NetworkAttestationError("TIMESTAMP_TIMEZONE_REQUIRED")
    return out.astimezone(UTC)


def _walk_wallclocks(obj: Any) -> Iterable[str]:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if str(key).lower() == "wallclock" and isinstance(value, str):
                yield value
            else:
                yield from _walk_wallclocks(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_wallclocks(value)


def first_play_utc(summary: Mapping[str, object]) -> str | None:
    parsed = []
    for value in _walk_wallclocks(summary):
        try:
            parsed.append(parse_ts(value))
        except NetworkAttestationError:
            continue
    return iso(min(parsed)) if parsed else None


def completed_status(summary: Mapping[str, object]) -> tuple[bool, str]:
    header = summary.get("header")
    if not isinstance(header, Mapping):
        return False, "UNKNOWN"
    comps = header.get("competitions")
    if not isinstance(comps, list) or not comps or not isinstance(comps[0], Mapping):
        return False, "UNKNOWN"
    status = comps[0].get("status")
    if not isinstance(status, Mapping):
        return False, "UNKNOWN"
    stype = status.get("type")
    if not isinstance(stype, Mapping):
        return False, "UNKNOWN"
    return bool(stype.get("completed")), str(stype.get("name") or "UNKNOWN")


def canonical_settlement_view(*, espn_event_id: str, summary: Mapping[str, object]) -> dict[str, object]:
    completed, status_name = completed_status(summary)
    return {
        "schema_version": "CFB_ESPN_SETTLEMENT_VIEW_V1",
        "espn_event_id": str(espn_event_id),
        "completed": completed,
        "status_name": status_name,
        "first_play_utc": first_play_utc(summary),
    }


def canonical_sha256(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_observation(*, espn_event_id: str, summary: Mapping[str, object], observed_at: datetime, raw_sha256: str) -> dict[str, object]:
    view = canonical_settlement_view(espn_event_id=espn_event_id, summary=summary)
    return {
        "schema_version": "CFB_ESPN_ATTESTATION_OBSERVATION_V1",
        "espn_event_id": str(espn_event_id),
        "observed_at_utc": iso(observed_at),
        "provider": "ESPN_CFB_SUMMARY",
        "provider_raw_sha256": str(raw_sha256),
        "canonical_snapshot": view,
        "canonical_snapshot_sha256": canonical_sha256(view),
        "promotion_authority": False,
        "evidence_eligibility_authority": False,
    }


def build_attestation_record(observations: Iterable[Mapping[str, object]]) -> dict[str, object]:
    rows = sorted(observations, key=lambda r: parse_ts(r.get("observed_at_utc")))
    if not rows:
        raise NetworkAttestationError("NO_ATTESTATION_OBSERVATIONS")
    event_ids = {str(r.get("espn_event_id") or "") for r in rows}
    if "" in event_ids or len(event_ids) != 1:
        raise NetworkAttestationError("ATTESTATION_EVENT_ID_MISMATCH")
    completed_rows = [r for r in rows if isinstance(r.get("canonical_snapshot"), Mapping) and r["canonical_snapshot"].get("completed") is True]
    if not completed_rows:
        return {"status": "PENDING_FINAL_STATUS", "espn_event_id": next(iter(event_ids)), "promotion_authority": False}
    final_observed = completed_rows[0]
    first_play = final_observed["canonical_snapshot"].get("first_play_utc")
    matching = [r for r in completed_rows if r.get("canonical_snapshot_sha256") == completed_rows[-1].get("canonical_snapshot_sha256")]
    if len(matching) < 2:
        return {"status": "PENDING_STABILITY_SECOND_READ", "espn_event_id": next(iter(event_ids)), "promotion_authority": False}
    prior, current = matching[-2], matching[-1]
    return {
        "schema_version": "CFB_FIRST_PLAY_ATTESTATION_RECORD_V1",
        "status": "STABILITY_OBSERVED_NOT_EVIDENCE_BY_ITSELF",
        "espn_event_id": next(iter(event_ids)),
        "first_play_utc": first_play,
        "final_status_utc": final_observed.get("observed_at_utc"),
        "sealed_at_utc": current.get("observed_at_utc"),
        "prior_snapshot_sha256": prior.get("canonical_snapshot_sha256"),
        "current_snapshot_sha256": current.get("canonical_snapshot_sha256"),
        "prior_observed_at_utc": prior.get("observed_at_utc"),
        "current_observed_at_utc": current.get("observed_at_utc"),
        "timestamp_precision_known": bool(first_play),
        "timestamp_uncertainty_seconds": None,
        "timestamp_uncertainty_status": "UNVERIFIED_FAIL_CLOSED",
        "promotion_authority": False,
        "evidence_eligibility_authority": False,
    }


def discover_event_ids(root: Path) -> list[str]:
    ids = set()
    if root.exists():
        for path in root.glob("*/close_raw/*/*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            event_id = str(row.get("espn_event_id") or "")
            if event_id:
                ids.add(event_id)
    return sorted(ids)
