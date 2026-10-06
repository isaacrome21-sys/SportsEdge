from datetime import date

import pytest

from sportsedge.mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource


def _row(i, *, started=1, bf=None):
    return {
        "date": date(2026, 9, i + 1),
        "stat": {
            "gamesStarted": started,
            "battersFaced": 20 + i if bf is None else bf,
            "numberOfPitches": 80 + i,
            "strikeOuts": 4 + (i % 5),
            "inningsPitched": "6.0",
        },
    }


class StubSource(MLBGenericHistorySource):
    def __init__(self, rows):
        super().__init__(opener=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")))
        self.rows = rows

    def player_rows(self, *, player_id, group, target_date):
        assert player_id == 99
        assert group == "pitching"
        assert target_date == date(2026, 10, 6)
        return list(self.rows)


def test_workload_candidate_reuses_prior_history_rows_without_new_fetch():
    rows = [_row(i) for i in range(12)]
    rows.insert(3, _row(20, started=0))
    got = StubSource(rows).pitcher_k_workload_candidate(
        player_id=99,
        target_date=date(2026, 10, 6),
    )
    assert got["start_count"] == 10
    assert got["history"][0]["batters_faced"] == 22
    assert got["history"][-1]["batters_faced"] == 31
    assert got["deployment"] is False
    assert got["model_p_eligible"] is False


def test_workload_candidate_fails_closed_when_required_prior_stat_is_missing():
    rows = [_row(i) for i in range(5)]
    rows[2] = _row(2, bf=None)
    del rows[2]["stat"]["battersFaced"]
    with pytest.raises(MLBGenericFeatureError, match="pitcher_k_workload_candidate:.*battersFaced"):
        StubSource(rows).pitcher_k_workload_candidate(
            player_id=99,
            target_date=date(2026, 10, 6),
        )
