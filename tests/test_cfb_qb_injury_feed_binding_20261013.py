"""Regression tests for the CFB QB-identity binding failure (Oct 13, 2026).

Root cause, live-verified: ESPN's college-football injuries feed carries
groups ONLY for teams with current injury entries -- the recorded live
payload below (fetched 2026-10-13T12:00Z, payload timestamp
2026-10-13T12:00:41Z) contains exactly 3 groups (Florida 57, Rice 242,
Virginia 258) for ~136 FBS teams, and the per-team endpoint returns {}
for every team in both leagues. Delaware (48), Middle Tennessee (2393),
FIU (2229) and Jacksonville State (55) have no group, so no team-group
binding is possible. The binder classified that as UNUSABLE_SCHEMA --
the same label used for genuinely unparseable payloads -- misstating
the evidence in the audit trail.

The fix classifies a well-formed league feed that lacks the team as
TEAM_NOT_IN_INJURY_FEED. The QB gate stays fail-closed: absence is NOT
a verified clean report and the game still blocks
BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED -- now with the accurate
reason. Genuinely present data (a group for the team) binds exactly as
before; malformed payloads still classify UNUSABLE_SCHEMA and block.

Re-contract (Oct 13, 2026; framing revised Oct 14 under the owner's
source-specific AS-OF VALIDITY standard): presence alone no longer
binds -- an injury report must be valid for the TARGET GAME's
reporting period. Each source's effective date, observation time,
validity period and game association govern; neither a universal
day-count nor an unrestricted season window is the standard. A
present group whose rows are stale for the target game or undated
(no effective date preserved, so period validity cannot be
established) classifies STALE_INJURY_ENTRIES_UNKNOWN and the gate
blocks fail-closed (UNKNOWN/BLOCKED); it is never reclassified as
absence, so Form 2 is never consulted for a feed-present team. The
fixtures below keep their recorded provenance; the expectations pin
fixture-level behavior that the as-of standard and main's current
construction agree on, mirroring the audit lane's #2192
reconciliation.

CONSTRUCTION GAP (documented, not blessed): main's merged #2184
construction implements currency as a UNIVERSAL 21-day window
(INJURY_CURRENCY_DAYS = {"CFB": 21} in free_models.PublicContext).
That window misclassifies the long-layoff case: a source's
game-associated report dated more than 21 days before the fixture,
with no newer report from that source (e.g. a late-November
regular-season report for a late-December bowl game), classifies
STALE_UNKNOWN although it is the report valid for the target game's
reporting period under the standard; symmetrically, an in-window
report belonging to an earlier game can satisfy the window. No
fixture below exercises either case, and no assertion in this file
endorses the universal window as the rule -- closing the gap means
replacing the day-count with per-source as-of validity in
PublicContext, which is main's module and outside this re-contract.

All payloads below are recorded fixtures (structure verbatim from the
live responses; athlete link lists trimmed). No network is touched.
"""
import unittest
from datetime import datetime, timezone

from artifacts import free_models
from sportsedge.prepricing import factor_ingestion as fi

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
KICKOFF_CFB = "2026-10-13T23:00:00Z"

# Recorded live CFB league injuries payload, 2026-10-13: 3 groups, one
# row each. (Florida's row is a stale 2020 wire entry -- the feed is a
# sparse, low-maintenance wire, which is the point of these fixtures.)
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


def recorded_getter(league_payload=RECORDED_CFB_LEAGUE):
    # The per-team endpoint returned {} for every team probed live
    # (all four CUSA teams, Florida, Rice, and four NFL teams).
    def getter(url):
        if "/teams/" in url and url.endswith("/injuries"):
            return {}
        if url.endswith("/football/college-football/injuries"):
            return league_payload
        raise AssertionError(url)
    return getter


class RecordedFeedBindingTests(unittest.TestCase):
    def test_recorded_cfb_feed_reports_stale_or_undated_rows_as_unknown(self):
        # The original recorded wire is NOT a current injury report:
        # Florida's row dates to 2020; Rice and Virginia have no row
        # dates. Preserve source provenance and assert the current
        # fail-closed rule (as-of validity; on main, the #2184
        # currency gate): a present group with
        # stale/undated rows is STALE_UNKNOWN, never a binding -- and
        # never reclassified as absence (TEAM_NOT_IN_INJURY_FEED).
        provider = free_models.PublicContext(NOW, getter=recorded_getter())
        for tid, name in (("57", "Florida"), ("242", "Rice"),
                          ("258", "Virginia")):
            rows, status = provider.injury_rows("CFB", {"id": tid})
            self.assertIsNone(rows, name)
            self.assertEqual(status, free_models.INJURY_STALE_UNKNOWN, name)
            self.assertEqual(provider.injury_points("CFB", {"id": tid}),
                             (0.0, free_models.INJURY_STALE_UNKNOWN), name)

    def test_recorded_cfb_feed_absent_cusa_teams_are_not_unusable_schema(self):
        provider = free_models.PublicContext(NOW, getter=recorded_getter())
        for tid, name in (("48", "Delaware"), ("2393", "Middle Tennessee"),
                          ("2229", "FIU"), ("55", "Jacksonville State")):
            rows, status = provider.injury_rows("CFB", {"id": tid})
            self.assertIsNone(rows, name)
            # Absent from a well-formed feed: unverified (the gate keeps
            # blocking) but NOT a schema failure.
            self.assertEqual(status, "TEAM_NOT_IN_INJURY_FEED", name)
            pts, pts_status = provider.injury_points("CFB", {"id": tid})
            self.assertEqual((pts, pts_status),
                             (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE"), name)
        receipts = [r for r in provider.receipts
                    if r.get("status") == "TEAM_NOT_IN_INJURY_FEED"]
        self.assertEqual(len(receipts), 4)
        self.assertFalse([r for r in provider.receipts
                          if r.get("status") == "UNUSABLE_SCHEMA"])
        self.assertIn("SAMPLE_TEAM_IDS=57,242,258", receipts[0]["reason"])
        self.assertIn("FEED_WELL_FORMED_TEAM_ABSENT", receipts[0]["note"])

    def test_present_group_with_empty_injuries_verifies_zero_rows(self):
        league = {"injuries": [
            {"id": "48", "displayName": "Delaware Blue Hens", "injuries": []}]}
        provider = free_models.PublicContext(
            NOW, getter=recorded_getter(league))
        rows, status = provider.injury_rows("CFB", {"id": "48"})
        self.assertEqual((rows, status), ([], "STRUCTURE_VERIFIED"))
        # A group that IS present with zero entries is a verified report
        # of no reported injuries -- unlike absence, it verifies.

    def test_team_endpoint_flat_empty_list_verifies_zero_rows(self):
        def getter(url):
            if "/teams/" in url and url.endswith("/injuries"):
                return {"injuries": []}
            raise AssertionError(url)
        provider = free_models.PublicContext(NOW, getter=getter)
        rows, status = provider.injury_rows("CFB", {"id": "48"})
        self.assertEqual((rows, status), ([], "STRUCTURE_VERIFIED"))


class MalformedStillUnusableTests(unittest.TestCase):
    def _classify(self, league_payload):
        provider = free_models.PublicContext(
            NOW, getter=recorded_getter(league_payload))
        return provider.injury_rows("CFB", {"id": "48"})

    def test_injuries_not_a_list(self):
        rows, status = self._classify({"injuries": "notalist"})
        self.assertEqual((rows, status), (None, "UNUSABLE_SCHEMA"))

    def test_payload_without_injuries_member(self):
        rows, status = self._classify({"unexpected": "shape"})
        self.assertEqual((rows, status), (None, "UNUSABLE_SCHEMA"))

    def test_group_without_resolvable_team_id(self):
        # An unresolvable group might BE the target team, so absence
        # cannot be declared: still a schema failure.
        rows, status = self._classify({"injuries": [
            {"displayName": "Mystery Team", "injuries": []}]})
        self.assertEqual((rows, status), (None, "UNUSABLE_SCHEMA"))

    def test_duplicate_target_groups_are_ambiguous_not_absent(self):
        rows, status = self._classify({"injuries": [
            {"id": "48", "displayName": "Delaware Blue Hens", "injuries": []},
            {"id": "48", "displayName": "Delaware Blue Hens", "injuries": []}]})
        self.assertEqual((rows, status), (None, "UNUSABLE_SCHEMA"))


# ---------------------------------------------------------------------------
# Stage-level: the Oct 13 fixture (Delaware @ Middle Tennessee)
# ---------------------------------------------------------------------------

def cfb_teams_payload():
    return {"sports": [{"leagues": [{"teams": [
        {"team": {"id": "48", "displayName": "Delaware Blue Hens",
                  "name": "Blue Hens", "shortDisplayName": "Delaware",
                  "abbreviation": "DEL", "location": "Delaware"}},
        {"team": {"id": "2393", "displayName": "Middle Tennessee Blue Raiders",
                  "name": "Blue Raiders", "shortDisplayName": "Middle Tennessee",
                  "abbreviation": "MTSU", "location": "Middle Tennessee"}},
    ]}]}]}


def cfb_scoreboard_payload():
    return {"events": [{
        "id": "401871067", "date": KICKOFF_CFB,
        "competitions": [{
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


def cfb_mapping(league_payload):
    mapping = {
        f"{ESPN}/football/college-football/teams?limit=500": cfb_teams_payload(),
        f"{ESPN}/football/college-football/scoreboard?dates=20261012&limit=500": {"events": []},
        f"{ESPN}/football/college-football/scoreboard?dates=20261013&limit=500": cfb_scoreboard_payload(),
        f"{ESPN}/football/college-football/scoreboard?dates=20261014&limit=500": {"events": []},
        # Recorded live shape: the per-team endpoint returns {} for all.
        f"{ESPN}/football/college-football/teams/48/injuries": {},
        f"{ESPN}/football/college-football/teams/2393/injuries": {},
        f"{ESPN}/football/college-football/injuries": league_payload,
    }
    return mapping


def cfb_row(**kw):
    row = {"sport": "CFB", "market": "SPREAD",
           "away": "Delaware Blue Hens", "home": "Middle Tennessee Blue Raiders",
           "side": "HOME", "line": -1.5, "odds": -110,
           "commence_time": KICKOFF_CFB, "quote_captured_at": NOW.isoformat()}
    row.update(kw)
    return row


def qb_factors(stage):
    return [f for f in stage["factors"] if f["factor"] == "qb_specific"]


class CfbStageTests(unittest.TestCase):
    def test_absent_teams_block_with_accurate_reason(self):
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW,
            getter=FakeGetter(cfb_mapping(RECORDED_CFB_LEAGUE)))
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        # The reason now states the evidence accurately: the feed is
        # well-formed and carries no report for the team -- it does NOT
        # claim a schema/binding failure.
        self.assertIn("carries no report for this team", stage["block_detail"])
        self.assertNotIn("failed team-group binding", stage["block_detail"])
        reasons = " ".join(f["reason"] for f in qb_factors(stage))
        self.assertIn("INJURY_FEED_NO_TEAM_REPORT:TEAM_NOT_IN_INJURY_FEED",
                      reasons)
        self.assertEqual(stage["adjustments"], {})

    def test_reported_teams_bind_and_pass_the_qb_gate(self):
        # Entries are dated in the fixture week -- the report for
        # the target game's reporting period -- so presence +
        # as-of validity binds (main's current construction reaches
        # the same result via its 21-day window; see the docstring
        # gap note).
        league = {"injuries": RECORDED_CFB_LEAGUE["injuries"] + [
            {"id": "48", "displayName": "Delaware Blue Hens", "injuries": [
                {"status": "Out", "date": "2026-10-13T11:00:00Z",
                 "athlete": {"displayName": "Reserve Wideout",
                             "position": {"abbreviation": "WR"}}}]},
            {"id": "2393", "displayName": "Middle Tennessee Blue Raiders",
             "injuries": [
                 {"status": "Active", "date": "2026-10-13T11:00:00Z",
                  "athlete": {"displayName": "Starting Quarterback",
                              "position": {"abbreviation": "QB"}}}]},
        ]}
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping(league)))
        self.assertFalse(stage["blocked"])
        used = [f for f in qb_factors(stage) if f["status"] == "USED"]
        self.assertEqual(len(used), 2)
        self.assertTrue(all(f["source"] == "ESPN_INJURIES_STRUCTURE_VERIFIED"
                            for f in used))
        # Delaware's Out WR costs the CFB 0.15; MTSU's Active QB costs 0.
        self.assertEqual(stage["adjustments"]["away_injury_pts"], -0.15)
        self.assertEqual(stage["adjustments"]["home_injury_pts"], 0.0)

    def test_stale_reported_teams_block_as_unknown_not_absent(self):
        # The same reported groups WITHOUT dates (the pre-#2184 fixture
        # shape): under the currency gate the bindings are
        # STALE_INJURY_ENTRIES_UNKNOWN. The gate blocks fail-closed and
        # the reason names staleness -- the teams are never treated as
        # absent from the feed (which is the only state in which Form 2
        # identity evidence may be consulted).
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
        (stage,) = fi.stage_games(
            [cfb_row()], now=NOW, getter=FakeGetter(cfb_mapping(league)))
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        reasons = " ".join(f["reason"] for f in qb_factors(stage))
        self.assertIn("STALE_INJURY_ENTRIES_UNKNOWN", reasons)
        self.assertNotIn("TEAM_NOT_IN_INJURY_FEED", reasons)
        self.assertEqual(stage["adjustments"], {})


if __name__ == "__main__":
    unittest.main()
