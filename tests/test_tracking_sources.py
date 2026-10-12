"""Tests for Phase 3 tracking-data sources.

All fixtures are recorded (tests/fixtures/tracking/); no test touches the
network. Openers are injected fakes.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path

import pytest

from sportsedge import tracking_source_registry as reg
from sportsedge import mlb_statsapi_pitch_tracking as mlb_pt
from sportsedge import nflverse_ngs as ngs

FIXTURES = Path(__file__).parent / "fixtures" / "tracking"


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _opener_for(payload: bytes, seen: dict):
    def opener(req, timeout=None):
        seen["url"] = req.full_url
        return _FakeResponse(payload)
    return opener


# ---------------------------------------------------------------- registry

def test_registry_has_eight_investigated_sources():
    assert len(reg.TRACKING_SOURCES) == 8


def test_registry_wired_sources_are_the_two_verifiable_ones_plus_legacy():
    wired = {e["id"] for e in reg.wired_sources()}
    assert wired == {
        "MLB_STATSAPI_PITCH_TRACKING",
        "NFLVERSE_NGS",
        "BASEBALL_SAVANT_STATCAST_CSV",
    }
    legacy = reg.verdict_for("BASEBALL_SAVANT_STATCAST_CSV")
    assert legacy["reason_code"] == "LEGACY_GRANDFATHERED"


def test_registry_not_wired_carry_explicit_reason_codes():
    expected = {
        "NFL_NGS_OFFICIAL_API": "UNDOCUMENTED_ENDPOINT",
        "ESPN_ADVANCED_METRICS": "UNDOCUMENTED_ENDPOINT",
        "CFB_PLAYER_TRACKING": "NO_PUBLIC_SOURCE_EXISTS",
        "CFBD_ADVANCED_STATS": "API_KEY_REQUIRED",
        "NFLVERSE_NON_TRACKING": "OUT_OF_SCOPE_DEFERRED",
    }
    for source_id, code in expected.items():
        entry = reg.verdict_for(source_id)
        assert entry["verdict"] == reg.NOT_WIRED
        assert entry["reason_code"] == code
        assert entry["evidence"]


def test_registry_unknown_source_fails_closed():
    with pytest.raises(KeyError, match="TRACKING_SOURCE_UNKNOWN"):
        reg.verdict_for("NOPE")


# ------------------------------------------------- MLB StatsAPI pitch tracking

def _mlb_fixture_bytes() -> bytes:
    return (FIXTURES / "mlb_feed_live_sample.json").read_bytes()


def test_mlb_fetch_parses_recorded_final_game():
    seen: dict = {}
    result = mlb_pt.fetch_game_pitch_tracking(
        849831, opener=_opener_for(_mlb_fixture_bytes(), seen)
    )
    assert "api/v1.1/game/849831/feed/live" in seen["url"]
    assert "fields=" in seen["url"]
    assert result["source"] == mlb_pt.SOURCE
    assert result["official_date"] == "2026-10-10"
    assert result["detailed_state"] == "Final"
    events = result["pitch_events"]
    assert len(events) == 7
    assert {e.pitcher_id for e in events} == {668909}
    first = events[0]
    assert first.start_speed is not None and first.start_speed > 80
    assert first.spin_rate is not None and first.spin_rate > 0
    assert first.pitch_type  # e.g. "Sinker"


def test_mlb_aggregate_pitcher_game_means():
    seen: dict = {}
    result = mlb_pt.fetch_game_pitch_tracking(
        849831, opener=_opener_for(_mlb_fixture_bytes(), seen)
    )
    agg = mlb_pt.aggregate_pitcher_game(result["pitch_events"])
    assert len(agg) == 1
    row = agg[0]
    assert row.pitcher_id == 668909
    assert row.pitcher_name == "Gavin Williams"
    assert row.n_pitches == 7
    speeds = [e.start_speed for e in result["pitch_events"]]
    assert row.avg_start_speed == round(sum(speeds) / len(speeds), 4)
    assert row.max_start_speed == round(max(speeds), 2)
    assert row.avg_spin_rate is not None
    assert sum(n for _, n in row.pitch_mix) == 7


def test_mlb_non_final_game_fails_closed():
    payload = json.loads(_mlb_fixture_bytes())
    payload["gameData"]["status"]["detailedState"] = "In Progress"
    with pytest.raises(mlb_pt.PitchTrackingError, match="PITCH_TRACKING_GAME_NOT_FINAL"):
        mlb_pt.fetch_game_pitch_tracking(
            849831, opener=_opener_for(json.dumps(payload).encode(), {})
        )


def test_mlb_missing_plays_fails_closed():
    payload = {"gameData": {"status": {"detailedState": "Final"},
                            "datetime": {"officialDate": "2026-10-10"}},
               "liveData": {"plays": {}}}
    with pytest.raises(mlb_pt.PitchTrackingError, match="PITCH_TRACKING_NO_PLAYS"):
        mlb_pt.fetch_game_pitch_tracking(
            1, opener=_opener_for(json.dumps(payload).encode(), {})
        )


def test_mlb_fetch_failure_has_reason_code():
    def bad_opener(req, timeout=None):
        raise ConnectionError("down")

    with pytest.raises(mlb_pt.PitchTrackingError, match="PITCH_TRACKING_FETCH_FAILED"):
        mlb_pt.fetch_game_pitch_tracking(1, opener=bad_opener)


def test_mlb_aggregate_empty_fails_closed():
    with pytest.raises(mlb_pt.PitchTrackingError, match="PITCH_TRACKING_NO_PITCH_EVENTS"):
        mlb_pt.aggregate_pitcher_game([])


# ---------------------------------------------------------------- nflverse NGS

def _ngs_fixture_gz() -> bytes:
    raw = (FIXTURES / "ngs_passing_sample.csv").read_bytes()
    return gzip.compress(raw)


def test_ngs_asset_urls_cover_all_stat_types():
    for stat_type in ("passing", "rushing", "receiving"):
        url = ngs.asset_url(stat_type)
        assert url.startswith(ngs.RELEASE_BASE)
        assert url.endswith(f"ngs_{stat_type}.csv.gz")


def test_ngs_invalid_stat_type_fails_closed():
    with pytest.raises(ngs.NGSFetchError, match="NGS_STAT_TYPE_INVALID"):
        ngs.asset_url("kicking")


def test_ngs_fetch_parses_recorded_fixture():
    rows = ngs.fetch_ngs("passing", opener=_opener_for(_ngs_fixture_gz(), {}))
    assert len(rows) == 14
    assert {r["season"] for r in rows} == {"2026"}
    sample = rows[0]
    assert float(sample["avg_time_to_throw"]) > 0
    assert sample["player_gsis_id"]


def test_ngs_rolling_metrics_use_strictly_prior_weeks():
    rows = ngs.fetch_ngs("passing", opener=_opener_for(_ngs_fixture_gz(), {}))
    out = ngs.rolling_player_metrics(rows, stat_type="passing", season=2026, week=2, window=4)
    assert len(out) == 14
    for entry in out:
        assert entry.target_week == 2
        assert entry.window_weeks == (1,)
        assert entry.n_weeks == 1
        metric_names = [name for name, _ in entry.metrics]
        assert "avg_time_to_throw" in metric_names


def test_ngs_rolling_metrics_exclude_target_week_no_lookahead():
    rows = [
        {"season": "2026", "season_type": "REG", "week": "1",
         "player_display_name": "Test QB", "player_gsis_id": "00-0001",
         "avg_time_to_throw": "2.50", "aggressiveness": "10.0"},
        {"season": "2026", "season_type": "REG", "week": "2",
         "player_display_name": "Test QB", "player_gsis_id": "00-0001",
         "avg_time_to_throw": "2.70", "aggressiveness": "12.0"},
        {"season": "2026", "season_type": "REG", "week": "3",
         "player_display_name": "Test QB", "player_gsis_id": "00-0001",
         "avg_time_to_throw": "9.99", "aggressiveness": "99.0"},
    ]
    out = ngs.rolling_player_metrics(rows, stat_type="passing", season=2026, week=3, window=2)
    assert len(out) == 1
    entry = out[0]
    # Week 3 (the target) must not leak into its own features.
    assert entry.window_weeks == (1, 2)
    metrics = dict(entry.metrics)
    assert metrics["avg_time_to_throw"] == round((2.50 + 2.70) / 2, 6)


def test_ngs_rolling_metrics_exclude_week_zero_summary():
    rows = [
        {"season": "2026", "season_type": "REG", "week": "0",
         "player_display_name": "Test QB", "player_gsis_id": "00-0001",
         "avg_time_to_throw": "1.00"},
        {"season": "2026", "season_type": "REG", "week": "1",
         "player_display_name": "Test QB", "player_gsis_id": "00-0001",
         "avg_time_to_throw": "2.50"},
    ]
    out = ngs.rolling_player_metrics(rows, stat_type="passing", season=2026, week=2, window=4)
    assert out[0].window_weeks == (1,)


def test_ngs_rolling_metrics_no_history_fails_closed():
    rows = ngs.fetch_ngs("passing", opener=_opener_for(_ngs_fixture_gz(), {}))
    with pytest.raises(ngs.NGSFetchError, match="NGS_NO_PRIOR_WEEKS"):
        ngs.rolling_player_metrics(rows, stat_type="passing", season=2026, week=1)


def test_ngs_fetch_failure_has_reason_code():
    def bad_opener(req, timeout=None):
        raise TimeoutError("slow")

    with pytest.raises(ngs.NGSFetchError, match="NGS_FETCH_FAILED"):
        ngs.fetch_ngs("passing", opener=bad_opener)
