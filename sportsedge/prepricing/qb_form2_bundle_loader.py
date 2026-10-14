#!/usr/bin/env python3
"""Runtime adapter for QB_IDENTITY_EVIDENCE Form 2 bundles (CFB).

This module is the RUN IT wiring for the Form 2 evaluator
(``qb_identity_evidence``, PR #2157): it hands the pre-pricing stage
the ``{espn_team_id: bundle}`` mapping it expects, keyed by ESPN
team ID, with a per-file audit the runner lands on the card as
``qb_form2_bundle_loader_audit``.

Trust contract (owner archive-convergence verdict, Oct 13, 2026 --
this module was reworked to it; the previous directory-trust loader
is superseded):

  * The archive module (``qb_evidence_archive``, PRs #2164/#2165)
    owns ALL file IO, strict JSON parsing, and integrity. This
    adapter never opens bundle content itself: object bytes are read
    through the archive's descriptor-based, size-capped,
    symlink/FIFO-refusing read, and parsed through its strict parser
    (duplicate keys, nonfinite numbers, and excess nesting are
    refusals, not silent reinterpretations). The disclosed defects
    of the old loader (a non-UTF-8 file crashed the run out of
    ``Path.read_text``; a FIFO hung it; symlinks were followed
    silently) are closed by this delegation.
  * Admission requires an EXTERNAL PIN: the caller supplies the
    archive manifest's SHA-256 from an independent channel (runner
    configuration -- never read from the bundle directory). The
    manifest bytes are verified against the pin before anything is
    admitted; each admitted object's raw bytes must hash to the
    content address the pinned manifest carries for it. The bundle
    receipt v2 chain (see ``_admission_check``) is still verified,
    but on its own it proves only self-consistency -- an attacker
    who edits a bundle can recompute it (a resealed forgery). The
    pin is what makes admission evidence-grade; this adapter is
    NOT a trusted evidence source without one.
  * NO PIN, NO ADMISSION. With ``manifest_sha256=None`` the mapping
    is empty and the audit records the refusal (``pin_status:
    ABSENT``); there is no parallel unpinned acceptance path, and a
    manifest's own hash, a neighboring file, or a runtime-provided
    digest is not an anchor. The run otherwise behaves exactly as
    it did before Form 2 existed (the QB gate blocks).
  * DUPLICATES FAIL CLOSED. Competing valid bundles for the same
    fixture/team refuse that fixture/team (all of them, audited);
    the old deterministic first-wins selection is rejected by the
    verdict. A manifest carrying more than one receipt for the same
    fixture/team is likewise refused for that fixture/team
    (``ARCHIVE_RECEIPT_NOT_UNIQUE``, the archive's own code).
  * EVALUATION stays with the evaluator at binder consult time
    (``factor_ingestion._consult_qb_form2``): staged-fixture
    equality, capture timestamps against kickoff and the stage
    clock, stamp staleness, roster completeness, and the
    derived-vs-asserted QB-order cross-check. An admitted bundle is
    a candidate, not a pass; QB1 is derived by the evaluator from
    the captured chart -- this adapter never reads, trusts, or
    forwards a bundle-asserted QB1 as identity. Form 2 remains
    identity-only and research-only end-to-end: availability stays
    AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT and injury points
    stay exactly 0.0 (issue #2158 guard untouched).

Fail-closed discipline: a bundle that fails any check is EXCLUDED
and recorded in the audit -- never silently dropped, never
partially applied. A bad bundle never fails the run: its fixture
simply proceeds without Form 2 and blocks at the gate exactly as it
did before Form 2 existed. This module performs NO fetching of any
kind; capture and preservation are operator-invoked ahead of
kickoff (``qb_identity_evidence``'s CLI and the archive writer).

Implementation note: the archive module currently exposes its read
and parse discipline only as the module-private helpers
``_read_bundle`` / ``_json`` / ``_digest`` / ``_time``. This adapter
imports those helpers rather than re-implementing them (no forked
IO logic); promoting them to a public archive API
(``read_object_bytes`` / ``parse_json_strict``, as proposed in the
convergence comparison) is a flagged follow-up for the archive
stack. The archive module's behavior is not modified here.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from artifacts.free_models import dt

from sportsedge.prepricing import qb_evidence_archive as _archive
from sportsedge.prepricing import qb_identity_evidence as _qe
from sportsedge.prepricing.factor_ingestion import _resolve_teams
from sportsedge.prepricing.qb_evidence_archive import EvidenceArchiveError

AUDIT_SCHEMA = "SPORTSEDGE_QB_FORM2_BUNDLE_LOADER_AUDIT_V1"
AUDIT_SOURCE = "QB_IDENTITY_EVIDENCE_FORM2_LOADER"

ADMITTED = "ADMITTED"
EXCLUDED = "EXCLUDED"
IGNORED = "IGNORED"

REASON_ADMITTED = "RECEIPT_V2_CHAIN_VERIFIED_SCHEMA_AND_HASH"
REASON_NON_CFB = "NON_CFB_BUNDLE"
REASON_NOT_AN_OBJECT = "BUNDLE_NOT_AN_OBJECT"
REASON_WRONG_FORM = "WRONG_EVIDENCE_FORM"
REASON_SCHEMA_INCOMPLETE = "BUNDLE_SCHEMA_INCOMPLETE"
REASON_TEAM_NOT_IN_INTAKE = "TEAM_NOT_IN_INTAKE"
REASON_FIXTURE_NOT_IN_INTAKE = "FIXTURE_NOT_IN_INTAKE"
REASON_DUPLICATE = "DUPLICATE_TEAM_BUNDLE"
# New under the convergence verdict. IO/parse/integrity refusals use
# the archive module's ARCHIVE_* codes verbatim (one failure, one
# name, in both audit surfaces); the three adapter-level reasons
# below are coined in that style and flagged in ADAPTER.md:
REASON_PIN_REQUIRED = "ARCHIVE_PIN_REQUIRED"  # coined: no pin given
REASON_MANIFEST_FILE = "ARCHIVE_MANIFEST_NOT_A_BUNDLE"  # coined
REASON_NOT_IN_MANIFEST = "ARCHIVE_BUNDLE_NOT_IN_MANIFEST"  # coined
REASON_OBJECT_NAME_INVALID = "ARCHIVE_OBJECT_NAME_INVALID"  # coined

PIN_VERIFIED = "VERIFIED"
PIN_ABSENT = "ABSENT"
PIN_UNVERIFIED = "UNVERIFIED"

_HEX64 = re.compile(r"[0-9a-f]{64}")


def _team_key(name):
    """Normalized intake-matching key for a team name: casefolded,
    punctuation collapsed. Exact match on this key is the adapter's
    intake surface -- a mismatch fails closed (audited), it never
    fuzzy-matches one school onto another."""
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def _intake_cfb_fixtures(game_rows):
    """Index the current intake's CFB fixtures: normalized team name ->
    set of kickoff datetimes, from the runner's game rows (the same
    rows, and the same team resolution, the stage itself will see)."""
    index = {}
    for row in game_rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("sport") or "").upper() != "CFB":
            continue
        away, home = _resolve_teams(row)
        if not away or not home:
            continue
        kickoff = dt(row.get("commence_time") or row.get("kickoff"))
        for name in (away, home):
            index.setdefault(_team_key(name), set()).add(kickoff)
    return index


def _entry(name, disposition, reason, detail, bundle=None):
    entry = {"source": AUDIT_SOURCE, "file": name,
             "disposition": disposition, "reason": reason,
             "detail": detail, "team_id": None, "team_name": None}
    if isinstance(bundle, dict):
        team = bundle.get("team")
        if not isinstance(team, dict):
            team = {}
        if team.get("espn_id") is not None:
            entry["team_id"] = str(team.get("espn_id"))
        if team.get("name") is not None:
            entry["team_name"] = str(team.get("name"))
    return entry


def _admission_check(bundle):
    """Admission-level verification against the corrected Form 2
    schema: evidence form, identity + exact-fixture-binding schema,
    component content-hash integrity, and the RECEIPT v2 chain seal
    (which covers the binding fields, both capture timestamps, the
    stamp, and the sealed assertions). Reason/detail vocabulary
    mirrors the evaluator's statuses wherever admission rejects what
    evaluation would reject. Returns (ok, reason, detail). Full
    evaluation stays with the evaluator at binder consult time.

    The chain is a self-consistency proof only: under the
    convergence verdict it is necessary but never sufficient --
    sufficiency comes from the external pin and the pinned
    manifest's byte anchor, verified before this check runs."""
    if (bundle.get("evidence_class") != _qe.EVIDENCE_CLASS
            or bundle.get("evidence_form") != _qe.EVIDENCE_FORM):
        return False, REASON_WRONG_FORM, (
            f"evidence_class={bundle.get('evidence_class')!r} "
            f"evidence_form={bundle.get('evidence_form')!r}")
    team = bundle.get("team")
    if not isinstance(team, dict) or team.get("espn_id") is None \
            or not str(team.get("name") or "").strip():
        return False, REASON_SCHEMA_INCOMPLETE, "TEAM_BINDING_FIELDS_MISSING"
    # Exact fixture binding (owner-review correction 1): the bundle
    # must CARRY the full binding set -- event ID plus the opponent's
    # ESPN team ID alongside the subject team's -- so a bundle that
    # cannot even name its fixture is excluded here, with an audit
    # entry, instead of failing obscurely at consult. Equality with
    # the STAGED fixture remains the evaluator's check.
    fixture = bundle.get("fixture")
    if not isinstance(fixture, dict):
        return False, REASON_SCHEMA_INCOMPLETE, "FIXTURE_BINDING_MISSING"
    if fixture.get("event_id") is None or str(fixture.get("event_id")) == "":
        return False, REASON_SCHEMA_INCOMPLETE, "FIXTURE_EVENT_ID_MISSING"
    if fixture.get("opponent_espn_id") is None \
            or str(fixture.get("opponent_espn_id")) == "":
        return False, REASON_SCHEMA_INCOMPLETE, "FIXTURE_OPPONENT_ID_MISSING"
    if dt(fixture.get("kickoff_utc")) is None:
        return False, REASON_SCHEMA_INCOMPLETE, "FIXTURE_KICKOFF_MISSING"
    if str(fixture.get("opponent_espn_id")) == str(team.get("espn_id")):
        # The opponent can never be the subject team itself: the
        # evaluator would reject this bundle against every staged
        # fixture (OPPONENT_MISMATCH), so admission rejects it too,
        # in the evaluator's own fixture-mismatch vocabulary.
        return False, _qe.STATUS_FIXTURE_MISMATCH, "OPPONENT_EQUALS_SUBJECT_TEAM"
    for label, snap in (("DEPTH", bundle.get("depth_snapshot")),
                        ("ROSTER", bundle.get("roster_snapshot"))):
        if not isinstance(snap, dict):
            return False, REASON_SCHEMA_INCOMPLETE, f"{label}_SNAPSHOT_MISSING"
        content = snap.get("content")
        if not isinstance(content, str) or not snap.get("sha256"):
            return False, REASON_SCHEMA_INCOMPLETE, f"{label}_CONTENT_OR_HASH_MISSING"
        if _qe.sha256_text(content) != snap.get("sha256"):
            return False, _qe.STATUS_HASH_MISMATCH, f"{label}_CONTENT_SHA256_MISMATCH"
    # Receipt v2 chain (owner-review correction 3): an unsealed,
    # legacy-sealed, or post-capture-edited bundle is not evidence,
    # however consistent its components look -- admission enforces
    # the same seal the evaluator recomputes, so nothing admitted
    # here can fail the seal there.
    sealed = bundle.get("receipt")
    if not isinstance(sealed, dict) or sealed.get("version") != _qe.RECEIPT_VERSION:
        return False, _qe.STATUS_HASH_MISMATCH, "RECEIPT_CHAIN_MISSING"
    if sealed.get("sha256") != _qe.receipt_chain_sha256(bundle):
        return False, _qe.STATUS_HASH_MISMATCH, "RECEIPT_CHAIN_MISMATCH"
    return True, REASON_ADMITTED, (
        "SCHEMA_COMPLETE; COMPONENT_HASHES_AND_RECEIPT_V2_CHAIN_VERIFIED "
        "(SEALED ASSERTIONS INTACT: QB_ORDER, ROSTER COUNTS, FIXTURE "
        "KICKOFFS, BINDING IDS, TIMESTAMPS)")


def _manifest_agreement(entry, bundle):
    """Bind the pinned manifest's receipt entry to the bundle object
    it anchors: same team, same event, the entry's home/away roles
    are exactly the bundle's subject + opponent, same kickoff, and
    the archive-layer temporal ordering the reader enforces -- the
    receipt was recorded no earlier than either snapshot's capture
    completion and strictly before kickoff. (The reader's
    recorded-vs-as_of availability check needs a stage clock and
    stays with evaluation, as before.) Refusals use the archive's
    own codes verbatim. Returns (ok, reason, detail)."""
    team = bundle.get("team")
    if not isinstance(team, dict):
        team = {}
    fixture = bundle.get("fixture")
    if not isinstance(fixture, dict):
        fixture = {}
    if str(entry.get("team_id")) != str(team.get("espn_id")):
        return False, "ARCHIVE_FIXTURE_MISMATCH", \
            "MANIFEST_TEAM_ID_DOES_NOT_MATCH_BUNDLE"
    if str(entry.get("event_id")) != str(fixture.get("event_id")):
        return False, "ARCHIVE_FIXTURE_MISMATCH", \
            "MANIFEST_EVENT_ID_DOES_NOT_MATCH_BUNDLE"
    roles = {str(entry.get("home_team_id")), str(entry.get("away_team_id"))}
    if roles != {str(team.get("espn_id")),
                 str(fixture.get("opponent_espn_id"))}:
        return False, "ARCHIVE_FIXTURE_MISMATCH", \
            "MANIFEST_HOME_AWAY_DO_NOT_MATCH_BUNDLE_TEAMS"
    try:
        entry_kickoff = _archive._time(entry.get("kickoff_utc"))
        bundle_kickoff = _archive._time(fixture.get("kickoff_utc"))
        recorded = _archive._time(entry.get("recorded_at_utc"))
        captured = [
            _archive._time(bundle["depth_snapshot"]["captured_at_utc"]),
            _archive._time(bundle["roster_snapshot"]["captured_at_utc"]),
        ]
    except EvidenceArchiveError as exc:
        return False, str(exc), "MANIFEST_OR_BUNDLE_TIME_INVALID"
    except (KeyError, TypeError, AttributeError):
        return False, REASON_SCHEMA_INCOMPLETE, \
            "SNAPSHOT_CAPTURE_TIMES_MISSING"
    if entry_kickoff != bundle_kickoff:
        return False, "ARCHIVE_FIXTURE_MISMATCH", \
            "MANIFEST_KICKOFF_DOES_NOT_MATCH_BUNDLE"
    if any(recorded < stamp for stamp in captured):
        return False, "ARCHIVE_RECEIPT_PRECEDES_FETCH", \
            "RECORDED_AT_PRECEDES_A_SNAPSHOT_CAPTURE"
    if recorded >= bundle_kickoff:
        return False, "ARCHIVE_RECEIPT_NOT_AVAILABLE", \
            "RECORDED_AT_NOT_STRICTLY_PRE_KICKOFF"
    return True, None, None


def _load_manifest(directory, manifest_sha256, manifest_bytes, audit):
    """Verify the external pin and return (manifest_entries, pin).

    On any refusal the audit is completed here (pin_status set,
    refusal entry appended) and (None, None) is returned: no
    admission proceeds from an unverified manifest. The manifest
    bytes come from the caller when supplied, else from the
    content-addressed object the pin names -- read through the
    archive's own bounded read, never from an editable side file."""
    try:
        pin = _archive._digest(manifest_sha256)
    except EvidenceArchiveError as exc:
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            None, EXCLUDED, str(exc), "SUPPLIED_PIN_NOT_A_SHA256_DIGEST"))
        return None, None
    if manifest_bytes is None:
        try:
            manifest_bytes = _archive._read_bundle(str(directory), pin)
        except EvidenceArchiveError as exc:
            audit["pin_status"] = PIN_UNVERIFIED
            audit["entries"].append(_entry(
                f"{pin}.json", EXCLUDED, str(exc),
                "PINNED_MANIFEST_OBJECT_UNREADABLE"))
            return None, None
    if not isinstance(manifest_bytes, bytes):
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            f"{pin}.json", EXCLUDED, "ARCHIVE_MANIFEST_BYTES_REQUIRED",
            "MANIFEST_BYTES_MUST_BE_BYTES"))
        return None, None
    if len(manifest_bytes) > _archive.MAX_MANIFEST_BYTES:
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            f"{pin}.json", EXCLUDED, "ARCHIVE_MANIFEST_TOO_LARGE",
            "MANIFEST_BYTES_EXCEED_ARCHIVE_CAP"))
        return None, None
    if hashlib.sha256(manifest_bytes).hexdigest() != pin:
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            f"{pin}.json", EXCLUDED, "ARCHIVE_MANIFEST_HASH_MISMATCH",
            "MANIFEST_BYTES_DO_NOT_MATCH_THE_EXTERNAL_PIN"))
        return None, None
    try:
        manifest = _archive._json(manifest_bytes)
    except EvidenceArchiveError as exc:
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            f"{pin}.json", EXCLUDED, str(exc),
            "MANIFEST_STRICT_PARSE_REFUSED"))
        return None, None
    if not isinstance(manifest, dict) \
            or manifest.get("schema") != _archive.SCHEMA:
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            f"{pin}.json", EXCLUDED, "ARCHIVE_SCHEMA_INVALID",
            "MANIFEST_SCHEMA_NOT_" + _archive.SCHEMA))
        return None, None
    entries = manifest.get("entries")
    if not isinstance(entries, list) \
            or any(not isinstance(e, dict) for e in entries):
        audit["pin_status"] = PIN_UNVERIFIED
        audit["entries"].append(_entry(
            f"{pin}.json", EXCLUDED, "ARCHIVE_ENTRIES_INVALID",
            "MANIFEST_ENTRIES_MUST_BE_A_LIST_OF_OBJECTS"))
        return None, None
    audit["pin_status"] = PIN_VERIFIED
    # The full pin is recorded: it is the caller's own trust anchor
    # (an integrity digest, not a secret), and the audit must show
    # exactly which external record the run's admissions hang on.
    audit["manifest_sha256"] = pin
    return entries, pin


def load_form2_bundles(bundles_dir, game_rows, *, manifest_sha256=None,
                       manifest_bytes=None):
    """Load Form 2 bundles from the pinned archive at ``bundles_dir``.

    ``game_rows`` are the runner's game lines (the intake the stage
    will price). ``manifest_sha256`` is the EXTERNAL PIN: the
    archive manifest's SHA-256, supplied by the caller from an
    independent channel; ``manifest_bytes`` optionally supplies the
    manifest itself (verified against the pin either way). Returns
    ``(mapping, audit)``: ``mapping`` is ``{espn_team_id_str:
    bundle}`` in exactly the shape ``stage_games(qb_form2_bundles=
    ...)`` consumes (empty when nothing was admitted); ``audit`` is
    the adapter audit dict for the card. Without a pin nothing is
    admitted -- admission is disabled by contract, and the audit
    says so (``pin_status: ABSENT``). This function never raises on
    bad bundle content and never touches the network.
    """
    audit = {"schema": AUDIT_SCHEMA, "bundles_dir": str(bundles_dir),
             "directory_status": "OK", "pin_status": PIN_ABSENT,
             "manifest_sha256": None, "admitted_team_ids": [],
             "entries": []}
    mapping = {}
    directory = Path(bundles_dir)
    if directory.is_symlink():
        # #2177 parity: a symlinked bundles directory is refused at
        # the directory, by name, before any name is enumerated. The
        # archive module's O_NOFOLLOW root open remains the
        # enforcement backstop on every content read; this check
        # gives that refusal its audited directory-level status
        # instead of a directory_status of OK over per-object
        # refusals. (is_symlink reads lstat metadata only; no bundle
        # content is touched here, as everywhere in this adapter.)
        audit["directory_status"] = "UNSAFE_DIRECTORY_SYMLINK"
        return mapping, audit
    if not directory.exists():
        audit["directory_status"] = "MISSING"
        return mapping, audit
    if not directory.is_dir():
        audit["directory_status"] = "NOT_A_DIRECTORY"
        return mapping, audit
    # Names only: enumerating the root reads no content. Every
    # content read below goes through the archive module.
    names = sorted(n for n in os.listdir(directory)
                   if n.endswith(".json"))
    if not names:
        audit["directory_status"] = "EMPTY"
        return mapping, audit

    # Pin gate (verdict: no trusted pin -> no archive-backed
    # admission, and no parallel unpinned path beside it).
    if manifest_sha256 is None:
        audit["entries"].append(_entry(
            None, EXCLUDED, REASON_PIN_REQUIRED,
            "NO_EXTERNAL_PIN_SUPPLIED; FORM2_ADMISSION_DISABLED"))
        return mapping, audit
    manifest_entries, pin = _load_manifest(
        directory, manifest_sha256, manifest_bytes, audit)
    if manifest_entries is None:
        return mapping, audit

    by_digest = {}
    fixture_groups = {}
    for entry in manifest_entries:
        digest = entry.get("bundle_sha256")
        if isinstance(digest, str):
            by_digest.setdefault(digest, []).append(entry)
        key = (str(entry.get("team_id")), str(entry.get("event_id")))
        fixture_groups.setdefault(key, []).append(entry)
    conflicted_fixtures = {key for key, group in fixture_groups.items()
                           if len(group) > 1}

    intake = _intake_cfb_fixtures(game_rows)
    candidates = {}
    for name in names:
        stem = name[:-len(".json")]
        if stem == pin:
            audit["entries"].append(_entry(
                name, IGNORED, REASON_MANIFEST_FILE,
                "PINNED_MANIFEST_OBJECT; NOT_A_BUNDLE"))
            continue
        if _HEX64.fullmatch(stem) is None:
            audit["entries"].append(_entry(
                name, IGNORED, REASON_OBJECT_NAME_INVALID,
                "NOT_A_CONTENT_ADDRESSED_ARCHIVE_OBJECT"))
            continue
        try:
            raw = _archive._read_bundle(str(directory), stem)
        except EvidenceArchiveError as exc:
            audit["entries"].append(_entry(
                name, EXCLUDED, str(exc), "ARCHIVE_READ_REFUSED"))
            continue
        if hashlib.sha256(raw).hexdigest() != stem:
            audit["entries"].append(_entry(
                name, EXCLUDED, "ARCHIVE_BUNDLE_HASH_MISMATCH",
                "OBJECT_BYTES_DO_NOT_MATCH_THEIR_CONTENT_ADDRESS"))
            continue
        try:
            bundle = _archive._json(raw)
        except EvidenceArchiveError as exc:
            audit["entries"].append(_entry(
                name, EXCLUDED, str(exc), "ARCHIVE_STRICT_PARSE_REFUSED"))
            continue
        if isinstance(bundle, dict) \
                and bundle.get("schema") == _archive.SCHEMA:
            audit["entries"].append(_entry(
                name, IGNORED, REASON_MANIFEST_FILE,
                "ARCHIVE_MANIFEST_OBJECT; NOT_A_BUNDLE"))
            continue
        if not isinstance(bundle, dict):
            audit["entries"].append(_entry(
                name, EXCLUDED, REASON_NOT_AN_OBJECT,
                f"JSON_{type(bundle).__name__.upper()}"))
            continue
        sport = bundle.get("sport")
        if sport is not None and str(sport).upper() != "CFB":
            audit["entries"].append(_entry(
                name, IGNORED, REASON_NON_CFB,
                f"BUNDLE_SPORT_{str(sport).upper()}", bundle))
            continue
        covering = by_digest.get(stem, [])
        if len(covering) != 1:
            reason = ("ARCHIVE_RECEIPT_NOT_UNIQUE" if covering
                      else REASON_NOT_IN_MANIFEST)
            audit["entries"].append(_entry(
                name, EXCLUDED, reason,
                "OBJECT_NOT_UNIQUELY_COVERED_BY_THE_PINNED_MANIFEST",
                bundle))
            continue
        receipt = covering[0]
        fixture_key = (str(receipt.get("team_id")),
                       str(receipt.get("event_id")))
        if fixture_key in conflicted_fixtures:
            audit["entries"].append(_entry(
                name, EXCLUDED, "ARCHIVE_RECEIPT_NOT_UNIQUE",
                "PINNED_MANIFEST_CARRIES_MULTIPLE_RECEIPTS_FOR_THIS_"
                "FIXTURE_TEAM; FAIL_CLOSED", bundle))
            continue
        ok, reason, detail = _admission_check(bundle)
        if not ok:
            audit["entries"].append(_entry(
                name, EXCLUDED, reason, detail, bundle))
            continue
        ok, reason, detail = _manifest_agreement(receipt, bundle)
        if not ok:
            audit["entries"].append(_entry(
                name, EXCLUDED, reason, detail, bundle))
            continue
        team_key = _team_key(bundle["team"]["name"])
        if team_key not in intake:
            audit["entries"].append(_entry(
                name, EXCLUDED, REASON_TEAM_NOT_IN_INTAKE,
                f"TEAM_NAME_{bundle['team']['name']!r}_NOT_IN_CFB_INTAKE",
                bundle))
            continue
        kickoff = dt(bundle["fixture"]["kickoff_utc"])
        if kickoff not in intake[team_key]:
            audit["entries"].append(_entry(
                name, EXCLUDED, REASON_FIXTURE_NOT_IN_INTAKE,
                f"KICKOFF_{bundle['fixture']['kickoff_utc']!r}_NOT_AN_INTAKE_"
                f"FIXTURE_FOR_THIS_TEAM", bundle))
            continue
        entry = _entry(
            name, ADMITTED, REASON_ADMITTED,
            "ADMITTED_AS_CANDIDATE_UNDER_PINNED_MANIFEST; FULL_"
            "EVALUATION_REMAINS_WITH_THE_BINDER_AT_CONSULT_TIME",
            bundle)
        entry["bundle_sha256"] = stem
        audit["entries"].append(entry)
        team_id = str(bundle["team"]["espn_id"])
        candidates.setdefault(team_id, []).append((entry, bundle))
    # Duplicate policy (verdict): competing valid bundles for the
    # same team are never resolved by selection. Every candidate for
    # a contested team is refused; the team proceeds without Form 2.
    # A team is contested by identity (two surviving candidates
    # under one ESPN team id) or by name (#2177 parity: surviving
    # candidates carrying the same normalized team name under
    # DIFFERENT ids leave the name -- the surface the binder
    # resolves teams by -- ambiguous, so no candidate under any of
    # those ids may be selected either).
    ids_by_name = {}
    for team_id, group in candidates.items():
        for _cand_entry, bundle in group:
            ids_by_name.setdefault(
                _team_key(bundle["team"]["name"]), set()).add(team_id)
    name_conflicted_ids = set()
    for ids in ids_by_name.values():
        if len(ids) > 1:
            name_conflicted_ids |= ids
    for team_id, group in candidates.items():
        if len(group) == 1 and team_id not in name_conflicted_ids:
            mapping[team_id] = group[0][1]
            continue
        for entry, _bundle in group:
            entry["disposition"] = EXCLUDED
            entry["reason"] = REASON_DUPLICATE
            if len(group) > 1:
                entry["detail"] = (
                    "CONFLICTING_VALID_BUNDLES_FOR_SAME_TEAM; "
                    "ALL_REFUSED_FAIL_CLOSED")
            else:
                entry["detail"] = (
                    "CONFLICTING_TEAM_IDS_FOR_SAME_TEAM_NAME; "
                    "ALL_REFUSED_FAIL_CLOSED")
    audit["admitted_team_ids"] = sorted(mapping)
    return mapping, audit
