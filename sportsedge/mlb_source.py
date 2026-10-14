from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace, dataclass, asdict
from datetime import datetime, timedelta, timezone
import hashlib
import os
import stat
import uuid
import time as _time
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from . import evidence_admission_gate as _anchor_gate
from .source_lineage import canonical_game_identity

BASE = "https://statsapi.mlb.com"
SAVANT_PREVIEW_BASE = "https://baseballsavant.mlb.com/preview"
CHICAGO_TZ = ZoneInfo("America/Chicago")


class MLBSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GameSnapshot:
    game_pk: int
    game_date: str
    status: str
    away_id: int
    away_name: str
    home_id: int
    home_name: str
    away_probable_pitcher_id: int | None
    away_probable_pitcher_name: str | None
    home_probable_pitcher_id: int | None
    home_probable_pitcher_name: str | None
    retrieved_at: str
    source: str = "MLB_STATSAPI_SCHEDULE"
    game_number: int | None = None
    double_header: str | None = None
    venue_id: int | None = None
    official_date: str | None = None
    detailed_status: str | None = None
    game_type: str | None = None
    # Caller's own timestamp (e.g. run as-of); never receipt evidence. Bounded in fetch_schedule.
    caller_asserted_at: str | None = None


RECEIPT_CLOCK_SKEW = timedelta(seconds=5)
# A claimed fetch receipt older than this cannot be certified by the current
# independent system clock. This is a transport-ingestion limit, not evidence
# that data were present at a historical game as-of instant.
RECEIPT_ANCHOR_MAX_AGE = timedelta(seconds=30)
RECEIPT_MAX_FETCH_SPAN = timedelta(seconds=30)


def _trusted_now() -> datetime:
    """Trusted system clock for fetch start / receipt. Not injectable by callers or
    recorders; only tests monkeypatch this module attribute."""
    return _DATETIME.fromtimestamp(_time.time_ns() / 1e9, tz=timezone.utc)


_utc_clock = _trusted_now  # backward-compatible name; same trusted source


_DATETIME = datetime  # unpatched type for isinstance checks


def _aware(value: Any, label: str) -> datetime:
    if not isinstance(value, _DATETIME) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBSourceError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def bound_caller_time(value: datetime, *, fetch_started_at: datetime, received_at: datetime,
                      skew: timedelta = RECEIPT_CLOCK_SKEW) -> datetime:
    """Fail closed unless fetch_started_at <= value <= received_at + skew."""
    v = _aware(value, "caller-supplied time")
    if v < fetch_started_at:
        raise MLBSourceError("CALLER_TIME_BEFORE_FETCH_START")
    if v > received_at + skew:
        raise MLBSourceError("CALLER_TIME_IN_FUTURE")
    return v


@dataclass(frozen=True)



class MLBSourceCaptureRecord:
    sequence: int
    source_kind: str
    url: str
    observed_at_utc: str
    sha256: str
    path: str
    byte_length: int
    game_pk: int | None = None
    # Persisted receipt bounds from the trusted module clock. observed_at_utc is
    # ALWAYS equal to received_at_utc (post-read completion), never earlier.
    fetch_started_at_utc: str | None = None
    received_at_utc: str | None = None
    # Non-evidentiary: the injectable recorder clock's own assertion, kept only
    # for diagnostics. Never used as a receipt or PIT time.
    recorder_clock_assertion_utc: str | None = None
    receipt_nonce: str | None = None
    prev_record_sha256: str | None = None
    record_sha256: str | None = None


RECEIPT_JOURNAL_NAME = "receipt_journal.jsonl"
# Intent journal for receipt appends: the same write-ahead discipline as the
# starter-capture store (sportsedge/sports/mlb/starter_capture.py). Every
# append is serialized under a stable, never-unlinked lock file and bracketed
# by BEGIN/COMMIT intent lines, so a crash mid-append leaves a *named* torn
# state (pending intent and/or orphaned raw payload) that verification
# refuses -- never a silently accepted partial pair.
RECEIPT_INTENT_JOURNAL_NAME = "receipt_journal.intent.jsonl"
RECEIPT_JOURNAL_LOCK_NAME = RECEIPT_JOURNAL_NAME + ".lock"
RECEIPT_INTENT_SCHEMA = "mlb_receipt_intent_v1"
_RECEIPT_RAW_NAME_RE = re.compile(r"^\d{4,}_.*_[0-9a-f]{64}\.json$")
GENESIS_SHA256 = "0" * 64
RECEIPT_PLAUSIBLE_FLOOR = datetime(2020, 1, 1, tzinfo=timezone.utc)
_HASHED_FIELDS = (
    "sequence", "source_kind", "url", "observed_at_utc", "sha256", "file_name",
    "byte_length", "game_pk", "fetch_started_at_utc", "received_at_utc",
    "recorder_clock_assertion_utc", "receipt_nonce", "prev_record_sha256",
)


def _record_hash(entry: dict[str, Any]) -> str:
    body = {k: entry.get(k) for k in _HASHED_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MLBSourceError(f"RECEIPT_FIELD_MISSING:{label}")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MLBSourceError(f"RECEIPT_FIELD_INVALID:{label}") from exc
    if dt.tzinfo is None:
        raise MLBSourceError(f"RECEIPT_FIELD_NAIVE:{label}")
    return dt.astimezone(timezone.utc)


# Hard limit on archived StatsAPI responses. A hostile or corrupted path must never
# block on a FIFO/device or cause unbounded memory consumption during verification.
MAX_RECEIPT_RAW_BYTES = 32 * 1024 * 1024


def _read_verified_receipt_raw(root: Path, filename: str, expected_length: Any) -> bytes:
    """Read regular immutable-evidence bytes with no symlink/FIFO following.

    This is local archive safety, NOT a trusted external timestamp, immutable
    storage guarantee or authority to promote retrospective source evidence.
    """
    if (type(expected_length) is not int or expected_length < 0
            or expected_length > MAX_RECEIPT_RAW_BYTES):
        raise MLBSourceError("RECEIPT_RAW_SIZE_INVALID")
    path = root / filename
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise MLBSourceError("RECEIPT_RAW_BYTES_MISSING") from exc
    except OSError as exc:
        raise MLBSourceError("RECEIPT_RAW_PATH_UNSAFE") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise MLBSourceError("RECEIPT_RAW_PATH_UNSAFE")
        if before.st_size > MAX_RECEIPT_RAW_BYTES:
            raise MLBSourceError("RECEIPT_RAW_SIZE_INVALID")
        if before.st_size != expected_length:
            raise MLBSourceError("RECEIPT_RAW_BYTES_TAMPERED")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            raw = handle.read(expected_length + 1)
            after = os.fstat(handle.fileno())
        # Check the path once more: a file swapped while open cannot silently
        # stand in for the path independently referenced by the journal.
        try:
            current = path.lstat()
        except OSError as exc:
            raise MLBSourceError("RECEIPT_RAW_PATH_UNSAFE") from exc
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if (len(raw) != expected_length or not stat.S_ISREG(current.st_mode)
                or identity(before) != identity(after) or identity(after) != identity(current)):
            raise MLBSourceError("RECEIPT_RAW_BYTES_TAMPERED")
        return raw
    finally:
        if fd >= 0:
            os.close(fd)


def _is_sha256_hex(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _canonical_line(obj: Mapping[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_receipt_write(path: Path, data: bytes, *, append: bool) -> None:
    """Descriptor-based durable write (path-safety hardening ported from
    the Codex durability build): opened ``O_NOFOLLOW`` with an ``fstat``
    regular-file check, written in full, fsync'd, and closed with a
    directory fsync. A FIFO, directory or symlink planted at the path is
    refused by name (``RECEIPT_WRITE_PATH_UNSAFE``) instead of being
    followed -- or, for a FIFO under a plain ``open("ab")``, blocked on
    indefinitely. Appends are size-capped so a journal file can never
    grow past ``MAX_RECEIPT_RAW_BYTES`` unnoticed
    (``RECEIPT_JOURNAL_SIZE_INVALID``). This changes only *how* bytes
    reach disk; the intent sequence built on it is unchanged."""
    flags = (os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    flags |= os.O_APPEND if append else os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise MLBSourceError("RECEIPT_WRITE_PATH_UNSAFE") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise MLBSourceError("RECEIPT_WRITE_PATH_UNSAFE")
        if append and info.st_size + len(data) > MAX_RECEIPT_RAW_BYTES:
            raise MLBSourceError("RECEIPT_JOURNAL_SIZE_INVALID")
        pending = memoryview(data)
        while pending:
            count = os.write(fd, pending)
            if count <= 0:
                raise MLBSourceError("RECEIPT_WRITE_INCOMPLETE")
            pending = pending[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _resync_existing_receipt_raw(path: Path) -> None:
    """Re-fsync a pre-existing identical raw payload inode before its
    first journal reference (defense in depth ported from the Codex
    durability build): bytes already present on disk do not establish
    that they are durable, so the existing inode is synced explicitly.
    Reachable only for a payload whose bytes already matched the new
    record exactly; anything else was refused earlier as a collision,
    and an unreferenced payload is refused by the orphan rule before
    this point in the append protocol."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise MLBSourceError("RECEIPT_WRITE_PATH_UNSAFE") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise MLBSourceError("RECEIPT_WRITE_PATH_UNSAFE")
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _append_line_fsync(path: Path, line: bytes) -> None:
    _durable_receipt_write(path, line, append=True)


def _read_journal_file(path: Path, *, unsafe: str,
                       size_invalid: str) -> bytes | None:
    """Read a journal file without following or blocking on a hostile
    path; ``None`` when the file is absent. ``lstat`` refuses symlinks,
    directories and FIFOs by name *before* any open -- a plain
    ``read_bytes()`` blocks indefinitely on a FIFO, raises an unnamed
    ``IsADirectoryError`` for a directory, and treats a dangling symlink
    as absent. The descriptor read is ``O_NOFOLLOW``, re-checks that
    the opened file is regular, and is size-capped."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MLBSourceError(unsafe) from exc
    if not stat.S_ISREG(info.st_mode):
        raise MLBSourceError(unsafe)
    if info.st_size > MAX_RECEIPT_RAW_BYTES:
        raise MLBSourceError(size_invalid)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MLBSourceError(unsafe) from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise MLBSourceError(unsafe)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RECEIPT_RAW_BYTES:
                raise MLBSourceError(size_invalid)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


@contextmanager
def _receipt_write_lock(root: Path) -> Iterator[None]:
    """Serialize receipt appends across instances and processes.

    The lock file is stable and never unlinked: changing its inode would
    permit separate processes to hold distinct locks while both believe
    they are alone. This is the serialization discipline of the
    starter-capture intent journal (its ``_locked``); it serializes
    cooperating writers only -- unsynchronized readers are not protected
    by it and must tolerate (and refuse) torn state.
    """
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / RECEIPT_JOURNAL_LOCK_NAME
    # Descriptor-based acquisition (ported from the Codex durability
    # build): O_NOFOLLOW + fstat regular-file check, so a symlink or
    # FIFO planted at the lock path fails closed by name instead of
    # being followed (or blocked on). The file is still never unlinked.
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR
                     | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0), 0o600)
    except OSError as exc:
        raise MLBSourceError("RECEIPT_LOCK_PATH_UNSAFE") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise MLBSourceError("RECEIPT_LOCK_PATH_UNSAFE")
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read_receipt_intents(root: Path) -> list[dict[str, Any]]:
    """Strictly parse the receipt intent journal (absent file = no intents).

    Mirrors the starter-capture intent reader: duplicate JSON keys and
    non-finite numbers are refused, the schema/state/identity fields are
    validated before anything trusts them, and an unterminated tail (a
    torn BEGIN/COMMIT append) fails closed.
    """
    path = root / RECEIPT_INTENT_JOURNAL_NAME
    raw = _read_journal_file(
        path, unsafe="RECEIPT_INTENT_JOURNAL_PATH_UNSAFE",
        size_invalid="RECEIPT_INTENT_JOURNAL_SIZE_INVALID")
    if raw is None:
        return []
    if raw and not raw.endswith(b"\n"):
        raise MLBSourceError("RECEIPT_INTENT_JOURNAL_UNTERMINATED")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MLBSourceError("RECEIPT_INTENT_JOURNAL_UNPARSEABLE") from exc
    out: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise MLBSourceError(f"RECEIPT_INTENT_LINE_INVALID:{lineno}")

        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            data = {}
            for key, value in pairs:
                if key in data:
                    raise MLBSourceError(f"RECEIPT_INTENT_DUPLICATE_JSON_KEY:{lineno}")
                data[key] = value
            return data

        try:
            obj = json.loads(line, object_pairs_hook=unique_pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(
                                 MLBSourceError(f"RECEIPT_INTENT_NONFINITE_NUMBER:{lineno}")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MLBSourceError(f"RECEIPT_INTENT_LINE_UNPARSEABLE:{lineno}") from exc
        if type(obj) is not dict or obj.get("schema") != RECEIPT_INTENT_SCHEMA:
            raise MLBSourceError(f"RECEIPT_INTENT_LINE_INVALID:{lineno}")
        state = obj.get("state")
        if state not in ("BEGIN", "COMMIT", "ABORT") or not _is_sha256_hex(obj.get("intent_id")):
            raise MLBSourceError(f"RECEIPT_INTENT_LINE_INVALID:{lineno}")
        if state == "BEGIN":
            seq = obj.get("sequence")
            if (type(seq) is not int or seq < 1
                    or not isinstance(obj.get("file_name"), str) or not obj.get("file_name")
                    or not _is_sha256_hex(obj.get("sha256"))
                    or not _is_sha256_hex(obj.get("record_sha256"))
                    or not isinstance(obj.get("url"), str)):
                raise MLBSourceError(f"RECEIPT_INTENT_LINE_INVALID:{lineno}")
        out.append(obj)
    return out


def _pending_receipt_intents(intents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open BEGINs, enforcing transition discipline (mirror of the
    starter-capture ``_pending``): an unpaired COMMIT/ABORT or a repeated
    BEGIN makes intent-journal integrity indeterminate and fails closed."""
    open_intents: dict[str, dict[str, Any]] = {}
    for intent in intents:
        ident = intent["intent_id"]  # _read_receipt_intents validated structure
        state = intent["state"]
        if state == "BEGIN":
            if ident in open_intents:
                raise MLBSourceError("RECEIPT_INTENT_DUPLICATE_BEGIN")
            open_intents[ident] = intent
        elif state in ("COMMIT", "ABORT"):
            if ident not in open_intents:
                raise MLBSourceError("RECEIPT_INTENT_ORPHAN_TERMINAL")
            del open_intents[ident]
        else:  # pragma: no cover - state validated in _read_receipt_intents
            raise MLBSourceError("RECEIPT_INTENT_STATE_INVALID")
    return list(open_intents.values())


def _refuse_unjournaled_raw(root: Path, entries: list[dict[str, Any]]) -> None:
    """A raw payload file that no journal entry references is the surviving
    half of a torn pair. It is refused -- never silently accepted, repaired
    or extended -- so a crash between the payload write and the journal
    append cannot launder a partial pair into the archive."""
    referenced = {entry["file_name"] for entry in entries}
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if _RECEIPT_RAW_NAME_RE.match(child.name) and child.name not in referenced:
            raise MLBSourceError("RECEIPT_RAW_ORPHAN_UNJOURNALED")


def _refuse_pending_receipt_intents(root: Path) -> None:
    """An intent BEGIN with no COMMIT/ABORT is a writer that died mid-pair.
    The pair it names may be complete on disk, but its commit never became
    durable, so the archive state is refused rather than presumed good --
    the receipt verifier's read-only posture, mirroring the starter
    store's INTENT_UNCOMMITTED refusal."""
    if _pending_receipt_intents(_read_receipt_intents(root)):
        raise MLBSourceError("RECEIPT_INTENT_ORPHAN_UNCOMMITTED")


def verify_receipt_journal(root: str | Path, *, verifier_now: datetime | None = None) -> list[dict[str, Any]]:
    """Independently re-verify a persisted capture directory (fresh process / restart).

    Fails closed on: missing fields, broken hash chain, edited entries, raw byte
    tamper, observed != received, received < fetch start, fetch span over the limit,
    implausible (pre-2020 or future vs verifier clock) receipts, duplicate nonces or
    duplicate receipt tuples. Also fails closed on the write-side crash states the
    intent-journal append protocol can leave behind: a raw payload file referenced
    by no journal entry (RECEIPT_RAW_ORPHAN_UNJOURNALED -- the surviving half of a
    torn pair) and an intent BEGIN with no COMMIT/ABORT (a writer that died
    mid-pair). A FIFO, directory, symlink or oversized file at the journal
    path itself is refused by name (RECEIPT_JOURNAL_PATH_UNSAFE /
    RECEIPT_JOURNAL_SIZE_INVALID) before any read. The chain is local
    tamper-evidence only; it is NOT an external, independently anchored
    timestamp.
    """
    root = Path(root)
    journal = root / RECEIPT_JOURNAL_NAME
    # Journal-path hardening (ported from the Codex durability build):
    # lstat refuses a FIFO, directory or symlink at the journal path by
    # name before any read -- a plain read_bytes() blocks indefinitely
    # on a FIFO, raises an unnamed IsADirectoryError for a directory,
    # and treats a dangling symlink as "no journal". The bytes are then
    # read through the same descriptor-based, size-capped, identity-
    # pinned reader as raw payloads, with its RECEIPT_RAW_* refusals
    # re-named into this journal's vocabulary.
    try:
        journal_info = journal.lstat()
    except FileNotFoundError:
        _refuse_unjournaled_raw(root, [])
        _refuse_pending_receipt_intents(root)
        return []
    except OSError as exc:
        raise MLBSourceError("RECEIPT_JOURNAL_PATH_UNSAFE") from exc
    if not stat.S_ISREG(journal_info.st_mode):
        raise MLBSourceError("RECEIPT_JOURNAL_PATH_UNSAFE")
    try:
        journal_bytes = _read_verified_receipt_raw(
            root, RECEIPT_JOURNAL_NAME, journal_info.st_size)
    except MLBSourceError as exc:
        raise MLBSourceError(
            str(exc).replace("RECEIPT_RAW", "RECEIPT_JOURNAL")) from exc
    # A half-written final JSON record may parse as a complete object, but the
    # next append would concatenate two lines. Reject such an archive as-is.
    if not journal_bytes or not journal_bytes.endswith(b"\n"):
        raise MLBSourceError("RECEIPT_JOURNAL_UNTERMINATED")
    now = _aware(verifier_now, "verifier clock") if verifier_now is not None else _aware(_trusted_now(), "verifier clock")
    entries: list[dict[str, Any]] = []
    prev = GENESIS_SHA256
    nonces: set[str] = set()
    keys: set[tuple[str, str, str, str]] = set()
    expected_keys = set(_HASHED_FIELDS) | {"record_sha256"}
    try:
        journal_text = journal_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MLBSourceError("RECEIPT_JOURNAL_CORRUPT") from exc
    for lineno, line in enumerate(journal_text.splitlines(), start=1):
        if not line.strip():
            raise MLBSourceError(f"RECEIPT_JOURNAL_BLANK_LINE:{lineno}")
        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            data = {}
            for key, value in pairs:
                if key in data:
                    raise MLBSourceError(f"RECEIPT_JOURNAL_DUPLICATE_JSON_KEY:{lineno}")
                data[key] = value
            return data
        try:
            entry = json.loads(line, object_pairs_hook=unique_pairs,
                               parse_constant=lambda value: (_ for _ in ()).throw(
                                   MLBSourceError("RECEIPT_JOURNAL_NONFINITE_NUMBER")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MLBSourceError(f"RECEIPT_JOURNAL_CORRUPT:{lineno}") from exc
        if type(entry) is not dict:
            raise MLBSourceError(f"RECEIPT_JOURNAL_SCHEMA_DRIFT:{lineno}")
        # Missing evidentiary fields retain their dedicated failure code.
        # Unexpected additional fields are still refused rather than silently
        # ignored by the fixed-field hash.
        for field in _HASHED_FIELDS + ("record_sha256",):
            if field not in entry:
                raise MLBSourceError(f"RECEIPT_FIELD_MISSING:{field}")
        if set(entry) != expected_keys:
            raise MLBSourceError(f"RECEIPT_JOURNAL_SCHEMA_DRIFT:{lineno}")
        for field in _HASHED_FIELDS + ("record_sha256",):
            if field not in entry or (entry[field] is None and field not in ("game_pk", "recorder_clock_assertion_utc")):
                raise MLBSourceError(f"RECEIPT_FIELD_MISSING:{field}")
        if entry["sequence"] != lineno:
            raise MLBSourceError("RECEIPT_SEQUENCE_GAP")
        if entry["prev_record_sha256"] != prev:
            raise MLBSourceError("RECEIPT_CHAIN_BROKEN")
        if _record_hash(entry) != entry["record_sha256"]:
            raise MLBSourceError("RECEIPT_RECORD_TAMPERED")
        start = _parse_utc(entry["fetch_started_at_utc"], "fetch_started_at_utc")
        received = _parse_utc(entry["received_at_utc"], "received_at_utc")
        observed = _parse_utc(entry["observed_at_utc"], "observed_at_utc")
        if observed != received:
            raise MLBSourceError("RECEIPT_OBSERVED_NOT_POST_READ")
        if received < start:
            raise MLBSourceError("RECEIPT_CLOCK_WENT_BACKWARDS")
        if received - start > RECEIPT_MAX_FETCH_SPAN:
            raise MLBSourceError("RECEIPT_FETCH_SPAN_UNBOUNDED")
        if start < RECEIPT_PLAUSIBLE_FLOOR:
            raise MLBSourceError("RECEIPT_IMPLAUSIBLY_OLD")
        if received > now + RECEIPT_CLOCK_SKEW:
            raise MLBSourceError("RECEIPT_FUTURE_VS_VERIFIER")
        key = (entry["url"], entry["sha256"], entry["fetch_started_at_utc"], entry["received_at_utc"])
        if entry["receipt_nonce"] in nonces or key in keys:
            raise MLBSourceError("RECEIPT_DUPLICATE_REPLAY")
        nonces.add(entry["receipt_nonce"]); keys.add(key)
        filename = entry["file_name"]
        if (not isinstance(filename, str) or not filename or len(filename) > 180
                or Path(filename).name != filename or chr(92) in filename):
            raise MLBSourceError("RECEIPT_RAW_PATH_UNSAFE")
        raw = _read_verified_receipt_raw(root, filename, entry["byte_length"])
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise MLBSourceError("RECEIPT_RAW_BYTES_TAMPERED")
        prev = entry["record_sha256"]
        entries.append(entry)
    _refuse_unjournaled_raw(root, entries)
    _refuse_pending_receipt_intents(root)
    return entries


def receipt_supports_as_of(entry: dict[str, Any], as_of: datetime) -> bool:
    """A receipt can only evidence pregame availability if bytes were received at or
    before ``as_of``. A schedule fetched today for an old game is never as-of proof."""
    received = _parse_utc(entry.get("received_at_utc") if isinstance(entry, dict) else None, "received_at_utc")
    return received <= _aware(as_of, "as_of")


RECEIPT_ANCHOR_REFUSED = "RECEIPT_ANCHOR_REFUSED"


def admit_anchored_receipt(root: str | Path, record_sha256: str, *, tsa_bundle: Any,
                           event_cutoff: datetime | None,
                           verifier_now: datetime | None = None) -> dict[str, Any]:
    """t127: admit ONE journal receipt as externally time-anchored evidence.

    Goes through the shared dual-TSA admission gate (#2090 anchor
    ``anchor:rfc3161+ots:v1``). While admission is off (committed config) every
    call is refused with ``RECEIPT_ANCHOR_REFUSED:admission_not_activated``
    before the journal is read; the local journal semantics above are
    unchanged. When separately activated, the dual-TSA bundle must cover
    ``record_sha256`` as a leaf, the journal must re-verify, the record must be
    in it and its receipt must be at or before ``event_cutoff``. Never raises.
    """
    refused = {"admitted": False, "external_time_anchor": False, "research_only": True}
    d = _anchor_gate.anchored_admission(tsa_bundle, bound_sha256=record_sha256,
                                        event_cutoff=event_cutoff)
    if not d.admitted:
        return {**refused, "reason": f"{RECEIPT_ANCHOR_REFUSED}:{d.reason}"}
    try:
        entries = verify_receipt_journal(root, verifier_now=verifier_now)
        entry = next((e for e in entries if e["record_sha256"] == record_sha256), None)
        if entry is None:
            return {**refused, "reason": f"{RECEIPT_ANCHOR_REFUSED}:record_not_in_journal"}
        if not receipt_supports_as_of(entry, event_cutoff):
            return {**refused, "reason": f"{RECEIPT_ANCHOR_REFUSED}:receipt_after_cutoff"}
    except MLBSourceError as exc:
        return {**refused, "reason": f"{RECEIPT_ANCHOR_REFUSED}:{exc}"}
    return {"admitted": True, "external_time_anchor": True, "research_only": True,
            "reason": "admitted", "sequence": entry["sequence"],
            "anchor_gen_time_utc": d.gen_time.isoformat() if d.gen_time else None}


class MLBSourceCapture:
    """Append-only recorder for the exact StatsAPI bytes consumed by inference.

    Capture is opt-in. Existing callers behave identically when no capture context
    is active. A recorder never refetches a source; it persists the bytes returned
    by the same response object that is subsequently JSON-decoded by the model.

    Appends are crash-safe and cross-process serialized under the receipt
    intent journal (see ``_append_receipt_locked``): a recorder's in-memory
    chain state is only a construction-time snapshot and is never trusted
    for an append, so concurrent instances cannot fork the hash chain, and
    a writer that dies mid-pair leaves state that verification refuses.
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None):
        self.root = Path(root)
        self.clock = clock or (lambda: _trusted_now())
        self.records: list[MLBSourceCaptureRecord] = []
        self._used_receipts: set[tuple[str, str, str, str]] = set()
        self._used_nonces: set[str] = set()
        self._prev_sha = GENESIS_SHA256
        self._sequence = 0
        # Restart: reload and re-verify persisted state so a new recorder at the
        # same root cannot re-admit a receipt tuple already in the journal.
        for entry in verify_receipt_journal(self.root):
            self._used_receipts.add((entry["url"], entry["sha256"], entry["fetch_started_at_utc"], entry["received_at_utc"]))
            self._used_nonces.add(entry["receipt_nonce"])
            self._prev_sha = entry["record_sha256"]
            self._sequence = entry["sequence"]

    @staticmethod
    def _identity(url: str) -> tuple[str, int | None]:
        if "/api/v1/schedule" in url:
            return "MLB_STATSAPI_SCHEDULE", None
        match = re.search(r"/api/v1/game/(\d+)/boxscore(?:\?|$)", url)
        if match:
            return "MLB_STATSAPI_BOXSCORE", int(match.group(1))
        return "MLB_STATSAPI_OTHER", None

    def record(self, *, url: str, raw: bytes, fetch_started_at: datetime,
               received_at: datetime) -> MLBSourceCaptureRecord:
        """Require an independent system-time anchor, not the recorder clock.

        Caller-provided fetch bounds alone are not evidence. Reject stale,
        future, implausibly long and duplicate receipt claims before writing.
        Every rejection above happens before any byte is written; the write
        itself is one serialized, intent-journaled pair append.
        This still is not a signed cross-process PIT receipt or proof of a
        historical sportsbook/StatsAPI state; all capture remains research.
        """
        try:
            observed = _aware(self.clock(), "source capture clock")
        except MLBSourceError:
            raise MLBSourceError("source capture clock must return timezone-aware datetime")
        start = _aware(fetch_started_at, "trusted fetch start")
        receipt = _aware(received_at, "trusted receipt")
        if receipt < start:
            raise MLBSourceError("RECEIPT_CLOCK_WENT_BACKWARDS")
        bound_caller_time(observed, fetch_started_at=start, received_at=receipt)
        try:
            anchor = _aware(_trusted_now(), "independent system receipt anchor")
        except Exception as exc:
            raise MLBSourceError("RECEIPT_ANCHOR_UNAVAILABLE") from exc
        if receipt > anchor + RECEIPT_CLOCK_SKEW:
            raise MLBSourceError("RECEIPT_FUTURE_VS_SYSTEM_ANCHOR")
        if receipt < anchor - RECEIPT_ANCHOR_MAX_AGE:
            raise MLBSourceError("RECEIPT_STALE_OR_REPLAYED")
        if receipt - start > RECEIPT_MAX_FETCH_SPAN:
            raise MLBSourceError("RECEIPT_FETCH_SPAN_UNBOUNDED")
        source_kind, game_pk = self._identity(url)
        digest = hashlib.sha256(raw).hexdigest()
        receipt_key = (url, digest, start.isoformat(), receipt.isoformat())
        if receipt_key in self._used_receipts:
            raise MLBSourceError("RECEIPT_DUPLICATE_REPLAY")
        if start < RECEIPT_PLAUSIBLE_FLOOR:
            raise MLBSourceError("RECEIPT_IMPLAUSIBLY_OLD")
        # All validation above is write-free: a rejected receipt leaves the
        # root byte-identical (no lock file, no intent line, no payload).
        # The append itself is serialized and intent-journaled so that two
        # recorders -- in this process or across processes -- cannot fork
        # the chain, and a crash mid-append leaves a refused torn state
        # rather than a silently accepted partial pair.
        with _receipt_write_lock(self.root):
            return self._append_receipt_locked(
                url=url, raw=raw, start=start, receipt=receipt,
                observed=observed, anchor=anchor, source_kind=source_kind,
                game_pk=game_pk, digest=digest, receipt_key=receipt_key)

    def _append_receipt_locked(self, *, url: str, raw: bytes, start: datetime,
                               receipt: datetime, observed: datetime,
                               anchor: datetime, source_kind: str,
                               game_pk: int | None, digest: str,
                               receipt_key: tuple[str, str, str, str]
                               ) -> MLBSourceCaptureRecord:
        """Append one raw+journal pair under the write lock.

        Chain state is re-derived from disk here, never trusted from the
        instance's construction-time snapshot: the full journal is
        re-verified (which also refuses a prior writer's pending intent or
        orphaned payload), and sequence / prev-hash / used-sets come from
        the verified entries. The pair is then written write-ahead --
        BEGIN intent, raw payload, journal line, COMMIT intent, each
        append fsync'd with the directory fsync'd after file creation --
        the starter-capture intent journal's protocol. An ordinary
        exception rolls both files back to their prior state and closes
        the intent with ABORT (the starter append's rollback discipline);
        a process death instead leaves the pending intent (and possibly
        an orphaned payload) behind for verification to refuse loudly.
        """
        entries = verify_receipt_journal(self.root, verifier_now=anchor)
        used_receipts = {(e["url"], e["sha256"], e["fetch_started_at_utc"],
                          e["received_at_utc"]) for e in entries}
        used_nonces = {e["receipt_nonce"] for e in entries}
        if receipt_key in used_receipts:
            raise MLBSourceError("RECEIPT_DUPLICATE_REPLAY")
        sequence = (entries[-1]["sequence"] if entries else 0) + 1
        prev_sha = entries[-1]["record_sha256"] if entries else GENESIS_SHA256
        nonce = uuid.uuid4().hex
        while nonce in used_nonces:
            nonce = uuid.uuid4().hex
        suffix = f"game_{game_pk}" if game_pk is not None else source_kind.lower()
        name = f"{sequence:04d}_{suffix}_{digest}.json"
        destination = self.root / name
        if destination.exists() and destination.read_bytes() != raw:
            raise MLBSourceError("immutable raw source capture collision")
        entry = {
            "sequence": sequence, "source_kind": source_kind, "url": url,
            # Canonical observation == trusted post-read completion. Never earlier.
            "observed_at_utc": receipt.isoformat(), "sha256": digest, "file_name": name,
            "byte_length": len(raw), "game_pk": game_pk,
            "fetch_started_at_utc": start.isoformat(), "received_at_utc": receipt.isoformat(),
            "recorder_clock_assertion_utc": observed.isoformat(), "receipt_nonce": nonce,
            "prev_record_sha256": prev_sha,
        }
        entry["record_sha256"] = _record_hash(entry)
        intent_id = hashlib.sha256(
            f"{prev_sha}:{entry['record_sha256']}".encode("utf-8")).hexdigest()
        begin = {"schema": RECEIPT_INTENT_SCHEMA, "intent_id": intent_id,
                 "state": "BEGIN", "sequence": sequence, "file_name": name,
                 "sha256": digest, "record_sha256": entry["record_sha256"],
                 "url": url}
        commit = {"schema": RECEIPT_INTENT_SCHEMA, "intent_id": intent_id,
                  "state": "COMMIT"}
        intent_path = self.root / RECEIPT_INTENT_JOURNAL_NAME
        journal_path = self.root / RECEIPT_JOURNAL_NAME
        journal_existed = journal_path.exists()
        journal_before = journal_path.stat().st_size if journal_existed else 0
        raw_attempted = False
        journal_attempted = False
        try:
            _append_line_fsync(intent_path, _canonical_line(begin))
            if not destination.exists():
                raw_attempted = True
                _durable_receipt_write(destination, raw, append=False)
            else:
                # Identical bytes already on disk (the collision check
                # above refused anything else): presence is not
                # durability, so re-sync the existing inode explicitly.
                _resync_existing_receipt_raw(destination)
            _fsync_dir(self.root)
            journal_attempted = True
            _append_line_fsync(journal_path, _canonical_line(entry))
            _fsync_dir(self.root)
            _append_line_fsync(intent_path, _canonical_line(commit))
        except BaseException:
            rollback_errors = []
            if journal_attempted:
                try:
                    if journal_existed:
                        with open(journal_path, "r+b") as fh:
                            fh.truncate(journal_before)
                            fh.flush()
                            os.fsync(fh.fileno())
                    elif journal_path.exists():
                        journal_path.unlink()
                    _fsync_dir(self.root)
                except OSError as exc:
                    rollback_errors.append(f"journal:{type(exc).__name__}")
            if raw_attempted:
                try:
                    if destination.exists():
                        destination.unlink()
                    _fsync_dir(self.root)
                except OSError as exc:
                    rollback_errors.append(f"raw:{type(exc).__name__}")
            try:
                abort = {"schema": RECEIPT_INTENT_SCHEMA,
                         "intent_id": intent_id, "state": "ABORT",
                         "reason": "APPEND_ROLLED_BACK"}
                _append_line_fsync(intent_path, _canonical_line(abort))
            except MLBSourceError as exc:
                rollback_errors.append(f"intent:{exc}")
            except OSError as exc:
                rollback_errors.append(f"intent:{type(exc).__name__}")
            if rollback_errors:
                raise MLBSourceError(
                    "RECEIPT_APPEND_ROLLBACK_FAILED:" + ",".join(rollback_errors))
            raise
        record = MLBSourceCaptureRecord(
            sequence=sequence, source_kind=source_kind, url=url,
            observed_at_utc=entry["observed_at_utc"], sha256=digest, path=str(destination),
            byte_length=len(raw), game_pk=game_pk,
            fetch_started_at_utc=entry["fetch_started_at_utc"], received_at_utc=entry["received_at_utc"],
            recorder_clock_assertion_utc=entry["recorder_clock_assertion_utc"], receipt_nonce=nonce,
            prev_record_sha256=entry["prev_record_sha256"], record_sha256=entry["record_sha256"],
        )
        self.records.append(record)
        self._used_receipts = used_receipts | {receipt_key}
        self._used_nonces = used_nonces | {nonce}
        self._prev_sha = entry["record_sha256"]
        self._sequence = sequence
        return record

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": "MLB_SAME_FETCH_PIT_SOURCE_CAPTURE_V1",
            "receipt_schema_version": 2,
            "receipt_journal": RECEIPT_JOURNAL_NAME,
            "receipt_chain_head_sha256": self._prev_sha,
            "receipt_time_semantics": "OBSERVED_EQUALS_TRUSTED_POST_READ_RECEIPT",
            "external_time_anchor": False,
            "capture_semantics": "SAME_RESPONSE_BYTES_CONSUMED_BY_MODEL",
            "promotion_authority": False,
            "retroactive_point_in_time_claim": False,
            "records": [asdict(record) for record in self.records],
        }


_ACTIVE_SOURCE_CAPTURE: ContextVar[MLBSourceCapture | None] = ContextVar(
    "sportsedge_mlb_source_capture", default=None
)


@contextmanager
def capture_mlb_source_bytes(
    root: str | Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Iterator[MLBSourceCapture]:
    """Capture exact MLB source bytes used inside this context, without refetching."""
    recorder = MLBSourceCapture(Path(root), clock=clock)
    token = _ACTIVE_SOURCE_CAPTURE.set(recorder)
    try:
        yield recorder
    finally:
        _ACTIVE_SOURCE_CAPTURE.reset(token)


def _get_json(url: str, opener: Callable = urlopen) -> dict[str, Any]:
    recorder = _ACTIVE_SOURCE_CAPTURE.get()
    started = _trusted_now()
    try:
        with opener(url, timeout=15) as r:
            raw = r.read()
        if not isinstance(raw, (bytes, bytearray)):
            raise MLBSourceError("MLB response body must be bytes")
        raw_bytes = bytes(raw)
        if recorder is not None:
            recorder.record(url=url, raw=raw_bytes, fetch_started_at=started, received_at=_trusted_now())
        return json.loads(raw_bytes.decode("utf-8"))
    except MLBSourceError:
        raise
    except Exception as exc:
        raise MLBSourceError(f"MLB fetch failed: {exc}") from exc


def _pitcher(team: dict[str, Any]) -> tuple[int | None, str | None]:
    p = team.get("probablePitcher") or {}
    return p.get("id"), p.get("fullName")


def parse_game_start(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MLBSourceError("schedule game missing gameDate")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBSourceError(f"invalid MLB gameDate: {value}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBSourceError("MLB gameDate must be timezone-aware")
    return dt.astimezone(timezone.utc)


def game_time_chicago(value: str | GameSnapshot) -> str:
    raw = value.game_date if isinstance(value, GameSnapshot) else value
    return parse_game_start(raw).astimezone(CHICAGO_TZ).isoformat()


def savant_preview_url(snapshot: GameSnapshot) -> str:
    """Return the canonical Baseball Savant Statcast Game Preview URL for a game."""
    if snapshot.official_date:
        try:
            game_day = datetime.fromisoformat(snapshot.official_date).date()
        except ValueError as exc:
            raise MLBSourceError(f"invalid MLB officialDate: {snapshot.official_date}") from exc
    else:
        game_day = parse_game_start(snapshot.game_date).astimezone(CHICAGO_TZ).date()
    return (
        f"{SAVANT_PREVIEW_BASE}?game_pk={snapshot.game_pk}"
        f"&game_date={game_day.strftime('%m/%d/%Y')}"
    )


def _optional_positive_int(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MLBSourceError(f"{name} must be a positive integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBSourceError(f"{name} must be a positive integer") from exc
    if out <= 0:
        raise MLBSourceError(f"{name} must be a positive integer")
    return out


def parse_schedule(payload: dict[str, Any], retrieved_at: datetime) -> list[GameSnapshot]:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise MLBSourceError("retrieved_at must be timezone-aware")
    out: list[GameSnapshot] = []
    seen_game_pks: set[int] = set()
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            if not all((game.get("gamePk"), away_team.get("id"), home_team.get("id"))):
                raise MLBSourceError("schedule game missing identity")
            game_pk = int(game["gamePk"])
            if game_pk in seen_game_pks:
                raise MLBSourceError(f"duplicate gamePk in schedule: {game_pk}")
            seen_game_pks.add(game_pk)
            game_start = parse_game_start(game.get("gameDate"))
            apid, apname = _pitcher(away)
            hpid, hpname = _pitcher(home)
            status_obj = game.get("status") or {}
            abstract_status = status_obj.get("abstractGameState")
            if abstract_status not in {"Preview", "Live", "Final"}:
                raise MLBSourceError("GAME_STATE_MISSING_OR_INVALID")
            game_type = game.get("gameType")
            if game_type is not None and (type(game_type) is not str or not game_type or len(game_type) > 2):
                raise MLBSourceError("GAME_TYPE_INVALID")
            detailed_status = status_obj.get("detailedState")
            if detailed_status is not None:
                detailed_status = str(detailed_status)
            game_number = _optional_positive_int("gameNumber", game.get("gameNumber"))
            double_header = game.get("doubleHeader")
            if double_header is not None:
                double_header = str(double_header)
                if double_header not in {"Y", "N", "S"}:
                    raise MLBSourceError("doubleHeader must be Y, N, S, or null")
            if double_header in {"Y", "S"} and game_number is None:
                raise MLBSourceError("doubleheader game missing gameNumber")
            venue_id = _optional_positive_int("venue.id", (game.get("venue") or {}).get("id"))
            official_date = game.get("officialDate") or date_block.get("date")
            if official_date is not None:
                official_date = str(official_date)
            out.append(GameSnapshot(
                game_pk, game_start.isoformat(), str(abstract_status),
                int(away_team["id"]), str(away_team.get("name", "")),
                int(home_team["id"]), str(home_team.get("name", "")),
                apid, apname, hpid, hpname,
                retrieved_at.astimezone(timezone.utc).isoformat(),
                game_number=game_number, double_header=double_header,
                venue_id=venue_id, official_date=official_date,
                detailed_status=detailed_status,
                game_type=game_type,
            ))
    out.sort(key=lambda g: (parse_game_start(g.game_date), g.game_pk))
    return out


def fetch_schedule(date_iso: str, opener: Callable = urlopen, now: datetime | None = None) -> list[GameSnapshot]:
    """retrieved_at is ALWAYS the post-fetch clock. A caller-supplied ``now`` is kept
    only as ``caller_asserted_at`` and must satisfy fetch_start <= now <= receipt + skew."""
    url = (
        f"{BASE}/api/v1/schedule?sportId=1&date={date_iso}"
        "&gameType=R,F,D,L,W,A,S,E&hydrate=probablePitcher,team"
    )
    fetch_started_at = _aware(_trusted_now(), "receipt clock")
    payload = _get_json(url, opener)
    retrieved_at = _aware(_trusted_now(), "receipt clock")
    if retrieved_at < fetch_started_at:
        raise MLBSourceError("RECEIPT_CLOCK_WENT_BACKWARDS")
    games = parse_schedule(payload, retrieved_at)
    if now is None:
        return games
    asserted = bound_caller_time(now, fetch_started_at=fetch_started_at, received_at=retrieved_at).isoformat()
    return [replace(g, caller_asserted_at=asserted) for g in games]


def parse_confirmed_lineup(boxscore: dict[str, Any], side: str) -> list[dict[str, Any]]:
    if side not in ("home", "away"):
        raise MLBSourceError("side must be home or away")
    team = ((boxscore.get("teams") or {}).get(side) or {})
    players = team.get("players") or {}
    lineup: list[dict[str, Any]] = []
    for player in players.values():
        order = player.get("battingOrder")
        person = player.get("person") or {}
        if order is None or int(order) <= 0:
            continue
        code = int(order)
        slot, sequence = divmod(code, 100)
        lineup.append({
            "player_id": person.get("id"),
            "name": person.get("fullName"),
            "batting_order_code": code,
            "slot": slot,
            "sequence": sequence,
            "substitution_evidence": sequence > 0,
        })
    lineup.sort(key=lambda x: (x["slot"], x["sequence"], x["player_id"] or 0))
    return lineup


def fetch_boxscore(game_pk: int, opener: Callable = urlopen) -> dict[str, Any]:
    return _get_json(f"{BASE}/api/v1/game/{int(game_pk)}/boxscore", opener)


def game_identity(snapshot: GameSnapshot):
    return canonical_game_identity(
        mlb_game_pk=snapshot.game_pk,
        scheduled_start=snapshot.game_date,
        away_team_id=snapshot.away_id,
        home_team_id=snapshot.home_id,
        game_number=snapshot.game_number,
    )


def snapshot_to_dict(snapshot: GameSnapshot) -> dict[str, Any]:
    out = asdict(snapshot)
    identity = game_identity(snapshot)
    out["game_time_utc"] = parse_game_start(snapshot.game_date).isoformat()
    out["game_time_ct"] = game_time_chicago(snapshot)
    out["sportsedge_game_id"] = identity.sportsedge_game_id
    out["mlb_game_pk"] = identity.mlb_game_pk
    out["savant_preview_url"] = savant_preview_url(snapshot)
    return out
