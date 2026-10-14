"""Wrong-type JSON matrix for the CFB Form 2 evidence boundaries.

Same class as the owner's PR #2168 finding (valid JSON of the wrong
type crashing an evidence consumer instead of producing a named
failure), audited across:

- ``qb_identity_evidence.evaluate_form2_bundle`` -- bundle sub-objects
  (team / fixture / previous_game / snapshots / receipt) of the wrong
  type, and load-bearing fields of the wrong type;
- ``qb_identity_evidence.receipt_chain_fields`` -- the chain is public
  and loader-called, so its inputs are a boundary too;
- ``qb_form2_bundle_loader.load_form2_bundles`` -- admission and the
  audit-entry builder on parsed JSON of the wrong type.

Contract under test: wrong-typed parsed JSON NEVER raises out of
these boundaries. It produces the module's existing named outcomes --
a QB_EVIDENCE_* / QB_DEPTH_* status with its detail reason, or a
loader audit exclusion.

Loader-section re-contract (Form 2 landing step; see RECONTRACT.md):
the loader is now the pinned-archive runtime adapter (ADAPTER.md).
Its own read_text/UnicodeDecodeError defect is closed BY DELEGATION
-- all object IO and strict parsing belong to the archive module --
and admission requires the caller's external pin. The
LoaderWrongTypeTests below therefore place each hostile object in
the archive root as a content-addressed object and drive the loader
under a pin: pin gate first, then the archive read/parse, the sport
screen, unique manifest coverage, and the unchanged admission
standard. The evaluator and chain sections above are untouched: the
adapter changed the loader's trust contract, not theirs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.prepricing import qb_evidence_archive as archive
from sportsedge.prepricing import qb_form2_bundle_loader as loader
from sportsedge.prepricing import qb_identity_evidence as qe

NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 10, 13, 23, 0, tzinfo=timezone.utc)
KICKOFF_ISO = "2026-10-13T23:00:00Z"
CAPTURED = "2026-10-13T13:21:00Z"
DISK_TMP = Path.home() / "workspace" / "tmp"

TEAM_ID = "48"
TEAM_NAME = "Delaware Blue Hens"
EVENT_ID = "401871067"
OPPONENT_ID = "2393"
CHART_URL = ("https://www.ourlads.com/ncaa-football-depth-charts/"
             "depth-chart/delaware/93097")
CHART_STAMP = "10/10/2026 9:07AM"
QB_ROW = ("1. Minicucci, Nick — SR, #4 · 2. Streeter, Braden — RS SO, #16 · "
          "3. Trujillo, Riley — RS SO/TR, #2 · 4. Archield Jr., EJ — RS FR, #11")
PREV_ISO = "2026-10-02T23:00:00Z"
QB_ROOM = [("5296312", "EJ Archield Jr.", "11"),
           ("5289314", "Tyler Bell", "7"),
           ("5153846", "Nick Minicucci", "4"),
           ("5224762", "Braden Streeter", "16"),
           ("5401929", "Sean Sutherland", "19"),
           ("5079614", "Riley Trujillo", "2")]


def roster_payload():
    athletes = [{"id": i, "displayName": n, "fullName": n, "jersey": j,
                 "position": {"id": "8", "name": "Quarterback",
                              "abbreviation": "QB"},
                 "status": {"id": "1", "name": "Active", "type": "active"},
                 "injuries": []} for (i, n, j) in QB_ROOM]
    return {"timestamp": "2026-10-13T13:12:14Z", "team": {"id": TEAM_ID},
            "athletes": [{"position": "offense", "items": athletes}]}


def depth_text():
    return ("# OurLads depth chart (fixture in the recorded sample format)\n"
            f"- **URL:** {CHART_URL}\n"
            f"- **On-page update stamp (verbatim):** "
            f"\"Updated: {CHART_STAMP} ET\"\n"
            f"- **QB row (Player 1 -> Player N):** {QB_ROW}\n")


def make_bundle():
    roster_obj = roster_payload()
    athletes = qe.roster_athletes(roster_obj)
    return qe.build_form2_bundle(
        team_id=TEAM_ID, team_name=TEAM_NAME,
        event_id=EVENT_ID, opponent_id=OPPONENT_ID,
        kickoff_utc=KICKOFF_ISO,
        previous_game_kickoff_utc=PREV_ISO,
        depth_url=CHART_URL, depth_content=depth_text(),
        depth_captured_at_utc=CAPTURED,
        roster_content=json.dumps(roster_obj, sort_keys=True),
        roster_captured_at_utc="2026-10-13T13:12:14Z",
        roster_athlete_count_repeat=len(athletes))


def evaluate(bundle):
    return qe.evaluate_form2_bundle(
        bundle, team_id=TEAM_ID, kickoff=KICKOFF, now=NOW,
        event_id=EVENT_ID, home_team_id=OPPONENT_ID, away_team_id=TEAM_ID)


def rechain(bundle):
    """Re-seal a mutated bundle so a hostile case reaches the check it
    targets (mirrors the helper in the Form 2 battery)."""
    depth = bundle["depth_snapshot"]
    depth["sha256"] = qe.sha256_text(depth["content"])
    roster_snap = bundle["roster_snapshot"]
    roster_snap["sha256"] = qe.sha256_text(roster_snap["content"])
    bundle["receipt"] = {"version": qe.RECEIPT_VERSION,
                         "sha256": qe.receipt_chain_sha256(bundle)}
    return bundle


def mutated(**top_level):
    bundle = make_bundle()
    bundle.update(top_level)
    return bundle


class EvaluatorTopLevelTests(unittest.TestCase):
    def test_non_object_bundles_fail_named(self):
        for bad in ([1, 2], "bundle", 42, None, True):
            result = evaluate(bad)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], qe.STATUS_MISSING)
            self.assertEqual(result["detail"], "BUNDLE_ABSENT")

    def test_valid_bundle_control_satisfies(self):
        result = evaluate(make_bundle())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], qe.STATUS_SATISFIED)


class EvaluatorSubObjectWrongTypeTests(unittest.TestCase):
    """team / fixture / previous_game as truthy non-objects: the
    ``bundle.get(x) or {}`` idiom crashed on these pre-fix."""

    def test_team_as_list_fails_named(self):
        result = evaluate(mutated(team=[TEAM_ID]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_MISSING)
        self.assertEqual(result["detail"], "TEAM_BINDING_MISMATCH")

    def test_team_as_string_fails_named(self):
        result = evaluate(mutated(team=TEAM_ID))
        self.assertEqual(result["detail"], "TEAM_BINDING_MISMATCH")

    def test_team_as_number_fails_named(self):
        result = evaluate(mutated(team=48))
        self.assertEqual(result["detail"], "TEAM_BINDING_MISMATCH")

    def test_team_as_null_already_safe(self):
        result = evaluate(mutated(team=None))
        self.assertEqual(result["detail"], "TEAM_BINDING_MISMATCH")

    def test_fixture_as_list_fails_named(self):
        result = evaluate(mutated(fixture=["x"]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(result["detail"], "EVENT_ID_MISMATCH")

    def test_fixture_as_string_fails_named(self):
        result = evaluate(mutated(fixture="x"))
        self.assertEqual(result["detail"], "EVENT_ID_MISMATCH")

    def test_fixture_as_number_fails_named(self):
        result = evaluate(mutated(fixture=5))
        self.assertEqual(result["detail"], "EVENT_ID_MISMATCH")

    def test_previous_game_as_list_fails_at_chain_named(self):
        result = evaluate(mutated(previous_game=["x"]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_previous_game_as_string_fails_at_chain_named(self):
        result = evaluate(mutated(previous_game="x"))
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_depth_snapshot_as_string_already_safe(self):
        result = evaluate(mutated(depth_snapshot="x"))
        self.assertEqual(result["status"], qe.STATUS_MISSING)
        self.assertEqual(result["detail"], "COMPONENT_SNAPSHOT_MISSING")

    def test_roster_snapshot_as_list_already_safe(self):
        result = evaluate(mutated(roster_snapshot=[1]))
        self.assertEqual(result["detail"], "COMPONENT_SNAPSHOT_MISSING")

    def test_receipt_as_list_already_safe(self):
        result = evaluate(mutated(receipt=[1]))
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISSING")

    def test_receipt_version_as_list_already_safe(self):
        bundle = make_bundle()
        bundle["receipt"] = {"version": ["2"], "sha256": "x"}
        result = evaluate(bundle)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISSING")


class ReceiptChainFieldsWrongTypeTests(unittest.TestCase):
    """receipt_chain_sha256 is public and loader-called: its field
    reads must be total over wrong-typed sub-objects."""

    def test_all_sub_objects_wrong_type(self):
        bundle = mutated(team=[1], fixture="x", depth_snapshot=[1],
                         roster_snapshot=5, previous_game="x")
        fields = qe.receipt_chain_fields(bundle)
        self.assertIsNone(fields["team_id"])
        self.assertIsNone(fields["event_id"])
        self.assertIsNone(fields["previous_game_kickoff_utc"])
        self.assertIsNone(fields["depth_qb_order"])
        self.assertIsNone(fields["roster_athlete_count"])
        self.assertIsInstance(qe.receipt_chain_sha256(bundle), str)

    def test_bundle_itself_wrong_type(self):
        fields = qe.receipt_chain_fields([1, 2])
        self.assertIsNone(fields["team_id"])
        self.assertIsInstance(qe.receipt_chain_sha256("x"), str)


class EvaluatorFieldWrongTypeTests(unittest.TestCase):
    """Load-bearing fields of the wrong type, re-sealed so each case
    reaches the semantic check it targets."""

    def test_qb_order_as_string_is_assertion_mismatch(self):
        bundle = make_bundle()
        bundle["depth_snapshot"]["qb_order"] = "Minicucci, Nick"
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_QB1_ASSERTION_MISMATCH)
        self.assertEqual(result["detail"],
                         "ASSERTED_QB_ORDER_LENGTH_OR_SHAPE_MISMATCH")

    def test_roster_count_as_string_coerces_by_design(self):
        bundle = make_bundle()
        bundle["roster_snapshot"]["athlete_count"] = "6"
        bundle["roster_snapshot"]["athlete_count_repeat"] = "6"
        result = evaluate(rechain(bundle))
        self.assertTrue(result["ok"], result)

    def test_roster_count_as_list_is_named_incomplete(self):
        bundle = make_bundle()
        bundle["roster_snapshot"]["athlete_count"] = [6]
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_ROSTER_INCOMPLETE)
        self.assertEqual(result["detail"], "ROSTER_COUNT_ATTESTATION_MISSING")

    def test_captured_at_as_number_is_unreadable_named(self):
        bundle = make_bundle()
        bundle["depth_snapshot"]["captured_at_utc"] = 1760000000
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_STALE)
        self.assertEqual(result["detail"], "CAPTURE_TIMESTAMP_UNREADABLE")

    def test_team_espn_id_as_list_already_safe(self):
        bundle = make_bundle()
        bundle["team"]["espn_id"] = [48]
        result = evaluate(bundle)
        self.assertEqual(result["detail"], "TEAM_BINDING_MISMATCH")

    def test_fixture_event_id_as_object_already_safe(self):
        bundle = make_bundle()
        bundle["fixture"]["event_id"] = {"id": EVENT_ID}
        result = evaluate(bundle)
        self.assertEqual(result["detail"], "EVENT_ID_MISMATCH")

    def test_fixture_kickoff_as_number_already_safe(self):
        bundle = make_bundle()
        bundle["fixture"]["kickoff_utc"] = 1760000000
        result = evaluate(bundle)
        self.assertEqual(result["detail"], "FIXTURE_KICKOFF_MISMATCH")

    def test_qb1_position_as_list_fails_named(self):
        bundle = make_bundle()
        roster_obj = roster_payload()
        for group in roster_obj["athletes"]:
            for athlete in group["items"]:
                if athlete["id"] == "5153846":
                    athlete["position"] = ["QB"]
        bundle["roster_snapshot"]["content"] = json.dumps(
            roster_obj, sort_keys=True)
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertTrue(result["status"])

    def test_qb1_name_as_number_fails_named(self):
        bundle = make_bundle()
        roster_obj = roster_payload()
        for group in roster_obj["athletes"]:
            for athlete in group["items"]:
                if athlete["id"] == "5153846":
                    athlete["displayName"] = 42
                    athlete["fullName"] = 42
        bundle["roster_snapshot"]["content"] = json.dumps(
            roster_obj, sort_keys=True)
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertTrue(result["status"])


def cfb_row():
    return {"sport": "CFB", "market": "SPREAD",
            "away": "Delaware Blue Hens",
            "home": "Middle Tennessee Blue Raiders",
            "side": "HOME", "line": -1.5, "odds": -110,
            "commence_time": KICKOFF_ISO,
            "quote_captured_at": NOW.isoformat()}


class LoaderWrongTypeTests(unittest.TestCase):
    """Re-contracted to the pinned-archive adapter contract. The
    retired section wrote plain-named files into a trusted directory
    and asserted unpinned admission/exclusion. Under the adapter
    contract an object reaches the checks below only as a
    content-addressed archive object under the caller's external
    pin, and a bundle reaches the admission standard only when the
    pinned manifest uniquely covers it. The intent of every case is
    unchanged: wrong-typed parsed JSON produces the module's named
    outcome and never raises out of the loader."""

    def setUp(self):
        DISK_TMP.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="form2_wrongtype_",
                                         dir=str(DISK_TMP)))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _publish(self, raw):
        """Store raw bytes as a content-addressed archive object;
        return its file name."""
        digest = hashlib.sha256(raw).hexdigest()
        name = f"{digest}.json"
        (self.dir / name).write_bytes(raw)
        return name

    def _publish_bundle(self, bundle):
        return self._publish(json.dumps(
            bundle, sort_keys=True, separators=(",", ":")).encode())

    def _cover(self, bundle, name):
        """The manifest receipt entry covering a published bundle,
        derived from the bundle's own binding fields with
        recorded_at = NOW (after both captures, strictly
        pre-kickoff), as the adapter's agreement check requires."""
        fixture = bundle["fixture"]
        return {"team_id": TEAM_ID,
                "event_id": str(fixture["event_id"]),
                "home_team_id": OPPONENT_ID, "away_team_id": TEAM_ID,
                "kickoff_utc": fixture["kickoff_utc"],
                "recorded_at_utc": NOW.isoformat(),
                "bundle_sha256": name[:-len(".json")]}

    def _load(self, covers=()):
        raw = json.dumps({"schema": archive.SCHEMA,
                          "entries": list(covers)},
                         sort_keys=True, separators=(",", ":")).encode()
        pin = hashlib.sha256(raw).hexdigest()
        return loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)

    def _entry_for(self, audit, name):
        return {e["file"]: e for e in audit["entries"]}[name]

    def test_valid_bundle_control_admitted(self):
        # The control now does both halves of the adapter contract:
        # the same valid bundle in the same root admits NOTHING
        # without the external pin (the retired unpinned admission),
        # and admits under the pin (the surviving intent).
        bundle = make_bundle()
        name = self._publish_bundle(bundle)
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["pin_status"], "ABSENT")
        self.assertIn(loader.REASON_PIN_REQUIRED,
                      [e["reason"] for e in audit["entries"]])
        mapping, audit = self._load([self._cover(bundle, name)])
        self.assertEqual(sorted(mapping), [TEAM_ID])
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.ADMITTED)

    def test_top_level_array_excluded_named(self):
        name = self._publish(b"[1, 2, 3]")
        mapping, audit = self._load()
        self.assertEqual(mapping, {})
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertEqual(entry["reason"], loader.REASON_NOT_AN_OBJECT)

    def test_top_level_string_excluded_named(self):
        name = self._publish(b'"bundle"')
        _, audit = self._load()
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["reason"], loader.REASON_NOT_AN_OBJECT)

    def test_top_level_number_excluded_named(self):
        name = self._publish(b"42")
        _, audit = self._load()
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["reason"], loader.REASON_NOT_AN_OBJECT)

    def test_team_as_list_excluded_with_audit_entry(self):
        # Admission rejects the bundle (schema), and building the
        # audit entry must not crash on the same wrong type.
        bundle = mutated(team=[1, 2])
        name = self._publish_bundle(bundle)
        mapping, audit = self._load([self._cover(bundle, name)])
        self.assertEqual(mapping, {})
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertEqual(entry["reason"], loader.REASON_SCHEMA_INCOMPLETE)
        self.assertIsNone(entry["team_id"])

    def test_team_as_string_excluded_with_audit_entry(self):
        bundle = mutated(team=TEAM_NAME)
        name = self._publish_bundle(bundle)
        _, audit = self._load([self._cover(bundle, name)])
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertEqual(entry["reason"], loader.REASON_SCHEMA_INCOMPLETE)

    def test_non_cfb_bundle_with_wrong_type_team_ignored(self):
        bundle = mutated(team=[1, 2])
        bundle["sport"] = "NFL"
        name = self._publish_bundle(bundle)
        _, audit = self._load()
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.IGNORED)
        self.assertEqual(entry["reason"], loader.REASON_NON_CFB)

    def test_previous_game_as_list_excluded_at_chain(self):
        bundle = mutated(previous_game=[1, 2])
        name = self._publish_bundle(bundle)
        mapping, audit = self._load([self._cover(bundle, name)])
        self.assertEqual(mapping, {})
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertEqual(entry["reason"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(entry["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_sport_as_list_ignored_named(self):
        bundle = mutated()
        bundle["sport"] = ["CFB"]
        name = self._publish_bundle(bundle)
        _, audit = self._load()
        entry = self._entry_for(audit, name)
        self.assertEqual(entry["disposition"], loader.IGNORED)
        self.assertEqual(entry["reason"], loader.REASON_NON_CFB)


if __name__ == "__main__":
    unittest.main()
