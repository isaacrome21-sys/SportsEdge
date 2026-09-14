from __future__ import annotations

from datetime import date, datetime, timezone

from sportsedge.dfs.mlb_starter_features import build_starter_path_features


class _Source:
    retrieved_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

    def player_rows(self, *, player_id: int, group: str, target_date: date):
        assert player_id == 99
        assert group == "pitching"
        rows = []
        for day in range(1, 7):
            stat = {
                "gamesStarted": 1,
                "inningsPitched": "6.0",
                "battersFaced": 24,
                "numberOfPitches": 92,
                "hitByPitch": 1,
                "strikeOuts": 7,
                "earnedRuns": 2,
                "runs": 2,
                "hits": 5,
                "baseOnBalls": 2,
                "completeGames": 0,
                "shutouts": 0,
            }
            if day == 1:
                stat.pop("numberOfPitches")
            rows.append({"date": date(2026, 8, day), "stat": stat})
        return rows


class _F5Source:
    retrieved_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

    def win_credit_rows(self, *, team_id: int, target_date: date):
        assert team_id == 112
        return tuple(
            {
                "game_pk": 1000 + index,
                "date": f"2026-08-{index + 1:02d}",
                "f5_state": "LEAD" if index % 2 == 0 else "TIE",
                "team_won": index % 3 != 0,
                "win_credit_required_outs": 15 if index % 3 != 0 else None,
            }
            for index in range(12)
        )


def test_feature_builder_keeps_actual_workload_and_skips_incomplete_rows() -> None:
    result = build_starter_path_features(
        _Source(),
        f5_source=_F5Source(),
        pitcher_id=99,
        team_id=112,
        target_date=date(2026, 9, 14),
    )
    assert result["usable_starts"] == 5
    assert result["incomplete_starts_skipped"] == 1
    row = result["starter_history"][0]
    assert row["starter_exit_batters_faced"] == 24
    assert row["starter_exit_pitch_count"] == 92
    assert row["hbp_allowed"] == 1
    assert row["runs_allowed"] == 2
    assert len(result["credit_history"]) == 12
    assert len(result["feature_source_hash"]) == 64


def test_feature_builder_is_deterministic_for_same_pit_inputs() -> None:
    kwargs = {
        "f5_source": _F5Source(),
        "pitcher_id": 99,
        "team_id": 112,
        "target_date": date(2026, 9, 14),
    }
    first = build_starter_path_features(_Source(), **kwargs)
    second = build_starter_path_features(_Source(), **kwargs)
    assert first == second
