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
loader audit exclusion. (The loader's read_text/UnicodeDecodeError
defect is already known and disclosed and is owned by the archive
convergence rework; it is deliberately NOT covered here.)
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

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
    def setUp(self):
        DISK_TMP.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="form2_wrongtype_",
                                         dir=str(DISK_TMP)))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, name, content):
        path = self.dir / name
        path.write_text(content if isinstance(content, str)
                        else json.dumps(content), encoding="utf-8")
        return path

    def _load(self):
        return loader.load_form2_bundles(self.dir, [cfb_row()])

    def _entry_for(self, audit, name):
        return {e["file"]: e for e in audit["entries"]}[name]

    def test_valid_bundle_control_admitted(self):
        self._write("delaware.json", make_bundle())
        mapping, audit = self._load()
        self.assertEqual(sorted(mapping), [TEAM_ID])
        entry = self._entry_for(audit, "delaware.json")
        self.assertEqual(entry["disposition"], loader.ADMITTED)

    def test_top_level_array_excluded_named(self):
        self._write("array.json", [1, 2, 3])
        mapping, audit = self._load()
        self.assertEqual(mapping, {})
        entry = self._entry_for(audit, "array.json")
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertEqual(entry["reason"], loader.REASON_NOT_AN_OBJECT)

    def test_top_level_string_excluded_named(self):
        self._write("string.json", '"bundle"')
        _, audit = self._load()
        entry = self._entry_for(audit, "string.json")
        self.assertEqual(entry["reason"], loader.REASON_NOT_AN_OBJECT)

    def test_top_level_number_excluded_named(self):
        self._write("number.json", "42")
        _, audit = self._load()
        entry = self._entry_for(audit, "number.json")
        self.assertEqual(entry["reason"], loader.REASON_NOT_AN_OBJECT)

    def test_team_as_list_excluded_with_audit_entry(self):
        # Admission rejects the bundle (schema), and building the
        # audit entry must not crash on the same wrong type.
        self._write("badteam.json", mutated(team=[1, 2]))
        mapping, audit = self._load()
        self.assertEqual(mapping, {})
        entry = self._entry_for(audit, "badteam.json")
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertIsNone(entry["team_id"])

    def test_team_as_string_excluded_with_audit_entry(self):
        self._write("badteam.json", mutated(team=TEAM_NAME))
        _, audit = self._load()
        entry = self._entry_for(audit, "badteam.json")
        self.assertEqual(entry["disposition"], loader.EXCLUDED)

    def test_non_cfb_bundle_with_wrong_type_team_ignored(self):
        bundle = mutated(team=[1, 2])
        bundle["sport"] = "NFL"
        self._write("nfl.json", bundle)
        _, audit = self._load()
        entry = self._entry_for(audit, "nfl.json")
        self.assertEqual(entry["disposition"], loader.IGNORED)

    def test_previous_game_as_list_excluded_at_chain(self):
        self._write("badprev.json", mutated(previous_game=[1, 2]))
        mapping, audit = self._load()
        self.assertEqual(mapping, {})
        entry = self._entry_for(audit, "badprev.json")
        self.assertEqual(entry["disposition"], loader.EXCLUDED)
        self.assertEqual(entry["reason"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(entry["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_sport_as_list_ignored_named(self):
        bundle = mutated()
        bundle["sport"] = ["CFB"]
        self._write("listsport.json", bundle)
        _, audit = self._load()
        entry = self._entry_for(audit, "listsport.json")
        self.assertEqual(entry["disposition"], loader.IGNORED)


if __name__ == "__main__":
    unittest.main()
