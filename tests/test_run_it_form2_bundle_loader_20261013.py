"""Trusted Form 2 bundle loader tests (Oct 13, 2026; v2 re-alignment).

The loader (sportsedge/prepricing/qb_form2_bundle_loader.py) is the
last step PR #2157 disclosed: operator-captured QB_IDENTITY_EVIDENCE
Form 2 bundle files in a local directory -> the mapping
``stage_games(qb_form2_bundles=...)`` consumes, wired through
``run_full(form2_bundles_dir=...)``. The loader never fetches; it
verifies the corrected-schema admission standard -- schema including
the exact fixture binding (event ID + opponent ESPN ID), component
hash integrity, and the RECEIPT v2 chain seal over the binding IDs,
timestamps, stamp, and sealed assertions (asserted qb_order, roster
counts, fixture kickoffs) -- matches the current intake, dedupes, and
audits every exclusion. Full evaluation stays with the evaluator at
binder consult time: QB1 is DERIVED there from the captured chart,
never trusted from the bundle.

Fixtures reuse the recorded Oct 13 samples from
tests/test_cfb_qb_identity_evidence_form2_20261013.py (OurLads chart
texts/stamps/URLs and QB rooms verbatim; scaffolding trimmed) and are
built against that file's recorded-fixture map (Delaware 48 @ MTSU
2393, event 401871067; FIU 2229 @ Jacksonville State 55, event
401871053), so bundles carry real event/opponent bindings and v2
seals from ``build_form2_bundle``. Bundle team names use the intake
display forms -- the loader's intake surface is the team name, so an
operator capture must name the team as the intake does; the
evaluator's ID+kickoff binding remains the authority.
No network is touched. Temp directories are disk-backed
(~/workspace/tmp): /tmp is a small tmpfs in this environment.
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.prepricing import factor_ingestion as fi
from sportsedge.prepricing import qb_identity_evidence as qe
from sportsedge.prepricing import qb_form2_bundle_loader as loader

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "run_it_full_form2_loader", ROOT / "artifacts" / "run_it_full.py")
full = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(full)

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
KICKOFF_ISO = "2026-10-13T23:00:00Z"
CAPTURED = "2026-10-13T13:21:00Z"
DISK_TMP = Path.home() / "workspace" / "tmp"

QB_ROOMS = {
    "48": [("5296312", "EJ Archield Jr.", "11"), ("5289314", "Tyler Bell", "7"),
           ("5153846", "Nick Minicucci", "4"), ("5224762", "Braden Streeter", "16"),
           ("5401929", "Sean Sutherland", "19"), ("5079614", "Riley Trujillo", "2")],
    "2393": [("5296411", "Stanley Anderson-Lofton", "18"), ("4565180", "Peter Costelli", "11"),
             ("5194626", "Roman Gagliano", "16"), ("5304182", "Peter Grandjean", "12"),
             ("5203853", "Mason Mallory", "10"), ("5281464", "Rocco Williams", "15")],
    "2229": [("5302764", "DJ Alexander", "5"), ("5299092", "Matt Ivaldi", "20"),
             ("4870883", "JJ Kohl", "17"), ("5153845", "Zach Marker", "11"),
             ("5158421", "Zachary Waters", "16"), ("5220127", "Trey Whirley", "23")],
}

# team_id -> (intake display name, chart url, stamp, QB row, prev kickoff)
TEAMS = {
    "48": ("Delaware Blue Hens",
           "https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/delaware/93097",
           "10/10/2026 9:07AM",
           "1. Minicucci, Nick — SR, #4 · 2. Streeter, Braden — RS SO, #16 · "
           "3. Trujillo, Riley — RS SO/TR, #2 · 4. Archield Jr., EJ — RS FR, #11",
           "2026-10-02T23:00:00Z"),
    "2393": ("Middle Tennessee Blue Raiders",
             "https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/middle-tennessee/91165",
             "10/10/2026 9:08AM",
             "1. Gagliano, Roman — RS SO, #16 · 2. Costelli, Peter — GR/TR, #11 · "
             "3. Williams, Rocco — FR, #15",
             "2026-10-03T23:00:00Z"),
    "2229": ("FIU Panthers",
             "https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/florida-international/90475",
             "10/10/2026 9:08AM",
             "1. Kohl, JJ — RS JR/TR, #17 · 2. Marker, Zach — GR/TR, #11",
             "2026-10-07T23:00:00Z"),
}

# team_id -> (event_id, opponent_espn_id): the recorded-fixture map,
# mirroring FIXTURE_OF_TEAM in the corrected Form 2 test file. A bundle
# must name its exact fixture; the v1 loader fixtures' placeholder
# opponent ("0") is exactly the loose binding correction 1 removed.
FIXTURES = {
    "48": ("401871067", "2393"),
    "2393": ("401871067", "48"),
    "2229": ("401871053", "55"),
}


def roster_payload(team_id):
    athletes = [{"id": i, "displayName": n, "fullName": n, "jersey": j,
                 "position": {"id": "8", "name": "Quarterback",
                              "abbreviation": "QB"},
                 "status": {"id": "1", "name": "Active", "type": "active"},
                 "injuries": []} for (i, n, j) in QB_ROOMS[team_id]]
    return {"timestamp": "2026-10-13T13:12:14Z", "team": {"id": team_id},
            "athletes": [{"position": "offense", "items": athletes}]}


def depth_text(team_id):
    _, url, stamp, qb_row, _ = TEAMS[team_id]
    return ("# OurLads depth chart (fixture in the recorded sample format)\n"
            f"- **URL:** {url}\n"
            f"- **On-page update stamp (verbatim):** \"Updated: {stamp} ET\"\n"
            f"- **QB row (Player 1 -> Player N):** {qb_row}\n")


def make_bundle(team_id, *, kickoff_iso=KICKOFF_ISO, event_id=None,
                opponent_id=None):
    name, url, _, _, prev = TEAMS[team_id]
    default_event, default_opponent = FIXTURES[team_id]
    roster_obj = roster_payload(team_id)
    return qe.build_form2_bundle(
        team_id=team_id, team_name=name,
        event_id=event_id if event_id is not None else default_event,
        opponent_id=opponent_id if opponent_id is not None else default_opponent,
        kickoff_utc=kickoff_iso,
        previous_game_kickoff_utc=prev,
        depth_url=url, depth_content=depth_text(team_id),
        depth_captured_at_utc=CAPTURED,
        roster_content=json.dumps(roster_obj, sort_keys=True),
        roster_captured_at_utc="2026-10-13T13:12:14Z",
        roster_athlete_count_repeat=len(qe.roster_athletes(roster_obj)))


RECORDED_CFB_LEAGUE = {
    "timestamp": "2026-10-13T12:00:41Z", "status": "success",
    "season": {"year": 2026, "type": 2, "name": "Regular Season",
               "displayName": "2026"},
    "injuries": [
        {"id": "57", "displayName": "Florida Gators", "injuries": [
            {"id": "139830", "status": "Out", "date": "2020-11-21T18:31Z",
             "athlete": {"displayName": "Kahleil Jackson",
                         "position": {"abbreviation": "WR"}}}]},
        {"id": "242", "displayName": "Rice Owls", "injuries": [
            {"status": "Active",
             "athlete": {"displayName": "Braylen Walker",
                         "position": {"abbreviation": "WR"}}}]},
        {"id": "258", "displayName": "Virginia Cavaliers", "injuries": [
            {"status": "Active",
             "athlete": {"displayName": "Will Bettridge",
                         "position": {"abbreviation": "PK"}}}]},
    ],
}


class FakeGetter:
    """Recorded-fixture getter: unmapped URLs fail like a dead network."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.mapping:
            raise OSError("UNMAPPED_URL:" + url)
        return self.mapping[url]


def cfb_mapping():
    teams = {"sports": [{"leagues": [{"teams": [
        {"team": {"id": "48", "displayName": "Delaware Blue Hens",
                  "name": "Blue Hens", "shortDisplayName": "Delaware",
                  "abbreviation": "DEL", "location": "Delaware"}},
        {"team": {"id": "2393", "displayName": "Middle Tennessee Blue Raiders",
                  "name": "Blue Raiders", "shortDisplayName": "Middle Tennessee",
                  "abbreviation": "MTSU", "location": "Middle Tennessee"}},
    ]}]}]}
    scoreboard = {"events": [{
        "id": "401871067", "date": KICKOFF_ISO,
        "competitions": [{
            # The corrected stage derives the staged event ID from the
            # competition object (owner-review correction 1); real ESPN
            # competition payloads carry it.
            "id": "401871067",
            "competitors": [
                {"homeAway": "home",
                 "team": {"id": "2393", "abbreviation": "MTSU",
                          "displayName": "Middle Tennessee Blue Raiders"}},
                {"homeAway": "away",
                 "team": {"id": "48", "abbreviation": "DEL",
                          "displayName": "Delaware Blue Hens"}}],
            "venue": {"indoor": False, "fullName": "Johnny Red Floyd Stadium",
                      "address": {"city": "Murfreesboro", "state": "TN"}},
        }],
    }]}
    return {
        f"{ESPN}/football/college-football/teams?limit=500": teams,
        f"{ESPN}/football/college-football/scoreboard?dates=20261012&limit=500": {"events": []},
        f"{ESPN}/football/college-football/scoreboard?dates=20261013&limit=500": scoreboard,
        f"{ESPN}/football/college-football/scoreboard?dates=20261014&limit=500": {"events": []},
        f"{ESPN}/football/college-football/teams/48/injuries": {},
        f"{ESPN}/football/college-football/teams/2393/injuries": {},
        f"{ESPN}/football/college-football/injuries": RECORDED_CFB_LEAGUE,
    }


def cfb_row(**kw):
    row = {"sport": "CFB", "market": "SPREAD",
           "away": "Delaware Blue Hens", "home": "Middle Tennessee Blue Raiders",
           "side": "HOME", "line": -1.5, "odds": -110,
           "commence_time": KICKOFF_ISO, "quote_captured_at": NOW.isoformat()}
    row.update(kw)
    return row


class LoaderCase(unittest.TestCase):
    def setUp(self):
        DISK_TMP.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="form2_bundles_",
                                         dir=str(DISK_TMP)))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, content):
        path = self.dir / name
        if not isinstance(content, str):
            content = json.dumps(content)
        path.write_text(content, encoding="utf-8")
        return path

    def entries_by_file(self, audit):
        return {e["file"]: e for e in audit["entries"]}


class AdmissionTests(LoaderCase):
    def test_valid_bundles_admitted_keyed_by_team_id(self):
        self.write("delaware.json", make_bundle("48"))
        self.write("mtsu.json", make_bundle("2393"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(set(mapping), {"48", "2393"})
        self.assertEqual(audit["directory_status"], "OK")
        self.assertEqual(audit["admitted_team_ids"], ["2393", "48"])
        entries = self.entries_by_file(audit)
        self.assertEqual(entries["delaware.json"]["disposition"], "ADMITTED")
        # Admission under the corrected standard names the v2 chain.
        self.assertEqual(entries["delaware.json"]["reason"],
                         loader.REASON_ADMITTED)
        self.assertEqual(entries["delaware.json"]["team_id"], "48")
        self.assertEqual(entries["mtsu.json"]["disposition"], "ADMITTED")

    def test_valid_bundle_reaches_binder_and_satisfies_identity(self):
        self.write("delaware.json", make_bundle("48"))
        self.write("mtsu.json", make_bundle("2393"))
        mapping, _ = loader.load_form2_bundles(self.dir, [cfb_row()])
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping()),
            qb_form2_bundles=mapping)
        self.assertFalse(stage["blocked"], stage["block_detail"])
        used = [f for f in stage["factors"]
                if f["factor"] == "qb_specific" and f["status"] == "USED"]
        self.assertEqual(len(used), 2)
        self.assertTrue(all(
            f["source"] == "QB_IDENTITY_EVIDENCE_FORM2_DEPTH_ROSTER_COMPOSITE"
            for f in used))
        reasons = " ".join(f["reason"] for f in used)
        self.assertEqual(reasons.count(qe.STATUS_SATISFIED), 2)
        # Availability explicitly UNKNOWN on the record, never clean.
        self.assertEqual(
            reasons.count("AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"), 2)
        # Injury points exactly 0.0: no report exists to extract from.
        self.assertEqual(stage["adjustments"]["away_injury_pts"], 0.0)
        self.assertEqual(stage["adjustments"]["home_injury_pts"], 0.0)
        # The stage result carries the availability state structurally
        # (issue #2158): the runner stamps it on the priced rows.
        self.assertEqual(stage["availability_status"],
                         qe.AVAILABILITY_UNVERIFIED)
        receipts = [r for r in stage["receipts"]
                    if r.get("source") == "QB_IDENTITY_EVIDENCE_FORM2"]
        self.assertEqual({r["resolved_qb1_athlete_id"] for r in receipts},
                         {"5153846", "5194626"})
        # The receipts the stage merges carry the verified v2 seal.
        self.assertTrue(all(r["receipt_version"] == qe.RECEIPT_VERSION
                            for r in receipts))
        self.assertTrue(all(len(r["receipt_sha256"]) == 64
                            for r in receipts))


class ReceiptChainAdmissionTests(LoaderCase):
    """Admission enforces the receipt v2 seal itself (owner-review
    correction 3): a bundle the evaluator would refuse at the chain
    never becomes a candidate."""

    def _excluded(self, bundle, detail):
        self.write("delaware.json", bundle)
        self.write("mtsu.json", make_bundle("2393"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertNotIn("48", mapping)
        self.assertIn("2393", mapping)  # a bad bundle never poisons the run
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(entry["detail"], detail)

    def test_unsealed_bundle_excluded(self):
        bundle = make_bundle("48")
        del bundle["receipt"]
        self._excluded(bundle, "RECEIPT_CHAIN_MISSING")

    def test_legacy_v1_receipt_excluded(self):
        bundle = make_bundle("48")
        bundle["receipt"] = {"version": 1, "sha256": bundle["receipt"]["sha256"]}
        self._excluded(bundle, "RECEIPT_CHAIN_MISSING")

    def test_sealed_timestamp_edited_after_capture_excluded(self):
        # The capture timestamps are post-fetch receipts under the
        # corrected schema and are chain-sealed: editing one without
        # touching either component content still breaks the seal.
        bundle = make_bundle("48")
        bundle["depth_snapshot"]["captured_at_utc"] = "2026-10-13T13:25:00Z"
        self._excluded(bundle, "RECEIPT_CHAIN_MISMATCH")


class SealedAssertionAdmissionTests(LoaderCase):
    """The repair round sealed the assertions under the chain -- the
    asserted qb_order, the roster count attestations, the fixture
    kickoffs. Editing any of them post-capture is an admission
    exclusion, with the component contents untouched."""

    def _chain_excluded(self, bundle):
        self.write("delaware.json", bundle)
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(entry["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_asserted_qb_order_edited_excluded(self):
        bundle = make_bundle("48")
        bundle["depth_snapshot"]["qb_order"][1]["jersey"] = "99"
        self._chain_excluded(bundle)

    def test_roster_count_assertion_edited_excluded(self):
        bundle = make_bundle("48")
        bundle["roster_snapshot"]["athlete_count"] += 1
        self._chain_excluded(bundle)

    def test_fixture_kickoff_edited_excluded(self):
        bundle = make_bundle("48")
        bundle["fixture"]["kickoff_utc"] = "2026-10-13T23:30:00Z"
        self._chain_excluded(bundle)


class FixtureBindingAdmissionTests(LoaderCase):
    """Exact fixture binding at admission (owner-review correction 1):
    the bundle must CARRY event ID + opponent ESPN ID; a binding that
    is internally impossible is excluded in the evaluator's own
    fixture-mismatch vocabulary; equality with the staged fixture is
    then enforced by the evaluator at consult, through this loader."""

    def test_missing_event_id_excluded_as_schema_incomplete(self):
        bundle = make_bundle("48")
        del bundle["fixture"]["event_id"]
        self.write("delaware.json", bundle)
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "BUNDLE_SCHEMA_INCOMPLETE")
        self.assertEqual(entry["detail"], "FIXTURE_EVENT_ID_MISSING")

    def test_missing_opponent_id_excluded_as_schema_incomplete(self):
        bundle = make_bundle("48")
        del bundle["fixture"]["opponent_espn_id"]
        self.write("delaware.json", bundle)
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "BUNDLE_SCHEMA_INCOMPLETE")
        self.assertEqual(entry["detail"], "FIXTURE_OPPONENT_ID_MISSING")

    def test_opponent_equal_to_subject_excluded_as_fixture_mismatch(self):
        self.write("delaware.json", make_bundle("48", opponent_id="48"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(entry["detail"], "OPPONENT_EQUALS_SUBJECT_TEAM")

    def test_wrong_event_bundle_admitted_but_stage_blocks_on_binding(self):
        # Self-consistently sealed for a DIFFERENT event: admission can
        # verify the seal but cannot know the staged event ID (intake
        # carries names + kickoffs, not ESPN event IDs), so the bundle
        # is admitted as a candidate -- and the evaluator's exact
        # binding refuses it at consult. Admission is not a pass.
        self.write("delaware.json", make_bundle("48", event_id="401871999"))
        self.write("mtsu.json", make_bundle("2393"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(set(mapping), {"48", "2393"})
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping()),
            qb_form2_bundles=mapping)
        self.assertTrue(stage["blocked"])
        reasons = " ".join(f["reason"] for f in stage["factors"])
        self.assertIn("FORM2_FAILED:QB_EVIDENCE_FIXTURE_MISMATCH", reasons)


class ExclusionTests(LoaderCase):
    def test_tampered_hash_excluded_and_audited_others_unaffected(self):
        bundle = make_bundle("48")
        bundle["depth_snapshot"]["content"] += "\n<!-- tampered -->"
        self.write("delaware.json", bundle)
        self.write("mtsu.json", make_bundle("2393"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertNotIn("48", mapping)
        self.assertIn("2393", mapping)  # a bad bundle never poisons the run
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], qe.STATUS_HASH_MISMATCH)
        self.assertIn("DEPTH_CONTENT_SHA256_MISMATCH", entry["detail"])

    def test_malformed_json_excluded_and_audited(self):
        self.write("broken.json", "{not json")
        self.write("mtsu.json", make_bundle("2393"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(set(mapping), {"2393"})
        entry = self.entries_by_file(audit)["broken.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "BUNDLE_JSON_MALFORMED")

    def test_team_not_in_intake_excluded_and_audited(self):
        self.write("fiu.json", make_bundle("2229"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["fiu.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "TEAM_NOT_IN_INTAKE")
        self.assertEqual(entry["team_id"], "2229")

    def test_fixture_not_in_intake_excluded_and_audited(self):
        self.write("delaware.json",
                   make_bundle("48", kickoff_iso="2026-10-20T23:00:00Z"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["delaware.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "FIXTURE_NOT_IN_INTAKE")

    def test_duplicate_bundle_for_team_excluded_and_audited(self):
        self.write("a_delaware.json", make_bundle("48"))
        self.write("b_delaware.json", make_bundle("48"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entries = self.entries_by_file(audit)
        # Conflict poisons both names: never trust lexical winner.
        self.assertEqual(entries["a_delaware.json"]["disposition"], "EXCLUDED")
        self.assertEqual(entries["b_delaware.json"]["disposition"], "EXCLUDED")
        self.assertEqual(entries["a_delaware.json"]["reason"], loader.REASON_DUPLICATE)
        self.assertEqual(entries["b_delaware.json"]["reason"], loader.REASON_DUPLICATE)


    def test_three_duplicate_bundles_refuse_entire_conflict(self):
        for name in ("z.json", "a.json", "m.json"):
            self.write(name, make_bundle("48"))
        self.write("good_mtsu.json", make_bundle("2393"))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(set(mapping), {"2393"})
        entries = self.entries_by_file(audit)
        for name in ("a.json", "m.json", "z.json"):
            self.assertEqual(entries[name]["disposition"], "EXCLUDED")
            self.assertEqual(entries[name]["reason"], loader.REASON_DUPLICATE)

    def test_symlink_bundle_refused_without_following(self):
        self.write("good_mtsu.json", make_bundle("2393"))
        target = self.write("elsewhere.txt", make_bundle("48"))
        (self.dir / "z_link.json").symlink_to(target)
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(set(mapping), {"2393"})
        entry = self.entries_by_file(audit)["z_link.json"]
        self.assertEqual(entry["reason"], loader.REASON_UNSAFE_FILE)

    def test_symlink_directory_refused(self):
        alias = self.dir.parent / (self.dir.name + "_alias")
        alias.symlink_to(self.dir, target_is_directory=True)
        self.addCleanup(alias.unlink)
        mapping, audit = loader.load_form2_bundles(alias, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["directory_status"], "UNSAFE_DIRECTORY_SYMLINK")

    def test_oversized_bundle_is_excluded(self):
        self.write("oversized.json", "x" * (loader.MAX_BUNDLE_BYTES + 1))
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(self.entries_by_file(audit)["oversized.json"]["reason"],
                         loader.REASON_UNSAFE_FILE)

    def test_non_cfb_bundle_ignored_and_audited(self):
        bundle = make_bundle("48")
        bundle["sport"] = "NFL"  # the chain does not seal this field;
        # the sport screen runs before admission verification, as before
        self.write("nfl.json", bundle)
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)["nfl.json"]
        self.assertEqual(entry["disposition"], "IGNORED")
        self.assertEqual(entry["reason"], "NON_CFB_BUNDLE")


class DirectoryRegressionTests(LoaderCase):
    def _baseline_stage(self):
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping()))
        return stage

    def test_empty_directory_staging_identical_to_no_loader(self):
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["directory_status"], "EMPTY")
        self.assertEqual(audit["entries"], [])
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping()),
            qb_form2_bundles=mapping or None)
        self.assertEqual(stage, self._baseline_stage())

    def test_missing_directory_staging_identical_to_no_loader(self):
        missing = self.dir / "does_not_exist"
        mapping, audit = loader.load_form2_bundles(missing, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["directory_status"], "MISSING")
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping()),
            qb_form2_bundles=mapping or None)
        self.assertEqual(stage, self._baseline_stage())
        # And the baseline itself still blocks at the QB gate, as today.
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"],
                         fi.BLOCK_QB_IDENTITY_UNVERIFIED)


class RunnerWiringTests(LoaderCase):
    def _lenient_getter(self):
        mapping = cfb_mapping()
        return lambda url: mapping.get(url, {})

    def test_run_full_wires_bundles_and_audits_loader(self):
        self.write("delaware.json", make_bundle("48"))
        self.write("mtsu.json", make_bundle("2393"))
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=self._lenient_getter(),
                             form2_bundles_dir=self.dir)
        audit = card["qb_form2_bundle_loader_audit"]
        self.assertEqual(audit["schema"],
                         "SPORTSEDGE_QB_FORM2_BUNDLE_LOADER_AUDIT_V1")
        self.assertEqual(audit["admitted_team_ids"], ["2393", "48"])
        self.assertTrue(all(e["reason"] == loader.REASON_ADMITTED
                            for e in audit["entries"]))
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        self.assertFalse(entry["blocked"])
        qb = [f for f in entry["factors"] if f["factor"] == "qb_specific"]
        self.assertTrue(any(f["status"] == "USED" for f in qb))
        reasons = " ".join(f["reason"] for f in qb)
        self.assertIn("AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT",
                      reasons)
        self.assertEqual(entry["adjustments"]["away_injury_pts"], 0.0)
        self.assertEqual(entry["adjustments"]["home_injury_pts"], 0.0)

    def test_run_full_without_bundles_dir_has_no_loader_audit(self):
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=self._lenient_getter())
        self.assertNotIn("qb_form2_bundle_loader_audit", card)
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        # Without Form 2 the same fixture still blocks at the QB gate.
        self.assertTrue(entry["blocked"])
        self.assertEqual(entry["block_reason"],
                         "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED")

    def test_run_full_form2_game_is_research_only_end_to_end(self):
        # Issue #2158, asserted on the composed runner -- not at the
        # gate function: bundles arrive through the loader, the stage
        # satisfies identity via Form 2, the game is priced, and the
        # priced rows carry the availability field and come out
        # research-only with every actionable surface empty. (The
        # offline fixture yields no engine probability for this game,
        # so the row surfaces nowhere regardless; that the guard
        # demotes even a positive-EV would-be play is pinned by
        # tests/test_availability_research_only_gate_20261013.py.)
        self.write("delaware.json", make_bundle("48"))
        self.write("mtsu.json", make_bundle("2393"))
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=self._lenient_getter(),
                             form2_bundles_dir=self.dir)
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        self.assertFalse(entry["blocked"])  # the game was priced
        rows = [r for r in card["evaluated_rows"]
                if r.get("input_index") == 0]
        self.assertEqual(len(rows), 1)
        (row,) = rows
        self.assertEqual(row["availability_status"],
                         qe.AVAILABILITY_UNVERIFIED)
        self.assertIs(row["research_only"], True)
        self.assertEqual(
            row["play_blocked_reason"],
            "QB_AVAILABILITY_UNVERIFIED_CANNOT_SURFACE_AS_PLAY")
        self.assertEqual(card["edges"], [])
        self.assertEqual(card["independent_candidates"], [])
        self.assertEqual(card["prop_candidates"], [])
        self.assertEqual(
            card["play_gate"]["availability_unverified_max_surface"],
            "RESEARCH_ONLY")


if __name__ == "__main__":
    unittest.main()
