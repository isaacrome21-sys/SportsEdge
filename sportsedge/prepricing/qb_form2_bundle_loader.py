#!/usr/bin/env python3
"""Trusted loader for QB_IDENTITY_EVIDENCE Form 2 bundle files (CFB).

PR #2157 wired the Form 2 evaluator (``qb_identity_evidence``) and the
binder consult in ``factor_ingestion.stage_games``; this module is the
missing last step the PR disclosed: reading operator-captured bundle
files from a local directory and handing the stage the mapping it
expects, keyed by ESPN team ID.

Trust boundary (same discipline as the archived-weather rule in
factor_ingestion): bundles arrive ONLY through this loader, from an
operator-supplied directory -- never from an intake row, never from
the network. This module performs NO fetching of any kind. Capture is
operator-invoked ahead of kickoff (``qb_identity_evidence``'s CLI);
OurLads automated-acquisition terms remain UNVERIFIED, so nothing here
automates acquisition.

What the loader verifies, and what it deliberately does not:

  * ADMISSION (here): the file parses as a JSON object; it declares
    the Form 2 evidence class/form; its schema carries the identity,
    exact-fixture-binding and receipt fields (subject team,
    ``fixture.event_id``, ``fixture.opponent_espn_id``, fixture
    kickoff, both snapshots); both component receipts hash-match
    their captured contents (the evaluator's own ``sha256_text`` --
    receipt verification is reused, not re-implemented); and the
    bundle carries a valid RECEIPT v2 seal -- ``receipt.version`` is
    the evaluator's ``RECEIPT_VERSION`` and the chained hash
    (``receipt_chain_sha256``) recomputes over the bundle as
    presented. The chain seals both content hashes, both source
    URLs, the verbatim update stamp, both capture timestamps, the
    event ID, BOTH team IDs, the fixture and previous-game kickoffs,
    and the sealed assertions (the recorded ``qb_order`` and the
    roster count attestations) -- so a post-capture edit to any of
    them, assertions included, is an admission exclusion here, not a
    surprise at consult time. The bundle's team must name a CFB team
    in the current intake and its (now chain-sealed) fixture kickoff
    must match that team's intake fixture.
  * EVALUATION (NOT here): team/fixture binding against the
    provider-resolved staged fixture (the loader sees intake names
    and kickoffs, never ESPN's staged event/team IDs, so exact
    staged-fixture equality remains the evaluator's check), capture
    timestamps against kickoff and the stage clock, stamp staleness,
    roster completeness, the derived-vs-asserted QB-order
    cross-check (the chain proves the asserted order is the one
    sealed at capture; only the evaluator, parsing the captured
    chart, can prove it TRUE), and the QB1 resolution join all
    remain the evaluator's authority, exercised by the binder at
    consult time (``factor_ingestion._consult_qb_form2``). An
    admitted bundle is a candidate, not a pass. QB1 is derived by
    the evaluator from the captured chart -- this loader never
    reads, trusts, or forwards a bundle-asserted QB1 as identity.

Fail-closed discipline: a bundle that fails admission, is malformed,
names a team/fixture outside the current intake, or is in a duplicate
team group is EXCLUDED and recorded in the returned audit
-- never silently dropped, never partially applied. A bad bundle
never fails the run: its fixture simply proceeds without Form 2 and
blocks at the gate exactly as it did before Form 2 existed. A
missing or empty directory is a directory-level audit entry and an
empty mapping -- today's behavior, unchanged.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

from artifacts.free_models import dt

from sportsedge.prepricing import qb_identity_evidence as _qe
from sportsedge.prepricing.factor_ingestion import _resolve_teams

AUDIT_SCHEMA = "SPORTSEDGE_QB_FORM2_BUNDLE_LOADER_AUDIT_V1"
AUDIT_SOURCE = "QB_IDENTITY_EVIDENCE_FORM2_LOADER"

ADMITTED = "ADMITTED"
EXCLUDED = "EXCLUDED"
IGNORED = "IGNORED"

REASON_ADMITTED = "RECEIPT_V2_CHAIN_VERIFIED_SCHEMA_AND_HASH"
REASON_NON_CFB = "NON_CFB_BUNDLE"
REASON_MALFORMED_JSON = "BUNDLE_JSON_MALFORMED"
REASON_NOT_AN_OBJECT = "BUNDLE_NOT_AN_OBJECT"
REASON_UNREADABLE = "BUNDLE_FILE_UNREADABLE"
REASON_WRONG_FORM = "WRONG_EVIDENCE_FORM"
REASON_SCHEMA_INCOMPLETE = "BUNDLE_SCHEMA_INCOMPLETE"
REASON_TEAM_NOT_IN_INTAKE = "TEAM_NOT_IN_INTAKE"
REASON_FIXTURE_NOT_IN_INTAKE = "FIXTURE_NOT_IN_INTAKE"
REASON_DUPLICATE = "DUPLICATE_TEAM_BUNDLE"
REASON_UNSAFE_FILE = "UNSAFE_BUNDLE_FILE"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024


class UnsafeBundleError(OSError):
    """Untrusted file type, changed inode, symlink, or oversized bundle."""


def _read_regular_bundle(path):
    """Read one bounded regular file, refusing symlinks and detected swaps.

    Open with O_NOFOLLOW and O_NONBLOCK where supported: a malicious FIFO
    may not hang the runner, and a symlink may not redirect evidence. Read
    from the opened descriptor, then compare file identity/size/mtime with
    its post-read path identity. This is local file safety, NOT an externally
    anchored immutable archive or independent proof of capture time.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BUNDLE_BYTES:
            raise UnsafeBundleError("BUNDLE_NONREGULAR_OR_OVERSIZED")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(MAX_BUNDLE_BYTES + 1)
            after = os.fstat(handle.fileno())
        if len(raw) > MAX_BUNDLE_BYTES:
            raise UnsafeBundleError("BUNDLE_OVERSIZED")
        current = path.lstat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if (not stat.S_ISREG(current.st_mode)
                or identity(before) != identity(after)
                or identity(after) != identity(current)):
            raise UnsafeBundleError("BUNDLE_MUTATED_DURING_READ")
        return raw.decode("utf-8")
    finally:
        if descriptor >= 0:
            os.close(descriptor)



def _team_key(name):
    """Normalized intake-matching key for a team name: casefolded,
    punctuation collapsed. Exact match on this key is the loader's
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


def _entry(path, disposition, reason, detail, bundle=None):
    entry = {"source": AUDIT_SOURCE, "file": path.name,
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
    evaluation stays with the evaluator at binder consult time."""
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


def load_form2_bundles(bundles_dir, game_rows):
    """Load Form 2 bundles from ``bundles_dir`` for the current intake.

    ``game_rows`` are the runner's game lines (the intake the stage
    will price). Returns ``(mapping, audit)``: ``mapping`` is
    ``{espn_team_id_str: bundle}`` in exactly the shape
    ``stage_games(qb_form2_bundles=...)`` consumes (empty when nothing
    was admitted); ``audit`` is the loader audit dict for the run's
    audit output. Files are processed in sorted filename order, so
    admission and duplicate outcomes are deterministic. This function
    never raises on bad bundle content and never touches the network.
    """
    audit = {"schema": AUDIT_SCHEMA, "bundles_dir": str(bundles_dir),
             "directory_status": "OK", "admitted_team_ids": [],
             "entries": []}
    mapping = {}
    directory = Path(bundles_dir)
    if directory.is_symlink():
        audit["directory_status"] = "UNSAFE_DIRECTORY_SYMLINK"
        return mapping, audit
    if not directory.exists():
        audit["directory_status"] = "MISSING"
        return mapping, audit
    if not directory.is_dir():
        audit["directory_status"] = "NOT_A_DIRECTORY"
        return mapping, audit
    files = sorted(directory.glob("*.json"))
    if not files:
        audit["directory_status"] = "EMPTY"
        return mapping, audit

    intake = _intake_cfb_fixtures(game_rows)
    admitted_names = {}
    conflicting_ids = set()
    conflicting_names = set()
    for path in files:
        try:
            raw = _read_regular_bundle(path)
        except UnsafeBundleError as exc:
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_UNSAFE_FILE, str(exc)))
            continue
        except (OSError, UnicodeError) as exc:
            reason = REASON_UNSAFE_FILE if path.is_symlink() else REASON_UNREADABLE
            audit["entries"].append(_entry(
                path, EXCLUDED, reason, type(exc).__name__))
            continue
        try:
            bundle = json.loads(raw)
        except ValueError as exc:
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_MALFORMED_JSON,
                f"{type(exc).__name__}:{exc}"))
            continue
        if not isinstance(bundle, dict):
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_NOT_AN_OBJECT,
                f"JSON_{type(bundle).__name__.upper()}"))
            continue
        sport = bundle.get("sport")
        if sport is not None and str(sport).upper() != "CFB":
            audit["entries"].append(_entry(
                path, IGNORED, REASON_NON_CFB,
                f"BUNDLE_SPORT_{str(sport).upper()}", bundle))
            continue
        ok, reason, detail = _admission_check(bundle)
        if not ok:
            audit["entries"].append(_entry(
                path, EXCLUDED, reason, detail, bundle))
            continue
        team_key = _team_key(bundle["team"]["name"])
        if team_key not in intake:
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_TEAM_NOT_IN_INTAKE,
                f"TEAM_NAME_{bundle['team']['name']!r}_NOT_IN_CFB_INTAKE",
                bundle))
            continue
        kickoff = dt(bundle["fixture"]["kickoff_utc"])
        if kickoff not in intake[team_key]:
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_FIXTURE_NOT_IN_INTAKE,
                f"KICKOFF_{bundle['fixture']['kickoff_utc']!r}_NOT_AN_INTAKE_"
                f"FIXTURE_FOR_THIS_TEAM", bundle))
            continue
        team_id = str(bundle["team"]["espn_id"])
        if team_id in conflicting_ids or team_key in conflicting_names:
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_DUPLICATE,
                "TEAM_OR_ID_PREVIOUSLY_CONFLICTED", bundle))
            continue
        if team_id in mapping or team_key in admitted_names:
            # Never use lexical filename order to select an identity source.
            # Both sides of a duplicate conflict, and any later candidates,
            # fail as a group rather than preserving the first entry.
            prior_id = team_id if team_id in mapping else admitted_names[team_key]
            prior = mapping.pop(prior_id)
            prior_name = _team_key(prior["team"]["name"])
            admitted_names.pop(prior_name, None)
            conflicting_ids.update((prior_id, team_id))
            conflicting_names.update((prior_name, team_key))
            for earlier in audit["entries"]:
                if (earlier["disposition"] == ADMITTED
                        and earlier.get("team_id") == prior_id):
                    earlier["disposition"] = EXCLUDED
                    earlier["reason"] = REASON_DUPLICATE
                    earlier["detail"] = "TEAM_CONFLICT_BOTH_BUNDLES_REFUSED"
            audit["entries"].append(_entry(
                path, EXCLUDED, REASON_DUPLICATE,
                "TEAM_CONFLICT_BOTH_BUNDLES_REFUSED", bundle))
            continue
        mapping[team_id] = bundle
        admitted_names[team_key] = team_id
        audit["entries"].append(_entry(
            path, ADMITTED, REASON_ADMITTED,
            "ADMITTED_AS_CANDIDATE; FULL_EVALUATION_REMAINS_WITH_THE_"
            "BINDER_AT_CONSULT_TIME", bundle))
    audit["admitted_team_ids"] = sorted(mapping)
    return mapping, audit
