"""DK event-availability contract is fixture-level, not universal or an engine gate."""
import pytest

from sportsedge.dk_event_availability import (
    DKObservationError,
    reconcile_dk_event,
)

SOURCE = "https://sportsbook.draftkings.com/leagues/baseball/mlb"


def board(*, sport="MLB", event_id="849813", required=None,
          inspected=None, observed=None, absent=None):
    return {
        "sport": sport, "event_id": event_id, "book": "draftkings",
        "observed_at_utc": "2026-10-13T11:00:00Z", "source_url": SOURCE,
        "required_tabs": required or ["Popular", "Pitcher", "Batter", "Game"],
        "inspected_tabs": inspected if inspected is not None else ["Popular"],
        "market_observations": observed or [],
        "explicit_absent_markets": absent or [],
    }


def offered(market, shape, tab="Popular", period="FULL_GAME"):
    return {"market": market, "offer_shape": shape,
            "source_tab": tab, "period": period,
            "phase": "PREGAME", "settlement": "RULE_UNVERIFIED"}


def absent(market, tab="Popular"):
    return {"market": market, "source_tab": tab}


def by_market(report):
    return {r["market"]: r for r in report["rows"]}


def test_mlb_f5_total_absent_but_f5_team_total_present_without_global_claim():
    evidence = board(
        inspected=["Popular", "Game"],
        observed=[offered("F5_TEAM_TOTALS", "TWO_SIDED_OU",
                          period="FIRST_5")],
        absent=[absent("F5_TOTALS", "Game")],
    )
    report = reconcile_dk_event(
        ["F5_TOTALS", "F5_TEAM_TOTALS", "STOLEN_BASES"],
        evidence,
        engine_states={"F5_TOTALS": "NO_ENGINE",
                       "F5_TEAM_TOTALS": "ENGINE_BLOCKED"},
    )
    rows = by_market(report)
    assert rows["F5_TOTALS"]["availability"] == "NOT_OFFERED_ON_THIS_EVENT"
    assert rows["F5_TOTALS"]["engine_state"] == "NO_ENGINE"
    assert rows["F5_TEAM_TOTALS"]["availability"] == "OFFERED_ON_THIS_EVENT"
    assert rows["F5_TEAM_TOTALS"]["engine_state"] == "ENGINE_BLOCKED"
    assert rows["F5_TEAM_TOTALS"]["evidence"]["period"] == "FIRST_5"
    assert rows["STOLEN_BASES"]["availability"] == "NOT_VERIFIED_ON_THIS_EVENT"
    assert report["catalog_inspection_complete"] is False
    assert report["catalog_verified_globally"] is False


def test_either_pitcher_ladder_is_not_a_two_sided_no_vig_market():
    report = reconcile_dk_event(
        ["EITHER_PITCHER_HITS_ALLOWED", "PITCHER_K"],
        board(inspected=["Popular", "Pitcher"],
              observed=[offered("EITHER_PITCHER_HITS_ALLOWED",
                                "LADDER_ONLY", "Pitcher")],
              absent=[absent("PITCHER_K", "Pitcher")]),
    )
    rows = by_market(report)
    assert rows["EITHER_PITCHER_HITS_ALLOWED"]["evidence"]["offer_shape"] == "LADDER_ONLY"
    assert rows["EITHER_PITCHER_HITS_ALLOWED"]["can_derive_two_sided_no_vig"] is False
    assert rows["PITCHER_K"]["availability"] == "NOT_OFFERED_ON_THIS_EVENT"


def test_cfb_game_can_have_no_player_props_without_engine_status_conflation():
    evidence = board(
        sport="CFB", event_id="401871067",
        required=["Game", "Passing", "Receiving"],
        inspected=["Game", "Passing", "Receiving"],
        observed=[offered("moneyline", "TWO_SIDED_MONEYLINE", "Game")],
        absent=[absent("passing_yards", "Passing"),
                absent("receiving_yards", "Receiving")],
    )
    report = reconcile_dk_event(
        ["moneyline", "passing_yards", "receiving_yards"], evidence,
        engine_states={"moneyline": "PRICED_PATH",
                       "passing_yards": "NO_ENGINE",
                       "receiving_yards": "NO_ENGINE"},
    )
    rows = by_market(report)
    assert report["catalog_inspection_complete"] is True
    assert rows["PASSING_YARDS"]["availability"] == "NOT_OFFERED_ON_THIS_EVENT"
    assert rows["PASSING_YARDS"]["engine_state"] == "NO_ENGINE"
    assert rows["MONEYLINE"]["availability"] == "OFFERED_ON_THIS_EVENT"
    assert rows["MONEYLINE"]["engine_state"] == "PRICED_PATH"
    assert rows["RECEIVING_YARDS"]["deployment_eligible"] is False


def test_unregistered_offered_is_gap_not_ghost_price_or_research_approval():
    evidence = board(
        observed=[
            offered("PITCHER_K", "TWO_SIDED_OU"),
            offered("FIRST_INNING_HITS", "TWO_SIDED_OU"),
        ],
    )
    report = reconcile_dk_event(["PITCHER_K"], evidence)
    rows = by_market(report)
    assert report["unregistered_offered"] == ["FIRST_INNING_HITS"]
    assert rows["FIRST_INNING_HITS"]["registration_status"] == "NOT_REGISTERED"
    assert rows["FIRST_INNING_HITS"]["engine_state"] == "NOT_REGISTERED"
    assert rows["FIRST_INNING_HITS"]["model_validated"] is False
    assert report["promotion_authority"] is False


def test_all_tabs_inspected_does_not_imply_unlisted_market_absence():
    report = reconcile_dk_event(
        ["TARGETS", "LARGEST_LEAD"],
        board(required=["Game"], inspected=["Game"],
              observed=[offered("MONEYLINE", "TWO_SIDED_MONEYLINE", "Game")]),
    )
    assert report["catalog_inspection_complete"] is True
    assert by_market(report)["TARGETS"]["availability"] == "NOT_VERIFIED_ON_THIS_EVENT"
    assert by_market(report)["LARGEST_LEAD"]["availability"] == "NOT_VERIFIED_ON_THIS_EVENT"


def test_absence_is_fenced_to_inspected_tab():
    with pytest.raises(DKObservationError, match="ABSENCE_TAB_NOT_INSPECTED"):
        reconcile_dk_event(["F5_TOTALS"],
                           board(absent=[absent("F5_TOTALS", "Game")]))


def test_reject_contradictory_offered_and_absent():
    with pytest.raises(DKObservationError, match="OFFERED_AND_ABSENT_CONFLICT"):
        reconcile_dk_event(
            ["STOLEN_BASES"],
            board(observed=[offered("STOLEN_BASES", "LADDER_ONLY")],
                  absent=[absent("STOLEN_BASES")]))


@pytest.mark.parametrize("bad_shape", ["O/U", "UNKNOWN", "BOTH", "", "TWO_SIDED"])
def test_invalid_offer_shape_cannot_create_an_observed_market(bad_shape):
    with pytest.raises(DKObservationError, match="OFFER_SHAPE_"):
        reconcile_dk_event(
            [], board(observed=[offered("PITCHER_K", bad_shape)]))


def test_no_synthetic_freshness_from_naive_datetime():
    evidence = board()
    evidence["observed_at_utc"] = "2026-10-13T11:00:00"
    with pytest.raises(DKObservationError, match="OBSERVED_AT_TIMEZONE_REQUIRED"):
        reconcile_dk_event([], evidence)


def test_provider_documentation_not_interchangeable_with_dk():
    evidence = board()
    evidence["book"] = "the_odds_api"
    with pytest.raises(DKObservationError, match="BOOK_NOT_DRAFTKINGS"):
        reconcile_dk_event([], evidence)


def test_arbitrary_source_url_cannot_be_labeled_draftkings_observation():
    evidence = board()
    evidence["source_url"] = "https://the-odds-api.com/sports-odds-data/"
    with pytest.raises(DKObservationError, match="DRAFTKINGS_SOURCE_URL_REQUIRED"):
        reconcile_dk_event([], evidence)


def test_engine_state_is_independent_from_availability_and_can_be_unverified():
    report = reconcile_dk_event(
        ["PITCHER_K", "PITCHER_OUTS"],
        board(observed=[offered("PITCHER_K", "TWO_SIDED_OU")]),
        engine_states={"PITCHER_K": "UNVALIDATED_RESEARCH_ONLY",
                       "PITCHER_OUTS": "NO_ENGINE"})
    rows = by_market(report)
    assert rows["PITCHER_K"]["availability"] == "OFFERED_ON_THIS_EVENT"
    assert rows["PITCHER_K"]["engine_state"] == "UNVALIDATED_RESEARCH_ONLY"
    assert rows["PITCHER_OUTS"]["availability"] == "NOT_VERIFIED_ON_THIS_EVENT"
    assert rows["PITCHER_OUTS"]["engine_state"] == "NO_ENGINE"


def test_duplicate_rows_or_tabs_cannot_be_counted_as_distinct_markets():
    with pytest.raises(DKObservationError, match="DUPLICATE_MARKET_OBSERVATION"):
        reconcile_dk_event(
            [], board(observed=[offered("PITCHER_K", "TWO_SIDED_OU")] * 2))
    with pytest.raises(DKObservationError, match="TAB_NAME_DUPLICATE"):
        reconcile_dk_event(
            [], board(required=["Popular", "Popular"]))


def test_market_registration_cannot_self_attest_price_or_deployment():
    report = reconcile_dk_event(
        ["MONEYLINE"],
        board(observed=[offered("MONEYLINE", "TWO_SIDED_MONEYLINE")]),
        engine_states={"MONEYLINE": "PRICED_PATH"},
    )
    row = by_market(report)["MONEYLINE"]
    assert row["can_derive_two_sided_no_vig"] is False
    assert row["model_validated"] is False
    assert row["deployment_eligible"] is False


def test_one_family_can_have_main_alternate_and_ladder_without_erasing_shapes():
    observed = [
        dict(offered("PASSING_YARDS", "TWO_SIDED_OU"), line_variant="MAIN"),
        dict(offered("PASSING_YARDS", "TWO_SIDED_OU"), line_variant="ALTERNATE"),
        dict(offered("PASSING_YARDS", "LADDER_ONLY"), line_variant="LADDER"),
    ]
    report = reconcile_dk_event(
        ["PASSING_YARDS"], board(sport="NFL", observed=observed))
    row = by_market(report)["PASSING_YARDS"]
    assert report["registered_count"] == 1
    assert report["market_count"] == 1
    assert report["offered_contract_count"] == 3
    assert row["offer_variant_count"] == 3
    assert {x["line_variant"] for x in row["offer_variants"]} == {
        "MAIN", "ALTERNATE", "LADDER"
    }
    assert row["evidence"]["offer_shape"] is None
    assert row["can_derive_two_sided_no_vig"] is False


def test_same_family_pregame_and_live_are_distinct_contracts():
    pregame = offered("TEAM_TOTAL", "TWO_SIDED_OU")
    live = dict(pregame, phase="LIVE")
    result = reconcile_dk_event(
        ["TEAM_TOTAL"], board(sport="NFL", observed=[pregame, live]))
    variants = by_market(result)["TEAM_TOTAL"]["offer_variants"]
    assert len(variants) == 2
    assert {r["phase"] for r in variants} == {"PREGAME", "LIVE"}


def test_same_family_full_and_first_half_periods_not_merged():
    full = offered("TEAM_TOTAL", "TWO_SIDED_OU", period="FULL_GAME")
    half = offered("TEAM_TOTAL", "TWO_SIDED_OU", period="FIRST_HALF")
    result = reconcile_dk_event(
        ["TEAM_TOTAL"], board(sport="CFB", observed=[full, half]))
    variants = by_market(result)["TEAM_TOTAL"]["offer_variants"]
    assert len(variants) == 2
    assert {r["period"] for r in variants} == {"FULL_GAME", "FIRST_HALF"}


def test_same_family_different_settlement_not_silently_merged():
    a = offered("MONEYLINE", "TWO_SIDED_MONEYLINE")
    b = dict(a, settlement="TIE_PUSH_VERIFIED")
    result = reconcile_dk_event(["MONEYLINE"], board(observed=[a, b]))
    assert by_market(result)["MONEYLINE"]["offer_variant_count"] == 2
    assert {r["settlement"] for r in
            by_market(result)["MONEYLINE"]["offer_variants"]} == {
                "RULE_UNVERIFIED", "TIE_PUSH_VERIFIED"
            }


def test_scoped_absence_cannot_erase_offered_other_period_or_phase():
    observed = [offered("TEAM_TOTAL", "TWO_SIDED_OU",
                        period="FULL_GAME")]
    evidence = board(
        observed=observed,
        absent=[dict(absent("TEAM_TOTAL"), period="FIRST_HALF")])
    result = reconcile_dk_event(["TEAM_TOTAL"], evidence)
    row = by_market(result)["TEAM_TOTAL"]
    assert row["availability"] == "OFFERED_ON_THIS_EVENT"
    assert row["explicit_absence_scopes"][0]["period"] == "FIRST_HALF"
    assert row["offer_variant_count"] == 1


def test_variant_specific_absence_does_not_deny_whole_family():
    evidence = board(
        absent=[dict(absent("TEAM_TOTAL"), period="FIRST_HALF")])
    result = reconcile_dk_event(["TEAM_TOTAL"], evidence)
    row = by_market(result)["TEAM_TOTAL"]
    assert row["availability"] == "NOT_VERIFIED_ON_THIS_EVENT"
    assert row["explicit_absence_scopes"][0]["period"] == "FIRST_HALF"
    assert result["catalog_verified_globally"] is False


def test_overlapping_scoped_absence_and_offer_is_a_conflict():
    evidence = board(
        observed=[offered("TEAM_TOTAL", "TWO_SIDED_OU")],
        absent=[dict(absent("TEAM_TOTAL"), period="FULL_GAME")])
    with pytest.raises(DKObservationError, match="OFFERED_AND_ABSENT_CONFLICT"):
        reconcile_dk_event(["TEAM_TOTAL"], evidence)


def test_duplicate_contract_across_different_tabs_is_not_independent_evidence():
    a = offered("TEAM_TOTAL", "TWO_SIDED_OU")
    b = offered("TEAM_TOTAL", "TWO_SIDED_OU", tab="Game")
    evidence = board(
        inspected=["Popular", "Game"], observed=[a, b])
    with pytest.raises(DKObservationError, match="DUPLICATE_MARKET_OBSERVATION"):
        reconcile_dk_event(["TEAM_TOTAL"], evidence)


def test_bad_line_variant_refused_in_offered_and_absent_contracts():
    with pytest.raises(DKObservationError, match="LINE_VARIANT_INVALID"):
        reconcile_dk_event(
            ["PITCHER_K"], board(observed=[
                dict(offered("PITCHER_K", "TWO_SIDED_OU"),
                     line_variant="MAGIC_ODDS")]))
    with pytest.raises(DKObservationError, match="ABSENCE_LINE_VARIANT_INVALID"):
        reconcile_dk_event(
            ["PITCHER_K"], board(absent=[
                dict(absent("PITCHER_K"), line_variant="MAGIC_ODDS")]))


def test_repeat_market_with_same_dimensions_rejected_even_if_line_prices_differ():
    # This API audits *catalog contract families*, not individual prices.
    # Quoted lines/odds belong in immutable quote evidence, never an
    # independent second contract that manufactures market coverage.
    a = dict(offered("PITCHER_K", "TWO_SIDED_OU"), line=5.5, odds=-110)
    b = dict(offered("PITCHER_K", "TWO_SIDED_OU"), line=6.5, odds=+120)
    with pytest.raises(DKObservationError, match="DUPLICATE_MARKET_OBSERVATION"):
        reconcile_dk_event(["PITCHER_K"], board(observed=[a, b]))
