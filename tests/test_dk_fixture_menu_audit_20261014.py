"""DK fixture-menu census audit: negative fixtures are intentionally unpriced."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from sportsedge.dk_fixture_menu_audit import (
    DKFixtureMenuError, SNAPSHOT_SCHEMA, audit_dk_fixture_menu, load_census,
)


def fixture(sport="MLB", *, offers=None, absent=None):
    return {
        "schema": SNAPSHOT_SCHEMA, "sport": sport, "event_id": "GAME-42",
        "book": "draftkings", "scheduled_start": "2026-10-15T00:00:00Z",
        "captured_at": "2026-10-14T22:30:00Z",
        "offers": [] if offers is None else offers,
        "observed_absent": [] if absent is None else absent,
    }


def row(market, form, **kw):
    return {"market_key": market, "form": form,
            "period": "FULL_GAME", **kw}


def quoted_row(market="PITCHER_K", form="X_PLUS_LADDER", **kw):
    return row(
        market, form, player_id="P-6", line=5.5, selection="OVER",
        price_american=115, book_event_id="DK-42",
        quote_captured_at="2026-10-14T22:29:00Z",
        source_receipt="owner-reported-snapshot-not-verified", **kw)


def test_all_reported_sports_have_unique_declared_market_keys():
    cat = load_census()
    assert set(cat["sports"]) == {"MLB", "NFL", "CFB"}
    assert {s: len(o["markets"]) for s, o in cat["sports"].items()} == {
        "MLB": 64, "NFL": 65, "CFB": 23}
    for sport, obj in cat["sports"].items():
        assert len(set(m["market_key"] for m in obj["markets"])) == len(obj["markets"])


def test_mlb_strikeout_ladder_is_visible_without_inventing_under():
    out = audit_dk_fixture_menu(fixture(offers=[quoted_row()]))
    assert len(out["observations"]) == 1
    assert out["observations"][0]["status"] == "QUOTE_REPORTED_RECEIPT_NOT_VERIFIED"
    assert out["no_vig_without_true_two_sided_quote"] == "UNAVAILABLE"
    assert "estimate_p" not in str(out)
    assert "odds" not in out["observations"][0]
    assert out["promotion_eligible"] is False


def test_native_and_milestone_are_separate_even_on_same_player():
    a = quoted_row(form="X_PLUS_LADDER")
    b = row("PITCHER_K", "TWO_SIDED", player_id="P-6", line=5.5,
            selection="UNDER")
    out = audit_dk_fixture_menu(fixture(offers=[a, b]))
    assert out["status_counts"] == {
        "MENU_OBSERVATION_UNPRICED": 1,
        "QUOTE_REPORTED_RECEIPT_NOT_VERIFIED": 1}
    assert out["duplicate_keys"] == []


def test_nfl_same_stat_native_and_x_plus_both_registered():
    f = fixture("NFL", offers=[
        row("PLAYER_PASSING_YARDS", "TWO_SIDED", player_id="QB1", line=249.5),
        row("PLAYER_PASSING_YARDS", "X_PLUS_LADDER", player_id="QB1", line=249.5),
    ])
    r = audit_dk_fixture_menu(f)
    assert r["status_counts"] == {"MENU_OBSERVATION_UNPRICED": 2}


def test_cfb_zero_player_offers_does_not_mean_global_absence():
    out = audit_dk_fixture_menu(fixture(
        "CFB", offers=[row("MONEYLINE", "TWO_SIDED")],
        absent=["PLAYER_PASSING_YARDS", "ANYTIME_TD"]))
    assert out["observed_absent_on_this_fixture"] == [
        "ANYTIME_TD", "PLAYER_PASSING_YARDS"]
    assert out["snapshot_is_not_proven_tradable_quote"] is True
    assert out["promotion_eligible"] is False


def test_cfb_other_fixture_can_include_player_qb_ladder():
    out = audit_dk_fixture_menu(fixture(
        "CFB", offers=[row("PLAYER_PASSING_YARDS", "X_PLUS_LADDER",
                           period="FULL_GAME", player_id="QB1", line=225.5)]))
    assert out["observations"][0]["status"] == "MENU_OBSERVATION_UNPRICED"


def test_per_fixture_absence_conflict_rejected():
    with pytest.raises(DKFixtureMenuError, match="OBSERVED_ABSENT_CONFLICT"):
        audit_dk_fixture_menu(fixture(
            offers=[row("BATTER_HITS", "TWO_SIDED", player_id="B")],
            absent=["BATTER_HITS"]))


def test_f5_total_discrepancy_requires_explicit_new_catalog_entry():
    out = audit_dk_fixture_menu(fixture(
        offers=[row("F5_GAME_TOTAL", "TWO_SIDED", period="FIRST_5", line=4.5)]))
    assert out["observations"][0]["status"] == "MARKET_UNCATALOGED"


@pytest.mark.parametrize("bad", [None, [], "", 1, {"foo": 2}])
def test_bad_offer_refused_without_reflecting_input(bad):
    out = audit_dk_fixture_menu(fixture(offers=[bad]))
    assert out["observations"][0]["status"] == "REFUSED_MALFORMED_OFFER"
    assert "foo" not in str(out)


@pytest.mark.parametrize("price", [None, -1, -99, True, "-110", 0])
def test_no_partial_or_fabricated_quote_on_invalid_price(price):
    q = quoted_row()
    q["price_american"] = price
    out = audit_dk_fixture_menu(fixture(offers=[q]))
    assert out["observations"][0]["status"] == "QUOTE_EVIDENCE_INCOMPLETE"


def test_quote_after_kickoff_never_pregame_evidence():
    q = quoted_row()
    q["quote_captured_at"] = "2026-10-15T01:00:00Z"
    out = audit_dk_fixture_menu(fixture(offers=[q]))
    assert out["observations"][0]["status"] == "QUOTE_NOT_PREGAME_OR_AFTER_SNAPSHOT"


def test_future_capture_without_proven_utc_refused():
    f = fixture()
    f["captured_at"] = "2026-10-14T23:15:00"
    with pytest.raises(DKFixtureMenuError, match="TIMEZONE_REQUIRED"):
        audit_dk_fixture_menu(f)


def test_duplicate_same_offer_not_silently_paired():
    q = quoted_row()
    o = audit_dk_fixture_menu(fixture(offers=[q, deepcopy(q)]))
    assert o["status_counts"]["DUPLICATE_MARKET_OFFER"] == 1
    assert o["duplicate_keys"] == ["PITCHER_K"]


def test_unobserved_market_not_global_not_offered():
    out = audit_dk_fixture_menu(fixture(offers=[]))
    assert "PITCHER_K" in out["not_reported_no_absence_proof"]
    assert out["observed_absent_on_this_fixture"] == []
    assert "NOT_OFFERED" not in str(out)


def test_side_probability_or_price_in_user_input_not_leaked_to_report():
    q = quoted_row()
    q.update({"model_p": 0.99, "ev": 4.0, "artificial_opposite_odds": -999,
              "validated": True, "staking_authority": True})
    out = audit_dk_fixture_menu(fixture(offers=[q]))
    assert out["promotion_eligible"] is False
    assert out["betting_authority"] is False
    assert "0.99" not in str(out) and "4.0" not in str(out)


def test_wrong_period_and_wrong_form_fail_closed():
    out = audit_dk_fixture_menu(fixture(offers=[
        row("FIRST_3_MONEYLINE", "TWO_SIDED", period="FIRST_5"),
        row("PITCHER_K", "EXACTA", player_id="P-6"),
    ]))
    assert [x["status"] for x in out["observations"]] == [
        "MARKET_PERIOD_CONFLICT", "MARKET_FORM_NOT_REGISTERED"]


def test_invalid_ladder_missing_threshold_refused():
    out = audit_dk_fixture_menu(fixture(offers=[
        row("PITCHER_K", "X_PLUS_LADDER", player_id="P-6")]))
    assert out["observations"][0]["status"] == "MILESTONE_LINE_REQUIRED"


def test_umbrella_label_is_not_executable_book_market():
    o = audit_dk_fixture_menu(fixture(offers=[
        row("INNING_2_MARKETS", "TWO_SIDED", period="INNING_2", line=0.5)]))
    assert o["observations"][0]["status"] == "PROVISIONAL_FAMILY_NOT_EXECUTABLE"
    assert o["promotion_eligible"] is False


def test_nfl_generic_period_placeholder_needs_exact_stat_identity():
    o = audit_dk_fixture_menu(fixture("NFL", offers=[
        row("PLAYER_1H_RECEIVING", "TWO_SIDED", period="FIRST_HALF", line=35.5)]))
    assert o["observations"][0]["status"] == "PROVISIONAL_FAMILY_NOT_EXECUTABLE"
