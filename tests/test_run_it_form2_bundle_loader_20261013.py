"""Form 2 bundle loader tests (Oct 13, 2026; v2 re-alignment;
RE-CONTRACTED to the pinned-archive adapter contract as the Form 2
landing step -- see ADAPTER.md and RECONTRACT.md).

The loader (sportsedge/prepricing/qb_form2_bundle_loader.py) is the
runtime adapter for PR #2157's Form 2 evaluator: operator-captured
QB_IDENTITY_EVIDENCE Form 2 bundles, preserved as content-addressed
objects in an archive root -> the mapping
``stage_games(qb_form2_bundles=...)`` consumes, wired through
``run_full(form2_bundles_dir=..., form2_manifest_sha256=...)``. The
loader never fetches.

Original contract (retired): the loader trusted the directory --
plain-named bundle files were admitted on the strength of the
receipt v2 chain alone, and duplicate bundles for a team resolved
deterministically first-wins. The owner's archive-convergence
verdict retired that contract, and this battery is re-contracted to
the adapter that replaced it:

  * Admission requires an EXTERNAL PIN -- the archive manifest's
    SHA-256, supplied by the caller from an independent channel,
    never read from the bundle directory. No pin -> nothing is
    admitted (``pin_status: ABSENT``, an ``ARCHIVE_PIN_REQUIRED``
    audit entry) and the run is otherwise pre-loader behavior.
  * Objects are content-addressed: a bundle is stored at
    ``<sha256 of its bytes>.json``; the pinned manifest's receipt
    entry must uniquely cover that digest and agree with the bundle
    (team, event, home/away set, kickoff, and the recorded_at
    ordering: at/after both snapshot captures, strictly pre-kickoff).
  * Duplicates FAIL CLOSED. A pinned manifest carrying two receipts
    for one fixture/team refuses both objects
    (``ARCHIVE_RECEIPT_NOT_UNIQUE``); the adapter's first-wins
    ``DUPLICATE_TEAM_BUNDLE`` detail is gone -- where two surviving
    candidates for one team remain, ALL are refused with that reason.
  * The admission standard itself is unchanged: schema including the
    exact fixture binding (event ID + opponent ESPN ID), component
    hash integrity, and the RECEIPT v2 chain seal over the binding
    IDs, timestamps, stamp, and sealed assertions (asserted qb_order,
    roster counts, fixture kickoffs). Full evaluation stays with the
    evaluator at binder consult time: QB1 is DERIVED there from the
    captured chart, never trusted from the bundle.

Fixtures reuse the recorded Oct 13 samples from
tests/test_cfb_qb_identity_evidence_form2_20261013.py (OurLads chart
texts/stamps/URLs and QB rooms verbatim; scaffolding trimmed) and are
built against that file's recorded-fixture map (Delaware 48 @ MTSU
2393, event 401871067; FIU 2229 @ Jacksonville State 55, event
401871053), so bundles carry real event/opponent bindings and v2
seals from ``build_form2_bundle``. Bundle team names use the intake
display forms -- the loader's intake surface is the team name, so an
operator capture must name the team as the intake does; the
evaluator's ID+kickoff binding remains the authority. The pin
manifests in these fixtures are composed in-test as the caller's
independent channel: each entry is derived from its bundle's own
binding fields with ``recorded_at`` = NOW (after both captures,
strictly pre-kickoff), exactly the agreement the adapter verifies.
(The writer -> manifest -> adapter chain itself is exercised by
tests/test_cfb_form2_loader_adapter_20261013.py.)
No network is touched. Temp directories are disk-backed
(~/workspace/tmp): /tmp is a small tmpfs in this environment.
"""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.prepricing import factor_ingestion as fi
from sportsedge.prepricing import qb_evidence_archive as archive
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

# team_id -> (event_id, opponent_espn_id, home_espn_id, away_espn_id):
# the recorded-fixture map, mirroring FIXTURE_OF_TEAM in the corrected
# Form 2 test file. A bundle must name its exact fixture; the v1 loader
# fixtures' placeholder opponent ("0") is exactly the loose binding
# correction 1 removed.
FIXTURES = {
    "48": ("401871067", "2393", "2393", "48"),
    "2393": ("401871067", "48", "2393", "48"),
    "2229": ("401871053", "55", "55", "2229"),
}


def roster_payload(team_id):
    athletes = [{"id": i, "displayName": n, "fullName": n, "jersey": j,
                 "position": {"id": "8", "name": "Quarterback",
                              "abbreviation": "QB"},
                 "status": {"id": "1", "name": "Active", "type": "active"},
                 "injuries": []} for (i, n, j) in QB_ROOMS[team_id]]
    return {"timestamp": "2026-10-13T13:12:14Z", "team": {"id": team_id},
            "athletes": [{"position": "offense", "items": athletes}]}


def depth_text(team_id, stamp=None):
    _, url, default_stamp, qb_row, _ = TEAMS[team_id]
    return ("# OurLads depth chart (fixture in the recorded sample format)\n"
            f"- **URL:** {url}\n"
            f"- **On-page update stamp (verbatim):** "
            f"\"Updated: {stamp or default_stamp} ET\"\n"
            f"- **QB row (Player 1 -> Player N):** {qb_row}\n")


def make_bundle(team_id, *, kickoff_iso=KICKOFF_ISO, event_id=None,
                opponent_id=None, depth_stamp=None, depth_captured=CAPTURED):
    name, url, _, _, prev = TEAMS[team_id]
    default_event, default_opponent = FIXTURES[team_id][:2]
    roster_obj = roster_payload(team_id)
    return qe.build_form2_bundle(
        team_id=team_id, team_name=name,
        event_id=event_id if event_id is not None else default_event,
        opponent_id=opponent_id if opponent_id is not None else default_opponent,
        kickoff_utc=kickoff_iso,
        previous_game_kickoff_utc=prev,
        depth_url=url, depth_content=depth_text(team_id, stamp=depth_stamp),
        depth_captured_at_utc=depth_captured,
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

    # -- Pinned-archive fixture helpers (re-contract) ----------------
    # The retired fixtures wrote plain-named files (delaware.json)
    # into a trusted directory. Under the adapter contract a bundle
    # is a content-addressed archive object and admission hangs on
    # the caller's external pin; these helpers publish objects and
    # compose the pin manifest the way a caller's independent
    # channel would deliver it.

    def publish(self, bundle):
        """Store a bundle dict as a content-addressed archive object;
        return its digest (the object's file stem)."""
        raw = json.dumps(bundle, sort_keys=True,
                         separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (self.dir / f"{digest}.json").write_bytes(raw)
        return digest

    def publish_raw(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        (self.dir / f"{digest}.json").write_bytes(raw)
        return digest

    def cover(self, bundle, digest):
        """The manifest receipt entry for a published bundle, derived
        from the bundle's own binding fields (team, event, kickoff)
        with the recorded fixture's home/away orientation and
        recorded_at = NOW -- after both snapshot captures, strictly
        pre-kickoff, as the adapter's agreement check requires."""
        team_id = str(bundle["team"]["espn_id"])
        fixture = bundle["fixture"]
        recorded_event, _, home_id, away_id = FIXTURES[team_id]
        return {"team_id": team_id,
                "event_id": str(fixture.get("event_id") or recorded_event),
                "home_team_id": home_id, "away_team_id": away_id,
                "kickoff_utc": fixture["kickoff_utc"],
                "recorded_at_utc": NOW.isoformat(),
                "bundle_sha256": digest}

    def manifest_for(self, entries):
        raw = json.dumps({"schema": archive.SCHEMA,
                          "entries": list(entries)},
                         sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest(), raw

    def load_pinned(self, entries, rows=None):
        pin, raw = self.manifest_for(entries)
        return loader.load_form2_bundles(
            self.dir, [cfb_row()] if rows is None else rows,
            manifest_sha256=pin, manifest_bytes=raw)

    def entries_by_file(self, audit):
        return {e["file"]: e for e in audit["entries"]}

    def reasons(self, audit):
        return [e["reason"] for e in audit["entries"]]


class AdmissionTests(LoaderCase):
    def test_valid_bundles_admitted_keyed_by_team_id(self):
        bundle48, bundle2393 = make_bundle("48"), make_bundle("2393")
        digest48 = self.publish(bundle48)
        digest2393 = self.publish(bundle2393)
        covers = [self.cover(bundle48, digest48),
                  self.cover(bundle2393, digest2393)]
        # Replaces the retired unpinned-admission assertion: the same
        # directory, loaded WITHOUT the external pin, admits nothing
        # and the audit names the refusal (adapter contract: no pin,
        # no admission; the pin is never read from the directory).
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["pin_status"], "ABSENT")
        self.assertEqual(audit["admitted_team_ids"], [])
        self.assertIn(loader.REASON_PIN_REQUIRED, self.reasons(audit))
        # With the pin supplied, admission is exactly as before.
        pin, _ = self.manifest_for(covers)
        mapping, audit = self.load_pinned(covers)
        self.assertEqual(set(mapping), {"48", "2393"})
        self.assertEqual(audit["directory_status"], "OK")
        self.assertEqual(audit["pin_status"], "VERIFIED")
        self.assertEqual(audit["manifest_sha256"], pin)
        self.assertEqual(audit["admitted_team_ids"], ["2393", "48"])
        entries = self.entries_by_file(audit)
        self.assertEqual(entries[f"{digest48}.json"]["disposition"],
                         "ADMITTED")
        # Admission under the corrected standard names the v2 chain.
        self.assertEqual(entries[f"{digest48}.json"]["reason"],
                         loader.REASON_ADMITTED)
        self.assertEqual(entries[f"{digest48}.json"]["team_id"], "48")
        self.assertEqual(entries[f"{digest2393}.json"]["disposition"],
                         "ADMITTED")

    def test_valid_bundle_reaches_binder_and_satisfies_identity(self):
        bundle48, bundle2393 = make_bundle("48"), make_bundle("2393")
        covers = [self.cover(bundle48, self.publish(bundle48)),
                  self.cover(bundle2393, self.publish(bundle2393))]
        mapping, _ = self.load_pinned(covers)
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
    never becomes a candidate. Under the re-contract each bundle is
    a pinned-archive object whose manifest entry covers its (mutated)
    bytes; the seal check still decides."""

    def _excluded(self, bundle, detail):
        good = make_bundle("2393")
        digest_bad = self.publish(bundle)
        covers = [self.cover(bundle, digest_bad),
                  self.cover(good, self.publish(good))]
        mapping, audit = self.load_pinned(covers)
        self.assertNotIn("48", mapping)
        self.assertIn("2393", mapping)  # a bad bundle never poisons the run
        entry = self.entries_by_file(audit)[f"{digest_bad}.json"]
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
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([self.cover(bundle, digest)])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
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
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([self.cover(bundle, digest)])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "BUNDLE_SCHEMA_INCOMPLETE")
        self.assertEqual(entry["detail"], "FIXTURE_EVENT_ID_MISSING")

    def test_missing_opponent_id_excluded_as_schema_incomplete(self):
        bundle = make_bundle("48")
        del bundle["fixture"]["opponent_espn_id"]
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([self.cover(bundle, digest)])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "BUNDLE_SCHEMA_INCOMPLETE")
        self.assertEqual(entry["detail"], "FIXTURE_OPPONENT_ID_MISSING")

    def test_opponent_equal_to_subject_excluded_as_fixture_mismatch(self):
        bundle = make_bundle("48", opponent_id="48")
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([self.cover(bundle, digest)])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(entry["detail"], "OPPONENT_EQUALS_SUBJECT_TEAM")

    def test_wrong_event_bundle_admitted_but_stage_blocks_on_binding(self):
        # Self-consistently sealed for a DIFFERENT event: admission can
        # verify the seal but cannot know the staged event ID (intake
        # carries names + kickoffs, not ESPN event IDs), so the bundle
        # is admitted as a candidate -- and the evaluator's exact
        # binding refuses it at consult. Admission is not a pass.
        bundle48 = make_bundle("48", event_id="401871999")
        bundle2393 = make_bundle("2393")
        covers = [self.cover(bundle48, self.publish(bundle48)),
                  self.cover(bundle2393, self.publish(bundle2393))]
        mapping, audit = self.load_pinned(covers)
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
        good = make_bundle("2393")
        digest_bad = self.publish(bundle)
        covers = [self.cover(bundle, digest_bad),
                  self.cover(good, self.publish(good))]
        mapping, audit = self.load_pinned(covers)
        self.assertNotIn("48", mapping)
        self.assertIn("2393", mapping)  # a bad bundle never poisons the run
        entry = self.entries_by_file(audit)[f"{digest_bad}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], qe.STATUS_HASH_MISMATCH)
        self.assertIn("DEPTH_CONTENT_SHA256_MISMATCH", entry["detail"])

    def test_malformed_json_excluded_and_audited(self):
        # Replaces the retired BUNDLE_JSON_MALFORMED assertion: at the
        # archive IO seam a malformed object is refused by the
        # archive's strict parser under its own code (ADAPTER.md S4,
        # retired vocabulary), before coverage is consulted.
        digest_bad = self.publish_raw(b"{not json")
        good = make_bundle("2393")
        covers = [self.cover(good, self.publish(good))]
        mapping, audit = self.load_pinned(covers)
        self.assertEqual(set(mapping), {"2393"})
        entry = self.entries_by_file(audit)[f"{digest_bad}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "ARCHIVE_JSON_INVALID")

    def test_team_not_in_intake_excluded_and_audited(self):
        bundle = make_bundle("2229")
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([self.cover(bundle, digest)])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "TEAM_NOT_IN_INTAKE")
        self.assertEqual(entry["team_id"], "2229")

    def test_fixture_not_in_intake_excluded_and_audited(self):
        bundle = make_bundle("48", kickoff_iso="2026-10-20T23:00:00Z")
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([self.cover(bundle, digest)])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry["disposition"], "EXCLUDED")
        self.assertEqual(entry["reason"], "FIXTURE_NOT_IN_INTAKE")

    def test_duplicate_bundle_for_team_excluded_and_audited(self):
        # Replaces the retired first-wins assertion (the first file
        # ADMITTED, the second EXCLUDED / DUPLICATE_TEAM_BUNDLE with
        # its "selected the first" semantics). Under the verdict, a
        # pinned manifest carrying two receipts for the same
        # fixture/team refuses BOTH objects with the archive's own
        # ARCHIVE_RECEIPT_NOT_UNIQUE; the other fixture/team is
        # unaffected.
        bundle_a = make_bundle("48")
        bundle_b = make_bundle("48", depth_stamp="10/10/2026 9:12AM",
                               depth_captured="2026-10-13T13:26:00Z")
        self.assertNotEqual(bundle_a, bundle_b)
        good = make_bundle("2393")
        digest_a = self.publish(bundle_a)
        digest_b = self.publish(bundle_b)
        covers = [self.cover(bundle_a, digest_a),
                  self.cover(bundle_b, digest_b),
                  self.cover(good, self.publish(good))]
        mapping, audit = self.load_pinned(covers)
        self.assertEqual(set(mapping), {"2393"})
        entries = self.entries_by_file(audit)
        for digest in (digest_a, digest_b):
            entry = entries[f"{digest}.json"]
            self.assertEqual(entry["disposition"], "EXCLUDED")
            self.assertEqual(entry["reason"], "ARCHIVE_RECEIPT_NOT_UNIQUE")

    def test_competing_bundles_distinct_fixtures_all_refused(self):
        # The adapter-level backstop of the same verdict clause: two
        # bundles for one team that survive every per-object check --
        # each uniquely covered, each agreeing with its own manifest
        # receipt, for two DIFFERENT manifest fixtures at the intake
        # kickoff -- still refuse the team entirely: every candidate
        # is flipped to EXCLUDED / DUPLICATE_TEAM_BUNDLE, never
        # resolved by selection. (Added in the re-contract; the
        # retired battery asserted first-wins instead.)
        bundle_a = make_bundle("48")
        bundle_b = make_bundle("48", event_id="401871999")
        digest_a = self.publish(bundle_a)
        digest_b = self.publish(bundle_b)
        covers = [self.cover(bundle_a, digest_a),
                  self.cover(bundle_b, digest_b)]
        mapping, audit = self.load_pinned(covers)
        self.assertEqual(mapping, {})
        entries = self.entries_by_file(audit)
        for digest in (digest_a, digest_b):
            entry = entries[f"{digest}.json"]
            self.assertEqual(entry["disposition"], "EXCLUDED")
            self.assertEqual(entry["reason"], "DUPLICATE_TEAM_BUNDLE")

    def test_non_cfb_bundle_ignored_and_audited(self):
        bundle = make_bundle("48")
        bundle["sport"] = "NFL"  # the chain does not seal this field;
        # the sport screen runs before admission verification, as before
        digest = self.publish(bundle)
        mapping, audit = self.load_pinned([])
        self.assertEqual(mapping, {})
        entry = self.entries_by_file(audit)[f"{digest}.json"]
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

    def _pinned_archive(self):
        bundle48, bundle2393 = make_bundle("48"), make_bundle("2393")
        covers = [self.cover(bundle48, self.publish(bundle48)),
                  self.cover(bundle2393, self.publish(bundle2393))]
        return self.manifest_for(covers)

    @staticmethod
    def _assert_runtime_registry_refusal(card):
        # The merged #2224 family registry is a prepricing hard stop.
        # Archive loader and QB identity admission are tested directly
        # above; the canonical runner cannot allow CFB markets through
        # to the underlying stage while the family is unvalidated.
        assert "prepricing_factor_audit" not in card
        (row,) = card["evaluated_rows"]
        assert row["status"] == "NO_MODEL_OR_MARKET"
        assert row["blocker"] == "NO_VALIDATION"
        assert row["registry_enforced"] is True
        for key in ("model_p", "probability", "fair_odds",
                    "ev_per_dollar", "fair_price", "edge"):
            assert row.get(key) is None, key
        assert card["edges"] == []
        assert card["independent_candidates"] == []
        assert card["prop_candidates"] == []

    def test_run_full_wires_archive_audit_without_registry_bypass(self):
        # Even an externally pinned Form 2 archive cannot price CFB
        # when the runtime market registry blocks the family. The
        # direct loader+binder tests prove admission of the same
        # bundles in their research-only internal stage.
        pin, raw = self._pinned_archive()
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=self._lenient_getter(),
                             form2_bundles_dir=self.dir,
                             form2_manifest_sha256=pin,
                             form2_manifest_bytes=raw)
        audit = card["qb_form2_bundle_loader_audit"]
        self.assertEqual(audit["schema"],
                         "SPORTSEDGE_QB_FORM2_BUNDLE_LOADER_AUDIT_V1")
        self.assertEqual(audit["pin_status"], "VERIFIED")
        self.assertEqual(audit["manifest_sha256"], pin)
        self.assertEqual(audit["admitted_team_ids"], [])
        self._assert_runtime_registry_refusal(card)

    def test_run_full_without_bundles_dir_has_no_loader_audit(self):
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=self._lenient_getter())
        self.assertNotIn("qb_form2_bundle_loader_audit", card)
        self._assert_runtime_registry_refusal(card)

    def test_run_full_form2_game_cannot_bypass_unvalidated_family(self):
        # #2158's research-only availability gate still has its
        # standalone positive tests. The stronger current runtime
        # rule (#2224) rejects the market before prepricing.
        pin, raw = self._pinned_archive()
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=self._lenient_getter(),
                             form2_bundles_dir=self.dir,
                             form2_manifest_sha256=pin,
                             form2_manifest_bytes=raw)
        self.assertEqual(
            card["qb_form2_bundle_loader_audit"]["admitted_team_ids"], [])
        self._assert_runtime_registry_refusal(card)

if __name__ == "__main__":
    unittest.main()
