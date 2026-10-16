"""Participation wiring tests: skill-position verdicts + phone intake lift.

Two fictional teams (CHI vs GB), 2026 season, target week 4 -- the same
synthetic universe as the QB bridge battery.  All player ids/names are
synthetic; the ESPN payloads below are fabricated in the recorded
fixture's shape, not captured data.

Rules under test (documented in the bridge + phone modules, as
remediated per the PR #2274 audit):
- Skill states mirror the QB discipline.  Only the confirmed tier --
  CONFIRMED_STARTER (game-day active, chart rank 1) and CONFIRMED_ACTIVE
  (game-day active, rotation) -- passes a participation gate, and
  "game-day active" now requires a completeness-provable official
  inactive snapshot (B1): loose designation rows are positive evidence
  only.  Projected tiers never confirm.
- In the phone pricer, that same confirmed tier lifts
  STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG only when the bundle arrives
  through the anchored archive loader with verified provenance (B2);
  an inline payload bundle is UNVERIFIED_BUNDLE and never lifts.
  Bindings are the versioned ESPN-ID <-> GSIS-ID crosswalk (B3).
  Every non-lift outcome keeps the stamp and records the named
  refusal.  Labels and authority flags are identical either way.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlparse

import pytest

from artifacts import run_it_full as runner
from sportsedge.nfl_participation_bridge import (
    NFLParticipationError,
    assess_skill_participation,
    require_confirmed_qb_role,
    assess_qb_participation,
    require_confirmed_skill_role,
    skill_role_assessment,
)
from sportsedge.nfl_phone_player_pricing import phone_nfl_player_rows

KICKOFF = "2026-10-04T17:00:00Z"
GAME_ID = "synthetic-2026-w4-chi-gb"
SNAPSHOT = "2026-10-01T12:00:00Z"
GAMEDAY = "2026-10-04T16:00:00Z"
PRE_INACTIVES = "2026-10-02T18:00:00Z"


# ------------------------------------------------------------- fixtures

def _stat(player_id, name, position, week, *, team, carries=0, targets=0,
          receptions=0, receiving_yards=0, rushing_yards=0):
    return {
        "player_id": player_id, "player_name": name, "position": position,
        "recent_team": team, "season": 2026, "week": week,
        "season_type": "REG", "attempts": 0, "completions": 0,
        "passing_yards": 0, "passing_tds": 0, "interceptions": 0,
        "carries": carries, "rushing_yards": rushing_yards,
        "rushing_tds": 0, "targets": targets, "receptions": receptions,
        "receiving_yards": receiving_yards, "receiving_tds": 0,
    }


def player_rows():
    rows = []
    for week in (1, 2, 3):
        rows.append(_stat("qb1", "Chi QB", "QB", week, team="CHI",
                          carries=4, rushing_yards=20))
        rows.append(_stat("rb1", "Chi RB", "RB", week, team="CHI",
                          carries=15, rushing_yards=65, targets=5,
                          receptions=4, receiving_yards=30))
        rows.append(_stat("rb2", "Chi RB Two", "RB", week, team="CHI",
                          carries=6, rushing_yards=22))
        rows.append(_stat("wr1", "Chi WR One", "WR", week, team="CHI",
                          targets=9, receptions=6, receiving_yards=80))
        rows.append(_stat("wr2", "Chi WR Two", "WR", week, team="CHI",
                          targets=6, receptions=4, receiving_yards=52))
        rows.append(_stat("te1", "Chi TE", "TE", week, team="CHI",
                          targets=4, receptions=3, receiving_yards=35))
        rows.append(_stat("gqb", "Gb QB", "QB", week, team="GB",
                          carries=3, rushing_yards=12))
        rows.append(_stat("gwr1", "Gb WR One", "WR", week, team="GB",
                          targets=8, receptions=5, receiving_yards=66))
    return rows


def _depth(dt, team, pid, name, pos, rank):
    return {"dt": dt, "team": team, "gsis_id": pid, "player_name": name,
            "pos_abb": pos, "pos_rank": rank}


def depth_rows(snapshot=SNAPSHOT):
    rows = []
    for team, players in (
            ("CHI", (("qb1", "Chi QB", "QB", 1), ("rb1", "Chi RB", "RB", 1),
                     ("rb2", "Chi RB Two", "RB", 2),
                     ("wr1", "Chi WR One", "WR", 1),
                     ("wr2", "Chi WR Two", "WR", 2),
                     ("te1", "Chi TE", "TE", 1))),
            ("GB", (("gqb", "Gb QB", "QB", 1), ("grb", "Gb RB", "RB", 1),
                    ("gwr1", "Gb WR One", "WR", 1)))):
        for pid, name, pos, rank in players:
            rows.append(_depth(snapshot, team, pid, name, pos, rank))
    return rows


def inactive_rows(inactive_ids=("rb2",), published="2026-10-04T15:30:00Z"):
    team_of = {"rb2": "CHI", "wr1": "CHI", "wr2": "CHI", "qb1": "CHI",
               "gwr1": "GB"}
    return [
        {"game_id": GAME_ID, "team": team_of[pid], "gsis_id": pid,
         "status": "INACTIVE", "published_at": published}
        for pid in inactive_ids]


def _complete_ids(team, named):
    ids = list(named)
    i = 1
    while len(ids) < 7:
        filler = f"{team.lower()}-inactive-{i}"
        if filler not in ids:
            ids.append(filler)
        i += 1
    return ids


def _proven(snapshot, *, attach_token=True):
    """Add the #2274 completeness proof: the official game-day roster
    partition (inactives + actives == roster) and, for in-memory
    fixtures, the archive provenance token the pinned loader attaches."""
    from sportsedge.nfl_participation_archive import (
        ArchiveProvenance, PROVENANCE_KEY)
    team = snapshot["team"]
    inactive = list(snapshot["player_ids"])
    team_ids = []
    for row in depth_rows():
        if str(row.get("club_code") or row.get("team")) == team:
            pid = row.get("gsis_id") or row.get("player_id")
            if pid and pid not in team_ids:
                team_ids.append(pid)
    active = [p for p in team_ids if p not in inactive]
    snapshot["active_player_ids"] = active
    snapshot["gameday_roster_player_ids"] = inactive + active
    if attach_token:
        snapshot[PROVENANCE_KEY] = ArchiveProvenance("0" * 64, "1" * 64)
    return snapshot


def inactive_snapshots(chi_ids=("rb2",), gb_ids=(),
                       published="2026-10-04T15:30:00Z", attach_token=True):
    """Source-complete official inactive snapshots (audit B1 form)."""
    out = [{"game_id": GAME_ID, "team": "CHI", "published_at": published,
            "player_ids": _complete_ids("CHI", chi_ids)}]
    out = [_proven(o, attach_token=attach_token) for o in out]
    if gb_ids:
        out.append({"game_id": GAME_ID, "team": "GB",
                    "published_at": published,
                    "player_ids": _complete_ids("GB", gb_ids)})
        out[-1] = _proven(out[-1], attach_token=attach_token)
    return out


def injury_row(player_id, status, *, team="CHI",
               modified="2026-10-01T17:00:00Z"):
    return {"season": 2026, "week": 4, "team": team, "gsis_id": player_id,
            "report_status": status, "date_modified": modified}


def assess(pid, **overrides):
    kwargs = dict(
        team="CHI", player_id=pid, depth_rows=depth_rows(),
        inactive_snapshots=inactive_snapshots(), game_id=GAME_ID,
        target_season=2026, target_week=4, kickoff=KICKOFF, as_of=GAMEDAY)
    kwargs.update(overrides)
    return assess_skill_participation(**kwargs)


# ------------------------------------------- skill verdict state machine

def test_skill_rb1_confirmed_starter_when_gameday_active():
    verdict = assess("rb1")
    assert verdict["state"] == "CONFIRMED_STARTER"
    assert verdict["subclass"] == "GAMEDAY_ACTIVE_STARTER"
    assert verdict["chart_position"] == "RB" and verdict["chart_rank"] == 1
    assert require_confirmed_skill_role(verdict)["player_id"] == "rb1"


def test_skill_rotation_player_confirmed_active_when_dressed():
    verdict = assess("wr2")
    assert verdict["state"] == "CONFIRMED_ACTIVE"
    assert verdict["subclass"] == "GAMEDAY_ACTIVE_ROTATION"
    assert verdict["chart_rank"] == 2
    # The confirmed tier includes dressed rotation players: game-day
    # actives are published and he is not on them.
    assert require_confirmed_skill_role(verdict)["state"] == "CONFIRMED_ACTIVE"


def test_skill_te1_confirmed_starter():
    verdict = assess("te1", position="TE")
    assert verdict["state"] == "CONFIRMED_STARTER"
    assert verdict["position"] == "TE"


def test_skill_projected_tiers_refuse_by_name_before_inactives():
    starter = assess("wr1", as_of=PRE_INACTIVES, inactive_snapshots=())
    assert starter["state"] == "PROJECTED_STARTER"
    assert starter["subclass"] == "DEPTH_STARTER_NO_ADVERSE_DESIGNATION"
    with pytest.raises(NFLParticipationError,
                       match="NFL_SKILL_ROLE_NOT_CONFIRMED:PROJECTED_STARTER"):
        require_confirmed_skill_role(starter)

    rotation = assess("wr2", as_of=PRE_INACTIVES, inactive_snapshots=())
    assert rotation["state"] == "PROJECTED_ROTATION"
    assert rotation["subclass"] == "DEPTH_ROTATION_NO_ADVERSE_DESIGNATION"
    with pytest.raises(NFLParticipationError,
                       match="NFL_SKILL_ROLE_NOT_CONFIRMED:PROJECTED_ROTATION"):
        require_confirmed_skill_role(rotation)


def test_skill_officially_inactive_refuses_out():
    verdict = assess("rb2")
    assert verdict["state"] == "OUT"
    assert verdict["subclass"] == "OFFICIAL_INACTIVE"
    with pytest.raises(NFLParticipationError,
                       match="NFL_SKILL_ROLE_OUT:OFFICIAL_INACTIVE"):
        require_confirmed_skill_role(verdict)


def test_skill_injury_out_refuses_out():
    verdict = assess("wr1", as_of=PRE_INACTIVES, inactive_snapshots=(),
                     injury_rows=[injury_row("wr1", "Out")])
    assert verdict["state"] == "OUT"
    with pytest.raises(NFLParticipationError,
                       match="NFL_SKILL_ROLE_OUT:INJURY_REPORT_OUT"):
        require_confirmed_skill_role(verdict)


def test_skill_questionable_refuses_by_name():
    verdict = assess("wr1", as_of=PRE_INACTIVES, inactive_snapshots=(),
                     injury_rows=[injury_row("wr1", "Questionable")])
    assert verdict["state"] == "QUESTIONABLE"
    with pytest.raises(
            NFLParticipationError,
            match="NFL_SKILL_ROLE_NOT_CONFIRMED:QUESTIONABLE:INJURY_QUESTIONABLE"):
        require_confirmed_skill_role(verdict)


def test_skill_gameday_active_supersedes_earlier_questionable():
    verdict = assess("wr1", injury_rows=[injury_row("wr1", "Questionable")])
    assert verdict["state"] == "CONFIRMED_STARTER"
    assert verdict["injury_status"] == "QUESTIONABLE"


def test_skill_team_switch_detected_by_name():
    rows = [r for r in depth_rows() if r["gsis_id"] != "wr1"]
    rows.append(_depth(SNAPSHOT, "GB", "wr1", "Chi WR One", "WR", 1))
    verdict = assess("wr1", depth_rows=rows)
    assert verdict["state"] == "UNKNOWN"
    assert verdict["subclass"] == "PLAYER_ON_OTHER_TEAM_CHART"
    assert verdict["other_team"] == "GB"
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_TEAM_MISMATCH:wr1:GB"):
        require_confirmed_skill_role(verdict)


def test_skill_stale_depth_refuses():
    verdict = assess("wr1", depth_rows=depth_rows(
        snapshot="2026-09-20T12:00:00Z"))
    assert verdict["state"] == "UNKNOWN"
    assert verdict["subclass"] == "DEPTH_SNAPSHOT_STALE"
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_EVIDENCE_STALE"):
        require_confirmed_skill_role(verdict)


def test_skill_missing_snapshot_and_absent_player_refuse():
    rows = [r for r in depth_rows() if r["team"] != "CHI"]
    verdict = assess("wr1", depth_rows=rows)
    assert verdict["subclass"] == "DEPTH_SNAPSHOT_MISSING"
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_DEPTH_SNAPSHOT_MISSING"):
        require_confirmed_skill_role(verdict)

    ghost = assess("ghost")
    assert ghost["subclass"] == "PLAYER_NOT_ON_DEPTH_CHART"
    with pytest.raises(
            NFLParticipationError,
            match="NFL_PARTICIPATION_PLAYER_NOT_ON_DEPTH_CHART:ghost"):
        require_confirmed_skill_role(ghost)


def test_skill_assessment_shares_and_route_unknown_propagates():
    bundle = skill_role_assessment(
        team="CHI", player_id="wr1", depth_rows=depth_rows(),
        player_stat_rows=player_rows(),
        inactive_snapshots=inactive_snapshots(),
        game_id=GAME_ID, target_season=2026, target_week=4,
        kickoff=KICKOFF, as_of=GAMEDAY, position="WR")
    assert bundle["verdict"]["state"] == "CONFIRMED_STARTER"
    shares = bundle["opportunity_shares"]
    # wr1 targets 27 of team 72 across the strictly-prior window.
    assert shares["target_share"]["status"] == "MEASURED_PRIOR"
    assert shares["target_share"]["value"] == pytest.approx(27 / 72)
    assert shares["carry_share"]["status"] == "MEASURED_PRIOR"
    assert shares["snap_share"]["status"] == "UNKNOWN"
    # Route share has no consumed source: UNKNOWN propagates verbatim.
    assert shares["route_share"]["status"] == "UNKNOWN"
    assert shares["route_share"]["reason"] == "NO_ROUTE_SOURCE_CONSUMED"
    assert shares["route_share"]["value"] is None

    snap_rows = [
        {"player_id": "rb1", "season": 2026, "week": w, "offense_pct": 0.62}
        for w in (1, 2, 3)]
    rb_bundle = skill_role_assessment(
        team="CHI", player_id="rb1", depth_rows=depth_rows(),
        player_stat_rows=player_rows(),
        inactive_snapshots=inactive_snapshots(),
        snap_rows=snap_rows, game_id=GAME_ID, target_season=2026,
        target_week=4, kickoff=KICKOFF, as_of=GAMEDAY, position="RB")
    rb_shares = rb_bundle["opportunity_shares"]
    assert rb_shares["carry_share"]["value"] == pytest.approx(45 / 75)
    assert rb_shares["snap_share"]["status"] == "MEASURED_PRIOR"
    assert rb_shares["snap_share"]["value"] == pytest.approx(0.62)
    assert rb_shares["route_share"]["status"] == "UNKNOWN"


def test_qb_require_gate_matches_bridge_rule():
    verdict = assess_qb_participation(
        team="CHI", depth_rows=depth_rows(),
        inactive_snapshots=inactive_snapshots(),
        game_id=GAME_ID, target_season=2026, target_week=4,
        kickoff=KICKOFF, as_of=GAMEDAY, expected_player_id="qb1")
    assert require_confirmed_qb_role(
        verdict, depth_rows=depth_rows(), as_of=GAMEDAY)["state"] \
        == "CONFIRMED_STARTER"
    projected = assess_qb_participation(
        team="CHI", depth_rows=depth_rows(), inactive_snapshots=(),
        game_id=GAME_ID, target_season=2026, target_week=4,
        kickoff=KICKOFF, as_of=PRE_INACTIVES, expected_player_id="qb1")
    with pytest.raises(NFLParticipationError,
                       match="NFL_QB_ROLE_NOT_CONFIRMED:PROJECTED_STARTER"):
        require_confirmed_qb_role(
            projected, depth_rows=depth_rows(), as_of=PRE_INACTIVES)


# ------------------------------------------------------- phone ESPN fake

_GAME_DATES = ["2026-09-06", "2026-09-10", "2026-09-14", "2026-09-20",
               "2026-09-24", "2026-09-27", "2026-10-01"]


def _gamelog(names, games):
    """Fabricated ESPN gamelog in the recorded fixture's shape."""
    events, cat_events = {}, []
    for i, (day, stats) in enumerate(games):
        eid = f"4019001{i:02d}"
        events[eid] = {"id": eid,
                       "gameDate": f"{day}T17:00:00.000+00:00",
                       "gameResult": "W"}
        cat_events.append({"eventId": eid,
                           "stats": [str(s) for s in stats]})
    return {"names": names, "events": events,
            "seasonTypes": [{"displayName": "2026 Regular Season",
                             "categories": [{"events": cat_events}]}]}


_QB_NAMES = ["completions", "passingAttempts", "passingYards",
             "passingTouchdowns", "interceptions", "rushingAttempts",
             "rushingYards"]
_QB_YARDS = [275, 310, 265, 330, 290, 305, 280]
_QB_GAMELOG = _gamelog(_QB_NAMES, [
    (d, [20, 30, y, 2, 1, 4, 20]) for d, y in zip(_GAME_DATES, _QB_YARDS)])

_WR_NAMES = ["receptions", "receivingYards", "rushingAttempts",
             "rushingYards"]
_WR_YARDS = [88, 92, 74, 105, 61, 97, 83]
_WR_GAMELOG = _gamelog(_WR_NAMES, [
    (d, [6, y, 0, 0]) for d, y in zip(_GAME_DATES, _WR_YARDS)])

_GAMELOGS = {"900101": _QB_GAMELOG, "900102": _WR_GAMELOG}
_ROSTERS = {
    "3": {"team": {"id": "3"}, "athletes": [{"items": [
        {"id": "900101", "displayName": "Chi QB"},
        {"id": "900102", "displayName": "Chi WR One"}]}]},
    "9": {"team": {"id": "9"}, "athletes": [{"items": [
        {"id": "900201", "displayName": "Gb QB"}]}]},
}
_SCOREBOARD = {"events": [{
    "id": "401900001", "date": KICKOFF,
    "competitions": [{"competitors": [
        {"homeAway": "home",
         "team": {"id": "3", "displayName": "Chicago Bears"}},
        {"homeAway": "away",
         "team": {"id": "9", "displayName": "Green Bay Packers"}},
    ]}]}]}


def _getter(url):
    path = urlparse(url).path
    if path.endswith("/scoreboard"):
        return json.loads(json.dumps(_SCOREBOARD))
    if "/teams/" in path and path.endswith("/roster"):
        return json.loads(json.dumps(
            _ROSTERS[path.split("/teams/")[1].split("/")[0]]))
    if path.endswith("/gamelog"):
        return json.loads(json.dumps(_GAMELOGS[path.split("/")[-2]]))
    if path.endswith("/search/v2"):
        return {"results": []}
    raise AssertionError("Unexpected ESPN URL: " + url)


def _phone_pair(player, market, line, *, captured="2026-10-04T15:59:00Z"):
    base = {"sport": "NFL", "market": market, "player_name": player,
            "away": "Green Bay Packers", "home": "Chicago Bears",
            "kickoff": KICKOFF, "line": line, "odds": -110,
            "book": "draftkings", "quote_captured_at": captured}
    return [dict(base, side="OVER"), dict(base, side="UNDER")]


def _bundle(*, depth=None, inactives=None, snapshots=None, bindings=None):
    return {
        "schema": "SPORTSEDGE_NFL_PARTICIPATION_BUNDLE_V1",
        "depth_rows": depth if depth is not None else depth_rows(),
        "injury_rows": [],
        "inactive_rows": [] if inactives is None else inactives,
        "inactive_snapshots":
            inactive_snapshots(attach_token=False) if snapshots is None
            else snapshots,
        "games": [{"away": "Green Bay Packers", "home": "Chicago Bears",
                   "kickoff": KICKOFF, "game_id": GAME_ID,
                   "season": 2026, "week": 4,
                   "away_code": "GB", "home_code": "CHI"}],
        "player_bindings_version": "ESPN_GSIS_CROSSWALK_V1",
        "player_bindings": bindings if bindings is not None else [
            {"player_name": "Chi QB", "team": "CHI",
             "espn_player_id": "900101", "gsis_id": "qb1",
             "position": "QB"},
            {"player_name": "Chi WR One", "team": "CHI",
             "espn_player_id": "900102", "gsis_id": "wr1",
             "position": "WR"}],
    }


def _write_archive(tmp_path, bundle, *, recorded="2026-10-01T00:00:00Z"):
    """Write a manifest + content-addressed bundle; return loader kwargs.

    Test-side mirror of the operator archive layout: the bundle object
    is named by its own SHA-256 and the manifest -- the file the
    external pin covers -- names that digest.
    """
    import hashlib
    raw = json.dumps(bundle, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / f"{digest}.json").write_bytes(raw)
    manifest = {"schema": "SPORTSEDGE_NFL_PARTICIPATION_MANIFEST_V1",
                "entries": [{"bundle_sha256": digest,
                             "recorded_at_utc": recorded}]}
    mraw = json.dumps(manifest, sort_keys=True).encode()
    (tmp_path / "manifest.json").write_bytes(mraw)
    return {"participation_archive_root": str(tmp_path),
            "participation_manifest_sha256":
                hashlib.sha256(mraw).hexdigest()}


def _over(rows):
    return next(r for r in rows if r["selection"] == "OVER")


# ------------------------------------------------------------- phone lift

def test_phone_stamp_and_demotion_without_participation_bundle():
    rows, receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter)
    over = _over(rows)
    assert over["participation_status"] == \
        "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert over["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
    assert over["research_only"] is True
    assert receipts[0]["participation"] == "NOT_VERIFIED"


def test_phone_stamp_lifts_on_confirmed_skill_verdict(tmp_path):
    rows, receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter, **_write_archive(tmp_path, _bundle()))
    over = _over(rows)
    assert over["participation_status"] == "CONFIRMED_STARTER"
    assert over["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
    assert over["research_only"] is True
    assert over["official_authority"] is False
    assert over["participation_provenance"] == "VERIFIED_ANCHORED"
    assert "participation_refusal" not in over
    verdict = over["participation_verdict"]
    assert verdict["subclass"] == "GAMEDAY_ACTIVE_STARTER"
    assert verdict["candidate_id"] == "wr1"
    assert receipts[0]["participation"] == "CONFIRMED_STARTER"
    assert receipts[0]["participation_player_id"] == "wr1"
    assert receipts[0]["participation_provenance"] == "VERIFIED_ANCHORED"


def test_phone_stamp_lifts_on_confirmed_qb_verdict(tmp_path):
    rows, receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter, **_write_archive(tmp_path, _bundle()))
    over = _over(rows)
    assert over["participation_status"] == "CONFIRMED_STARTER"
    assert over["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
    assert over["participation_verdict"]["subclass"] == "GAMEDAY_ACTIVE"
    assert receipts[0]["participation"] == "CONFIRMED_STARTER"


def test_phone_inline_bundle_never_lifts(tmp_path):
    # The same perfectly-formed bundle, carried inline in the payload:
    # untrusted by construction (audit B2).  No lift, UNVERIFIED_BUNDLE
    # recorded on the row and in the receipt.
    rows, receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter, participation=_bundle())
    over = _over(rows)
    assert over["participation_status"] == \
        "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert over["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
    assert over["participation_provenance"] == "UNVERIFIED_BUNDLE"
    assert over["participation_refusal"] == \
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:NO_EXTERNAL_ANCHOR"
    assert "participation_verdict" not in over
    assert receipts[0]["participation"] == "UNVERIFIED_BUNDLE"
    assert receipts[0]["participation_provenance"] == "UNVERIFIED_BUNDLE"
    assert receipts[0]["participation_refusal"].startswith(
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED")


def test_phone_stamp_persists_on_projected_only_verdict(tmp_path):
    captured = "2026-10-02T17:59:00Z"
    rows, receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5,
                    captured=captured),
        now=datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc),
        getter=_getter,
        **_write_archive(tmp_path, _bundle(snapshots=[])))
    over = _over(rows)
    assert over["participation_status"] == \
        "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert over["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
    assert over["participation_refusal"].startswith(
        "NFL_SKILL_ROLE_NOT_CONFIRMED:PROJECTED_STARTER")
    assert receipts[0]["participation"] == "PROJECTED_STARTER"
    assert receipts[0]["participation_refusal"].startswith(
        "NFL_SKILL_ROLE_NOT_CONFIRMED")


def test_phone_stamp_persists_and_names_team_switch(tmp_path):
    rows = [r for r in depth_rows() if r["gsis_id"] != "wr1"]
    rows.append(_depth(SNAPSHOT, "GB", "wr1", "Chi WR One", "WR", 1))
    out, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter,
        **_write_archive(tmp_path, _bundle(depth=rows)))
    over = _over(out)
    assert over["participation_status"] == \
        "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert over["participation_refusal"] == \
        "NFL_PARTICIPATION_TEAM_MISMATCH:wr1:GB"
    assert over["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"


def test_phone_stamp_persists_on_stale_participation_evidence(tmp_path):
    out, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter,
        **_write_archive(tmp_path, _bundle(depth=depth_rows(
            snapshot="2026-09-20T12:00:00Z"))))
    over = _over(out)
    assert over["participation_status"] == \
        "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert over["participation_refusal"] == \
        "NFL_PARTICIPATION_EVIDENCE_STALE"


def test_phone_stamp_persists_without_player_binding(tmp_path):
    out, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc),
        getter=_getter,
        **_write_archive(tmp_path, _bundle(bindings=[])))
    over = _over(out)
    assert over["participation_status"] == \
        "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert over["participation_refusal"] == \
        "PARTICIPATION_PLAYER_BINDING_MISSING"


@pytest.mark.registry_lane_internals
def test_run_full_forwards_participation_bundle_to_phone_pricer():
    line = {"sport": "NFL", "away": "Buffalo Bills",
            "home": "Los Angeles Rams", "kickoff": "2026-10-12T00:00:00Z",
            "market": "RECEIVING_YARDS", "side": "OVER",
            "player_name": "Example Receiver", "line": 50.5, "odds": -110,
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:29:00Z"}
    bundle = {"depth_rows": [], "games": []}
    fake = ([{"status": "NO_MODEL_OR_MARKET", "reason": "TEST_BUNDLE",
              "market": "PLAYER_RECEIVING_YARDS", "sport": "NFL"}], [])
    with patch.object(runner, "phone_nfl_player_rows",
                      return_value=fake) as phone:
        runner.run_full({"sport": "NFL", "lines": [line],
                         "nfl_participation": bundle},
                        now=datetime(2026, 10, 11, 20, 30,
                                     tzinfo=timezone.utc),
                        auto_context=False)
    assert phone.call_args.kwargs["participation"] == bundle
    # The payload can never supply the trust channel: with no runner
    # configuration, both provenance kwargs forward as None and the
    # inline bundle stays UNVERIFIED_BUNDLE downstream.
    assert phone.call_args.kwargs["participation_archive_root"] is None
    assert phone.call_args.kwargs["participation_manifest_sha256"] is None
    with patch.object(runner, "phone_nfl_player_rows",
                      return_value=fake) as phone:
        runner.run_full({"sport": "NFL", "lines": [line],
                         "nfl_participation": bundle},
                        now=datetime(2026, 10, 11, 20, 30,
                                     tzinfo=timezone.utc),
                        auto_context=False,
                        nfl_participation_archive_root="/srv/archive",
                        nfl_participation_manifest_sha256="a" * 64)
    assert phone.call_args.kwargs["participation_archive_root"] == \
        "/srv/archive"
    assert phone.call_args.kwargs["participation_manifest_sha256"] == \
        "a" * 64
