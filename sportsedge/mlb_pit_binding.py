from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class MLBPITBindingError(ValueError):
    pass


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBPITBindingError("PIT_SOURCE_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBPITBindingError("PIT_SOURCE_TIMESTAMP_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise MLBPITBindingError(f"PIT_SOURCE_FILE_MISSING:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_record(record: Mapping[str, Any], *, captured_at: datetime) -> dict[str, Any]:
    path = Path(str(record.get("path") or ""))
    expected = str(record.get("sha256") or "").lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise MLBPITBindingError("PIT_SOURCE_SHA256_INVALID")
    actual = _sha256_file(path)
    if actual != expected:
        raise MLBPITBindingError(f"PIT_SOURCE_SHA256_MISMATCH:{path}")
    observed = _parse_ts(record.get("observed_at_utc"))
    if observed > captured_at:
        raise MLBPITBindingError("PIT_SOURCE_OBSERVED_AFTER_DECISION_CAPTURE")
    out = dict(record)
    out["path"] = str(path)
    out["sha256"] = actual
    out["observed_at_utc"] = observed.isoformat()
    return out


def _schedule_contains_game(path: Path, game_pk: int) -> bool:
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except Exception as exc:
        raise MLBPITBindingError("PIT_SCHEDULE_RAW_JSON_INVALID") from exc
    for date_block in payload.get("dates") or []:
        for game in date_block.get("games") or []:
            try:
                if int(game.get("gamePk")) == game_pk:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def bind_v8_game_sources(
    card: Mapping[str, Any],
    *,
    game_id: str,
    captured_at: datetime,
) -> dict[str, Any]:
    """Return immutable same-fetch lineup/starter provenance for one V8 decision.

    This function never refetches or backfills. It can only bind files named in the
    card's same-fetch manifest. Multiple plausible snapshots are rejected because
    the final inference source would be ambiguous.
    """
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise MLBPITBindingError("DECISION_CAPTURE_TIMESTAMP_TIMEZONE_REQUIRED")
    captured = captured_at.astimezone(timezone.utc)
    manifest = card.get("pit_source_capture")
    if not isinstance(manifest, Mapping):
        raise MLBPITBindingError("PIT_SOURCE_CAPTURE_MANIFEST_MISSING")
    if manifest.get("schema") != "MLB_SAME_FETCH_PIT_SOURCE_CAPTURE_V1":
        raise MLBPITBindingError("PIT_SOURCE_CAPTURE_SCHEMA_INVALID")
    if manifest.get("capture_semantics") != "SAME_RESPONSE_BYTES_CONSUMED_BY_MODEL":
        raise MLBPITBindingError("PIT_SOURCE_CAPTURE_SEMANTICS_INVALID")
    if manifest.get("promotion_authority") is not False:
        raise MLBPITBindingError("PIT_SOURCE_CAPTURE_AUTHORITY_INVALID")
    if manifest.get("retroactive_point_in_time_claim") is not False:
        raise MLBPITBindingError("PIT_SOURCE_CAPTURE_RETROACTIVE_CLAIM_INVALID")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise MLBPITBindingError("PIT_SOURCE_CAPTURE_RECORDS_INVALID")
    try:
        game_pk = int(game_id)
    except (TypeError, ValueError) as exc:
        raise MLBPITBindingError("PIT_SOURCE_GAME_ID_INVALID") from exc

    schedules = []
    boxscores = []
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("source_kind") or "")
        if kind == "MLB_STATSAPI_SCHEDULE":
            schedules.append(_valid_record(raw, captured_at=captured))
        elif kind == "MLB_STATSAPI_BOXSCORE":
            try:
                record_game_pk = int(raw.get("game_pk"))
            except (TypeError, ValueError):
                continue
            if record_game_pk == game_pk:
                boxscores.append(_valid_record(raw, captured_at=captured))

    schedules = [record for record in schedules if _schedule_contains_game(Path(record["path"]), game_pk)]
    if len(schedules) != 1:
        raise MLBPITBindingError(f"PIT_STARTER_SOURCE_AMBIGUOUS_OR_MISSING:{len(schedules)}")
    if len(boxscores) != 1:
        raise MLBPITBindingError(f"PIT_LINEUP_SOURCE_AMBIGUOUS_OR_MISSING:{len(boxscores)}")

    starter = schedules[0]
    lineup = boxscores[0]
    return {
        "pit_capture_schema": manifest["schema"],
        "pit_capture_semantics": manifest["capture_semantics"],
        "starter_snapshot_path": starter["path"],
        "starter_snapshot_sha256": starter["sha256"],
        "starter_observed_at_utc": starter["observed_at_utc"],
        "lineup_snapshot_path": lineup["path"],
        "lineup_snapshot_sha256": lineup["sha256"],
        "lineup_observed_at_utc": lineup["observed_at_utc"],
        "pit_binding_promotion_authority": False,
        "pit_binding_retroactive_claim": False,
    }


# --------------------------------------------------------------------------
# Research-only loader: verified starter_capture records -> pitcher binding.
# --------------------------------------------------------------------------

STARTER_LOADER_SCHEMA = "SPORTSEDGE_MLB_STARTER_CAPTURE_RESEARCH_BINDING_V1"
_SAME_FETCH_SKEW_SECONDS = 5


def _blocked(reason: str, game_pk: Any, **extra: Any) -> dict[str, Any]:
    out = {
        "schema": STARTER_LOADER_SCHEMA,
        "game_pk": game_pk,
        "binding_status": "BLOCKED",
        "block_reason": reason,
        "pricing_authorized": False,
        "betting_authorized": False,
        "model_eligible": False,
        "max_action": "NONE",
        "research_only": True,
        "promotion_authority": False,
        "retroactive_point_in_time_claim": False,
        "away_probable_id": None,
        "home_probable_id": None,
    }
    out.update(extra)
    return out


def load_research_starter_binding(
    *,
    capture_path: Path,
    manifest_path: Path,
    raw_dir: Path,
    receipt_root: Path,
    game_pk: int,
    as_of: datetime,
    plan_first_pitch_utc: str,
    verifier_now: datetime | None = None,
) -> dict[str, Any]:
    """Read-only: bind starters for one game from verified starter_capture.

    Fails closed (BLOCKED, pricing not authorized) on: unverified capture
    chain, unverified/missing raw bytes, unverified receipt journal, no
    receipt for the record's bytes, a receipt after ``as_of``
    (``receipt_supports_as_of``), postponement, OBSERVED-only, ID_MISSING,
    any other FAILED record, or a stale/rescheduled plan epoch.

    Success is research-only: ``binding_status`` RESEARCH_BOUND, ``max_action``
    WATCH, and ``pricing_authorized``/``betting_authorized`` always False.
    Never writes, refetches, or repairs anything; never creates a timestamp.
    """
    from sportsedge import mlb_source
    from sportsedge.sports.mlb import starter_capture as sc

    if type(game_pk) is not int or game_pk <= 0:
        return _blocked("GAME_PK_INVALID", game_pk)
    try:
        as_of_utc = _parse_ts(as_of.isoformat() if isinstance(as_of, datetime) else as_of)
    except (MLBPITBindingError, AttributeError):
        return _blocked("AS_OF_INVALID", game_pk)

    chain = sc.verify_capture_chain(Path(capture_path), Path(manifest_path),
                                    verifier_now=verifier_now)
    if not chain["ok"]:
        return _blocked(f"CAPTURE_CHAIN_UNVERIFIED:{chain['failure']['reason']}", game_pk)
    raw = sc.verify_raw_store(Path(capture_path), Path(raw_dir))
    if not raw["ok"]:
        return _blocked(f"RAW_BYTES_UNVERIFIED:{raw['failure']['reason']}", game_pk)
    try:
        receipts = mlb_source.verify_receipt_journal(Path(receipt_root),
                                                     verifier_now=verifier_now)
    except Exception as exc:  # MLBSourceError or I/O: fail closed
        return _blocked(f"RECEIPT_JOURNAL_UNVERIFIED:{exc}"[:200], game_pk)

    candidates = []
    for rec in sc.read_records(Path(capture_path)):
        if rec.get("record_type") != "SNAPSHOT" or rec.get("game_pk") != game_pk:
            continue
        try:
            captured = _parse_ts(rec.get("captured_at_utc"))
        except MLBPITBindingError:
            return _blocked("RECORD_TIMESTAMP_INVALID", game_pk)
        if captured <= as_of_utc:
            candidates.append((captured, rec))
    if not candidates:
        return _blocked("NO_SNAPSHOT_AT_OR_BEFORE_AS_OF", game_pk)
    candidates.sort(key=lambda item: item[0])
    captured, rec = candidates[-1]
    if len([c for c in candidates if c[0] == captured]) > 1:
        return _blocked("LATEST_SNAPSHOT_AMBIGUOUS", game_pk)

    if "Postpon" in str(rec.get("detailed_state") or "") or rec.get("status_code") == "D":
        return _blocked("POSTPONED_NOT_IDENTITY_EVIDENCE", game_pk)
    status = rec.get("record_status")
    reason = str(rec.get("failure_reason") or "")
    if status == "OBSERVED":
        return _blocked("OBSERVED_ONLY_NOT_IDENTITY_EVIDENCE", game_pk)
    if status == "FAILED" and reason.startswith("PROBABLE_PITCHER_ID_MISSING"):
        return _blocked("ID_MISSING", game_pk)
    if status != "CAPTURED":
        return _blocked(f"RECORD_NOT_CAPTURED:{status}:{reason}"[:200], game_pk)
    ids = {}
    for side in ("away", "home"):
        pid = rec.get(f"{side}_probable_id")
        if rec.get(f"{side}_probable_status") != "BOUND" or type(pid) is not int or pid <= 0:
            return _blocked("ID_MISSING", game_pk)
        ids[side] = pid
    planned = rec.get("planned_first_pitch_utc")
    if (not plan_first_pitch_utc or planned is None
            or _parse_ts(planned) != _parse_ts(plan_first_pitch_utc)
            or rec.get("game_date_utc") is None
            or _parse_ts(rec["game_date_utc"]) != _parse_ts(plan_first_pitch_utc)):
        return _blocked("STALE_RESCHEDULE_EPOCH", game_pk)
    if as_of_utc >= _parse_ts(plan_first_pitch_utc):
        return _blocked("AS_OF_NOT_PREGAME", game_pk)

    fetch_started = _parse_ts(rec.get("fetch_started_at_utc"))
    skew = __import__("datetime").timedelta(seconds=_SAME_FETCH_SKEW_SECONDS)
    matches = [
        e for e in receipts
        if e.get("sha256") == rec.get("raw_sha256") and e.get("url") == rec.get("source_url")
    ]
    if not matches:
        return _blocked("RECEIPT_NOT_FOUND_FOR_RAW_BYTES", game_pk)
    same_fetch = [
        e for e in matches
        if _parse_ts(e["fetch_started_at_utc"]) >= fetch_started - skew
        and _parse_ts(e["received_at_utc"]) <= captured + skew
    ]
    if not same_fetch:
        return _blocked("RECEIPT_NOT_SAME_FETCH_AS_RECORD", game_pk)
    if len(same_fetch) > 1:
        return _blocked("RECEIPT_AMBIGUOUS", game_pk)
    receipt = same_fetch[0]
    if not mlb_source.receipt_supports_as_of(receipt, as_of_utc):
        return _blocked("RECEIPT_AFTER_AS_OF", game_pk)

    return {
        "schema": STARTER_LOADER_SCHEMA,
        "game_pk": game_pk,
        "binding_status": "RESEARCH_BOUND",
        "block_reason": None,
        "pricing_authorized": False,
        "betting_authorized": False,
        "model_eligible": False,
        "max_action": "WATCH",
        "research_only": True,
        "promotion_authority": False,
        "retroactive_point_in_time_claim": False,
        "away_probable_id": ids["away"],
        "home_probable_id": ids["home"],
        "slot_id": rec.get("slot_id"),
        "captured_at_utc": rec.get("captured_at_utc"),
        "receipt_received_at_utc": receipt["received_at_utc"],
        "receipt_record_sha256": receipt.get("record_sha256"),
        "raw_sha256": rec["raw_sha256"],
        "raw_store_kind": sc.RAW_STORE_KIND,
        "evidence_limits": "LOCAL_CHAIN_AND_LOCAL_RAW_STORE_ONLY;NO_EXTERNAL_TIME_ANCHOR",
    }
