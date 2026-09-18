from __future__ import annotations

from hashlib import sha256

import pytest

from sportsedge.sports.cfb.reconstructed_selection_acquisition import (
    AcquisitionRequest,
    CFBReconstructedAcquisitionError,
    EXPECTED_REQUEST_COUNT,
    assert_private_cache_root,
    build_cache_manifest_entry,
    build_reconstructed_selection_plan,
    governance_stamp,
    verify_cached_response,
)


def test_plan_is_exact_254_calls_and_contains_2014_prior_fallback():
    plan = build_reconstructed_selection_plan()
    assert len(plan) == EXPECTED_REQUEST_COUNT == 254
    assert len({request.query_sha256 for request in plan}) == 254
    assert all(request.season <= 2025 for request in plan)

    advanced = [x for x in plan if x.endpoint == "/stats/season/advanced"]
    assert len(advanced) == 220
    assert sum(x.end_week is not None for x in advanced) == 209
    assert sum(x.end_week is None for x in advanced) == 11
    assert any(
        x.season == 2014 and x.end_week is None and x.query_params["year"] == 2014
        for x in advanced
    )

    assert sum(x.endpoint == "/games" for x in plan) == 12
    assert sum(x.endpoint == "/teams/fbs" for x in plan) == 11
    assert sum(x.endpoint == "/games/weather" for x in plan) == 11


def test_request_identity_is_deterministic_and_secret_free():
    a = AcquisitionRequest(
        endpoint="/stats/season/advanced",
        season=2020,
        end_week=4,
        provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
        query_params={"year": 2020, "classification": "fbs", "endWeek": 4},
    )
    b = AcquisitionRequest(
        endpoint="/stats/season/advanced",
        season=2020,
        end_week=4,
        provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
        query_params={"endWeek": 4, "classification": "fbs", "year": 2020},
    )
    assert a.query_sha256 == b.query_sha256

    with pytest.raises(CFBReconstructedAcquisitionError, match="SECRET_IN_QUERY"):
        AcquisitionRequest(
            endpoint="/games", season=2020, end_week=None,
            provider_contract="CFBD_GAMES_REGULAR_FBS_V1",
            query_params={"year": 2020, "api_key": "must-not-enter-manifest"},
        ).query_sha256


def test_cache_manifest_hashes_raw_bytes_without_embedding_them():
    request = AcquisitionRequest(
        endpoint="/games", season=2019, end_week=None,
        provider_contract="CFBD_GAMES_REGULAR_FBS_V1",
        query_params={"year": 2019, "seasonType": "regular", "classification": "fbs"},
    )
    raw = b'[{"id":123,"homeTeam":"A","awayTeam":"B"}]'
    entry = build_cache_manifest_entry(
        request, raw_response=raw, retrieved_at_utc="2026-09-18T10:00:00Z"
    )
    assert entry["response_sha256"] == sha256(raw).hexdigest()
    assert "raw_response" not in entry
    assert "query_params" not in entry
    assert verify_cached_response(request, entry=entry, raw_response=raw) is True
    assert verify_cached_response(request, entry=entry, raw_response=raw + b"x") is False


def test_raw_cache_must_live_outside_public_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(CFBReconstructedAcquisitionError, match="PUBLIC_REPOSITORY_RAW_CACHE"):
        assert_private_cache_root(repo / ".cache" / "cfbd", repository_root=repo)
    private_root = tmp_path / "private-cfbd-cache"
    assert assert_private_cache_root(private_root, repository_root=repo) == private_root.resolve()


def test_governance_stamp_has_zero_authority_and_no_network_call():
    stamp = governance_stamp()
    assert stamp
    assert set(stamp.values()) == {False}
    assert stamp["network_call_performed"] is False
    assert stamp["attempt_consumed"] is False
    assert stamp["model_fit_performed"] is False
    assert stamp["model_p_created"] is False
    assert stamp["promotion_authority"] is False
    assert stamp["official_authority"] is False
