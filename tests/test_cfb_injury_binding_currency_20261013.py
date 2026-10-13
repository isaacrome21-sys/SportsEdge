"""CFB injury-binding currency + QB-position gate (Oct 13, 2026).

Defect (CFB coverage dry-run, COVERAGE.md section (c)): for Florida @
Texas, Florida's prepricing `qb_specific` factor was staged USED with
-0.15 injury points on the strength of the team's single ESPN feed
entry -- Kahleil Jackson, WR, Out, dated 2020-11-21 -- via the
structure-only binding in free_models.injury_rows. The fixture blocked
only because Texas had no feed group at all. Two defects:

  1. POSITION: a non-QB entry satisfied a qb_specific factor.
  2. STALENESS: an entry dated years before the fixture satisfied
     anything at all (gate, points, notes).

Rule implemented (see artifacts/free_models.py injury_rows and
sportsedge/prepricing/factor_ingestion.py):

  * An entry with a parseable `date` satisfies only if the date falls
    inside the fixture's season window: on/after August 1 of the
    fixture's season year (fixtures in Jan-Jul belong to the season
    that began the previous calendar year -- the bowl/January edge).
    Stale-dated entries are dropped from the bound rows; if every
    entry in a bound group is stale-dated, the binding returns
    (None, "NO_CURRENT_ENTRIES") and satisfies nothing.
  * qb_specific (NFL/CFB) is satisfied only when the bound report
    contains at least one CURRENT (in-window, parseably dated) QB
    entry -- or is empty after filtering (legacy clean-report
    behavior, unchanged). A current WR entry alone does not satisfy
    it; an undated QB entry does not satisfy it (fail-closed).
  * Undated entries are NOT dropped from the rows: the legacy
    injury_points contract (whose preserved-contract tests stub
    undated entries, as the pre-fix binding accepted) is unchanged
    for points. Real ESPN entries always carry `date` (verified
    against the live 2026-10-13 CFB census payload), so the
    undated carve-out is synthetic-only. Flagged for owner review.
"""
from datetime import datetime, timezone

import pytest

from artifacts import free_models
from sportsedge.prepricing import factor_ingestion as fi

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-17T16:00:00Z"  # Florida @ Texas (dry-run fixture)
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
CFB = "football/college-football"
FLORIDA_ID = "57"
TEXAS_ID = "251"


class FakeGetter:
    """Unmapped URLs fail like a dead network (fetch degrades to None)."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.mapping:
            raise OSError("UNMAPPED_URL:" + url)
        return self.mapping[url]


def entry(name, pos, status, date=None, athlete_id="1"):
    e = {"athlete": {"id": athlete_id, "displayName": name,
                     "position": {"abbreviation": pos}},
         "status": status}
    if date is not None:
        e["date"] = date
    return e


def grouped(team_id, team_name, entries):
    """The grouped league-shaped payload ESPN's CFB endpoints return."""
    return {"injuries": [{"id": team_id, "displayName": team_name,
                          "injuries": entries}]}


def flat(entries):
    return {"injuries": entries}


def binding_provider(team_payload):
    mapping = {
        f"{ESPN}/{CFB}/teams/{FLORIDA_ID}/injuries": team_payload,
        f"{ESPN}/{CFB}/injuries": {"injuries": []},
    }
    return free_models.PublicContext(NOW, getter=FakeGetter(mapping))


FLORIDA = {"id": FLORIDA_ID}
REF = free_models.dt(KICKOFF)


# ------------------------------------------------------------- binding

def test_stale_wr_entry_binds_nothing():
    # The exact dry-run case: Florida's only entry is a WR, Out,
    # dated 2020-11-21 -- six seasons before the fixture.
    provider = binding_provider(grouped(FLORIDA_ID, "Florida Gators", [
        entry("Kahleil Jackson", "WR", "Out", "2020-11-21T18:31Z",
              athlete_id="4693740"),
    ]))
    rows, status = provider.injury_rows("CFB", FLORIDA, reference_date=REF)
    assert rows is None
    assert status == "NO_CURRENT_ENTRIES"
    pts, pts_status = provider.injury_points(
        "CFB", FLORIDA, reference_date=REF)
    assert pts == 0.0
    assert pts_status == "MISSING_OR_UNRECOGNIZED_SOURCE"


def test_current_qb_entry_satisfies_exactly_as_before():
    provider = binding_provider(flat([
        entry("Gator QB", "QB", "Out", "2026-10-10T15:00Z"),
    ]))
    rows, status = provider.injury_rows("CFB", FLORIDA, reference_date=REF)
    assert status == "STRUCTURE_VERIFIED"
    assert len(rows) == 1
    pts, pts_status = provider.injury_points(
        "CFB", FLORIDA, reference_date=REF)
    # Identical to the pre-fix contract for this input.
    assert pts == -0.15
    assert pts_status == ("HEURISTIC_OUT_DOUBTFUL_REPORTED_1"
                          "_UNKNOWN_COMPLETENESS")


def test_stale_qb_entry_binds_nothing():
    provider = binding_provider(flat([
        entry("Gator QB", "QB", "Out", "2022-09-03T16:00Z"),
    ]))
    rows, status = provider.injury_rows("CFB", FLORIDA, reference_date=REF)
    assert rows is None
    assert status == "NO_CURRENT_ENTRIES"
    pts, pts_status = provider.injury_points(
        "CFB", FLORIDA, reference_date=REF)
    assert pts == 0.0
    assert pts_status == "MISSING_OR_UNRECOGNIZED_SOURCE"


def test_stale_entries_contribute_no_points_when_mixed():
    provider = binding_provider(flat([
        entry("Kahleil Jackson", "WR", "Out", "2020-11-21T18:31Z",
              athlete_id="4693740"),
        entry("Gator QB", "QB", "Out", "2026-10-10T15:00Z",
              athlete_id="2"),
    ]))
    rows, status = provider.injury_rows("CFB", FLORIDA, reference_date=REF)
    assert status == "STRUCTURE_VERIFIED"
    assert len(rows) == 1  # the stale entry is gone from the bound rows
    pts, pts_status = provider.injury_points(
        "CFB", FLORIDA, reference_date=REF)
    # Pre-fix this was -0.30 / REPORTED_2: the 2020 entry moved points.
    assert pts == -0.15
    assert pts_status == ("HEURISTIC_OUT_DOUBTFUL_REPORTED_1"
                          "_UNKNOWN_COMPLETENESS")


def test_undated_entries_keep_legacy_points_contract():
    # Scoping decision (module docstring): undated entries never
    # satisfy the qb_specific gate, but the preserved injury_points
    # contract -- whose own contract tests stub undated entries --
    # is unchanged. Real ESPN entries always carry a date.
    provider = binding_provider(flat([
        entry("Gator QB", "QB", "Out"),
        entry("Gator RB", "RB", "Questionable", athlete_id="2"),
    ]))
    rows, status = provider.injury_rows("CFB", FLORIDA, reference_date=REF)
    assert status == "STRUCTURE_VERIFIED"
    assert len(rows) == 2
    pts, pts_status = provider.injury_points(
        "CFB", FLORIDA, reference_date=REF)
    assert pts == -0.15
    assert pts_status == ("HEURISTIC_OUT_DOUBTFUL_REPORTED_1"
                          "_UNKNOWN_COMPLETENESS")


def test_empty_bound_group_is_unchanged():
    provider = binding_provider(flat([]))
    rows, status = provider.injury_rows("CFB", FLORIDA, reference_date=REF)
    assert status == "STRUCTURE_VERIFIED"
    assert rows == []
    pts, pts_status = provider.injury_points(
        "CFB", FLORIDA, reference_date=REF)
    assert pts == 0.0
    assert pts_status == ("HEURISTIC_OUT_DOUBTFUL_REPORTED_0"
                          "_UNKNOWN_COMPLETENESS")


@pytest.mark.parametrize("ref_iso,entry_date,binds", [
    # October fixture: window = Aug 1 of the same calendar year.
    ("2026-10-17T16:00:00Z", "2026-08-01T00:00Z", True),
    ("2026-10-17T16:00:00Z", "2026-07-31T23:59Z", False),
    ("2026-10-17T16:00:00Z", "2026-01-15T00:00Z", False),  # prior season
    ("2026-10-17T16:00:00Z", "2025-11-20T00:00Z", False),
    # Late-August opener: same window boundary.
    ("2026-08-29T16:00:00Z", "2026-08-01T00:00Z", True),
    ("2026-08-29T16:00:00Z", "2026-07-15T00:00Z", False),
    # January bowl fixture: season year is the PREVIOUS calendar year.
    ("2027-01-10T16:00:00Z", "2026-08-01T00:00Z", True),
    ("2027-01-10T16:00:00Z", "2026-10-03T00:00Z", True),
    ("2027-01-10T16:00:00Z", "2026-07-31T00:00Z", False),
    ("2027-01-10T16:00:00Z", "2025-12-01T00:00Z", False),
])
def test_season_window_edges(ref_iso, entry_date, binds):
    provider = binding_provider(flat([
        entry("Gator QB", "QB", "Out", entry_date),
    ]))
    rows, status = provider.injury_rows(
        "CFB", FLORIDA, reference_date=free_models.dt(ref_iso))
    if binds:
        assert status == "STRUCTURE_VERIFIED"
        assert len(rows) == 1
    else:
        assert rows is None
        assert status == "NO_CURRENT_ENTRIES"


# ------------------------------------------------------- prepricing stage

TEAM_FIELDS = {
    "57": ("Florida Gators", "Gators", "Florida", "FLA", "Florida"),
    "251": ("Texas Longhorns", "Longhorns", "Texas", "TEX", "Texas"),
}
CFB_TEAMS_URL = f"{ESPN}/{CFB}/teams?limit=500"


def _team_dict(tid):
    dn, nm, short, abbr, loc = TEAM_FIELDS[tid]
    return {"id": tid, "displayName": dn, "name": nm,
            "shortDisplayName": short, "abbreviation": abbr,
            "location": loc}


def _scoreboard():
    def comp(tid, home_away):
        return {"homeAway": home_away, "team": _team_dict(tid)}
    return {"events": [{"id": "401856724", "date": KICKOFF,
                        "competitions": [{
                            "competitors": [comp(TEXAS_ID, "home"),
                                            comp(FLORIDA_ID, "away")],
                            "venue": {"indoor": False,
                                      "fullName": "Test Stadium",
                                      "address": {"city": "Austin",
                                                  "state": "TX"}}}]}]}


def _stage_mapping(florida_payload, texas_payload):
    return {
        CFB_TEAMS_URL: {"sports": [{"leagues": [{"teams": [
            {"team": _team_dict(FLORIDA_ID)},
            {"team": _team_dict(TEXAS_ID)}]}]}]},
        f"{ESPN}/{CFB}/scoreboard?dates=20261016&limit=500":
            {"events": []},
        f"{ESPN}/{CFB}/scoreboard?dates=20261017&limit=500":
            _scoreboard(),
        f"{ESPN}/{CFB}/scoreboard?dates=20261018&limit=500":
            {"events": []},
        f"{ESPN}/{CFB}/teams/{FLORIDA_ID}/injuries": florida_payload,
        f"{ESPN}/{CFB}/teams/{TEXAS_ID}/injuries": texas_payload,
        f"{ESPN}/{CFB}/injuries": {"injuries": []},
    }


def _stage(florida_payload, texas_payload):
    row = {"sport": "CFB", "market": "SPREAD", "away": "Florida Gators",
           "home": "Texas Longhorns", "side": "HOME", "line": -3.5,
           "odds": -110, "commence_time": KICKOFF}
    return fi.stage_games([row], now=NOW,
                          getter=FakeGetter(
                              _stage_mapping(florida_payload,
                                             texas_payload)))[0]


def _qb_factors(stage):
    return [f for f in stage["factors"] if f["factor"] == "qb_specific"]


def _side_factor(stage, side):
    for f in _qb_factors(stage):
        if side in f["reason"] or side in f.get("source", ""):
            return f
    # The failure-branch reason names the side; the USED reason embeds
    # "<SIDE>_OUT_QB:...". Match on the reason prefix token.
    for f in _qb_factors(stage):
        if f["reason"].startswith(side + "_"):
            return f
    raise AssertionError(f"no qb_specific factor for {side}: "
                         f"{_qb_factors(stage)}")


TEXAS_CURRENT_QB = grouped(TEXAS_ID, "Texas Longhorns", [
    entry("Longhorn QB", "QB", "Out", "2026-10-12T15:00Z",
          athlete_id="9"),
])


def test_stage_stale_wr_does_not_satisfy_florida_qb_specific():
    stage = _stage(
        grouped(FLORIDA_ID, "Florida Gators", [
            entry("Kahleil Jackson", "WR", "Out", "2020-11-21T18:31Z",
                  athlete_id="4693740"),
        ]),
        TEXAS_CURRENT_QB)
    away = _side_factor(stage, "AWAY")
    assert away["status"] != "USED"
    home = _side_factor(stage, "HOME")
    assert home["status"] == "USED"
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_QB_IDENTITY_UNVERIFIED
    assert "AWAY" in stage["block_detail"]


def test_stage_current_qbs_satisfy_exactly_as_before():
    stage = _stage(
        grouped(FLORIDA_ID, "Florida Gators", [
            entry("Gator QB", "QB", "Out", "2026-10-10T15:00Z"),
        ]),
        grouped(TEXAS_ID, "Texas Longhorns", [
            entry("Longhorn QB", "QB", "Doubtful", "2026-10-12T15:00Z",
                  athlete_id="9"),
        ]))
    for side in ("AWAY", "HOME"):
        assert _side_factor(stage, side)["status"] == "USED"
    assert stage["adjustments"]["away_injury_pts"] == -0.15
    assert stage["adjustments"]["home_injury_pts"] == -0.15
    assert stage["block_reason"] != fi.BLOCK_QB_IDENTITY_UNVERIFIED


def test_stage_current_wr_alone_does_not_satisfy_qb_specific():
    stage = _stage(
        grouped(FLORIDA_ID, "Florida Gators", [
            entry("Gator WR", "WR", "Out", "2026-10-10T15:00Z"),
        ]),
        TEXAS_CURRENT_QB)
    away = _side_factor(stage, "AWAY")
    assert away["status"] != "USED"
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_QB_IDENTITY_UNVERIFIED
    assert "AWAY" in stage["block_detail"]


def test_stage_undated_qb_does_not_satisfy_qb_specific():
    stage = _stage(
        grouped(FLORIDA_ID, "Florida Gators", [
            entry("Gator QB", "QB", "Out"),  # no date: fail-closed
        ]),
        TEXAS_CURRENT_QB)
    away = _side_factor(stage, "AWAY")
    assert away["status"] != "USED"
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_QB_IDENTITY_UNVERIFIED
    assert "AWAY" in stage["block_detail"]
