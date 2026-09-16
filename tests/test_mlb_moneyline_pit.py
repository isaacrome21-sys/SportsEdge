from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_moneyline_pit import MLBMoneylinePITError, build_moneyline_feature


def _rows(start):
    rows = []
    for team_id, base in ((10, 3.0), (20, 4.0)):
        for i in range(12):
            rows.append({
                "team_id": team_id,
                "runs": base + (i % 3),
                "feature_asof_ts": (start - timedelta(days=20-i)).isoformat(),
                "source_game_pk": f"{team_id}-{i}",
            })
    return rows


def test_moneyline_pit_feature_is_market_blind_and_strictly_prior():
    start = datetime(2026, 9, 15, 23, 40, tzinfo=timezone.utc)
    out = build_moneyline_feature(
        game_pk=999, away_team_id=10, home_team_id=20,
        event_start_ts=start, observations=_rows(start), window=10, minimum=10,
    )
    assert out["market"] == "MONEYLINE"
    assert out["market_blind"] is True
    assert datetime.fromisoformat(out["feature_asof_ts"]) < start
    assert out["observation_count"] == 20
    assert "odds" in out["forbidden_market_inputs"]


def test_moneyline_pit_leakage_fails_closed():
    start = datetime(2026, 9, 15, 23, 40, tzinfo=timezone.utc)
    rows = _rows(start)
    rows.append({"team_id": 10, "runs": 99, "feature_asof_ts": start.isoformat(), "source_game_pk": "leak"})
    with pytest.raises(MLBMoneylinePITError, match="PIT_LEAKAGE"):
        build_moneyline_feature(
            game_pk=999, away_team_id=10, home_team_id=20,
            event_start_ts=start, observations=rows, window=10, minimum=10,
        )


def test_moneyline_pit_missing_timestamp_fails_closed():
    start = datetime(2026, 9, 15, 23, 40, tzinfo=timezone.utc)
    rows = _rows(start)
    rows[0] = {"team_id": 10, "runs": 3, "source_game_pk": "missing-ts"}
    with pytest.raises(MLBMoneylinePITError, match="feature_asof_ts"):
        build_moneyline_feature(
            game_pk=999, away_team_id=10, home_team_id=20,
            event_start_ts=start, observations=rows, window=10, minimum=10,
        )
