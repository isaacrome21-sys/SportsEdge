"""Raw-receipt-first preservation for strict MLB forward captures.

The strict forward-capture pipeline (``scripts/capture_strict_mlb_record.py``)
can only archive an evaluator record after two live dependencies succeed:
the frozen production pricer and the Elo comparison floor (which fetches
the full-season StatsAPI schedule). On October 12, 2026 the Elo leg's
fetch was truncated by an 8 MB response cap in the outcomes fetcher,
the CLI refused with ``BACKTEST_SOURCE_UNAVAILABLE``, and **no evaluator
record was archived** — the timestamped two-sided quotes survived only
because an operator had separately filed a raw-evidence JSON by hand.

This module is the safeguard that makes that preservation automatic and
structural rather than manual. The receipt layer sits *in front of* the
capture pipeline:

1. **Receipt first.** Before any model or Elo dependency runs, the
   capture input (schema ``SPORTSEDGE_STRICT_CAPTURE_INPUT_V1``) is
   preserved verbatim in an append-only receipts area with status
   ``PENDING_EVALUATION``. The quotes — the perishable evidence — are
   on disk, immutably, before anything can fail.
2. **Outcome second.** After the pipeline runs, its result is appended
   to a separate append-only outcomes log: ``ARCHIVED`` with the record
   path, or ``REFUSED`` with the verbatim refusal reason (or the failure
   class when the pipeline crashed without producing a verdict). A
   fourth status, ``INDETERMINATE``, is written only by reconciliation
   after an interruption when no archived record is found: the record's
   absence is established, but the original run's outcome is not
   knowable, so it is never recorded as an established refusal.

Honesty contract:

- A receipt is **evidence preservation, never an evaluation**. A
  ``REFUSED`` receipt means the quotes were preserved and *no evaluator
  record exists*; an ``INDETERMINATE`` receipt means the same about the
  record, with the original run's outcome unknown rather than refused.
  Nothing in this module prices anything, touches the network, or
  writes into ``captures/`` — the evaluator-facing archive format and
  behavior are unchanged.
- Receipt files are **write-once**: created with ``open(..., "x")`` and
  never mutated afterwards. The ``status`` field inside a receipt file
  is its creation-time status (``PENDING_EVALUATION``) forever; the
  *effective* status is derived from the outcomes log by the reader
  functions here, never by editing the receipt.
- Receipt ids are **deterministic from content**: the SHA-256 of the
  canonical serialization of the parsed input. Re-submitting the same
  capture input is detected (the receipt already exists) and never
  duplicated; different quote content yields a different receipt.
- The outcomes log is **append-only** (same discipline as
  ``settlements.jsonl``). If more than one outcome line ever names a
  receipt, the latest line is the current state; every line is kept.

Layout (inside the existing archive directory)::

    archive/strict-forward-capture/
        captures/…            (unchanged; evaluator records)
        settlements.jsonl     (unchanged)
        receipts/
            rcpt_<sha256>.json   one write-once receipt per input
            outcomes.jsonl       per pipeline outcome: an entry line
                                 plus its ACK line (two-phase commit —
                                 the entry counts only with its ACK)
            snapshots/
                rcpt_<sha256>.json   byte-identical immutable copy of the
                                     receipted input; the pipeline runs
                                     against THIS file, never the
                                     operator's mutable original
            .receipts.lock       inter-process lock file (fcntl.flock):
                                     held exclusively by writers across
                                     receipt creation, snapshot creation,
                                     and the whole outcome-append
                                     protocol, and shared (LOCK_SH) by
                                     journal readers (round 4)

Audit #2086 repairs (owner integration audit, Oct 12 2026):

- **Input integrity.** The pipeline consumes the content-addressed
  snapshot, whose SHA-256 is re-verified against the receipt's input
  hash immediately before the run. A mutation of the operator's file
  after receipting cannot change what gets priced.
- **No false success.** An ``ARCHIVED`` outcome is appended only after
  the archived record is located in ``captures/`` and verified: the
  file exists, its stored provenance input-hash equals the receipt's
  input hash, and its game/market identity matches the input.
- **Crash recovery.** A receipt still ``PENDING_EVALUATION`` (a prior
  run died between receipt and outcome) is never auto-replayed:
  resubmission reports ``RECONCILIATION_REQUIRED``; an explicit
  reconciliation inspects the archive — a verified record becomes
  ``ARCHIVED``; no record becomes ``INDETERMINATE`` (absence is the
  only established fact; the interrupted run's outcome is unknown,
  not refused). All receipt/snapshot/outcome writes are fsync'd
  (file and parent directory) and outcome appends run under the
  inter-process lock, so concurrent writers cannot interleave lines.
- **Journal integrity (round 2).** An outcome append that fails or
  writes short is rolled back to the journal's pre-append byte
  offset under the same lock — a failed write never leaves a
  partial line behind — and the reader reports a malformed line
  distinctly (ReceiptError naming the line) instead of parsing or
  choking on it silently.
- **Journal crash recovery (round 3).** The round-2 rollback is an
  exception path: it cannot run when the writer process is killed
  mid-append (the owner reproduced this — SIGKILL leaves the
  fragment, and no cleanup code executes). Newline termination
  alone is not a commit boundary either: a process can die after
  writing the newline but before the outcome is durable. So an
  append is **two-phase**: entry line → fsync → a separate ACK
  line bound to the entry line's SHA-256 → fsync. An entry is
  **committed** only with its ACK present. Recovery then has
  exactly three cases, all preserving committed entries:
  (1) *exception rollback* — an in-process write failure truncates
  back to the append's starting offset, leaving nothing behind;
  (2) *torn tail* — a partial line (no terminating newline) after
  the last complete line is uncommitted bytes: the next append
  truncates it under the lock (recording the recovered byte count
  on the outcome it appends), and the reader returns all
  committed entries while reporting the tail's size
  (``torn_tail_bytes``) instead of failing the read;
  (3) *complete-but-unacknowledged* — a complete entry line whose
  ACK never landed is preserved and reported, never counted as
  an outcome and never silently dropped: the affected receipt
  resolves to ``INDETERMINATE`` and enters reconciliation, which
  promotes the entry only by verifying ground truth (an
  ``ARCHIVED`` entry's record verifies on disk → its ACK is
  appended, plus a confirming outcome) and otherwise supersedes
  it with a committed ``INDETERMINATE`` outcome — a
  ``REFUSED``-type unacknowledged entry is likewise superseded,
  since a refusal whose ACK never landed was never durably
  established. The malformed-line error is reserved for
  corruption *inside* the committed region — a line that fails
  to parse while a parseable complete line follows it, or an
  ACK bound to no entry — which is real damage, not an
  interrupted write, and is never silently recovered away.
- **Coordinated reader locking (round 4).** The round-3 commit
  model still let a reader observe an outcome that never
  committed: ``read_outcomes`` scanned the journal *without*
  the writer's lock, so during an append that failed at the
  ACK fsync (and was then rolled back), a concurrent reader
  could see the entry line and its already-written ACK line in
  the file and report the outcome as committed in the window
  before the rollback truncation landed (owner's reproduction:
  committed = 1 in that window; the append then returned
  ``OUTCOME_WRITE_FAILED`` and committed = 0). The fix is
  coordination, not another commit layer. The writer holds the
  exclusive receipts lock across the ENTIRE append protocol —
  torn-tail recovery truncation, entry write + fsync, ACK write
  + fsync, and any rollback truncation on failure — and every
  journal reader (``read_outcomes``,
  ``unacknowledged_outcomes``, ``outcome_journal_status``,
  ``latest_outcomes``, ``receipt_status``, ``list_receipts``,
  ``read_receipts``) acquires the SAME lock shared
  (``LOCK_SH``) for its scan. **Durability contract (as amended
  by round 5, below): a locked reader observes only
  durable-or-absent states** — an outcome a reader reports
  either had its ACK fsynced under the writer's lock hold, or
  has had the durability of its surviving bytes established by
  the recovery fsync the scan itself performs under the lock
  before exposing it; an outcome whose durability can be
  established neither way never appears in any reader snapshot;
  the intermediate states of an append (entry written but ACK
  not yet durable; ACK visible but a rollback still pending)
  are unobservable, because the writer does not release the
  lock until the append has committed or been rolled back.
  Code paths that already hold the lock (reconciliation) read
  through ``*_unlocked`` internal helpers and never re-acquire
  it — flock is not re-entrant across separate opens, so
  re-acquiring would self-deadlock.
- **Recovery durability (round 5).** Coordinated locking
  closed the rollback-visibility window but left the
  **post-ACK crash window** (owner's independent reproduction):
  a writer SIGKILLed *after* its ACK line's write but *before*
  the ACK's fsync leaves the complete entry+ACK unit in the
  page cache; process death releases the lock, and the next
  reader — locking correctly — reported the entry as committed,
  although no fsync ever established its durability and
  recovery performed zero fsync calls before exposing it.
  Page-cache survival is not durability. So every scan that
  would expose committed entries first runs a named
  **recovery-durability step** under the lock it already holds
  (``_establish_journal_durability_locked``): fsync the journal
  file and its containing directory, making every surviving
  byte durable *as of recovery*. That is sound because appends
  are serialized under the exclusive lock and the protocol is
  entry write → fsync → ACK write → fsync in program order: a
  later ACK line can exist only if its writer first completed
  the phase-1 fsync that flushed the whole file prefix, so
  **at most the trailing ACK-backed unit** can lack a completed
  writer-side fsync — and that unit's completeness is
  independently verifiable through the ACK's SHA-256 binding
  to the entry line's exact bytes. If the recovery fsync
  **fails**, durability of that trailing unit — and only it —
  is unproven: it is demoted to the unacknowledged state
  (preserved, reported via ``unacknowledged_outcomes``, its
  receipt resolving to INDETERMINATE and entering
  reconciliation under the round-3 rules) and never reported
  as committed; earlier units remain exposable because their
  durability never depended on the recovery fsync. The
  demotion is a per-scan verdict, not an edit: the journal
  bytes are untouched, and a later scan whose recovery fsync
  succeeds exposes the same unit as committed. No additional
  ACK layer is added. **When an outcome becomes readable —
  the exact protocol point:** only when a scan holding the
  receipts lock (shared or exclusive) has parsed the outcome's
  complete entry line *and* the bound ACK line, AND that unit's
  durability is established at that moment — either (i) its
  writer's ACK fsync completed under the writer's exclusive
  hold before the lock was released, or (ii) this scan's
  recovery fsync (journal file + containing directory) has
  completed over the surviving bytes. Not before either
  point; if neither can be established, the unit is reported
  unacknowledged instead of readable.
- **Elo schedule provenance persisted (round 3).** The archived
  record's format is frozen and cannot carry the v1 pipeline's
  ``elo_schedule_provenance`` object (the point-in-time evidence
  for the Elo leg's training schedule), so the wrapper persists
  it verbatim on the ``ARCHIVED`` outcome entry. An ``ARCHIVED``
  outcome produced without one (e.g. by reconciliation, which runs
  no pipeline) records ``elo_schedule_provenance: null`` with a
  ``provenance_note`` — never reconstructed values.
- **Fail-closed identity (round 2).** Archived-record verification
  requires every identity element — provenance input-hash,
  fixture_id, market, selection, line — present and matching on
  BOTH sides: an expected element the caller could not derive
  fails verification before any candidate is read, and a record
  missing any element fails naming that element. A wrong-game
  record can no longer pass because an identity field was absent.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path

RECEIPT_SCHEMA = "MLB_STRICT_CAPTURE_RECEIPT_V1"
OUTCOME_SCHEMA = "MLB_STRICT_CAPTURE_RECEIPT_OUTCOME_V1"
RECEIPTS_DIRNAME = "receipts"
OUTCOMES_FILENAME = "outcomes.jsonl"
SNAPSHOTS_DIRNAME = "snapshots"
LOCK_FILENAME = ".receipts.lock"
RECEIPT_ID_PREFIX = "rcpt_"

STATUS_PENDING = "PENDING_EVALUATION"
STATUS_ARCHIVED = "ARCHIVED"
STATUS_REFUSED = "REFUSED"
STATUS_INDETERMINATE = "INDETERMINATE"


class ReceiptError(ValueError):
    pass


def _iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fsync_dir(path):
    """fsync a directory so a creation/rename inside it is durable."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _receipts_flock(archive_dir, flags):
    """Hold the receipts lock file with ``flags`` (flock).

    Each call opens its own file description; callers must not nest
    holds (flock is not re-entrant across separate opens). Code that
    already holds the lock reads through the module's ``*_unlocked``
    helpers instead of re-acquiring it.
    """
    directory = receipts_dir(archive_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(directory / LOCK_FILENAME),
                 os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, flags)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextlib.contextmanager
def receipts_lock(archive_dir):
    """Exclusive inter-process lock over the receipts area (flock).

    Guards receipt creation, snapshot creation, outcome appends, and
    reconciliation so concurrent wrapper processes cannot interleave
    partial JSONL lines or race a write-once creation. An outcome
    append holds this lock across the ENTIRE append protocol —
    torn-tail recovery truncation, entry write + fsync, ACK write +
    fsync, and any rollback truncation on failure — so a reader
    holding the shared lock (``_receipts_read_lock``) can only ever
    observe a pre-append state or a post-commit / post-rollback
    state, never an intermediate one (audit #2086, round 4).
    """
    with _receipts_flock(archive_dir, fcntl.LOCK_EX):
        yield


@contextlib.contextmanager
def _receipts_read_lock(archive_dir):
    """Shared lock for journal readers (audit #2086, round 4).

    The same lock file the writer holds exclusively, taken shared
    (``LOCK_SH``): readers may scan concurrently with each other
    but never while a writer's append protocol is in flight, so
    every reader snapshot is a durable-or-absent state — an
    outcome it reports either had its ACK fsynced under the
    writer's lock hold, or has just had its durability
    established by the scan's recovery-durability fsync,
    performed under this same lock hold before any committed
    entry is exposed (round 5). A unit whose durability can be
    established neither way is reported unacknowledged, never
    committed.
    """
    with _receipts_flock(archive_dir, fcntl.LOCK_SH):
        yield


def canonical_input_sha256(input_obj):
    """SHA-256 of the canonical serialization of a parsed capture input.

    Canonical = JSON with sorted keys and tight separators, so two
    submissions of the same capture input map to the same digest even
    if the files' whitespace or key order differ.
    """
    canonical = json.dumps(input_obj, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def receipt_id_for(input_obj):
    """Deterministic receipt id for a parsed capture input."""
    return RECEIPT_ID_PREFIX + canonical_input_sha256(input_obj)


def receipts_dir(archive_dir):
    return Path(archive_dir) / RECEIPTS_DIRNAME


def outcomes_path(archive_dir):
    return receipts_dir(archive_dir) / OUTCOMES_FILENAME


def receipt_path(archive_dir, receipt_id):
    return receipts_dir(archive_dir) / (str(receipt_id) + ".json")


def build_receipt(input_bytes, input_obj, *, now=None):
    """Assemble the receipt dict for one capture input.

    ``input_bytes`` are the input file's raw bytes (their SHA-256 is the
    file receipt, matching the capture CLI's provenance hash);
    ``input_obj`` is the same file parsed. The input is embedded
    verbatim — parsed, so key order may be normalized on write, but no
    field is added, dropped, or altered.
    """
    if not isinstance(input_obj, dict):
        raise ReceiptError("INPUT_NOT_JSON_OBJECT")
    created = now or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ReceiptError("RECEIPT_CLOCK_NOT_UTC_AWARE")
    rid = receipt_id_for(input_obj)
    return {
        "receipt_schema": RECEIPT_SCHEMA,
        "receipt_id": rid,
        # The immutable snapshot of the receipted bytes, relative to
        # the receipts directory. The pipeline runs against the
        # snapshot, never the operator's original file (audit #2086).
        "input_snapshot_relpath": SNAPSHOTS_DIRNAME + "/" + rid + ".json",
        # Creation-time status. Write-once: this never changes in the
        # file; the effective status comes from the outcomes log.
        "status": STATUS_PENDING,
        "receipt_created_at_utc": _iso(created),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "input_canonical_sha256": canonical_input_sha256(input_obj),
        # The quote timestamps EXACTLY as supplied in the input — never
        # re-stamped, never reinterpreted. The verbatim input below is
        # authoritative; these are lifted out only for auditor scanning.
        "quote_timestamps_as_supplied": {
            "kickoff_utc": input_obj.get("kickoff_utc"),
            "selection_captured_at_utc":
                input_obj.get("selection_captured_at_utc"),
            "opposite_captured_at_utc":
                input_obj.get("opposite_captured_at_utc"),
        },
        "input": input_obj,
    }


def write_receipt(archive_dir, input_bytes, input_obj, *, now=None):
    """Write one receipt write-once; detect (never duplicate) a resubmit.

    Returns ``(path, receipt, duplicate)``. ``duplicate`` is True when a
    receipt for this exact input content already existed — the existing
    file is left byte-identical and returned as-is.
    """
    receipt = build_receipt(input_bytes, input_obj, now=now)
    directory = receipts_dir(archive_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (receipt["receipt_id"] + ".json")
    with receipts_lock(archive_dir):
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(receipt, indent=2, sort_keys=True)
                             + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_dir(directory)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("input_canonical_sha256") != \
                    receipt["input_canonical_sha256"]:
                # Same id, different content: a hash collision or a
                # corrupt receipts area. Refuse rather than bless
                # either copy.
                raise ReceiptError("RECEIPT_ID_COLLISION:" + str(path))
            return path, existing, True
    return path, receipt, False


def snapshot_path(archive_dir, receipt_id):
    return receipts_dir(archive_dir) / SNAPSHOTS_DIRNAME / \
        (str(receipt_id) + ".json")


def ensure_input_snapshot(archive_dir, receipt_id, input_bytes,
                          expected_sha256):
    """Create (write-once) or verify the immutable input snapshot.

    The snapshot is the byte-identical copy of the receipted input
    that the pipeline will consume. If a snapshot already exists for
    this receipt, it is authoritative: its SHA-256 must equal
    ``expected_sha256`` (the receipt's input hash) or ReceiptError is
    raised — later submissions never overwrite it with their own
    bytes. If none exists, ``input_bytes`` are written, but only when
    their hash equals ``expected_sha256`` (true for the submission
    that created the receipt and for byte-identical resubmissions).

    Returns ``(path, created)``.
    """
    path = snapshot_path(archive_dir, receipt_id)
    with receipts_lock(archive_dir):
        if path.is_file():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected_sha256:
                raise ReceiptError(
                    "INPUT_SNAPSHOT_HASH_MISMATCH:" + str(path))
            return path, False
        if hashlib.sha256(input_bytes).hexdigest() != expected_sha256:
            raise ReceiptError(
                "INPUT_SNAPSHOT_BYTES_MISMATCH: submitted bytes do not "
                "match the receipted input hash; the original receipted "
                "bytes are required to run this receipt")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:
            handle.write(input_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
    return path, True


def verify_snapshot(archive_dir, receipt_id, expected_sha256):
    """Re-read and re-hash the snapshot immediately before a run.

    Returns ``(True, actual_sha256)`` or ``(False, actual_or_None)``.
    """
    path = snapshot_path(archive_dir, receipt_id)
    if not path.is_file():
        return False, None
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return actual == expected_sha256, actual


def _any_parseable_line(raw):
    """True when any newline-terminated line in ``raw`` parses as JSON."""
    for segment in raw.split(b"\n")[:-1]:
        if segment.strip():
            try:
                json.loads(segment.decode("utf-8"))
            except ValueError:
                continue
            return True
    return False


def _is_ack_line(parsed):
    """An ACK line is exactly ``{"ack": "<sha256 hex>"}`` — one key."""
    return (isinstance(parsed, dict) and set(parsed) == {"ack"}
            and isinstance(parsed["ack"], str))


def _scan_journal_bytes(raw, path=None):
    """Scan raw outcomes-journal bytes under the ACK commit model.

    The journal is a sequence of complete (newline-terminated)
    lines of two kinds: outcome **entry** lines and **ACK** lines
    (``{"ack": "<sha256 of an entry line's bytes>"}``). An entry is
    **committed** only when an ACK line bound to its exact bytes
    appears after it; the writer fsyncs the entry line, then the
    ACK line, then fsyncs again, so commitment means the outcome
    was durably acknowledged, not merely written. A complete entry
    line with no ACK is **unacknowledged**: it is preserved and
    reported (never truncated, never counted as an outcome),
    because a writer killed between the entry write and the ACK
    leaves exactly that state and its content may be true — only
    its durability is unestablished.

    Returns ``(records, complete_bytes, torn_tail_bytes)``:
    ``records`` is one dict per entry line, in journal order —
    ``{"entry", "sha256", "committed"}`` — and ``complete_bytes``
    is the offset just past the last complete line. Bytes past it
    are a **torn tail** (an unterminated partial line, or bytes
    from the first unparseable line onward when nothing parseable
    follows): uncommitted by definition, truncated away by the
    next append, never parsed as an outcome, never fatal to a
    read.

    Raises ReceiptError (``OUTCOME_JOURNAL_MALFORMED_LINE:<n>``)
    only for corruption *inside* the committed region: a line that
    fails to parse while a parseable complete line follows it, or
    an ACK line bound to no entry anywhere before it. That is
    real damage an auditor must see, not an interrupted write, and
    recovery never silently truncates it away.
    """
    records = []
    by_sha = {}
    pos = 0
    lineno = 0
    size = len(raw)
    while pos < size:
        nl = raw.find(b"\n", pos)
        if nl < 0:
            break  # unterminated remainder -> torn tail
        lineno += 1
        segment = raw[pos:nl]
        if segment.strip():
            try:
                parsed = json.loads(segment.decode("utf-8"))
            except ValueError:
                if _any_parseable_line(raw[nl + 1:]):
                    raise ReceiptError(
                        "OUTCOME_JOURNAL_MALFORMED_LINE:%d:%s"
                        % (lineno, path))
                break  # unparseable from here on -> torn tail
            if _is_ack_line(parsed):
                target = None
                for record in by_sha.get(parsed["ack"], []):
                    if not record["committed"]:
                        target = record
                        break
                if target is not None:
                    target["committed"] = True
                elif parsed["ack"] not in by_sha:
                    raise ReceiptError(
                        "OUTCOME_JOURNAL_MALFORMED_LINE:%d:%s"
                        % (lineno, path))
                # A repeat ACK for an already-committed entry is a
                # benign no-op (promotion may be retried after a
                # crash that followed the ACK append itself).
            else:
                record = {
                    "entry": parsed,
                    "sha256": hashlib.sha256(segment).hexdigest(),
                    "committed": False,
                }
                records.append(record)
                by_sha.setdefault(record["sha256"], []).append(record)
        pos = nl + 1
    return records, pos, size - pos


def _journal_recovery_locked(fd, path):
    """Scan the open journal and truncate any torn tail.

    Caller must hold receipts_lock(). Returns ``(start, recovered)``:
    the offset the next write begins at (just past the last
    complete line) and how many uncommitted tail bytes were
    removed. Committed AND unacknowledged complete lines are never
    truncated — only the fragment after them. Corruption inside
    the committed region raises from the scan before any write.
    """
    size = os.fstat(fd).st_size
    raw = os.pread(fd, size, 0) if size else b""
    _records, complete_bytes, tail_bytes = _scan_journal_bytes(
        raw, path)
    if tail_bytes:
        os.ftruncate(fd, complete_bytes)
        os.fsync(fd)
    return complete_bytes, tail_bytes


def _write_bytes(fd, path, data):
    """Write all of ``data`` at the fd's current offset.

    Tolerates short os.write counts; raises on any failure.
    Durability is the caller's job (fsync between phases).
    """
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise ReceiptError("OUTCOME_WRITE_PARTIAL:" + str(path))
        view = view[written:]


def _rollback_to(fd, path, start, exc):
    """Truncate back to ``start`` after a failed append, then raise.

    An in-process failed write leaves nothing behind (audit
    #2086, round 2). Process death is NOT covered here and cannot
    be: it is what torn-tail recovery and the unacknowledged-entry
    state exist for (round 3). Always raises.
    """
    try:
        os.ftruncate(fd, start)
        os.fsync(fd)
    except OSError as rollback_exc:
        raise ReceiptError(
            "OUTCOME_WRITE_ROLLBACK_FAILED:" + str(path)
        ) from rollback_exc
    if isinstance(exc, ReceiptError):
        raise exc
    raise ReceiptError("OUTCOME_WRITE_FAILED:" + str(path)) from exc


def _append_outcome_locked(archive_dir, outcome):
    """Append one outcome line + its ACK. Caller holds receipts_lock().

    Two-phase commit (audit #2086, round 3): the entry line is
    written and fsync'd, then a separate ACK line bound to the
    entry line's SHA-256, then fsync'd again. The entry is
    committed only once its ACK is durable — a writer killed
    after the entry write but before the ACK leaves a complete-
    but-unacknowledged entry, a distinct recoverable state the
    reader reports rather than a torn tail (see
    ``_scan_journal_bytes``). Before writing, any torn tail left
    by a previously killed writer is truncated (recovery, under
    the same lock) and the recovered byte count is recorded on
    the entry being appended; committed and unacknowledged
    complete lines are never truncated.
    """
    if outcome.get("outcome") not in (STATUS_ARCHIVED, STATUS_REFUSED,
                                       STATUS_INDETERMINATE):
        raise ReceiptError("OUTCOME_INVALID:" + str(outcome.get("outcome")))
    if not outcome.get("receipt_id"):
        raise ReceiptError("OUTCOME_RECEIPT_ID_MISSING")
    entry = dict(outcome)
    entry.setdefault("outcome_schema", OUTCOME_SCHEMA)
    entry.setdefault("recorded_at_utc",
                     _iso(datetime.now(timezone.utc)))
    path = outcomes_path(archive_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        start, recovered = _journal_recovery_locked(fd, path)
        if recovered:
            entry.setdefault("journal_recovered_torn_bytes", recovered)
        entry_line = json.dumps(entry, sort_keys=True).encode("utf-8")
        ack_line = json.dumps(
            {"ack": hashlib.sha256(entry_line).hexdigest()},
            sort_keys=True).encode("utf-8")
        # Phase 1: the entry line, fsync'd. Phase 2: its ACK line,
        # fsync'd. Only the second fsync makes the entry
        # committed. An in-process failure anywhere rolls the
        # whole append back to ``start``; a process killed between
        # the phases runs no rollback and leaves the entry
        # complete-but-unacknowledged — a distinct, recoverable
        # state, by design.
        try:
            os.lseek(fd, start, os.SEEK_SET)
            _write_bytes(fd, path, entry_line + b"\n")
            os.fsync(fd)
            _write_bytes(fd, path, ack_line + b"\n")
            os.fsync(fd)
        except BaseException as exc:
            _rollback_to(fd, path, start, exc)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)
    return path


def _append_ack_locked(archive_dir, entry_sha256):
    """Append an ACK line for an existing unacknowledged entry.

    Caller must hold receipts_lock(). Used only by reconciliation
    promotion: ground truth has been verified for the entry the
    ACK binds to, so acknowledging it after the fact is an
    established act, not a guess. Performs the same torn-tail
    recovery as an outcome append and returns the recovered byte
    count so the caller can record it on the confirming outcome.
    """
    path = outcomes_path(archive_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        start, recovered = _journal_recovery_locked(fd, path)
        ack_line = json.dumps({"ack": entry_sha256},
                              sort_keys=True).encode("utf-8")
        try:
            os.lseek(fd, start, os.SEEK_SET)
            _write_bytes(fd, path, ack_line + b"\n")
            os.fsync(fd)
        except BaseException as exc:
            _rollback_to(fd, path, start, exc)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)
    return recovered


def append_outcome(archive_dir, outcome):
    """Append one outcome (entry line + ACK) to the outcomes log.

    The append runs under the inter-process receipts lock, held
    EXCLUSIVELY across the entire append protocol — torn-tail
    recovery, the entry write + fsync, the ACK write + fsync, and
    any rollback truncation on failure — and is two-phase, so the
    entry is committed only once the ACK is durable (see
    ``_append_outcome_locked``). Before writing, a torn tail left
    by a previously killed writer is truncated away (recovery);
    committed and unacknowledged complete lines are never
    truncated. An in-process failure rolls the append back to its
    starting offset *before the lock is released*, so no reader
    can observe the intermediate state (audit #2086, round 4:
    readers take the same lock shared and see only
    durable-or-absent states).
    """
    with receipts_lock(archive_dir):
        return _append_outcome_locked(archive_dir, outcome)


def _read_receipts_unlocked(archive_dir):
    """Every receipt file, directory order. Caller holds the lock.

    Receipt files are write-once, but they are created under the
    exclusive lock; reading them under the shared lock (round 4)
    means a reader never globs a receipt whose creation write is
    still in flight.
    """
    directory = receipts_dir(archive_dir)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        out.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def read_receipts(archive_dir):
    """Every receipt file, directory order, read under the shared
    receipts lock (audit #2086, round 4)."""
    if not receipts_dir(archive_dir).is_dir():
        return []
    with _receipts_read_lock(archive_dir):
        return _read_receipts_unlocked(archive_dir)


# Recovery-durability memo (audit #2086, round 5): journal path
# -> (inode, size, mtime_ns, sha256) of the exact journal bytes a
# scan's recovery-durability step has fsynced successfully in
# THIS process. Durability, once established for given bytes,
# does not expire while the file is unchanged, so a later scan
# of identical bytes need not fsync again before exposing them;
# any write to the journal changes the hash (and the size or
# mtime), misses the memo, and re-runs the step. A failed step
# never writes a memo entry. The memo is process-local by
# design: a new process has established nothing and fsyncs for
# itself. One entry per journal path keeps it bounded.
_JOURNAL_DURABILITY_ESTABLISHED = {}


def _establish_journal_durability_locked(archive_dir, path):
    """Recovery-durability step (audit #2086, round 5).

    Caller holds the receipts lock — shared for readers,
    exclusive for writers / reconciliation — and has scanned a
    journal containing at least one ACK-backed (committed-looking)
    unit. fsync the journal file and its containing directory,
    making every surviving byte durable *as of this recovery*.
    Returns True when durability is established, False when an
    fsync failed and durability is therefore unproven.

    Why this step exists: an ACK line's presence in the page
    cache does not prove its writer's fsync ever completed. A
    writer SIGKILLed after the ACK ``write()`` but before the
    ACK fsync leaves a complete, ACK-backed unit that is
    byte-identical to a durable commit (the round-3 scan marks
    it committed on sight — its *completeness* is genuine,
    proven by the ACK's SHA-256 binding to the entry line's
    bytes; only its *durability* is unestablished). No reader
    may expose such a unit as committed until a recovery fsync
    under the lock has made the surviving bytes durable.

    Why the directory is fsync'd too: a writer killed inside
    its first append may have created the journal file
    (``O_CREAT``) and written a complete unit without reaching
    the append's trailing ``_fsync_dir``, so the file's
    directory entry — its very existence — is exactly as
    unproven as its contents. Establishing the durability of
    the surviving bytes includes the file that carries them.
    Failure of either fsync means durability is unestablished.

    Why one recovery fsync covers the whole journal, and why
    at most the trailing ACK-backed unit is ever in doubt:
    appends are serialized under the exclusive lock, and the
    append protocol is entry write → fsync → ACK write → fsync
    in program order within one process. A later ACK line can
    therefore exist only if its writer first completed the
    phase-1 fsync — which flushes the entire file prefix,
    including every earlier unit. So every ACK-backed unit
    except possibly the last one is durable independent of
    this step; only the trailing ACK-backed unit can lack a
    completed writer-side fsync, and it is precisely that unit
    this fsync now makes durable.
    """
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(path.parent)
    except OSError:
        return False
    return True


def _scan_journal_unlocked(archive_dir):
    """Scan the outcomes journal. Caller holds the receipts lock —
    shared for readers, exclusive for writers / reconciliation.

    Returns ``(records, complete_bytes, torn_tail_bytes)`` (see
    ``_scan_journal_bytes``), or ``None`` when no journal exists.
    This is the single scan every journal reader derives from, so
    all readers share one definition of the journal's state; the
    lock hold is what makes that state a durable-or-absent
    snapshot rather than a mid-append glimpse (round 4).

    Recovery durability (round 5): before any ACK-backed unit
    is exposed through this scan, the recovery-durability step
    (``_establish_journal_durability_locked``) fsyncs the
    journal and its directory under the caller's lock hold.
    The step runs at most once per distinct journal content
    per process: a scan whose bytes match this process's
    durability memo (``_JOURNAL_DURABILITY_ESTABLISHED``) has
    already had exactly those bytes made durable by a
    completed recovery fsync, and durability does not expire
    while the file is unchanged — any append, truncation, or
    rollback changes the bytes and re-runs the step. If the
    step's fsync fails, durability of the trailing ACK-backed
    unit — the only unit that can lack a completed writer-side
    fsync; see the step's docstring — is unproven, so that unit
    (and only it) is demoted in the returned records to
    unacknowledged (marked ``durability_unestablished``):
    preserved in the journal, reported through the
    unacknowledged path, its receipt resolving to INDETERMINATE
    under the round-3 rules, never exposed as committed.
    Earlier units remain exposable: their durability was
    established by their own writers' completed protocols (and
    by later writers' phase-1 fsyncs), not by this step. The
    demotion is a per-scan verdict — the scan writes nothing —
    so a later scan whose recovery fsync succeeds exposes the
    same surviving unit as committed. The append path needs no
    separate step: it exposes nothing, and its own phase fsyncs
    establish the durability of all prior surviving bytes
    before its unit can commit.
    """
    path = outcomes_path(archive_dir)
    if not path.is_file():
        return None
    raw = path.read_bytes()
    records, complete, tail = _scan_journal_bytes(raw, path)
    if any(record["committed"] for record in records):
        stat = path.stat()
        state = (stat.st_ino, stat.st_size, stat.st_mtime_ns,
                 hashlib.sha256(raw).hexdigest())
        if _JOURNAL_DURABILITY_ESTABLISHED.get(str(path)) != state:
            if _establish_journal_durability_locked(
                    archive_dir, path):
                _JOURNAL_DURABILITY_ESTABLISHED[str(path)] = state
            else:
                for record in reversed(records):
                    if record["committed"]:
                        record["committed"] = False
                        record["durability_unestablished"] = True
                        break
    return records, complete, tail


def _committed_entries_unlocked(archive_dir):
    """Committed journal entries, in order. Caller holds the lock."""
    scan = _scan_journal_unlocked(archive_dir)
    if scan is None:
        return []
    records, _complete, _tail = scan
    return [record["entry"] for record in records
            if record["committed"]]


def _unacknowledged_unlocked(archive_dir):
    """Unacknowledged journal entries. Caller holds the lock."""
    scan = _scan_journal_unlocked(archive_dir)
    if scan is None:
        return []
    records, _complete, _tail = scan
    return [{"entry": record["entry"], "sha256": record["sha256"]}
            for record in records if not record["committed"]]


def _journal_status_unlocked(archive_dir):
    """Journal health counts. Caller holds the lock."""
    path = outcomes_path(archive_dir)
    scan = _scan_journal_unlocked(archive_dir)
    if scan is None:
        return {"journal_path": str(path), "entry_count": 0,
                "unacknowledged_entries": 0, "complete_bytes": 0,
                "torn_tail_bytes": 0}
    records, complete, tail = scan
    return {"journal_path": str(path),
            "entry_count": sum(1 for r in records if r["committed"]),
            "unacknowledged_entries": sum(
                1 for r in records if not r["committed"]),
            "complete_bytes": complete,
            "torn_tail_bytes": tail}


def _latest_outcomes_unlocked(archive_dir):
    """Map receipt_id -> its latest committed outcome entry
    (append order wins). Caller holds the lock."""
    latest = {}
    for entry in _committed_entries_unlocked(archive_dir):
        rid = entry.get("receipt_id")
        if rid:
            latest[rid] = entry
    return latest


def read_outcomes(archive_dir):
    """Parse the outcomes journal's COMMITTED entries, in order.

    An entry is committed only when its ACK line is present (see
    ``_scan_journal_bytes``) AND the unit's durability is
    established — by its writer's completed fsyncs, or by the
    scan's recovery-durability fsync (round 5, see
    ``_scan_journal_unlocked``). A complete-but-unacknowledged
    entry is NOT returned here — it is preserved in the journal
    and reported by ``unacknowledged_outcomes`` — and neither is
    a trailing ACK-backed unit whose durability the recovery
    step could not establish: it is reported through the
    unacknowledged path instead. A torn tail (bytes after the
    last complete line) is not returned and does not fail the
    read; its size is surfaced by ``outcome_journal_status`` and
    on ``receipt_status`` as ``torn_tail_bytes``. The distinct
    malformed-line ReceiptError (naming the line number, never
    a bare JSON error) is raised only for corruption *inside*
    the committed region: a line that fails to parse while a
    parseable complete line follows it, or an ACK bound to no
    entry — real damage an auditor must see, which recovery
    never silently truncates.

    The scan runs under the shared receipts lock (audit #2086,
    round 4) — the same lock the writer holds exclusively across
    the entire append protocol, rollback included — so a snapshot
    shows only durable-or-absent states: an entry is reported
    only if its ACK was fsynced under the writer's lock hold, or
    the recovery fsync performed under this lock hold has just
    established the surviving unit's durability; an append that
    fails (e.g. at the ACK fsync) and rolls back is never
    visible to any reader, at any moment.
    """
    if not outcomes_path(archive_dir).is_file():
        return []
    with _receipts_read_lock(archive_dir):
        return _committed_entries_unlocked(archive_dir)


def unacknowledged_outcomes(archive_dir):
    """Complete journal entries that were never durably ACKed.

    Returns ``[{"entry", "sha256"}]`` in journal order. These are
    outcomes whose durability as committed state is not
    established: entry lines a writer wrote (and may even have
    fsync'd) but whose ACK never became durable — most plausibly
    a process killed between the two phases — AND a trailing
    ACK-backed unit whose ACK survived in the page cache after
    its writer was killed before the ACK fsync, when the scan's
    recovery-durability fsync could not establish its durability
    either (round 5). They are NOT outcomes: they are preserved,
    reported here, and resolved only by reconciliation against
    ground truth (see ``reconcile_receipt``). Read under the
    shared receipts lock (round 4), like every journal reader.
    """
    if not outcomes_path(archive_dir).is_file():
        return []
    with _receipts_read_lock(archive_dir):
        return _unacknowledged_unlocked(archive_dir)


def outcome_journal_status(archive_dir):
    """Journal health: committed count, unacked count, tail size.

    ``torn_tail_bytes`` > 0 means an interrupted writer left an
    uncommitted fragment after the last complete line; committed
    entries are unaffected and readable, and the next append
    truncates the fragment (recovery). ``unacknowledged_entries``
    counts complete entry lines whose durability as committed
    state is not established — no ACK, or a surviving ACK whose
    durability the recovery step could not establish (round 5) —
    preserved and reported, resolved by reconciliation, never
    counted as outcomes. Raises ReceiptError only for corruption
    inside the committed region, exactly as ``read_outcomes``
    does. Read under the shared receipts lock (round 4), like
    every journal reader.
    """
    if not outcomes_path(archive_dir).is_file():
        return _journal_status_unlocked(archive_dir)
    with _receipts_read_lock(archive_dir):
        return _journal_status_unlocked(archive_dir)


def latest_outcomes(archive_dir):
    """Map receipt_id -> its latest outcome entry (append order wins).

    Read under the shared receipts lock (round 4), like every
    journal reader.
    """
    if not outcomes_path(archive_dir).is_file():
        return {}
    with _receipts_read_lock(archive_dir):
        return _latest_outcomes_unlocked(archive_dir)


def _identity_elements(input_sha256, fixture_id, market, selection,
                       line):
    """The identity elements an archived record must match, in order."""
    return (("provenance.input_sha256", input_sha256),
            ("fixture_id", fixture_id),
            ("market", market),
            ("selection", selection),
            ("line", line))


def _element_missing(value):
    """An identity element counts as missing when it is absent, null,
    or an empty/blank string."""
    return value is None or (isinstance(value, str)
                             and not value.strip())


def _check_archived_record(path, *, input_sha256, fixture_id, market,
                           selection, line):
    """Verify one candidate archived record. Returns (ok, why, record).

    Fail-closed on EVERY identity element (audit #2086, round 2):
    provenance input-hash, fixture (game) identity, market,
    selection, and line must each be present on the record and equal
    to the expected value. An absent, null, unparseable, or
    mismatched element fails verification with a reason naming that
    specific element — an element the caller could not supply is
    rejected earlier, in ``verify_archived_record``, before any
    candidate is even read.
    """
    if not path.is_file():
        return False, "RECORD_NOT_FOUND", None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "RECORD_UNREADABLE", None
    if not isinstance(record, dict):
        return False, "RECORD_NOT_AN_OBJECT", None
    provenance = record.get("capture_provenance")
    if not isinstance(provenance, dict):
        return False, "IDENTITY_MISSING:capture_provenance", None
    record_sha = provenance.get("input_sha256")
    if _element_missing(record_sha):
        return False, "IDENTITY_MISSING:provenance.input_sha256", None
    if record_sha != input_sha256:
        return False, "PROVENANCE_INPUT_HASH_MISMATCH", None
    record_fixture = record.get("fixture_id")
    if _element_missing(record_fixture):
        return False, "IDENTITY_MISSING:fixture_id", None
    if record_fixture != fixture_id:
        return False, "FIXTURE_ID_MISMATCH", None
    record_market = record.get("market")
    if _element_missing(record_market):
        return False, "IDENTITY_MISSING:market", None
    if record_market != market:
        return False, "MARKET_MISMATCH", None
    record_selection = record.get("selection")
    if _element_missing(record_selection):
        return False, "IDENTITY_MISSING:selection", None
    if record_selection != selection:
        return False, "SELECTION_MISMATCH", None
    record_line = record.get("line")
    if _element_missing(record_line):
        return False, "IDENTITY_MISSING:line", None
    if isinstance(line, str):
        # Moneyline: the only well-formed line is the string "ML".
        if record_line != line:
            return False, "LINE_MISMATCH", None
    else:
        try:
            record_point = float(record_line)
        except (TypeError, ValueError):
            return False, "IDENTITY_UNPARSEABLE:line", None
        if isinstance(record_line, bool) or record_point != line:
            return False, "LINE_MISMATCH", None
    return True, None, record


def verify_archived_record(archive_dir, *, input_sha256, fixture_id,
                           market, selection, line=None,
                           candidate_path=None):
    """Locate and verify the archived record for one capture.

    The pipeline's claimed ``candidate_path`` is checked first but
    never trusted: it must resolve inside the archive's ``captures/``
    directory and pass every check. The captures directory is also
    scanned, so a wrong claimed path cannot hide a genuine record.
    Returns ``(path, record)`` on success, ``(None, details)`` when no
    candidate verifies (audit #2086: a successful-looking pipeline
    response is not, by itself, evidence that anything was archived).
    The outcome the caller records on ``(None, details)`` depends on
    the path: REFUSED when a fresh run claimed success (an established
    failed verification), INDETERMINATE when a reconciliation simply
    finds nothing.

    Fail-closed identity (audit #2086, round 2): verification first
    requires EVERY expected identity element — provenance
    input-hash, fixture_id, market, selection, line — to be present
    and verifiable on the caller's side. If any element is missing
    or underivable (``line=None`` included), no candidate is read
    and verification fails naming each unverifiable element: a
    wrong-game record must never pass because the identity it should
    have been checked against was absent.
    """
    archive_dir = Path(archive_dir)
    unverifiable = [
        {"path": None,
         "check_failed": "EXPECTED_IDENTITY_UNVERIFIABLE:" + element}
        for element, value in _identity_elements(
            input_sha256, fixture_id, market, selection, line)
        if _element_missing(value)]
    if unverifiable:
        return None, {"candidates_checked": 0, "failures": unverifiable}
    cap_dir = archive_dir / "captures"
    candidates = []
    claimed_outside = False
    if candidate_path:
        claimed = Path(candidate_path)
        try:
            inside = claimed.resolve().parent == cap_dir.resolve()
        except OSError:
            inside = False
        if inside:
            candidates.append(claimed)
        else:
            claimed_outside = True
    if cap_dir.is_dir():
        for path in sorted(cap_dir.glob("*.json")):
            if path not in candidates:
                candidates.append(path)
    failures = []
    if claimed_outside:
        failures.append({"path": str(candidate_path),
                         "check_failed": "RECORD_OUTSIDE_CAPTURES_DIR"})
    for path in candidates:
        ok, why, record = _check_archived_record(
            path, input_sha256=input_sha256, fixture_id=fixture_id,
            market=market, selection=selection, line=line)
        if ok:
            return path, record
        failures.append({"path": str(path), "check_failed": why})
    return None, {"candidates_checked": len(candidates),
                  "failures": failures[:8]}


def _resolve_unacknowledged_locked(archive_dir, receipt, target, *,
                                     fixture_id, market, selection,
                                     line):
    """Resolve one unacknowledged journal entry. Lock held by caller.

    The unacknowledged entry is preserved in the journal whatever
    happens; resolution appends NEW committed state, never edits
    it (audit #2086, round 3):

    - An ``ARCHIVED``-type entry whose claimed record **verifies
      on disk** (the same verification a fresh run must pass) is
      **promoted**: its ACK line is appended — acknowledging it
      now, on verified ground truth — followed by a confirming
      ``ARCHIVED`` outcome marked ``reconciled``.
    - An ``ARCHIVED``-type entry whose record does not verify,
      and any ``REFUSED``/``INDETERMINATE``-type entry, is
      **superseded** by a committed ``INDETERMINATE`` outcome:
      the original outcome was never durably established (its ACK
      never landed), so it cannot stand as an established
      ARCHIVED or REFUSED.

    Returns the outcome entry appended (confirming ARCHIVED or
    superseding INDETERMINATE).
    """
    receipt_id = str(receipt["receipt_id"])
    entry = target["entry"]
    entry_sha = target["sha256"]
    if entry.get("outcome") == STATUS_ARCHIVED:
        found, record_or_details = verify_archived_record(
            archive_dir, input_sha256=receipt["input_sha256"],
            fixture_id=fixture_id, market=market, selection=selection,
            line=line, candidate_path=entry.get("record_path"))
        if found is not None:
            recovered = _append_ack_locked(archive_dir, entry_sha)
            outcome = {
                "outcome": STATUS_ARCHIVED,
                "receipt_id": receipt_id,
                "record_path": str(found),
                "fixture_id": record_or_details.get("fixture_id"),
                "reconciled": True,
                "confirms_unacknowledged_entry_sha256": entry_sha,
                "note": "an earlier run wrote this outcome's "
                        "entry line but died before its ACK; the "
                        "archived record verifies on disk, so the "
                        "entry is acknowledged now (promotion) and "
                        "this confirming outcome is appended.",
                # The interrupted run's own provenance object (or
                # its absence) is part of the preserved entry;
                # carry it verbatim, never reconstructed.
                "elo_schedule_provenance": entry.get(
                    "elo_schedule_provenance"),
            }
            if entry.get("provenance_note"):
                outcome["provenance_note"] = entry["provenance_note"]
            elif outcome["elo_schedule_provenance"] is None:
                outcome["provenance_note"] = (
                    "the promoted entry carried no "
                    "elo_schedule_provenance object; recorded as "
                    "null rather than reconstructed.")
            if recovered:
                outcome["journal_recovered_torn_bytes"] = recovered
            outcome.setdefault(
                "recorded_at_utc",
                _iso(datetime.now(timezone.utc)))
            _append_outcome_locked(archive_dir, outcome)
            return outcome
    else:
        found, record_or_details = None, None
    outcome = {
        "outcome": STATUS_INDETERMINATE,
        "receipt_id": receipt_id,
        "reason": "UNACKNOWLEDGED_OUTCOME_NOT_DURABLY_ESTABLISHED",
        "reconciled": True,
        "original_outcome_unknown": True,
        "supersedes_unacknowledged_entry_sha256": entry_sha,
        "unacknowledged_outcome_type": entry.get("outcome"),
        "note": "an earlier run wrote a %s entry line but died "
                "before its ACK, so that outcome was never durably "
                "established; it is superseded by this "
                "INDETERMINATE outcome and preserved unacknowledged "
                "in the journal." % entry.get("outcome"),
    }
    if entry.get("outcome") == STATUS_ARCHIVED:
        outcome["verification"] = record_or_details
        outcome["note"] = (
            "an earlier run wrote an ARCHIVED entry line but died "
            "before its ACK, and the claimed record does not "
            "verify on disk; the archived claim was never durably "
            "established and is superseded by this INDETERMINATE "
            "outcome. The unacknowledged entry is preserved in "
            "the journal.")
    outcome.setdefault("recorded_at_utc",
                       _iso(datetime.now(timezone.utc)))
    _append_outcome_locked(archive_dir, outcome)
    return outcome


def reconcile_receipt(archive_dir, receipt_id, *, fixture_id, market,
                      selection, line=None):
    """Reconcile one PENDING receipt against the archive (audit #2086).

    For a receipt whose run died between receipt and outcome: inspect
    ``captures/`` for a record whose provenance matches the receipt.
    Found -> append ``ARCHIVED`` (marked ``reconciled``). Not found ->
    append ``INDETERMINATE`` with reason
    ``NO_ARCHIVED_RECORD_FOUND_ON_RECONCILIATION``: the record's
    absence is the only established fact. Whether the original runner
    never started, crashed mid-run, or refused without its refusal
    being recorded is NOT knowable after the fact, so no refusal is
    recorded — ``REFUSED`` is reserved for established refusals (a
    runner that demonstrably ran and refused, or a claimed record
    that failed verification).

    If the journal holds an **unacknowledged entry** for this
    receipt (a prior append wrote its entry line but died before
    the ACK), that entry is resolved first — promoted on verified
    ground truth or superseded by ``INDETERMINATE``; see
    ``_resolve_unacknowledged_locked``. Returns the outcome entry
    appended. Raises ReceiptError when the receipt does not exist
    or already has a committed outcome.
    """
    archive_dir = Path(archive_dir)
    path = receipt_path(archive_dir, receipt_id)
    if not path.is_file():
        raise ReceiptError("RECEIPT_NOT_FOUND:" + str(receipt_id))
    receipt = json.loads(path.read_text(encoding="utf-8"))
    with receipts_lock(archive_dir):
        # This path already holds the exclusive lock, so it reads
        # through the *_unlocked helpers — the public readers take
        # the shared lock and would self-deadlock here (round 4).
        existing = _latest_outcomes_unlocked(archive_dir).get(
            str(receipt_id))
        if existing is not None:
            raise ReceiptError(
                "RECEIPT_ALREADY_HAS_OUTCOME:" + str(receipt_id))
        unacknowledged = [
            item for item in _unacknowledged_unlocked(archive_dir)
            if isinstance(item["entry"], dict)
            and item["entry"].get("receipt_id") == str(receipt_id)]
        if unacknowledged:
            return _resolve_unacknowledged_locked(
                archive_dir, receipt, unacknowledged[-1],
                fixture_id=fixture_id, market=market,
                selection=selection, line=line)
        found, record_or_details = verify_archived_record(
            archive_dir, input_sha256=receipt["input_sha256"],
            fixture_id=fixture_id, market=market, selection=selection,
            line=line)
        if found is not None:
            outcome = {
                "outcome": STATUS_ARCHIVED,
                "receipt_id": str(receipt_id),
                "record_path": str(found),
                "fixture_id": record_or_details.get("fixture_id"),
                "reconciled": True,
                # Reconciliation runs no pipeline, so no Elo schedule
                # provenance exists for the interrupted run; record
                # null with a note rather than reconstructing values
                # (audit #2086, round 3).
                "elo_schedule_provenance": None,
                "provenance_note":
                    "ARCHIVED by reconciliation, which ran no "
                    "pipeline; the interrupted run produced no "
                    "elo_schedule_provenance and none is "
                    "reconstructed.",
            }
        else:
            outcome = {
                "outcome": STATUS_INDETERMINATE,
                "receipt_id": str(receipt_id),
                "reason": "NO_ARCHIVED_RECORD_FOUND_ON_RECONCILIATION",
                "reconciled": True,
                "original_outcome_unknown": True,
                "note": "no archived record exists for this receipt; "
                        "the original run's outcome is unknown — the "
                        "runner may never have started, may have "
                        "crashed mid-run, or may have refused without "
                        "the refusal being recorded. Absence of a "
                        "record is the only established fact, so this "
                        "is INDETERMINATE, not REFUSED.",
                "verification": record_or_details,
            }
        outcome.setdefault("recorded_at_utc",
                           _iso(datetime.now(timezone.utc)))
        _append_outcome_locked(archive_dir, outcome)
    return outcome


def receipt_status(archive_dir, receipt_id):
    """Effective status of one receipt, for auditors.

    Returns a dict with the receipt verbatim, its effective ``status``
    (PENDING_EVALUATION until an outcome line exists, then ARCHIVED,
    REFUSED, or INDETERMINATE), and the outcome entry when one exists.
    A REFUSED status means the quotes were preserved but **no
    evaluator record exists**, and the refusal is established (the
    runner demonstrably ran and refused, or a claimed record failed
    verification). An INDETERMINATE status also means the quotes were
    preserved and **no evaluator record exists**, but the original
    run's outcome is unknown — reconciliation found no record, and
    whether the runner started, crashed, or refused cannot be known
    after the fact. Raises ReceiptError when no receipt carries that
    id.

    The result also carries ``torn_tail_bytes`` (the size of any
    uncommitted fragment an interrupted writer left at the end of
    the outcomes journal — committed entries are read normally
    regardless) and ``unacknowledged_outcome`` /
    ``unacknowledged_entry_sha256``: the latest complete journal
    entry for this receipt that was never durably ACKed, when one
    exists (round 3). A receipt with an unacknowledged entry but
    no committed outcome resolves to status ``INDETERMINATE`` —
    the entry's content may be true, but its outcome was never
    durably established — and enters the reconciliation flow,
    which promotes it on verified ground truth or supersedes it
    with a committed ``INDETERMINATE`` outcome.
    """
    path = receipt_path(archive_dir, receipt_id)
    if not path.is_file():
        raise ReceiptError("RECEIPT_NOT_FOUND:" + str(receipt_id))
    receipt = json.loads(path.read_text(encoding="utf-8"))
    # One shared-lock hold for every journal derivation below, so
    # the status is a single durable-or-absent snapshot (round 4)
    # rather than three separately-timed glimpses of the journal.
    with _receipts_read_lock(archive_dir):
        outcome = _latest_outcomes_unlocked(archive_dir).get(
            str(receipt_id))
        unacknowledged = [
            item for item in _unacknowledged_unlocked(archive_dir)
            if isinstance(item["entry"], dict)
            and item["entry"].get("receipt_id") == str(receipt_id)]
        torn_tail_bytes = _journal_status_unlocked(
            archive_dir)["torn_tail_bytes"]
    latest_unacknowledged = unacknowledged[-1] if unacknowledged \
        else None
    if outcome is not None:
        status = outcome["outcome"]
    elif latest_unacknowledged is not None:
        status = STATUS_INDETERMINATE
    else:
        status = STATUS_PENDING
    result = {
        "receipt_id": str(receipt_id),
        "receipt_path": str(path),
        "status": status,
        "receipt": receipt,
        "outcome": outcome,
        "record_path": outcome.get("record_path") if outcome else None,
        "refusal_reason": (outcome.get("reason") if outcome
                           and outcome.get("outcome") == STATUS_REFUSED
                           else None),
        "unacknowledged_outcome": (
            latest_unacknowledged["entry"]
            if latest_unacknowledged else None),
        "unacknowledged_entry_sha256": (
            latest_unacknowledged["sha256"]
            if latest_unacknowledged else None),
        "torn_tail_bytes": torn_tail_bytes,
    }
    return result


def list_receipts(archive_dir):
    """Every receipt with its effective status, creation order.

    Receipts and the outcomes map are read under one shared-lock
    hold (round 4), so the listing is one consistent snapshot.
    """
    if not receipts_dir(archive_dir).is_dir():
        return []
    with _receipts_read_lock(archive_dir):
        latest = _latest_outcomes_unlocked(archive_dir)
        receipts = _read_receipts_unlocked(archive_dir)
    out = []
    for path, receipt in receipts:
        outcome = latest.get(receipt["receipt_id"])
        out.append({
            "receipt_id": receipt["receipt_id"],
            "receipt_path": str(path),
            "status": outcome["outcome"] if outcome else STATUS_PENDING,
            "receipt_created_at_utc": receipt["receipt_created_at_utc"],
            "input_sha256": receipt["input_sha256"],
            "outcome": outcome,
        })
    out.sort(key=lambda item: (item["receipt_created_at_utc"],
                               item["receipt_id"]))
    return out
