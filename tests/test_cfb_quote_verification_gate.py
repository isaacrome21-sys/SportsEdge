"""Phase 4: a CFB quote is priceable only with a fresh DK rendered quote AND a fresh
independent (allowlisted, non-DK, non-ESPN) price for the same game/market/side."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.cfb.quote_verification_gate import (
    INDEPENDENT_SOURCE_ALLOWLIST, MAX_QUOTE_AGE_SECONDS, _verify_quote_pair_impl, verify_quote_pair)

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
KO = "2026-10-24T16:00:00Z"
TEST_ALLOW = frozenset({"TEST_INDEPENDENT_BOOK"})


def dk(**kw):
    q = dict(source="DRAFTKINGS_RENDERED_PAGE_V1", book="draftkings", home_team_id="130",
             away_team_id="84", kickoff=KO, captured_at=(NOW - timedelta(seconds=60)).isoformat(),
             market="SPREAD", side="HOME", line=-3.5, odds=-110)
    q.update(kw)
    return q


def ind(**kw):
    q = dict(source="TEST_INDEPENDENT_BOOK", book="testbook", home_team_id="130", away_team_id="84",
             kickoff="2026-10-24T11:00:00-05:00", captured_at=(NOW - timedelta(seconds=30)).isoformat(),
             market="SPREAD", side="HOME", line=-3.5, odds=-108)
    q.update(kw)
    return q


def v(d, i, **kw):
    return _verify_quote_pair_impl(d, i, now=NOW, allowlist=kw.get("allowlist", TEST_ALLOW))


def test_production_allowlist_is_empty_and_everything_unavailable():
    assert INDEPENDENT_SOURCE_ALLOWLIST == frozenset()
    for src in ("TEST_INDEPENDENT_BOOK", "circa", "", None, "pinnacle"):
        r = verify_quote_pair(dk(), ind(source=src), now=NOW)
        assert not r.ok and r.reason == "INDEPENDENT_PRICE_UNAVAILABLE"


def test_fresh_matching_allowlisted_pair_passes_but_stays_research_only():
    r = v(dk(), ind())
    assert r.ok and r.reason == "QUOTE_PAIR_VERIFIED"
    assert r.play_allowed is False and r.status_label == "SCREEN/NOT_VALIDATED"


def test_no_independent_quote_fails_closed():
    assert v(dk(), None).reason == "INDEPENDENT_PRICE_UNAVAILABLE"


@pytest.mark.parametrize("src", ["", None, "   ", "unknown_book"])
def test_empty_or_unlisted_independent_source_unavailable(src):
    assert v(dk(), ind(source=src)).reason == "INDEPENDENT_PRICE_UNAVAILABLE"


@pytest.mark.parametrize("bad", [dict(book="ESPN BET"), dict(book="espn"), dict(provider="espn_scoreboard"),
                                 dict(book="espndk"), dict(provider="ESPN partner")])
def test_espn_refused_even_if_source_allowlisted(bad):
    assert v(dk(), ind(**bad)).reason == "INDEPENDENT_SOURCE_NOT_INDEPENDENT"


def test_espn_source_refused_even_if_allowlisted():
    r = v(dk(), ind(source="ESPN_SCOREBOARD"), allowlist=frozenset({"ESPN_SCOREBOARD"}))
    assert r.reason == "INDEPENDENT_SOURCE_NOT_INDEPENDENT"


@pytest.mark.parametrize("bad", [dict(book="DraftKings"), dict(book="Draft-Kings"), dict(book="dkng"),
                                 dict(book="DK Sportsbook"), dict(provider="Draft Kings"), dict(book="DK")])
def test_dk_spellings_not_independent(bad):
    assert v(dk(), ind(**bad)).reason == "INDEPENDENT_SOURCE_NOT_INDEPENDENT"


def test_inclusive_180s_boundary_documented_and_enforced():
    assert MAX_QUOTE_AGE_SECONDS == 180
    assert v(dk(captured_at=(NOW - timedelta(seconds=180)).isoformat()), ind()).ok
    assert v(dk(captured_at=(NOW - timedelta(seconds=181)).isoformat()), ind()).reason == "DK_QUOTE_STALE"
    assert v(dk(), ind(captured_at=(NOW - timedelta(seconds=181)).isoformat())).reason == "INDEPENDENT_QUOTE_STALE"


def test_future_capture_rejected():
    assert v(dk(captured_at=(NOW + timedelta(seconds=5)).isoformat()), ind()).reason == "DK_CAPTURE_IN_FUTURE"


def test_dk_must_be_rendered_page():
    assert v(dk(source="DRAFTKINGS_API"), ind()).reason == "DK_SOURCE_NOT_RENDERED_PAGE"


@pytest.mark.parametrize("bad", [dict(home_team_id="999"), dict(home_team_id="84", away_team_id="130"),
                                 dict(kickoff="2026-10-24T19:30:00Z"), dict(home_team_id=130),
                                 dict(home_team_id=True)])
def test_game_identity_mismatch_or_type_cross(bad):
    assert not v(dk(), ind(**bad)).ok


@pytest.mark.parametrize("bad", [dict(market="TOTAL", side="OVER", line=49.5), dict(side="AWAY"), dict(line=-4.5)])
def test_market_side_line_must_match(bad):
    assert v(dk(), ind(**bad)).reason == "MARKET_SELECTION_MISMATCH"


@pytest.mark.parametrize("who", ["dk", "ind"])
@pytest.mark.parametrize("bad", [dict(odds=True), dict(odds=float("nan")), dict(odds=50), dict(odds=-99),
                                 dict(odds="-110"), dict(odds=None), dict(line=float("inf")), dict(line=True),
                                 dict(market=""), dict(market="FOO"), dict(side=None), dict(side="")])
def test_price_line_market_selection_validated_on_both(who, bad):
    r = v(dk(**bad), ind()) if who == "dk" else v(dk(), ind(**bad))
    assert not r.ok


@pytest.mark.parametrize("bad", [dict(kickoff=""), dict(kickoff="2026-10-24T16:00:00"), dict(captured_at=None),
                                 dict(home_team_id=None)])
def test_missing_or_naive_fields_fail_closed(bad):
    assert not v(dk(**bad), ind()).ok


def test_after_kickoff_rejected():
    later = datetime(2026, 10, 24, 16, 0, 30, tzinfo=timezone.utc)
    r = _verify_quote_pair_impl(dk(captured_at=later.isoformat()), ind(captured_at=later.isoformat()),
                                now=later, allowlist=TEST_ALLOW)
    assert r.reason == "KICKOFF_PASSED"


def test_naive_now_rejected():
    with pytest.raises(ValueError):
        _verify_quote_pair_impl(dk(), ind(), now=NOW.replace(tzinfo=None), allowlist=TEST_ALLOW)


# --- Explicit negative coverage requested for re-audit (pt266u) ---

@pytest.mark.parametrize("src", [None, "", "UNKNOWN_BOOK", "pinnacle", "circa"])
def test_neg_unknown_or_missing_source_rejected_with_production_allowlist(src):
    r = verify_quote_pair(dk(), ind(source=src), now=NOW)
    assert not r.ok and r.reason == "INDEPENDENT_PRICE_UNAVAILABLE" and r.play_allowed is False


@pytest.mark.parametrize("field", ["source", "book", "provider"])
@pytest.mark.parametrize("alias", ["Draft-Kings", "DRAFT KINGS", "dkng", "DK Sportsbook", "draftkings.com", "DK"])
def test_neg_dk_alias_in_any_field_rejected(field, alias):
    r = v(dk(), ind(**{field: alias}), allowlist=TEST_ALLOW | {alias})
    assert not r.ok and r.reason == "INDEPENDENT_SOURCE_NOT_INDEPENDENT"


@pytest.mark.parametrize("cap_offset", [0, 1, 600])
def test_neg_post_kickoff_capture_rejected(cap_offset):
    ko = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)
    cap = (ko + timedelta(seconds=cap_offset)).isoformat()
    for d, i in ((dk(captured_at=cap), ind()), (dk(), ind(captured_at=cap))):
        assert not v(d, i).ok  # now < kickoff: capture is in the future
        late = ko + timedelta(seconds=cap_offset + 1)
        assert not _verify_quote_pair_impl(d, i, now=late, allowlist=TEST_ALLOW).ok


def test_neg_stale_both_sides_over_180s():
    old = (NOW - timedelta(seconds=181)).isoformat()
    assert v(dk(captured_at=old), ind()).reason == "DK_QUOTE_STALE"
    assert v(dk(), ind(captured_at=old)).reason == "INDEPENDENT_QUOTE_STALE"


@pytest.mark.parametrize("odds", [0, 99, -100 + 1, 1e400, float("-inf"), "+110", [], True, False])
def test_neg_invalid_prices_rejected(odds):
    assert not v(dk(odds=odds), ind()).ok
    assert not v(dk(), ind(odds=odds)).ok


@pytest.mark.parametrize("bad", [dict(away_team_id="999"), dict(kickoff="2026-10-25T16:00:00Z"),
                                 dict(market="ML", side="HOME", line=None), dict(side="AWAY")])
def test_neg_mismatched_game_market_side_rejected(bad):
    r = v(dk(), ind(**bad))
    assert not r.ok and r.reason in {"GAME_IDENTITY_MISMATCH", "MARKET_SELECTION_MISMATCH"}


# --- t275 re-audit LOWs ---
import inspect
import subprocess
from pathlib import Path


def test_public_entrypoint_cannot_take_allowlist():
    assert "allowlist" not in inspect.signature(verify_quote_pair).parameters
    with pytest.raises(TypeError):
        verify_quote_pair(dk(), ind(), now=NOW, allowlist=TEST_ALLOW)


def test_no_production_call_site_uses_private_impl_or_allowlist():
    root = Path(__file__).resolve().parents[1]
    hits = subprocess.run(["git", "grep", "-l", "-e", "_verify_quote_pair_impl", "-e", "allowlist=",
                           "--", "sportsedge", "artifacts", "scripts"], cwd=root,
                          capture_output=True, text=True).stdout.split()
    assert [h for h in hits if h != "sportsedge/sports/cfb/quote_verification_gate.py"] == []


@pytest.mark.parametrize("field", ["source", "book", "provider"])
@pytest.mark.parametrize("val", [123, 1.5, True, ["circa"], {"n": "x"}, b"circa"])
def test_non_string_labels_fail_closed(field, val):
    r = v(dk(), ind(**{field: val}))
    assert not r.ok and r.reason == "INDEPENDENT_SOURCE_LABEL_INVALID"
