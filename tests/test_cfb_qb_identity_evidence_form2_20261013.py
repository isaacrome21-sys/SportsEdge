"""QB_IDENTITY_EVIDENCE Form 2 (DEPTH_ROSTER_COMPOSITE) tests, Oct 13 2026.

Owner ruling (issue #2154): Form 2 is an identity-only, research-stage
evidence path for CFB teams the ESPN injury feed does not cover
(TEAM_NOT_IN_INJURY_FEED). A verified OurLads QB1 -> ESPN roster match
establishes QB IDENTITY; it is not proof of availability or a clean
injury report, injury points are exactly 0.0, and availability stays
explicitly AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT.

Fixtures are built from the recorded live samples of 2026-10-13
(cfb_qb_alternative_source_20261013/samples + the participation-design
roster pulls): OurLads chart texts reproduce the recorded QB rows,
update stamps and URLs verbatim; roster fixtures carry the recorded
QB rooms (athlete IDs, names, jerseys verbatim from the live pulls,
record scaffolding trimmed -- counts describe the fixture). No network
is touched.
"""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.prepricing import factor_ingestion as fi
from sportsedge.prepricing import qb_identity_evidence as qe

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 10, 13, 23, 0, tzinfo=timezone.utc)
KICKOFF_ISO = "2026-10-13T23:00:00Z"
CAPTURED = "2026-10-13T13:21:00Z"

# Recorded QB rooms (athlete id, displayName, jersey) -- verbatim from
# the live ?limit=1000 roster pulls of 2026-10-13.
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
    "55": [("5122157", "Caden Creel", "12"), ("5290561", "Noah Lee", "16"),
           ("5291762", "Donovan Moorhead", "19"), ("5222557", "Jack Moran", "15"),
           ("5296090", "Kadyn Palmer", "2")],
}

# Recorded OurLads charts: (url, stamp, QB row, previous-game kickoff).
CHARTS = {
    "48": ("https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/delaware/93097",
           "10/10/2026 9:07AM",
           "1. Minicucci, Nick — SR, #4 · 2. Streeter, Braden — RS SO, #16 · "
           "3. Trujillo, Riley — RS SO/TR, #2 · 4. Archield Jr., EJ — RS FR, #11",
           "2026-10-02T23:00:00Z"),
    "2393": ("https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/middle-tennessee/91165",
             "10/10/2026 9:08AM",
             "1. Gagliano, Roman — RS SO, #16 · 2. Costelli, Peter — GR/TR, #11 · "
             "3. Williams, Rocco — FR, #15",
             "2026-10-03T23:00:00Z"),
    "2229": ("https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/florida-international/90475",
             "10/10/2026 9:08AM",
             "1. Kohl, JJ — RS JR/TR, #17 · 2. Marker, Zach — GR/TR, #11",
             "2026-10-07T23:00:00Z"),
    "55": ("https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/jacksonville-state/93028/",
           "10/10/2026 9:08AM",
           "1. Creel, Caden — RS JR, #12 · 2. Moran, Jack — RS FR, #15 · "
           "3. Palmer, Kadyn — RS FR, #2",
           "2026-10-07T23:30:00Z"),
}

EXPECTED_QB1 = {"48": ("5153846", "Nick Minicucci"),
                "2393": ("5194626", "Roman Gagliano"),
                "2229": ("4870883", "JJ Kohl"),
                "55": ("5122157", "Caden Creel")}

# The two recorded fixtures (owner-review correction 1: bundles bind
# to an exact event + exact opponent, so fixtures name both).
# Delaware (48, away) @ MTSU (2393, home), ESPN event 401871067;
# FIU (2229, away) @ Jacksonville State (55, home), event 401871053.
FIXTURE_OF_TEAM = {
    "48": {"event_id": "401871067", "home_team_id": "2393",
           "away_team_id": "48", "opponent_id": "2393"},
    "2393": {"event_id": "401871067", "home_team_id": "2393",
             "away_team_id": "48", "opponent_id": "48"},
    "2229": {"event_id": "401871053", "home_team_id": "55",
             "away_team_id": "2229", "opponent_id": "55"},
    "55": {"event_id": "401871053", "home_team_id": "55",
           "away_team_id": "2229", "opponent_id": "2229"},
}


def roster_payload(team_id, qb_records=None):
    records = QB_ROOMS[team_id] if qb_records is None else qb_records
    athletes = [{"id": i, "displayName": n, "fullName": n, "jersey": j,
                 "position": {"id": "8", "name": "Quarterback",
                              "abbreviation": "QB"},
                 "status": {"id": "1", "name": "Active", "type": "active"},
                 "injuries": []} for (i, n, j) in records]
    return {"timestamp": "2026-10-13T13:12:14Z", "team": {"id": team_id},
            "athletes": [{"position": "offense", "items": athletes}]}


def depth_text(team_id, stamp=None, qb_row=None):
    url, recorded_stamp, recorded_row, _ = CHARTS[team_id]
    return ("# OurLads depth chart (fixture in the recorded sample format)\n"
            f"- **URL:** {url}\n"
            f"- **On-page update stamp (verbatim):** "
            f"\"Updated: {stamp or recorded_stamp} ET\"\n"
            f"- **QB row (Player 1 -> Player N):** {qb_row or recorded_row}\n")


def make_bundle(team_id, *, kickoff_iso=KICKOFF_ISO, depth=None, roster=None,
                captured=CAPTURED, repeat=None, prev=None, event_id=None,
                opponent_id=None):
    """A valid bundle via the capture builder (offline, from fixtures)."""
    url, _, _, recorded_prev = CHARTS[team_id]
    fixture = FIXTURE_OF_TEAM[team_id]
    roster_obj = roster or roster_payload(team_id)
    athletes = qe.roster_athletes(roster_obj)
    return qe.build_form2_bundle(
        team_id=team_id, team_name=f"Team {team_id}",
        event_id=event_id or fixture["event_id"],
        opponent_id=opponent_id or fixture["opponent_id"],
        kickoff_utc=kickoff_iso,
        previous_game_kickoff_utc=prev or recorded_prev,
        depth_url=url, depth_content=depth or depth_text(team_id),
        depth_captured_at_utc=captured,
        roster_content=json.dumps(roster_obj, sort_keys=True),
        roster_captured_at_utc="2026-10-13T13:12:14Z",
        roster_athlete_count_repeat=len(athletes) if repeat is None else repeat)


def raw_bundle(team_id, *, roster_snapshot_overrides=None, depth_overrides=None):
    """A bundle assembled by hand (bypasses the capture builder's own
    fail-closed checks) so hostile snapshots can reach the evaluator."""
    bundle = make_bundle(team_id)
    if roster_snapshot_overrides:
        bundle["roster_snapshot"].update(roster_snapshot_overrides)
    if depth_overrides:
        bundle["depth_snapshot"].update(depth_overrides)
    return bundle


def evaluate(bundle, team_id="48", **kw):
    kw.setdefault("kickoff", KICKOFF)
    kw.setdefault("now", NOW)
    fixture = FIXTURE_OF_TEAM[team_id]
    kw.setdefault("event_id", fixture["event_id"])
    kw.setdefault("home_team_id", fixture["home_team_id"])
    kw.setdefault("away_team_id", fixture["away_team_id"])
    return qe.evaluate_form2_bundle(bundle, team_id=team_id, **kw)


def rechain(bundle):
    """Re-seal a mutated bundle (component hashes + receipt chain), so
    a hostile case reaches the check it targets instead of dying at
    the tamper checks: this simulates a capture that recorded bad
    data CONSISTENTLY, which the semantic checks must still refuse."""
    depth = bundle["depth_snapshot"]
    depth["sha256"] = qe.sha256_text(depth["content"])
    roster_snap = bundle["roster_snapshot"]
    roster_snap["sha256"] = qe.sha256_text(roster_snap["content"])
    bundle["receipt"] = {"version": qe.RECEIPT_VERSION,
                         "sha256": qe.receipt_chain_sha256(bundle)}
    return bundle


class FourTeamResolutionTests(unittest.TestCase):
    def test_all_four_teams_resolve_from_recorded_samples(self):
        for team_id, (athlete_id, name) in EXPECTED_QB1.items():
            result = evaluate(make_bundle(team_id), team_id=team_id)
            self.assertTrue(result["ok"], f"{team_id}: {result}")
            self.assertEqual(result["status"], qe.STATUS_SATISFIED)
            self.assertEqual(result["resolved_athlete_id"], athlete_id)
            self.assertEqual(result["resolved_athlete_name"], name)

    def test_pass_carries_availability_label_zero_points_and_receipt(self):
        result = evaluate(make_bundle("48"))
        # Availability is explicitly UNKNOWN -- labeled, never clean.
        self.assertEqual(result["availability_status"],
                         "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT")
        # No report exists to extract from: exactly 0.0, never synthesized.
        self.assertEqual(result["injury_points"], 0.0)
        receipt = result["receipt"]
        self.assertEqual(receipt["depth_source_url"], CHARTS["48"][0])
        self.assertEqual(receipt["depth_update_stamp"],
                         "Updated: 10/10/2026 9:07AM ET")
        self.assertEqual(receipt["depth_captured_at_utc"], CAPTURED)
        self.assertEqual(receipt["roster_captured_at_utc"],
                         "2026-10-13T13:12:14Z")
        self.assertEqual(receipt["resolved_qb1_athlete_id"], "5153846")
        self.assertEqual(len(receipt["depth_sha256"]), 64)
        self.assertEqual(len(receipt["roster_sha256"]), 64)
        # Receipt v2 (correction 3): the chain seal is on the receipt,
        # and the exact fixture binding (correction 1) is recorded.
        self.assertEqual(receipt["receipt_version"], qe.RECEIPT_VERSION)
        self.assertEqual(len(receipt["receipt_sha256"]), 64)
        self.assertEqual(receipt["event_id"], "401871067")
        self.assertEqual(receipt["opponent_espn_id"], "2393")


class HostileResolutionTests(unittest.TestCase):
    def test_qb1_matching_two_roster_athletes_fails_closed(self):
        records = QB_ROOMS["48"] + [("9999999", "Nick Minicucci", "4")]
        result = evaluate(make_bundle("48", roster=roster_payload("48", records)))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_AMBIGUOUS)

    def test_qb1_absent_from_roster_fails_closed(self):
        ghost = depth_text("48", qb_row="1. Ghost, Gary — SR, #9 · "
                                        "2. Streeter, Braden — RS SO, #16")
        result = evaluate(make_bundle("48", depth=ghost))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_NOT_ON_ROSTER)

    def test_qb1_name_present_with_wrong_jersey_fails_closed(self):
        wrong = depth_text("48", qb_row="1. Minicucci, Nick — SR, #44 · "
                                        "2. Streeter, Braden — RS SO, #16")
        result = evaluate(make_bundle("48", depth=wrong))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_NOT_ON_ROSTER)
        self.assertEqual(result["detail"], "NAME_MATCHES_WITH_DIFFERENT_JERSEY")

    def test_resolved_athlete_at_non_qb_position_fails_closed(self):
        records = [("5153846", "Nick Minicucci", "4")]
        roster = roster_payload("48", records)
        roster["athletes"][0]["items"][0]["position"] = {
            "id": "9", "name": "Wide Receiver", "abbreviation": "WR"}
        result = evaluate(make_bundle("48", roster=roster))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_POSITION_MISMATCH)


class HostileSnapshotTests(unittest.TestCase):
    def test_default_limit_truncated_roster_fails_closed(self):
        # The default-pull artifact: limit 100, count pinned at the cap.
        bundle = raw_bundle("48", roster_snapshot_overrides={
            "requested_limit": 100, "athlete_count": 100,
            "athlete_count_repeat": 100})
        # Simulate a consistently captured but incomplete roster; no tampering.
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_ROSTER_INCOMPLETE)

    def test_unstable_roster_count_fails_closed(self):
        bundle = raw_bundle("48", roster_snapshot_overrides={
            "athlete_count_repeat": 999})
        result = evaluate(rechain(bundle))
        self.assertEqual(result["status"], qe.STATUS_ROSTER_INCOMPLETE)
        self.assertIn("ROSTER_COUNT_UNSTABLE", result["detail"])

    def test_roster_content_shorter_than_attested_count_fails_closed(self):
        bundle = raw_bundle("48", roster_snapshot_overrides={
            "athlete_count": 42, "athlete_count_repeat": 42})
        result = evaluate(rechain(bundle))
        self.assertEqual(result["status"], qe.STATUS_ROSTER_INCOMPLETE)
        self.assertIn("ROSTER_COUNT_CONTENT_MISMATCH", result["detail"])

    def test_tampered_depth_content_fails_hash_check(self):
        bundle = make_bundle("48")
        bundle["depth_snapshot"]["content"] += "\n<!-- tampered -->"
        result = evaluate(bundle)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)

    def test_tampered_roster_content_fails_hash_check(self):
        bundle = make_bundle("48")
        bundle["roster_snapshot"]["content"] += " "
        result = evaluate(bundle)
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)

    def test_bundle_for_another_team_is_not_evidence(self):
        result = evaluate(make_bundle("48"), team_id="2393")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_MISSING)

    def test_bundle_for_another_fixture_is_not_evidence(self):
        # UPDATED (owner-review correction 1): a kickoff mismatch is
        # an exact-fixture-binding failure with its own status now,
        # not generic missing evidence.
        bundle = make_bundle("48", kickoff_iso="2026-10-20T23:00:00Z")
        result = evaluate(bundle)
        self.assertEqual(result["status"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(result["detail"], "FIXTURE_KICKOFF_MISMATCH")

    def test_missing_bundle_fails_closed(self):
        result = evaluate(None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_MISSING)


class ExactFixtureBindingTests(unittest.TestCase):
    """Owner-review correction 1: a bundle binds to an exact event
    and an exact opponent, not loosely to a team + a kickoff."""

    def test_wrong_event_id_fails_closed(self):
        bundle = make_bundle("48", event_id="401871068")
        result = evaluate(bundle)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(result["detail"], "EVENT_ID_MISMATCH")

    def test_wrong_opponent_fails_closed(self):
        # Delaware's chart, but the bundle claims the opponent was
        # Jacksonville State (55) instead of MTSU (2393).
        bundle = make_bundle("48", opponent_id="55")
        result = evaluate(bundle)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(result["detail"], "OPPONENT_MISMATCH")

    def test_team_not_in_staged_fixture_fails_closed(self):
        # The Delaware bundle evaluated against the FIU @ Jax State
        # fixture: right team, wrong game entirely.
        result = evaluate(make_bundle("48"), event_id="401871053",
                          home_team_id="55", away_team_id="2229")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(result["detail"], "TEAM_NOT_IN_STAGED_FIXTURE")

    def test_unverifiable_staged_identity_fails_closed(self):
        # Loose binding is the defect, not a fallback: without the
        # staged event identity the evaluator cannot bind exactly.
        result = evaluate(make_bundle("48"), event_id=None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_FIXTURE_MISMATCH)
        self.assertEqual(result["detail"], "FIXTURE_IDENTITY_UNVERIFIABLE")


class AssertedQb1Tests(unittest.TestCase):
    """Owner-review correction 2: the QB1 ranking is DERIVED from the
    captured chart. An asserted ordering can never override it."""

    def test_asserted_qb2_over_captured_qb1_fails_closed(self):
        # Streeter (QB2) IS on the roster at the right position --
        # resolution alone would accept him. The captured chart ranks
        # Minicucci first, and the assertion may not override it.
        bundle = make_bundle("48")
        order = bundle["depth_snapshot"]["qb_order"]
        bundle["depth_snapshot"]["qb_order"] = (
            [order[1], order[0]] + order[2:])
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_QB1_ASSERTION_MISMATCH)
        self.assertEqual(result["detail"],
                         "ASSERTED_QB_ORDER_DIFFERS_FROM_CAPTURED_CHART")

    def test_captured_chart_governs_assertion_must_agree(self):
        # A chart captured with Streeter ranked first: the builder's
        # stored order follows the CHART (Streeter), and the bundle
        # passes on the parsed QB1...
        depth = depth_text(
            "48", qb_row="1. Streeter, Braden — RS SO, #16 · "
                         "2. Minicucci, Nick — SR, #4")
        result = evaluate(make_bundle("48", depth=depth))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["resolved_athlete_id"], "5224762")
        # ...while rewriting the assertion back to Minicucci fails.
        bundle = make_bundle("48", depth=depth)
        order = bundle["depth_snapshot"]["qb_order"]
        bundle["depth_snapshot"]["qb_order"] = (
            [order[1], order[0]] + order[2:])
        result = evaluate(rechain(bundle))
        self.assertEqual(result["status"], qe.STATUS_QB1_ASSERTION_MISMATCH)

    def test_bundle_without_asserted_order_passes_on_parsed_order(self):
        bundle = make_bundle("48")
        del bundle["depth_snapshot"]["qb_order"]
        result = evaluate(rechain(bundle))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["resolved_athlete_id"], "5153846")

    def test_qb_rank_one_absent_or_duplicated_fails_closed(self):
        for rows in ("2. Streeter, Braden — RS SO, #16",
                     "1. Minicucci, Nick — SR, #4 · "
                     "1. Streeter, Braden — RS SO, #16"):
            depth = depth_text("48", qb_row=rows)
            self.assertEqual(qe.parse_qb_order(depth), [])
            with self.assertRaisesRegex(ValueError, "NO_QB_ORDER_CAPTURED"):
                make_bundle("48", depth=depth)

    def test_resealed_truncated_or_poisoned_order_still_blocks(self):
        for mutate in ("truncate", "poison_qb2"):
            bundle = make_bundle("48")
            order = bundle["depth_snapshot"]["qb_order"]
            if mutate == "truncate":
                bundle["depth_snapshot"]["qb_order"] = order[:1]
                expected = "ASSERTED_QB_ORDER_LENGTH_OR_SHAPE_MISMATCH"
            else:
                order[1] = dict(order[1], jersey="99")
                expected = "ASSERTED_QB_ORDER_DIFFERS_FROM_CAPTURED_CHART"
            result = evaluate(rechain(bundle))
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], qe.STATUS_QB1_ASSERTION_MISMATCH)
            self.assertEqual(result["detail"], expected)

    def test_unparseable_captured_order_fails_closed(self):
        # No readable QB row in the captured bytes and no assertion
        # to fall back on: fail closed, never guess an ordering.
        bundle = make_bundle("48")
        depth = bundle["depth_snapshot"]
        depth["content"] = depth_text(
            "48", qb_row="QB chart unavailable for this fixture")
        del depth["qb_order"]
        result = evaluate(rechain(bundle))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_MISSING)
        self.assertEqual(result["detail"], "NO_QB_ORDER_CAPTURED")


class ReceiptChainTests(unittest.TestCase):
    """Owner-review correction 3: receipt v2 seals every receipt
    field; any post-capture edit breaks the seal."""

    def test_captured_at_edited_after_capture_breaks_seal(self):
        bundle = make_bundle("48")
        bundle["depth_snapshot"]["captured_at_utc"] = "2026-10-13T10:00:00Z"
        result = evaluate(bundle)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_source_url_edited_after_capture_breaks_seal(self):
        bundle = make_bundle("48")
        bundle["depth_snapshot"]["source_url"] = (
            "https://example.invalid/not-the-captured-chart")
        result = evaluate(bundle)
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_event_id_edited_after_capture_breaks_seal(self):
        # Rebind the bundle to another event AND evaluate it against
        # that event, so the binding checks agree -- the seal is what
        # catches the edit.
        bundle = make_bundle("48")
        bundle["fixture"]["event_id"] = "401871068"
        result = evaluate(bundle, event_id="401871068")
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_sealed_fixture_and_roster_assertions_reject_tampering(self):
        # Align the caller's independently bound kickoff in the first case:
        # only the receipt seal, not an earlier fixture mismatch, can reject it.
        for mutate, overrides in (
            (lambda b: b["fixture"].__setitem__("kickoff_utc", "2026-10-13T22:00:00Z"),
             {"kickoff": datetime(2026, 10, 13, 22, 0, tzinfo=timezone.utc)}),
            (lambda b: b["previous_game"].__setitem__("kickoff_utc", "2026-10-10T23:00:00Z"), {}),
            (lambda b: b["roster_snapshot"].__setitem__("athlete_count_repeat", 1), {}),
        ):
            bundle = make_bundle("48")
            mutate(bundle)
            result = evaluate(bundle, **overrides)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
            self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_receipt_removed_fails_closed(self):
        bundle = make_bundle("48")
        del bundle["receipt"]
        result = evaluate(bundle)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISSING")

    def test_receipt_downgraded_to_v1_fails_closed(self):
        bundle = make_bundle("48")
        bundle["receipt"] = {"version": 1,
                             "sha256": bundle["receipt"]["sha256"]}
        result = evaluate(bundle)
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISSING")


class StalenessTests(unittest.TestCase):
    def test_stamp_predating_previous_game_is_stale(self):
        # Previous game kicked off Oct 11; the chart still shows the
        # Oct 10 batch stamp -- stale by construction (proposal 4.4).
        result = evaluate(make_bundle("48", prev="2026-10-11T23:00:00Z"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_STALE)
        self.assertEqual(result["detail"],
                         "STAMP_PREDATES_PREVIOUS_GAME_KICKOFF")

    def test_stamp_predating_previous_game_via_caller_value_is_stale(self):
        result = evaluate(make_bundle("48"),
                          previous_game_kickoff=datetime(
                              2026, 10, 12, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(result["status"], qe.STATUS_STALE)

    def test_capture_at_kickoff_is_invalid_not_retroactive(self):
        # A bundle captured AT kickoff is not pregame evidence; Form 2
        # can never be applied retroactively (proposal 4.6).
        result = evaluate(make_bundle("48", captured="2026-10-13T23:00:00Z"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_STALE)
        self.assertEqual(result["detail"], "CAPTURE_AT_OR_AFTER_KICKOFF")

    def test_capture_after_kickoff_is_invalid(self):
        result = evaluate(make_bundle("48", captured="2026-10-14T01:00:00Z"))
        self.assertEqual(result["status"], qe.STATUS_STALE)

    def test_unreadable_stamp_is_stale(self):
        # A capture that CONSISTENTLY recorded an unparseable stamp
        # (content, field and seal all agree -- the builder itself
        # refuses to emit such a bundle, so this is assembled by hand
        # and re-sealed) is stale evidence, refused on the stamp.
        bundle = make_bundle("48")
        depth = bundle["depth_snapshot"]
        depth["content"] = depth["content"].replace(
            "Updated: 10/10/2026 9:07AM ET", "Updated: recently ET")
        depth["update_stamp"] = "Updated: recently"
        result = evaluate(rechain(bundle))
        self.assertEqual(result["status"], qe.STATUS_STALE)
        self.assertEqual(result["detail"], "UPDATE_STAMP_UNPARSEABLE")

    def test_stamp_field_edited_after_capture_breaks_the_seal(self):
        # UPDATED (owner-review correction 3): the recorded stamp is
        # a sealed receipt field. Editing it after capture -- even to
        # another plausible value -- is tampering, not staleness.
        bundle = raw_bundle("48", depth_overrides={
            "update_stamp": "Updated: recently"})
        result = evaluate(bundle)
        self.assertEqual(result["status"], qe.STATUS_HASH_MISMATCH)
        self.assertEqual(result["detail"], "RECEIPT_CHAIN_MISMATCH")

    def test_stamp_after_capture_is_internally_inconsistent(self):
        # The chart's stamp (Oct 10) postdates the recorded capture
        # (Oct 9): the bytes cannot contain an update stamped after
        # they were captured. Self-consistent seal; semantic refusal.
        bundle = make_bundle("48", captured="2026-10-09T12:00:00Z")
        result = evaluate(bundle)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], qe.STATUS_STALE)
        self.assertEqual(result["detail"], "STAMP_AFTER_DEPTH_CAPTURE")


class CaptureHelperTests(unittest.TestCase):
    def test_parse_stamp_and_order_from_recorded_format(self):
        verbatim, parsed = qe.parse_update_stamp(depth_text("48"))
        self.assertEqual(verbatim, "Updated: 10/10/2026 9:07AM ET")
        self.assertEqual(parsed, datetime(2026, 10, 10, 13, 7,
                                          tzinfo=timezone.utc))
        order = qe.parse_qb_order(depth_text("48"))
        self.assertEqual([e["name"] for e in order],
                         ["Minicucci, Nick", "Streeter, Braden",
                          "Trujillo, Riley", "Archield Jr., EJ"])
        self.assertEqual(order[0]["jersey"], "4")

    def test_capture_with_injected_fetchers_runs_offline(self):
        roster_obj = roster_payload("48")
        bundle = qe.capture_form2_bundle(
            team_id="48", team_name="Delaware", event_id="401871067",
            opponent_id="2393", kickoff_utc=KICKOFF_ISO,
            previous_game_kickoff_utc=CHARTS["48"][3],
            depth_url=CHARTS["48"][0], now=NOW,
            clock=lambda: NOW,
            fetch_text=lambda url: depth_text("48"),
            fetch_json=lambda url: copy.deepcopy(roster_obj))
        result = evaluate(bundle)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["resolved_athlete_id"], "5153846")

    def test_capture_receipts_use_post_fetch_completion_times(self):
        seen = []
        times_checked = []
        roster_obj = roster_payload("48")

        def fetch_depth(_url):
            seen.append("depth_fetched")
            return depth_text("48")

        def fetch_roster(_url):
            seen.append("roster_fetched")
            return copy.deepcopy(roster_obj)

        def clock():
            times_checked.append(tuple(seen))
            return NOW - timedelta(seconds=30) if len(times_checked) == 1 else NOW

        bundle = qe.capture_form2_bundle(
            team_id="48", team_name="Delaware", event_id="401871067",
            opponent_id="2393", kickoff_utc=KICKOFF_ISO,
            previous_game_kickoff_utc=CHARTS["48"][3],
            depth_url=CHARTS["48"][0], now=NOW,
            clock=clock, fetch_text=fetch_depth, fetch_json=fetch_roster)
        self.assertEqual(times_checked,
                         [("depth_fetched",),
                          ("depth_fetched", "roster_fetched", "roster_fetched")])
        self.assertEqual(qe.dt(bundle["depth_snapshot"]["captured_at_utc"]),
                         NOW - timedelta(seconds=30))
        self.assertEqual(qe.dt(bundle["roster_snapshot"]["captured_at_utc"]), NOW)
        self.assertTrue(evaluate(bundle)["ok"])

    def test_capture_rejects_network_finish_at_kickoff(self):
        with self.assertRaisesRegex(ValueError, "CAPTURE_AT_OR_AFTER_KICKOFF"):
            qe.capture_form2_bundle(
                team_id="48", team_name="Delaware", event_id="401871067",
                opponent_id="2393", kickoff_utc=KICKOFF_ISO,
                previous_game_kickoff_utc=CHARTS["48"][3],
                depth_url=CHARTS["48"][0], now=NOW,
                clock=lambda: KICKOFF,
                fetch_text=lambda url: depth_text("48"),
                fetch_json=lambda url: copy.deepcopy(roster_payload("48")))

    def test_capture_rejects_nonmonotonic_or_unaware_clock(self):
        values = iter([NOW, NOW - timedelta(seconds=1)])
        with self.assertRaisesRegex(ValueError, "CAPTURE_CLOCK_NONMONOTONIC"):
            qe.capture_form2_bundle(
                team_id="48", team_name="Delaware", event_id="401871067",
                opponent_id="2393", kickoff_utc=KICKOFF_ISO,
                previous_game_kickoff_utc=CHARTS["48"][3],
                depth_url=CHARTS["48"][0],
                clock=lambda: next(values),
                fetch_text=lambda url: depth_text("48"),
                fetch_json=lambda url: copy.deepcopy(roster_payload("48")))
        with self.assertRaisesRegex(ValueError, "CAPTURE_CLOCK_UNVERIFIED"):
            qe.capture_form2_bundle(
                team_id="48", team_name="Delaware", event_id="401871067",
                opponent_id="2393", kickoff_utc=KICKOFF_ISO,
                previous_game_kickoff_utc=CHARTS["48"][3],
                depth_url=CHARTS["48"][0],
                clock=lambda: datetime(2026, 10, 13, 14),
                fetch_text=lambda url: depth_text("48"),
                fetch_json=lambda url: copy.deepcopy(roster_payload("48")))

    def test_capture_refuses_unstable_roster_count(self):
        roster_obj = roster_payload("48")
        calls = {"n": 0}

        def flaky(url):
            calls["n"] += 1
            obj = copy.deepcopy(roster_obj)
            if calls["n"] == 2:
                obj["athletes"][0]["items"] = obj["athletes"][0]["items"][:-1]
            return obj

        with self.assertRaises(ValueError) as ctx:
            qe.capture_form2_bundle(
                team_id="48", team_name="Delaware", event_id="401871067",
                opponent_id="2393", kickoff_utc=KICKOFF_ISO,
                previous_game_kickoff_utc=CHARTS["48"][3],
                depth_url=CHARTS["48"][0], now=NOW,
                clock=lambda: NOW,
                fetch_text=lambda url: depth_text("48"), fetch_json=flaky)
        self.assertIn(qe.STATUS_ROSTER_INCOMPLETE, str(ctx.exception))


# ---------------------------------------------------------------------------
# Stage-level: the pre-pricing gate consuming Form 2 (Delaware @ MTSU,
# the Oct 13 fixture both teams blocked on). Harness shapes follow the
# recorded-fixture pattern of test_cfb_qb_injury_feed_binding_20261013.
# ---------------------------------------------------------------------------

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


def cfb_mapping(league_payload):
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
        f"{ESPN}/football/college-football/injuries": league_payload,
    }


def cfb_row(**kw):
    row = {"sport": "CFB", "market": "SPREAD",
           "away": "Delaware Blue Hens", "home": "Middle Tennessee Blue Raiders",
           "side": "HOME", "line": -1.5, "odds": -110,
           "commence_time": KICKOFF_ISO, "quote_captured_at": NOW.isoformat()}
    row.update(kw)
    return row


def qb_factors(stage):
    return [f for f in stage["factors"] if f["factor"] == "qb_specific"]


def form2_receipts(stage):
    return [r for r in stage["receipts"]
            if r.get("source") == "QB_IDENTITY_EVIDENCE_FORM2"]


class CfbStageForm2Tests(unittest.TestCase):
    def stage(self, bundles_marker, league=RECORDED_CFB_LEAGUE):
        bundles = {}
        if bundles_marker in ("both", "delaware"):
            bundles["48"] = make_bundle("48")
        if bundles_marker == "both":
            bundles["2393"] = make_bundle("2393")
        if bundles_marker == "stale":
            bundles["48"] = make_bundle("48", prev="2026-10-11T23:00:00Z")
            bundles["2393"] = make_bundle("2393")
        return fi.stage_games([cfb_row()], now=NOW,
                              getter=FakeGetter(cfb_mapping(league)),
                              qb_form2_bundles=bundles or None)

    def test_form2_pass_both_teams_proceeds_labeled_with_zero_points(self):
        (stage,) = self.stage("both")
        self.assertFalse(stage["blocked"], stage["block_detail"])
        used = [f for f in qb_factors(stage) if f["status"] == "USED"]
        self.assertEqual(len(used), 2)
        self.assertTrue(all(
            f["source"] == "QB_IDENTITY_EVIDENCE_FORM2_DEPTH_ROSTER_COMPOSITE"
            for f in used))
        reasons = " ".join(f["reason"] for f in used)
        # Identity satisfied via Form 2 on both sides...
        self.assertEqual(reasons.count(qe.STATUS_SATISFIED), 2)
        self.assertIn("QB1_ATHLETE_ID_5153846", reasons)
        self.assertIn("QB1_ATHLETE_ID_5194626", reasons)
        # ...availability explicitly UNKNOWN on the record, never clean...
        self.assertEqual(
            reasons.count("AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"), 2)
        # ...and injury points exactly 0.0 on both sides.
        self.assertEqual(stage["adjustments"]["away_injury_pts"], 0.0)
        self.assertEqual(stage["adjustments"]["home_injury_pts"], 0.0)
        # The stage result carries the availability state structurally
        # (issue #2158): the runner stamps it on the priced rows and
        # the classification gate forces them research-only.
        self.assertEqual(stage["availability_status"],
                         "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT")
        # Receipts carry both component hashes + resolved athlete IDs.
        receipts = form2_receipts(stage)
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(r["status"] == qe.STATUS_SATISFIED
                            for r in receipts))
        self.assertTrue(all(r["availability_status"] ==
                            "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"
                            for r in receipts))
        self.assertEqual({r["resolved_qb1_athlete_id"] for r in receipts},
                         {"5153846", "5194626"})

    def test_form2_one_team_only_still_blocks_fail_closed(self):
        (stage,) = self.stage("delaware")
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        self.assertIn("HOME_QB_IDENTITY_UNVERIFIABLE", stage["block_detail"])
        self.assertEqual(stage["adjustments"], {})

    def test_form2_failure_keeps_block_and_records_failure_status(self):
        (stage,) = self.stage("stale")
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        self.assertIn("Form 2 composite failed closed: QB_DEPTH_EVIDENCE_STALE",
                      stage["block_detail"])
        reasons = " ".join(f["reason"] for f in qb_factors(stage))
        self.assertIn("FORM2_FAILED:QB_DEPTH_EVIDENCE_STALE", reasons)
        receipts = form2_receipts(stage)
        self.assertTrue(any(r["status"] == qe.STATUS_STALE for r in receipts))

    def test_no_bundles_gate_behaves_exactly_as_before(self):
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW,
            getter=FakeGetter(cfb_mapping(RECORDED_CFB_LEAGUE)))
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        self.assertIn("carries no report for this team", stage["block_detail"])
        self.assertEqual(form2_receipts(stage), [])

    def test_form1_governs_feed_covered_teams_form2_never_consulted(self):
        # Re-contracted (Oct 13, 2026; framing revised Oct 14 under
        # the owner's source-specific as-of validity standard): the
        # feed entries are dated in the fixture week -- valid for
        # the target game's reporting period -- so the teams are
        # feed-covered AND binding (main's #2184 construction
        # reaches the same result via its 21-day window; the
        # universal-window gap vs the standard is documented in
        # the binding battery's docstring). The undated variant is
        # pinned separately below -- it blocks fail-closed as
        # UNKNOWN, Form 2 still untouched.
        league = {"injuries": RECORDED_CFB_LEAGUE["injuries"] + [
            {"id": "48", "displayName": "Delaware Blue Hens", "injuries": [
                {"status": "Out", "date": "2026-10-13T13:00:00Z",
                 "athlete": {"displayName": "Reserve Wideout",
                             "position": {"abbreviation": "WR"}}}]},
            {"id": "2393", "displayName": "Middle Tennessee Blue Raiders",
             "injuries": [
                 {"status": "Active", "date": "2026-10-13T13:00:00Z",
                  "athlete": {"displayName": "Starting Quarterback",
                              "position": {"abbreviation": "QB"}}}]},
        ]}
        # Even a poisoned (stale) bundle set changes nothing: a team in
        # the injury feed is Form 1 territory, full stop.
        (stage,) = self.stage("stale", league=league)
        self.assertFalse(stage["blocked"])
        self.assertEqual(stage["adjustments"]["away_injury_pts"], -0.15)
        self.assertEqual(stage["adjustments"]["home_injury_pts"], 0.0)
        self.assertEqual(form2_receipts(stage), [])

    def test_form1_governs_stale_feed_teams_form2_never_consulted(self):
        # The pre-#2184 fixture shape (UNDATED entries) for the same
        # feed-covered teams: the currency gate classifies both
        # bindings STALE_INJURY_ENTRIES_UNKNOWN, the stage blocks
        # fail-closed, and Form 2 is STILL never consulted -- staleness
        # is not absence, and only absence (TEAM_NOT_IN_INJURY_FEED)
        # may open the Form 2 consult.
        league = {"injuries": RECORDED_CFB_LEAGUE["injuries"] + [
            {"id": "48", "displayName": "Delaware Blue Hens", "injuries": [
                {"status": "Out",
                 "athlete": {"displayName": "Reserve Wideout",
                             "position": {"abbreviation": "WR"}}}]},
            {"id": "2393", "displayName": "Middle Tennessee Blue Raiders",
             "injuries": [
                 {"status": "Active",
                  "athlete": {"displayName": "Starting Quarterback",
                              "position": {"abbreviation": "QB"}}}]},
        ]}
        (stage,) = self.stage("stale", league=league)
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"],
                         fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        self.assertEqual(form2_receipts(stage), [])
        self.assertIsNone(stage["availability_status"])
        reasons = " ".join(f["reason"] for f in qb_factors(stage))
        self.assertIn("STALE_INJURY_ENTRIES_UNKNOWN", reasons)
        self.assertNotIn("TEAM_NOT_IN_INJURY_FEED", reasons)

    def test_disposition_switch_flip_restores_availability_block(self):
        original = qe.FORM2_PROCEEDS_WITH_AVAILABILITY_LABEL
        qe.FORM2_PROCEEDS_WITH_AVAILABILITY_LABEL = False
        try:
            (stage,) = self.stage("both")
        finally:
            qe.FORM2_PROCEEDS_WITH_AVAILABILITY_LABEL = original
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"],
                         "BLOCKED_PREPRICING_QB_AVAILABILITY_UNVERIFIED")
        self.assertEqual(stage["adjustments"], {})

    def test_stage_bundle_for_wrong_event_blocks_fixture_mismatch(self):
        # Both bundles name a different ESPN event than the staged
        # fixture (correction 1, end to end): the gate stays blocked
        # and the failure status is recorded on the factor + receipts.
        bundles = {"48": make_bundle("48", event_id="401871068"),
                   "2393": make_bundle("2393", event_id="401871068")}
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW,
            getter=FakeGetter(cfb_mapping(RECORDED_CFB_LEAGUE)),
            qb_form2_bundles=bundles)
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        reasons = " ".join(f["reason"] for f in qb_factors(stage))
        self.assertIn("FORM2_FAILED:QB_EVIDENCE_FIXTURE_MISMATCH", reasons)
        receipts = form2_receipts(stage)
        self.assertTrue(any(r["status"] == qe.STATUS_FIXTURE_MISMATCH
                            for r in receipts))
        self.assertIsNone(stage["availability_status"])

    def test_bundles_may_be_supplied_as_a_list(self):
        bundles = [make_bundle("48"), make_bundle("2393")]
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW,
            getter=FakeGetter(cfb_mapping(RECORDED_CFB_LEAGUE)),
            qb_form2_bundles=bundles)
        self.assertFalse(stage["blocked"], stage["block_detail"])


if __name__ == "__main__":
    unittest.main()
