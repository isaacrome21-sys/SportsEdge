"""Phase 4: a CFB quote is priceable only with a fresh DK rendered quote AND a fresh independent price for the same game."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.cfb.quote_verification_gate import verify_quote_pair

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
KO = "2026-10-24T16:00:00Z"


def dk(**kw):
    q = dict(source="DRAFTKINGS_RENDERED_PAGE_V1", book="draftkings", home_team_id="130",
             away_team_id="84", kickoff=KO, captured_at=(NOW - timedelta(seconds=60)).isoformat())
    q.update(kw)
    return q


def ind(**kw):
    q = dict(source="CIRCA_PUBLIC_PAGE", book="circa", home_team_id="130", away_team_id="84",
             kickoff="2026-10-24T11:00:00-05:00", captured_at=(NOW - timedelta(seconds=30)).isoformat())
    q.update(kw)
    return q


def test_fresh_matching_pair_passes_but_stays_research_only():
    r = verify_quote_pair(dk(), ind(), now=NOW)
    assert r.ok and r.reason == "QUOTE_PAIR_VERIFIED"
    assert r.play_allowed is False and r.status_label == "SCREEN/NOT_VALIDATED"


def test_no_independent_source_fails_closed():
    r = verify_quote_pair(dk(), None, now=NOW)
    assert not r.ok and r.reason == "INDEPENDENT_PRICE_UNAVAILABLE"


@pytest.mark.parametrize("age,ok", [(180, True), (181, False)])
def test_180s_boundary_dk(age, ok):
    r = verify_quote_pair(dk(captured_at=(NOW - timedelta(seconds=age)).isoformat()), ind(), now=NOW)
    assert r.ok is ok
    if not ok:
        assert r.reason == "DK_QUOTE_STALE"


def test_stale_independent():
    r = verify_quote_pair(dk(), ind(captured_at=(NOW - timedelta(seconds=181)).isoformat()), now=NOW)
    assert r.reason == "INDEPENDENT_QUOTE_STALE"


def test_future_capture_rejected():
    r = verify_quote_pair(dk(captured_at=(NOW + timedelta(seconds=5)).isoformat()), ind(), now=NOW)
    assert r.reason == "DK_CAPTURE_IN_FUTURE"


def test_dk_must_be_rendered_page():
    r = verify_quote_pair(dk(source="DRAFTKINGS_API"), ind(), now=NOW)
    assert r.reason == "DK_SOURCE_NOT_RENDERED_PAGE"


@pytest.mark.parametrize("bad", [dict(book="DraftKings"), dict(book="ESPN partner", provider="DraftKings"),
                                 dict(source="DRAFTKINGS_RENDERED_PAGE_V1")])
def test_dk_derived_feed_is_not_independent(bad):
    r = verify_quote_pair(dk(), ind(**bad), now=NOW)
    assert r.reason == "INDEPENDENT_SOURCE_NOT_INDEPENDENT"


@pytest.mark.parametrize("bad", [dict(home_team_id="999"), dict(home_team_id="84", away_team_id="130"),
                                 dict(kickoff="2026-10-24T19:30:00Z")])
def test_game_identity_mismatch(bad):
    r = verify_quote_pair(dk(), ind(**bad), now=NOW)
    assert r.reason == "GAME_IDENTITY_MISMATCH"


@pytest.mark.parametrize("bad", [dict(kickoff=""), dict(kickoff="2026-10-24T16:00:00"), dict(captured_at=None),
                                 dict(home_team_id=None)])
def test_missing_or_naive_fields_fail_closed(bad):
    r = verify_quote_pair(dk(**bad), ind(), now=NOW)
    assert not r.ok


def test_after_kickoff_rejected():
    later = datetime(2026, 10, 24, 16, 0, 30, tzinfo=timezone.utc)
    r = verify_quote_pair(dk(captured_at=later.isoformat()), ind(captured_at=later.isoformat()), now=later)
    assert r.reason == "KICKOFF_PASSED"


def test_naive_now_rejected():
    with pytest.raises(ValueError):
        verify_quote_pair(dk(), ind(), now=NOW.replace(tzinfo=None))
