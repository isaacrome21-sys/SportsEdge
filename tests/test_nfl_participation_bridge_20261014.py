"""Participation-bridge tests: synthetic fixture universe, labeled as such.

Two fictional teams (CHI priced, GB opponent), 2026 season, target week 4.
All player ids/names are synthetic; rows mirror the nflverse shapes the
repo's live role source consumes.  The fixture demonstrates the evidence
mechanics (depth chart + injuries + official inactives as of a cutoff),
not any real player's status.
"""
from __future__ import annotations

import pytest

from sportsedge.nfl_participation_bridge import (
    NFLParticipationError,
    assess_qb_participation,
    opportunity_shares,
    qb_passing_yards_research,
)

KICKOFF = "2026-10-04T17:00:00Z"
GAME_ID = "synthetic-2026-w4-chi-gb"


def _stat(player_id, name, position, week, *, team, attempts=0, completions=0,
          passing_yards=0, passing_tds=0, interceptions=0, carries=0,
          rushing_yards=0, rushing_tds=0, targets=0, receptions=0,
          receiving_yards=0, receiving_tds=0):
    return {
        "player_id": player_id, "player_name": name, "position": position,
        "recent_team": team, "season": 2026, "week": week,
        "season_type": "REG", "attempts": attempts,
        "completions": completions, "passing_yards": passing_yards,
        "passing_tds": passing_tds, "interceptions": interceptions,
        "carries": carries, "rushing_yards": rushing_yards,
        "rushing_tds": rushing_tds, "targets": targets,
        "receptions": receptions, "receiving_yards": receiving_yards,
        "receiving_tds": receiving_tds,
    }


def player_rows():
    rows = []
    for week, att, comp, yds in ((1, 30, 20, 220), (2, 36, 25, 285),
                                 (3, 40, 28, 320)):
        rows.append(_stat("qb1", "Chi QB", "QB", week, team="CHI",
                          attempts=att, completions=comp, passing_yards=yds,
                          passing_tds=2, interceptions=1, carries=4,
                          rushing_yards=20))
        rows.append(_stat("rb1", "Chi RB", "RB", week, team="CHI",
                          carries=15, rushing_yards=65,
                          rushing_tds=1 if week == 2 else 0, targets=5,
                          receptions=4, receiving_yards=30))
        rows.append(_stat("wr1", "Chi WR One", "WR", week, team="CHI",
                          targets=9, receptions=6, receiving_yards=80,
                          receiving_tds=1 if week != 2 else 0))
        rows.append(_stat("wr2", "Chi WR Two", "WR", week, team="CHI",
                          targets=6, receptions=4, receiving_yards=52))
        rows.append(_stat("gqb", "Gb QB", "QB", week, team="GB",
                          attempts=32, completions=21, passing_yards=240,
                          passing_tds=1, interceptions=1, carries=3,
                          rushing_yards=12))
        rows.append(_stat("grb", "Gb RB", "RB", week, team="GB",
                          carries=16, rushing_yards=70, targets=3,
                          receptions=2, receiving_yards=14))
        rows.append(_stat("gwr1", "Gb WR One", "WR", week, team="GB",
                          targets=8, receptions=5, receiving_yards=66,
                          receiving_tds=1 if week == 3 else 0))
        rows.append(_stat("gwr2", "Gb WR Two", "WR", week, team="GB",
                          targets=5, receptions=3, receiving_yards=40))
    return rows


def _depth(dt, team, pid, name, pos, rank):
    return {"dt": dt, "team": team, "gsis_id": pid, "player_name": name,
            "pos_abb": pos, "pos_rank": rank}


def depth_rows(snapshot="2026-10-01T12:00:00Z"):
    rows = []
    for team, qb, rb, w1, w2 in (
            ("CHI", ("qb1", "Chi QB"), ("rb1", "Chi RB"),
             ("wr1", "Chi WR One"), ("wr2", "Chi WR Two")),
            ("GB", ("gqb", "Gb QB"), ("grb", "Gb RB"),
             ("gwr1", "Gb WR One"), ("gwr2", "Gb WR Two"))):
        rows.append(_depth(snapshot, team, qb[0], qb[1], "QB", 1))
        rows.append(_depth(snapshot, team, rb[0], rb[1], "RB", 1))
        rows.append(_depth(snapshot, team, w1[0], w1[1], "WR", 1))
        rows.append(_depth(snapshot, team, w2[0], w2[1], "WR", 2))
    return rows


def inactive_rows(inactive_ids=("wr2",), published="2026-10-04T15:30:00Z"):
    team_of = {"wr2": "CHI", "gwr2": "GB", "qb1": "CHI", "gqb": "GB"}
    return [
        {"game_id": GAME_ID, "team": team_of[pid], "gsis_id": pid,
         "status": "INACTIVE", "published_at": published}
        for pid in inactive_ids]


def injury_row(player_id, status, *, team="CHI",
               modified="2026-10-01T17:00:00Z"):
    return {"season": 2026, "week": 4, "team": team, "gsis_id": player_id,
            "report_status": status, "date_modified": modified}


def research(**overrides):
    kwargs = dict(
        game_id=GAME_ID, priced_team="CHI", opponent_team="GB",
        target_season=2026, target_week=4, kickoff=KICKOFF,
        as_of="2026-10-04T16:00:00Z", depth_rows=depth_rows(),
        player_stat_rows=player_rows(), inactive_rows=inactive_rows(),
        min_paths=120,
    )
    kwargs.update(overrides)
    return qb_passing_yards_research(**kwargs)


def test_confirmed_qb_produces_research_distribution():
    out = research()
    assert out["status"] == "RESEARCH_ONLY"
    assert out["research_only"] is True
    assert out["validated"] is False
    assert out["participation_status"] == "CONFIRMED_STARTER"
    assert out["player_id"] == "qb1"
    dist = out["passing_yards_distribution"]
    assert dist["paths"] >= 120
    ladder = dist["ladder"]
    assert len(ladder) >= 20
    probs = [r["p_over"] for r in ladder]
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert all(a >= b for a, b in zip(probs, probs[1:]))  # survival monotone
    assert probs[0] > 0.9 and probs[-1] < 0.1
    assert 150.0 < dist["mean_yards_trapezoid_approx"] < 400.0
    assert dist["p10_yards_approx"] < dist["p50_yards_approx"] \
        < dist["p90_yards_approx"]
    verdict = out["participation"]["priced_team"]
    assert verdict["subclass"] == "GAMEDAY_ACTIVE"
    assert verdict["inactives_published"] is True
    assert out["provenance"]["evidence"].startswith("NFLVERSE_")


def test_projected_qb_refuses_by_name_before_inactives():
    with pytest.raises(NFLParticipationError,
                       match="NFL_QB_ROLE_NOT_CONFIRMED:PROJECTED_STARTER"):
        research(as_of="2026-10-02T18:00:00Z", inactive_rows=())


def test_questionable_qb_refuses_by_name():
    with pytest.raises(
            NFLParticipationError,
            match="NFL_QB_ROLE_NOT_CONFIRMED:QUESTIONABLE:INJURY_QUESTIONABLE"):
        research(as_of="2026-10-02T18:00:00Z", inactive_rows=(),
                 injury_rows=[injury_row("qb1", "Questionable")])


def test_officially_inactive_qb_refuses_out():
    with pytest.raises(NFLParticipationError,
                       match="NFL_QB_ROLE_OUT:OFFICIAL_INACTIVE"):
        research(inactive_rows=inactive_rows(inactive_ids=("qb1",)))


def test_injury_out_qb_refuses_out():
    with pytest.raises(NFLParticipationError,
                       match="NFL_QB_ROLE_OUT:INJURY_REPORT_OUT"):
        research(as_of="2026-10-02T18:00:00Z", inactive_rows=(),
                 injury_rows=[injury_row("qb1", "Out")])


def test_stale_depth_evidence_refuses():
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_EVIDENCE_STALE"):
        research(depth_rows=depth_rows(snapshot="2026-09-20T12:00:00Z"))


def test_missing_depth_snapshot_refuses():
    rows = [r for r in depth_rows() if r["team"] != "CHI"]
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_DEPTH_SNAPSHOT_MISSING"):
        research(depth_rows=rows)


def test_team_switch_is_detected_by_identity_binding():
    rows = depth_rows()
    # qb1 was traded: he is now GB's QB1 and a new QB fronts CHI's chart.
    rows = [r for r in rows
            if not (r["gsis_id"] in {"qb1", "gqb"} and r["pos_abb"] == "QB")]
    rows.append(_depth("2026-10-01T12:00:00Z", "CHI", "newqb", "New Chi QB",
                       "QB", 1))
    rows.append(_depth("2026-10-01T12:00:00Z", "GB", "qb1", "Chi QB",
                       "QB", 1))
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_TEAM_MISMATCH:qb1:GB"):
        research(depth_rows=rows, expected_qb_id="qb1")


def test_gameday_active_supersedes_earlier_questionable_designation():
    verdict = assess_qb_participation(
        team="CHI", depth_rows=depth_rows(),
        injury_rows=[injury_row("qb1", "Questionable")],
        inactive_rows=inactive_rows(), game_id=GAME_ID,
        target_season=2026, target_week=4, kickoff=KICKOFF,
        as_of="2026-10-04T16:00:00Z")
    assert verdict["state"] == "CONFIRMED_STARTER"
    assert verdict["subclass"] == "GAMEDAY_ACTIVE"
    assert verdict["injury_status"] == "QUESTIONABLE"


def test_future_evidence_is_invisible_and_counted():
    rows = depth_rows()
    rows.append(_depth("2026-10-03T12:00:00Z", "CHI", "futureqb",
                       "Future QB", "QB", 1))
    verdict = assess_qb_participation(
        team="CHI", depth_rows=rows, inactive_rows=(), game_id=GAME_ID,
        target_season=2026, target_week=4, kickoff=KICKOFF,
        as_of="2026-10-02T18:00:00Z")
    assert verdict["candidate_id"] == "qb1"
    assert verdict["excluded_evidence"] >= 1


def test_opportunity_shares_measured_and_unknowns_named():
    shares = opportunity_shares(
        player_id="wr1", team="CHI", player_stat_rows=player_rows(),
        target_season=2026, target_week=4)
    assert shares["target_share"]["status"] == "MEASURED_PRIOR"
    assert shares["target_share"]["value"] == pytest.approx(27 / 60)
    assert shares["carry_share"]["status"] == "MEASURED_PRIOR"
    assert shares["route_share"]["status"] == "UNKNOWN"
    assert shares["route_share"]["reason"] == "NO_ROUTE_SOURCE_CONSUMED"
    assert shares["snap_share"]["status"] == "UNKNOWN"

    snap_rows = [
        {"player_id": "wr1", "season": 2026, "week": w, "offense_pct": 0.8}
        for w in (1, 2, 3)]
    with_snaps = opportunity_shares(
        player_id="wr1", team="CHI", player_stat_rows=player_rows(),
        target_season=2026, target_week=4, snap_rows=snap_rows)
    assert with_snaps["snap_share"]["status"] == "MEASURED_PRIOR"
    assert with_snaps["snap_share"]["value"] == pytest.approx(0.8)


def test_cutoff_must_be_pregame():
    with pytest.raises(NFLParticipationError,
                       match="NFL_PARTICIPATION_CUTOFF_NOT_PREGAME"):
        research(as_of="2026-10-04T17:00:00Z")
