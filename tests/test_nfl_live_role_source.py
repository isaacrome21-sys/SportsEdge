from __future__ import annotations

from hashlib import sha256
import io

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.live_role_source import (
    PLAYER_STATS_URL,
    build_live_team_model,
    fetch_nflverse_player_stats,
)


def _stat(
    player_id,
    name,
    position,
    week,
    *,
    team="CHI",
    attempts=0,
    completions=0,
    passing_yards=0,
    passing_tds=0,
    interceptions=0,
    carries=0,
    rushing_yards=0,
    rushing_tds=0,
    targets=0,
    receptions=0,
    receiving_yards=0,
    receiving_tds=0,
):
    return {
        "player_id": player_id,
        "player_name": name,
        "position": position,
        "recent_team": team,
        "season": 2026,
        "week": week,
        "season_type": "REG",
        "attempts": attempts,
        "completions": completions,
        "passing_yards": passing_yards,
        "passing_tds": passing_tds,
        "interceptions": interceptions,
        "carries": carries,
        "rushing_yards": rushing_yards,
        "rushing_tds": rushing_tds,
        "targets": targets,
        "receptions": receptions,
        "receiving_yards": receiving_yards,
        "receiving_tds": receiving_tds,
    }


def player_rows():
    rows = []
    for week, attempts, completions, yards, pass_tds, ints in (
        (1, 30, 20, 220, 2, 1),
        (2, 36, 25, 285, 2, 0),
        (3, 40, 28, 320, 1, 1),
    ):
        rows.append(
            _stat(
                "qb1", "Current QB", "QB", week,
                attempts=attempts, completions=completions,
                passing_yards=yards, passing_tds=pass_tds,
                interceptions=ints, carries=4 + week,
                rushing_yards=18 + 4 * week,
                rushing_tds=1 if week == 2 else 0,
            )
        )
        rows.append(
            _stat(
                "rb1", "RB One", "RB", week,
                carries=14 + week, rushing_yards=60 + 5 * week,
                rushing_tds=1 if week in {1, 3} else 0,
                targets=4 + week, receptions=3 + week,
                receiving_yards=25 + 4 * week,
            )
        )
        rows.append(
            _stat(
                "wr1", "WR One", "WR", week,
                carries=1, rushing_yards=4,
                targets=8 + week, receptions=5 + week,
                receiving_yards=70 + 6 * week,
                receiving_tds=1 if week in {1, 3} else 0,
            )
        )
        rows.append(
            _stat(
                "wr2", "WR Two", "WR", week,
                targets=6, receptions=4, receiving_yards=52,
                receiving_tds=1 if week == 2 else 0,
            )
        )
        # Two off-depth players form residual OTHER.  Combined each week they
        # own exactly five carries and five targets; OTHER must keep that team
        # total rather than average the two player rows down to 2.5.
        rows.append(
            _stat(
                "x1", "Extra One", "WR", week,
                carries=2, rushing_yards=8,
                targets=3, receptions=2, receiving_yards=18,
                receiving_tds=1 if week == 2 else 0,
            )
        )
        rows.append(
            _stat(
                "x2", "Extra Two", "RB", week,
                carries=3, rushing_yards=12,
                targets=2, receptions=1, receiving_yards=9,
                rushing_tds=1 if week == 3 else 0,
            )
        )

    # A former starter has data but is not the current PIT depth-chart QB.
    rows.append(
        _stat(
            "oldqb", "Old QB", "QB", 1,
            attempts=50, completions=40, passing_yards=450, passing_tds=5,
        )
    )
    # Target-week hindsight poison: must be excluded entirely.
    rows.append(
        _stat(
            "qb1", "Current QB", "QB", 4,
            attempts=99, completions=99, passing_yards=999, passing_tds=9,
        )
    )
    return rows


def depth_rows():
    return [
        # Older snapshot.
        {
            "dt": "2026-09-28T12:00:00Z", "team": "CHI",
            "gsis_id": "oldqb", "player_name": "Old QB",
            "pos_abb": "QB", "pos_rank": 1,
        },
        # Latest eligible snapshot.
        {
            "dt": "2026-10-01T12:00:00Z", "team": "CHI",
            "gsis_id": "qb1", "player_name": "Current QB",
            "pos_abb": "QB", "pos_rank": 1,
        },
        {
            "dt": "2026-10-01T12:00:00Z", "team": "CHI",
            "gsis_id": "rb1", "player_name": "RB One",
            "pos_abb": "RB", "pos_rank": 1,
        },
        {
            "dt": "2026-10-01T12:00:00Z", "team": "CHI",
            "gsis_id": "wr1", "player_name": "WR One",
            "pos_abb": "WR", "pos_rank": 1,
        },
        {
            "dt": "2026-10-01T12:00:00Z", "team": "CHI",
            "gsis_id": "wr2", "player_name": "WR Two",
            "pos_abb": "WR", "pos_rank": 2,
        },
        # A future depth update must not replace the PIT starter.
        {
            "dt": "2026-10-02T12:00:00Z", "team": "CHI",
            "gsis_id": "futureqb", "player_name": "Future QB",
            "pos_abb": "QB", "pos_rank": 1,
        },
    ]


def build(**overrides):
    kwargs = dict(
        team="CHI",
        target_season=2026,
        target_week=4,
        kickoff="2026-10-04T17:00:00Z",
        observed_at="2026-10-01T18:00:00Z",
        depth_rows=depth_rows(),
        player_rows=player_rows(),
        lookback_games=8,
        decay=0.85,
    )
    kwargs.update(overrides)
    return build_live_team_model(**kwargs)


def test_current_pit_depth_chart_selects_exact_starting_qb_and_excludes_target_week():
    out = build()
    qb = out["qb"]
    assert qb["player"] == "Current QB"
    assert qb["player_id"] == "qb1"
    assert out["source"]["depth_as_of"] == "2026-10-01T12:00:00+00:00"
    assert qb["role_prior"]["pass_attempts"] < 50
    assert qb["role_prior"]["pass_attempts"] != pytest.approx(99.0)
    assert out["authority"]["post_kickoff_role_inference"] is False


def test_residual_other_aggregates_team_week_volume_instead_of_diluting_players():
    out = build(decay=1.0)
    players = {row["player"]: row for row in out["skill_players"]}
    other = players["CHI_OTHER"]
    assert other["player_id"] == "CHI:OTHER"
    assert other["role_prior"]["rush_attempts"] == pytest.approx(5.0)
    assert other["role_prior"]["targets"] == pytest.approx(5.0)
    assert other["pit_sample_games"] == 3


def test_td_shares_use_common_team_week_denominator_and_conserve_mass():
    out = build(decay=1.0)
    qb = out["qb"]
    skills = out["skill_players"]
    recv_mass = sum(float(row["receiving_td_share"]) for row in skills)
    rush_mass = float(qb["rushing_td_share"]) + sum(float(row["rushing_td_share"]) for row in skills)
    assert recv_mass == pytest.approx(1.0)
    assert rush_mass == pytest.approx(1.0)
    # Passing TDs: 5; rushing TDs: QB 1 + RB 2 + OTHER 1 = 4.
    assert out["pass_td_share"] == pytest.approx(5 / 9)
    assert qb["rushing_td_share"] == pytest.approx(1 / 4)


def test_future_depth_snapshot_is_ignored_and_duplicate_current_qb_fails_closed():
    out = build()
    assert out["qb"]["player"] != "Future QB"

    rows = depth_rows()
    rows.append(
        {
            "dt": "2026-10-01T12:00:00Z", "team": "CHI",
            "gsis_id": "oldqb", "player_name": "Old QB",
            "pos_abb": "QB", "pos_rank": 1,
        }
    )
    with pytest.raises(NFLContextError, match="exactly one PIT starting QB required"):
        build(depth_rows=rows)


def test_market_contamination_and_post_kickoff_observation_fail_closed():
    rows = player_rows()
    rows[0] = dict(rows[0], sportsbook_price=-110)
    with pytest.raises(NFLContextError, match="market input forbidden"):
        build(player_rows=rows)

    with pytest.raises(NFLContextError, match="observed before kickoff"):
        build(observed_at="2026-10-04T17:00:00Z")


def test_missing_current_qb_history_fails_instead_of_borrowing_old_starter():
    rows = [row for row in player_rows() if row["player_id"] != "qb1"]
    with pytest.raises(NFLContextError, match="prior player history missing:Current QB"):
        build(player_rows=rows)


class FakeResponse:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


def test_player_stats_fetch_keeps_exact_byte_receipts():
    raw = (
        "player_id,player_name,position,recent_team,season,week,season_type,attempts\n"
        "p1,Player One,QB,CHI,2026,1,REG,30\n"
    ).encode()

    def opener(request, timeout=0):
        assert request.full_url == PLAYER_STATS_URL.format(season=2026)
        assert timeout == 30
        return FakeResponse(raw)

    rows, receipts = fetch_nflverse_player_stats(seasons=[2026], opener=opener)
    assert len(rows) == 1
    assert receipts == [{
        "season": "2026",
        "source_uri": PLAYER_STATS_URL.format(season=2026),
        "raw_sha256": sha256(raw).hexdigest(),
    }]
