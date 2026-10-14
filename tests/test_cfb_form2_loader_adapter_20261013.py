"""Form 2 bundle loader as pinned-archive runtime adapter (Oct 13, 2026).

Owner verdict (archive convergence, Oct 13, 2026): the archive module
(``sportsedge/prepricing/qb_evidence_archive.py``, PRs #2164/#2165)
owns file IO and integrity; the loader survives only as a thin
runtime adapter. The loader's unkeyed receipt chain detects
accidental edits only -- a resealed forgery passes it -- so the
loader must NOT be a trusted evidence source:

  * Admission requires an EXTERNAL pin (a manifest SHA-256 supplied
    by the caller from an independent channel). No pin -> nothing is
    admitted; there is no parallel unpinned acceptance path, and a
    manifest's own hash, a neighboring file, or a runtime-provided
    digest is not an anchor.
  * Duplicate policy is fail-closed: competing valid bundles for the
    same fixture/team refuse that fixture/team; first-wins selection
    is rejected.
  * All file IO, strict JSON parsing, and integrity checks delegate
    to the archive module (descriptor reads, byte hashing, pin
    verification), closing the loader's disclosed IO defects
    (non-UTF-8 crash, FIFO hang, silent symlink following) by
    delegation rather than by a second local implementation.

Fixtures reuse the recorded Oct 13 samples from the loader battery
(OurLads chart texts/stamps/URLs and QB rooms verbatim; Delaware 48 @
MTSU 2393, event 401871067; FIU 2229 @ Jacksonville State 55, event
401871053), and bundles are preserved into the archive root through
the archive writer itself, so the happy path exercises the real
writer -> pinned manifest -> adapter -> binder chain. No network.
Temp directories are disk-backed (~/workspace/tmp).
"""
import hashlib
import importlib.util
import json
import os
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
    "run_it_full_form2_adapter", ROOT / "artifacts" / "run_it_full.py")
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

# team_id -> (event_id, opponent_espn_id, home_espn_id, away_espn_id)
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


def make_bundle(team_id, *, depth_stamp=None, depth_captured=CAPTURED):
    name, url, _, _, prev = TEAMS[team_id]
    event_id, opponent_id, _, _ = FIXTURES[team_id]
    roster_obj = roster_payload(team_id)
    return qe.build_form2_bundle(
        team_id=team_id, team_name=name,
        event_id=event_id, opponent_id=opponent_id,
        kickoff_utc=KICKOFF_ISO,
        previous_game_kickoff_utc=prev,
        depth_url=url,
        depth_content=depth_text(team_id, stamp=depth_stamp),
        depth_captured_at_utc=depth_captured,
        roster_content=json.dumps(roster_obj, sort_keys=True),
        roster_captured_at_utc="2026-10-13T13:12:14Z",
        roster_athlete_count_repeat=len(qe.roster_athletes(roster_obj)))


def bundle_bytes(bundle):
    return json.dumps(bundle, sort_keys=True,
                      separators=(",", ":")).encode()


def reseal(bundle):
    """Attacker-grade forgery: edit content, repair the component
    hash, and recompute the receipt v2 chain so the bundle is fully
    self-consistent under the loader's old unkeyed standard."""
    forged = json.loads(json.dumps(bundle))
    forged["depth_snapshot"]["content"] += "\n<!-- forged -->"
    forged["depth_snapshot"]["sha256"] = qe.sha256_text(
        forged["depth_snapshot"]["content"])
    forged["receipt"]["sha256"] = qe.receipt_chain_sha256(forged)
    return forged


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


class AdapterCase(unittest.TestCase):
    def setUp(self):
        DISK_TMP.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="form2_archive_",
                                         dir=str(DISK_TMP)))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def preserve(self, bundle, team_id):
        """Preserve a bundle through the archive writer itself; return
        (bundle_sha256, manifest_entry) for manifest composition."""
        event_id, _, home_id, away_id = FIXTURES[team_id]
        _, _, _, _, prev = TEAMS[team_id]
        # Re-pin the fixture under the archive's trusted time.time_ns clock.
        # A caller-supplied clock is no longer a production API.
        from unittest.mock import patch
        with patch("time.time_ns", return_value=int(NOW.timestamp() * 1_000_000_000)):
            result = archive.preserve_form2_bundle(
                self.dir, bundle_bytes=bundle_bytes(bundle),
                team_id=team_id, event_id=event_id,
                home_team_id=home_id, away_team_id=away_id,
                kickoff=KICKOFF_ISO, previous_game_kickoff=prev)
        entry = json.loads(result["manifest_bytes"])["entries"][0]
        return result["bundle_sha256"], entry

    def combined_manifest(self, entries):
        manifest = {"schema": archive.SCHEMA, "entries": list(entries)}
        raw = json.dumps(manifest, sort_keys=True,
                         separators=(",", ":")).encode()
        return raw, hashlib.sha256(raw).hexdigest()

    def publish_raw(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        (self.dir / f"{digest}.json").write_bytes(raw)
        return digest

    def entries_by_file(self, audit):
        return {e["file"]: e for e in audit["entries"]}

    def reasons(self, audit):
        return [e["reason"] for e in audit["entries"]]


class UnpinnedRefusalTests(AdapterCase):
    """Verdict clause: no external pin -> NO archive-backed admission,
    and no parallel unpinned path. The pre-verdict loader admitted
    both directories below; that is the defect these tests pin."""

    def test_no_pin_admits_nothing_and_audit_names_refusal(self):
        (self.dir / "delaware.json").write_text(
            json.dumps(make_bundle("48")), encoding="utf-8")
        (self.dir / "mtsu.json").write_text(
            json.dumps(make_bundle("2393")), encoding="utf-8")
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["admitted_team_ids"], [])
        self.assertEqual(audit["pin_status"], "ABSENT")
        self.assertIn(loader.REASON_PIN_REQUIRED, self.reasons(audit))

    def test_resealed_forgery_without_pin_admits_nothing(self):
        # A fully resealed forgery: component hash repaired, receipt
        # chain recomputed. Self-consistent under the old standard --
        # and still nothing without a pin.
        forged = reseal(make_bundle("48"))
        self.assertEqual(qe.receipt_chain_sha256(forged),
                         forged["receipt"]["sha256"])
        (self.dir / "delaware.json").write_text(
            json.dumps(forged), encoding="utf-8")
        mapping, audit = loader.load_form2_bundles(self.dir, [cfb_row()])
        self.assertEqual(mapping, {})
        self.assertEqual(audit["pin_status"], "ABSENT")


class PinIntegrityTests(AdapterCase):
    """A pin anchors the manifest; the manifest anchors the bundle
    bytes. Tampering at either layer is a named refusal."""

    def test_pin_does_not_cover_tampered_manifest(self):
        _, entry = self.preserve(make_bundle("48"), "48")
        _, good_pin = self.combined_manifest([entry])
        forged = reseal(make_bundle("48"))
        forged_digest = self.publish_raw(bundle_bytes(forged))
        forged_entry = dict(entry, bundle_sha256=forged_digest)
        forged_manifest, _ = self.combined_manifest([forged_entry])
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=good_pin,
            manifest_bytes=forged_manifest)
        self.assertEqual(mapping, {})
        self.assertEqual(audit["pin_status"], "UNVERIFIED")
        self.assertIn("ARCHIVE_MANIFEST_HASH_MISMATCH", self.reasons(audit))

    def test_tampered_bundle_bytes_refused_by_name(self):
        digest, entry = self.preserve(make_bundle("48"), "48")
        raw, pin = self.combined_manifest([entry])
        # Attacker rewrites the object in place under its pinned name
        # with resealed bytes: the byte hash no longer matches the
        # content address the manifest anchors.
        (self.dir / f"{digest}.json").write_bytes(
            bundle_bytes(reseal(make_bundle("48"))))
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        self.assertEqual(mapping, {})
        entry_for = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
        self.assertEqual(entry_for["reason"],
                         "ARCHIVE_BUNDLE_HASH_MISMATCH")

    def test_object_not_covered_by_manifest_excluded(self):
        _, entry48 = self.preserve(make_bundle("48"), "48")
        digest_fiu, _ = self.preserve(make_bundle("2229"), "2229")
        raw, pin = self.combined_manifest([entry48])
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        # The covered Delaware bundle admits; the preserved-but-
        # uncovered FIU object is not evidence under this pin.
        self.assertEqual(set(mapping), {"48"})
        entry_for = self.entries_by_file(audit)[f"{digest_fiu}.json"]
        self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
        self.assertEqual(entry_for["reason"],
                         loader.REASON_NOT_IN_MANIFEST)


class DuplicateFailClosedTests(AdapterCase):
    """Verdict clause: first-wins is REJECTED. Competing valid bundles
    for the same fixture/team fail closed for that fixture/team; the
    other fixture/team is unaffected."""

    def test_competing_bundles_same_fixture_team_fail_closed(self):
        bundle_a = make_bundle("48")
        bundle_b = make_bundle("48", depth_stamp="10/10/2026 9:12AM",
                               depth_captured="2026-10-13T13:26:00Z")
        self.assertNotEqual(bundle_bytes(bundle_a), bundle_bytes(bundle_b))
        _, entry_a = self.preserve(bundle_a, "48")
        _, entry_b = self.preserve(bundle_b, "48")
        _, entry_mtsu = self.preserve(make_bundle("2393"), "2393")
        raw, pin = self.combined_manifest([entry_a, entry_b, entry_mtsu])
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        # Delaware fails closed; MTSU is unaffected.
        self.assertEqual(set(mapping), {"2393"})
        for entry in (entry_a, entry_b):
            entry_for = self.entries_by_file(
                audit)[f"{entry['bundle_sha256']}.json"]
            self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
            self.assertEqual(entry_for["reason"],
                             "ARCHIVE_RECEIPT_NOT_UNIQUE")
        mtsu = self.entries_by_file(audit)[f"{entry_mtsu['bundle_sha256']}.json"]
        self.assertEqual(mtsu["disposition"], loader.ADMITTED)


class ArchiveIoDelegationTests(AdapterCase):
    """The loader's disclosed IO defects (non-UTF-8 crash, FIFO hang,
    silent symlink following) close by delegation to archive IO: each
    hostile object is a named refusal, never an exception or a hang."""

    def test_non_utf8_bundle_refused_via_archive_io(self):
        raw_bad = b"\xff\xfe\x00not-utf8-json"
        digest = self.publish_raw(raw_bad)
        _, entry48 = self.preserve(make_bundle("48"), "48")
        # The hostile object rides under a different fixture's entry:
        # strict parsing refuses it before coverage is even consulted,
        # and Delaware's own unique receipt stays admissible.
        entry_bad = {"team_id": "2229", "event_id": "401871053",
                     "home_team_id": "55", "away_team_id": "2229",
                     "kickoff_utc": KICKOFF_ISO,
                     "recorded_at_utc": NOW.isoformat(),
                     "bundle_sha256": digest}
        raw, pin = self.combined_manifest([entry48, entry_bad])
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        entry_for = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
        self.assertEqual(entry_for["reason"], "ARCHIVE_JSON_INVALID")
        self.assertIn("48", mapping)  # the run itself never fails

    def test_fifo_in_archive_root_refused_not_hang(self):
        _, entry48 = self.preserve(make_bundle("48"), "48")
        raw, pin = self.combined_manifest([entry48])
        fifo_name = "f" * 64 + ".json"
        os.mkfifo(self.dir / fifo_name)
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        entry_for = self.entries_by_file(audit)[fifo_name]
        self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
        self.assertEqual(entry_for["reason"], "ARCHIVE_BUNDLE_NOT_REGULAR")
        self.assertIn("48", mapping)

    def test_symlinked_bundle_refused_via_archive_io(self):
        _, entry48 = self.preserve(make_bundle("48"), "48")
        raw, pin = self.combined_manifest([entry48])
        outside = self.dir.parent / (self.dir.name + "_outside.json")
        self.addCleanup(lambda: outside.exists() and outside.unlink())
        outside.write_bytes(bundle_bytes(make_bundle("2393")))
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        os.symlink(outside, self.dir / f"{digest}.json")
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        entry_for = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
        self.assertEqual(entry_for["reason"], "ARCHIVE_BUNDLE_UNREADABLE")
        self.assertIn("48", mapping)

    def test_wrong_type_object_excluded_named(self):
        digest = self.publish_raw(b"[1, 2, 3]")
        _, entry48 = self.preserve(make_bundle("48"), "48")
        raw, pin = self.combined_manifest([entry48])
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        entry_for = self.entries_by_file(audit)[f"{digest}.json"]
        self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
        self.assertEqual(entry_for["reason"], loader.REASON_NOT_AN_OBJECT)
        self.assertIn("48", mapping)


class PinnedHappyPathTests(AdapterCase):
    """Pinned manifest + untampered bundles: admission exactly as
    before, and the research-only contract end-to-end (identity only,
    availability AVAILABILITY_UNVERIFIED, no actionable surface)."""

    def _pinned_two_team_archive(self):
        _, entry48 = self.preserve(make_bundle("48"), "48")
        _, entry2393 = self.preserve(make_bundle("2393"), "2393")
        raw, pin = self.combined_manifest([entry48, entry2393])
        # The manifest also lives in the root under its own digest:
        # the adapter must read it from there when only the pin is
        # supplied, and must never treat it as a bundle.
        self.publish_raw(raw)
        return pin

    def test_pinned_admission_and_binder_identity(self):
        pin = self._pinned_two_team_archive()
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin)
        self.assertEqual(set(mapping), {"48", "2393"})
        self.assertEqual(audit["pin_status"], "VERIFIED")
        self.assertEqual(audit["manifest_sha256"], pin)
        self.assertEqual(audit["admitted_team_ids"], ["2393", "48"])
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping()),
            qb_form2_bundles=mapping)
        self.assertFalse(stage["blocked"], stage["block_detail"])
        used = [f for f in stage["factors"]
                if f["factor"] == "qb_specific" and f["status"] == "USED"]
        self.assertEqual(len(used), 2)
        reasons = " ".join(f["reason"] for f in used)
        self.assertEqual(
            reasons.count("AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"),
            2)
        self.assertEqual(stage["adjustments"]["away_injury_pts"], 0.0)
        self.assertEqual(stage["adjustments"]["home_injury_pts"], 0.0)
        self.assertEqual(stage["availability_status"],
                         qe.AVAILABILITY_UNVERIFIED)

    def test_manifest_objects_in_root_ignored_not_admitted(self):
        pin = self._pinned_two_team_archive()
        _, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin)
        manifest_entries = [e for e in audit["entries"]
                             if e["reason"] == loader.REASON_MANIFEST_FILE]
        # The pinned manifest plus the writer's two single-entry
        # manifests all sit in the root; none is a bundle candidate.
        self.assertEqual(len(manifest_entries), 3)
        self.assertTrue(all(e["disposition"] == loader.IGNORED
                            for e in manifest_entries))

    def test_run_full_pinned_archive_cannot_bypass_family_registry(self):
        # Registry x Form 2 seam (owner ruling, Oct 14 2026): #2224
        # refuses PRICING at the output boundary, not evidence
        # collection. The pinned archive IS admitted against the game
        # rows and the prepricing audit IS produced (the evidence
        # path); the emitted row is still the registry refusal -- the
        # archive cannot create an eligible CFB market while the
        # family remains UNVALIDATED.
        pin = self._pinned_two_team_archive()
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=lambda url: cfb_mapping().get(url, {}),
                             form2_bundles_dir=self.dir,
                             form2_manifest_sha256=pin)
        audit = card["qb_form2_bundle_loader_audit"]
        self.assertEqual(audit["pin_status"], "VERIFIED")
        self.assertEqual(audit["manifest_sha256"], pin)
        self.assertEqual(audit["admitted_team_ids"], ["2393", "48"])
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        self.assertFalse(entry["blocked"])
        (row,) = card["evaluated_rows"]
        self.assertEqual(row["status"], "NO_MODEL_OR_MARKET")
        self.assertEqual(row["blocker"], "NO_VALIDATION")
        self.assertIs(row["registry_enforced"], True)
        for key in ("model_p", "probability", "fair_odds",
                    "ev_per_dollar", "fair_price", "edge"):
            self.assertIsNone(row.get(key), key)
        self.assertEqual(card["edges"], [])
        self.assertEqual(card["independent_candidates"], [])
        self.assertEqual(card["prop_candidates"], [])

    def test_run_full_without_pin_stays_registry_blocked(self):
        # No caller-independent archive pin means no Form 2 admission.
        # Under the registry x Form 2 seam the game still reaches
        # prepricing, where the QB gate blocks it and the audit
        # records that block; the emitted row is the registry refusal.
        self._pinned_two_team_archive()
        card = full.run_full({"lines": [cfb_row()]}, now=NOW,
                             getter=lambda url: cfb_mapping().get(url, {}),
                             form2_bundles_dir=self.dir)
        audit = card["qb_form2_bundle_loader_audit"]
        self.assertEqual(audit["pin_status"], "ABSENT")
        self.assertEqual(audit["admitted_team_ids"], [])
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        self.assertTrue(entry["blocked"])
        self.assertEqual(entry["block_reason"],
                         "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED")
        (row,) = card["evaluated_rows"]
        self.assertEqual(row["status"], "NO_MODEL_OR_MARKET")
        self.assertEqual(row["blocker"], "NO_VALIDATION")
        self.assertIs(row["registry_enforced"], True)
        for key in ("model_p", "probability", "fair_odds",
                    "ev_per_dollar", "fair_price", "edge"):
            self.assertIsNone(row.get(key), key)


class HardeningParityTests(AdapterCase):
    """#2177 loader-hardening parity (PR #2192's loader lineage),
    ported under the Oct 13 settlement: #2192's loader is not the
    survivor -- the pinned-archive adapter is -- but its hardening
    must not be lost. Each test names the #2192-side case it adapts;
    adaptations are limited to the canonical surface (pinned calls,
    content-addressed object names, archive reason vocabulary)."""

    def test_symlink_directory_refused(self):
        # Adapts #2192's test_symlink_directory_refused (loader battery):
        # a symlinked bundles directory is refused at the directory,
        # by name, before any object is enumerated -- not merely
        # refused object-by-object under a directory_status of OK.
        _, entry48 = self.preserve(make_bundle("48"), "48")
        raw, pin = self.combined_manifest([entry48])
        alias = self.dir.parent / (self.dir.name + "_alias")
        os.symlink(self.dir, alias, target_is_directory=True)
        self.addCleanup(lambda: alias.is_symlink() and alias.unlink())
        mapping, audit = loader.load_form2_bundles(
            alias, [cfb_row()], manifest_sha256=pin, manifest_bytes=raw)
        self.assertEqual(mapping, {})
        self.assertEqual(audit["directory_status"],
                         "UNSAFE_DIRECTORY_SYMLINK")
        self.assertEqual(audit["entries"], [])

    def test_conflicting_team_ids_same_name_all_refused(self):
        # Adapts the name-key half of #2192's both-sides duplicate
        # refusal (#2177): two sealed bundles carrying the SAME team
        # name under DIFFERENT ESPN ids, each uniquely covered by the
        # pinned manifest and each passing every per-object check,
        # still refuse BOTH -- the name the binder resolves by is
        # ambiguous, so neither candidate may be selected. An
        # unrelated team is unaffected.
        _, entry48 = self.preserve(make_bundle("48"), "48")
        _, entry_mtsu = self.preserve(make_bundle("2393"), "2393")
        roster_obj = roster_payload("48")
        roster_obj["team"] = {"id": "9999"}
        name, url, _, _, prev = TEAMS["48"]
        bundle_b = qe.build_form2_bundle(
            team_id="9999", team_name=name,
            event_id="401871067", opponent_id="2393",
            kickoff_utc=KICKOFF_ISO,
            previous_game_kickoff_utc=prev,
            depth_url=url,
            depth_content=depth_text("48"),
            depth_captured_at_utc=CAPTURED,
            roster_content=json.dumps(roster_obj, sort_keys=True),
            roster_captured_at_utc="2026-10-13T13:12:14Z",
            roster_athlete_count_repeat=len(qe.roster_athletes(roster_obj)))
        digest_b = self.publish_raw(bundle_bytes(bundle_b))
        entry_b = {"team_id": "9999", "event_id": "401871067",
                   "home_team_id": "2393", "away_team_id": "9999",
                   "kickoff_utc": KICKOFF_ISO,
                   "recorded_at_utc": NOW.isoformat(),
                   "bundle_sha256": digest_b}
        raw, pin = self.combined_manifest([entry48, entry_b, entry_mtsu])
        mapping, audit = loader.load_form2_bundles(
            self.dir, [cfb_row()], manifest_sha256=pin,
            manifest_bytes=raw)
        self.assertEqual(set(mapping), {"2393"})
        entries = self.entries_by_file(audit)
        digest_a = entry48["bundle_sha256"]
        for digest in (digest_a, digest_b):
            entry_for = entries[f"{digest}.json"]
            self.assertEqual(entry_for["disposition"], loader.EXCLUDED)
            self.assertEqual(entry_for["reason"], loader.REASON_DUPLICATE)
        self.assertIn("SAME_TEAM_NAME", entries[f"{digest_b}.json"]["detail"])


if __name__ == "__main__":
    unittest.main()
