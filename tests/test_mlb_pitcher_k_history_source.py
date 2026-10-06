from datetime import date

import pytest

from sportsedge.mlb_pitcher_k_workload_source import (
    PitcherKWorkloadSourceError,
    build_from_history_source,
)


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


class StubSource:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def player_rows(self, *, player_id, group, target_date):
        self.calls.append((player_id, group, target_date))
        return list(self.rows)


def test_workload_candidate_reuses_prior_history_rows_without_new_fetch():
    rows = [_row(i) for i in range(12)]
    rows.insert(3, _row(20, started=0))
    source = StubSource(rows)
    got = build_from_history_source(
        source,
        player_id=99,
        target_date=date(2026, 10, 6),
    )
    assert source.calls == [(99, "pitching", date(2026, 10, 6))]
    assert got["start_count"] == 10
    assert got["history"][0]["batters_faced"] == 22
    assert got["history"][-1]["batters_faced"] == 31
    assert got["deployment"] is False
    assert got["model_p_eligible"] is False


def test_workload_candidate_fails_closed_when_required_prior_stat_is_missing():
    rows = [_row(i) for i in range(5)]
    del rows[2]["stat"]["battersFaced"]
    with pytest.raises(PitcherKWorkloadSourceError, match="WORKLOAD_BUNDLE_BLOCKED:.*battersFaced"):
        build_from_history_source(
            StubSource(rows),
            player_id=99,
            target_date=date(2026, 10, 6),
        )


def test_history_source_failure_is_receipted_without_fallback_fetch():
    class Broken:
        def player_rows(self, **_kwargs):
            raise RuntimeError("boom")

    with pytest.raises(PitcherKWorkloadSourceError, match="HISTORY_SOURCE_FAILED:RuntimeError"):
        build_from_history_source(
            Broken(),
            player_id=99,
            target_date=date(2026, 10, 6),
        )
