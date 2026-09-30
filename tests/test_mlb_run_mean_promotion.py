import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from sportsedge.mlb_all_market_features import (
    MLBAllMarketHistorySource,
    PRODUCTION_RUN_MEAN_VERSION,
)
from sportsedge.mlb_generic_features import MLBGenericFeatureError


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


def _schedule(team_id: int, target: date, *, games: int = 10):
    if team_id == 1:
        runs_for, runs_against = 6, 4
    elif team_id == 2:
        runs_for, runs_against = 3, 5
    else:
        raise AssertionError(team_id)

    rows = []
    for idx in range(games):
        day = date(target.year, 9, idx + 1)
        if team_id == 1:
            away_id, home_id = 1, 99
            away_score, home_score = runs_for, runs_against
        else:
            away_id, home_id = 98, 2
            away_score, home_score = runs_against, runs_for
        rows.append({
            "date": day.isoformat(),
            "games": [{
                "officialDate": day.isoformat(),
                "status": {"abstractGameState": "Final"},
                "teams": {
                    "away": {"team": {"id": away_id}, "score": away_score},
                    "home": {"team": {"id": home_id}, "score": home_score},
                },
            }],
        })

    rows.append({
        "date": target.isoformat(),
        "games": [{
            "officialDate": target.isoformat(),
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": team_id}, "score": 99},
                "home": {"team": {"id": 77}, "score": 0},
            },
        }],
    })
    return {"dates": rows}


def _opener(req, timeout=15):
    url = getattr(req, "full_url", str(req))
    parsed = urlparse(url)
    if parsed.path != "/api/v1/schedule":
        raise AssertionError(url)
    team_id = int(parse_qs(parsed.query)["teamId"][0])
    return _Response(_schedule(team_id, date(2026, 9, 29)))


def test_promoted_defense_blend_matches_1183_formula_and_ignores_same_day():
    source = MLBAllMarketHistorySource(
        opener=_opener,
        retrieved_at=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
    )
    away, home, components = source.defense_blended_team_means(
        away_team_id=1,
        home_team_id=2,
        target_date=date(2026, 9, 29),
    )
    assert away == pytest.approx(5.5)
    assert home == pytest.approx(3.5)
    assert components["away_runs_for_mean"] == pytest.approx(6.0)
    assert components["away_runs_against_mean"] == pytest.approx(4.0)
    assert components["home_runs_for_mean"] == pytest.approx(3.0)
    assert components["home_runs_against_mean"] == pytest.approx(5.0)
    assert components["version"] == PRODUCTION_RUN_MEAN_VERSION


@pytest.mark.parametrize("market", ["MONEYLINE", "RUN_LINE", "TOTALS"])
def test_full_game_market_features_use_promoted_defense_blend(market):
    source = MLBAllMarketHistorySource(
        opener=_opener,
        retrieved_at=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
    )
    row = source.feature_row(
        game_pk=123,
        market=market,
        entity_id="123",
        target_date=date(2026, 9, 29),
        away_team_id=1,
        home_team_id=2,
    )
    assert row["away_mean_runs"] == pytest.approx(5.5)
    assert row["home_mean_runs"] == pytest.approx(3.5)
    assert row["run_mean_version"] == PRODUCTION_RUN_MEAN_VERSION
    assert row["source"] == "MLB_STATSAPI_STRICT_PRIOR_OFFENSE_DEFENSE_50_50"


def test_team_totals_use_same_promoted_defense_blend():
    source = MLBAllMarketHistorySource(
        opener=_opener,
        retrieved_at=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
    )
    row = source.feature_row(
        game_pk=123,
        market="TEAM_TOTALS",
        entity_id="1",
        target_date=date(2026, 9, 29),
        away_team_id=1,
        home_team_id=2,
        team_id=1,
    )
    assert row["away_mean_runs"] == pytest.approx(5.5)
    assert row["home_mean_runs"] == pytest.approx(3.5)
    assert row["run_mean_version"] == PRODUCTION_RUN_MEAN_VERSION


def test_defense_blend_fails_closed_below_minimum_history():
    def short_opener(req, timeout=15):
        url = getattr(req, "full_url", str(req))
        team_id = int(parse_qs(urlparse(url).query)["teamId"][0])
        return _Response(_schedule(team_id, date(2026, 9, 29), games=9))

    source = MLBAllMarketHistorySource(
        opener=short_opener,
        retrieved_at=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(MLBGenericFeatureError, match="insufficient run-profile sample"):
        source.defense_blended_team_means(
            away_team_id=1,
            home_team_id=2,
            target_date=date(2026, 9, 29),
        )
