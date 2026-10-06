from datetime import date
from unittest.mock import Mock

import pytest

from sportsedge import mlb_pitcher_k_historical_assembler as A


def _raw_start(i):
    return {"date": date(2025, 5, i), "stat": {
        "gamesStarted": 1, "battersFaced": 24, "numberOfPitches": 90,
        "strikeOuts": 6, "inningsPitched": "6.0",
    }}


def test_raw_prior_starts_are_strictly_source_filtered_and_last_ten():
    source = Mock()
    rows = [_raw_start(i) for i in range(1, 12)]
    rows.insert(3, {"date": date(2025, 5, 3), "stat": {"gamesStarted": 0}})
    source.player_rows.return_value = rows
    got = A._raw_prior_starts(source, pitcher_id=7, target_date=date(2025, 6, 1))
    assert len(got) == 10
    assert all(float(x["stat"]["gamesStarted"]) >= 1 for x in got)
    source.player_rows.assert_called_once_with(player_id=7, group="pitching", target_date=date(2025, 6, 1))


def test_assembler_fails_closed_when_workload_and_incumbent_starts_do_not_align(monkeypatch):
    source = Mock()
    source.player_rows.return_value = [_raw_start(i) for i in range(1, 7)]
    source._pitcher_start_rows_pk.return_value = [
        ({"strikeouts": 6, "outs": 18, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1},
         date(2025, 5, i), 2, 100 + i)
        for i in range(1, 6)
    ]
    with pytest.raises(A.PitcherKHistoricalAssemblerError, match="alignment mismatch"):
        A.assemble_historical_pitcher_k_row(
            source=source, season=2025, target_date=date(2025, 6, 1),
            game_id=200, pitcher_id=7, pitcher_team_id=1,
            away_team_id=1, home_team_id=2,
            realized_strikeouts=8, realized_batters_faced=25,
        )
    source._opp_k_payload.assert_not_called()


def test_assembler_rejects_nonfrozen_season_before_fetch():
    source = Mock()
    with pytest.raises(A.PitcherKHistoricalAssemblerError, match="frozen split"):
        A.assemble_historical_pitcher_k_row(
            source=source, season=2026, target_date=date(2026, 6, 1),
            game_id=200, pitcher_id=7, pitcher_team_id=1,
            away_team_id=1, home_team_id=2,
            realized_strikeouts=8, realized_batters_faced=25,
        )
    source.player_rows.assert_not_called()
