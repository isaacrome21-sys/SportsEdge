"""No-network tests for Rocky's posted SBR NBA Check B section-3 bars.

All observations are synthetic; no SBR/OddsPapi data, admission, or verified
close prices are asserted by passing these arithmetic checks.
"""
from copy import deepcopy
import pytest

from sportsedge.oddspapi_sbr_check_b_dryrun import (
    VERSION, SBRCheckBRefusal, inspect_sbr_check_b_dryrun,
)


def sample(i, market="MONEYLINE"):
    season_start = 2022 + i // 50
    season = f"{season_start}-{(season_start+1)%100:02d}"
    start = (f"2026-04-10T19:{i%60:02d}:00Z"
             if i >= 196 else f"{season_start+1}-03-15T19:00:00Z")
    return {
        "game_id": f"NBA_{i:04d}",
        "season": season,
        "game_start_utc": start,
        "side": "HOME" if market != "TOTAL" else "OVER",
        "sbr_bookmaker": "draftkings",
        "oddspapi_bookmaker": "draftkings",
        "sbr_close": {
            "american_price": -110 if market == "MONEYLINE" else None,
            "line": None if market == "MONEYLINE" else "5.5"},
        "oddspapi_candidate": {
            "american_price": -110 if market == "MONEYLINE" else None,
            "line": None if market == "MONEYLINE" else "5.5"},
        "sbr_receipt_sha256": "a"*64,
        "oddspapi_receipt_sha256": "b"*64,
    }


def cohort(market="MONEYLINE", n=200):
    return {
        "version": VERSION, "league": "NBA", "market": market,
        "bookmaker": "draftkings",
        "cohort": {
            "most_recent_complete_season": "2025-26",
            "final_week_start_utc": "2026-04-07T00:00:00Z",
            "final_week_end_utc": "2026-04-14T23:00:00Z",
            "final_week_game_ids": ["NBA_0196", "NBA_0197",
                                    "NBA_0198", "NBA_0199"],
            "official_schedule_snapshot_sha256": "c"*64,
            "archive_manifest_sha256": "d"*64,
        },
        "samples": [sample(i, market) for i in range(n)],
    }


def run(doc):
    return inspect_sbr_check_b_dryrun(doc)


@pytest.mark.parametrize("market", ["MONEYLINE", "SPREAD", "TOTAL"])
def test_perfect_200_game_four_season_cohort_is_still_not_admitted(market):
    r = run(cohort(market))
    assert r["observed_distinct_games"] == 200
    assert r["cohort_comparison_denominator"] == 200
    assert r["seasons_count"] == 4
    assert r["final_week_missing_games"] == 0
    assert r["numeric_b_bar_met_UNVERIFIED"] is True
    assert r["admission"] == "NOT_ADMITTED"
    assert r["status"] == "NOT_ADMITTED_UNPINNED_B_DRYRUN"
    assert r["source_policy_repo_sha256"] is None
    assert r["SBR_archive_independently_authenticated"] is False
    assert r["true_close_proven"] is False
    assert not r["source_eligible"] and not r["play_authority"]


def test_ml_194_of_200_exactly_97pct_passes_193_fails():
    d = cohort()
    for i in range(6):
        d["samples"][i]["oddspapi_candidate"]["american_price"] = -121
    r = run(d)
    assert r["bar_details"]["ml_within_10_american"] == 194
    assert r["bar_details"]["ml_observed_rate"] == "0.97"
    assert r["numeric_b_bar_met_UNVERIFIED"] is True
    assert r["admission"] == "NOT_ADMITTED"
    d["samples"][6]["oddspapi_candidate"]["american_price"] = -121
    r = run(d)
    assert r["bar_details"]["ml_observed_rate"] == "0.965"
    assert not r["market_numeric_requirement_met_unverified"]


def test_ml_price_delta_10_valid_11_invalid():
    d = cohort()
    d["samples"][0]["oddspapi_candidate"]["american_price"] = -120
    assert run(d)["row_results"][0]["status"] == "PASS_NUMERIC_ONLY"
    d["samples"][0]["oddspapi_candidate"]["american_price"] = -121
    r = run(d)
    assert r["row_results"][0]["reason"] == "B_MONEYLINE_PRICE_GAP_OVER_10"


@pytest.mark.parametrize("market", ["SPREAD", "TOTAL"])
def test_exact_95_and_within_half_99_on_boundary(market):
    d = cohort(market)
    for i in range(8):
        d["samples"][i]["oddspapi_candidate"]["line"] = "6.0"
    for i in range(8, 10):
        d["samples"][i]["oddspapi_candidate"]["line"] = "6.25"
    r = run(d)
    assert r["bar_details"]["line_exact"] == 190
    assert r["bar_details"]["line_observed_exact_rate"] == "0.95"
    assert r["bar_details"]["line_within_half"] == 198
    assert r["bar_details"]["line_observed_within_half_rate"] == "0.99"
    assert r["bar_details"]["line_gap_gt_one_game_count"] == 0
    assert r["numeric_b_bar_met_UNVERIFIED"]
    d["samples"][10]["oddspapi_candidate"]["line"] = "6.25"
    r = run(d)
    assert r["bar_details"]["line_observed_within_half_rate"] == "0.985"
    assert not r["market_numeric_requirement_met_unverified"]


@pytest.mark.parametrize("market", ["SPREAD", "TOTAL"])
def test_no_game_may_exceed_one_point_even_if_99pct_near_match(market):
    d = cohort(market)
    d["samples"][0]["oddspapi_candidate"]["line"] = "7.0"
    r = run(d)
    assert r["bar_details"]["line_gap_gt_one_game_count"] == 1
    assert not r["market_numeric_requirement_met_unverified"]
    assert r["row_results"][0]["reason"] == "B_LINE_GAP_GT_1"
    d["samples"][0]["oddspapi_candidate"]["line"] = "6.5"
    r = run(d)
    assert r["bar_details"]["line_gap_gt_one_game_count"] == 0
    assert r["market_numeric_requirement_met_unverified"]


def test_missing_sbr_close_is_counted_not_dropped():
    d = cohort()
    d["samples"][0]["sbr_close"] = None
    r = run(d)
    assert r["cohort_comparison_denominator"] == 200
    assert r["sample_games_submitted"] == 200
    assert r["missing_sbr_close_or_provider_quote"] == 1
    assert r["bar_details"]["ml_within_10_american"] == 199
    assert r["row_results"][0]["reason"] == "B_MISSING_CLOSE_OR_PROVIDER_QUOTE"


def test_missing_final_week_game_counts_as_denominator_failure():
    d = cohort()
    d["samples"].pop()
    r = run(d)
    assert r["sample_games_submitted"] == 199
    assert r["cohort_comparison_denominator"] == 200
    assert r["final_week_missing_games"] == 1
    assert r["final_week_sampled_game_count"] == 3
    assert r["cohort_numeric_requirement_met_unverified"] is False
    assert r["numeric_b_bar_met_UNVERIFIED"] is False


def test_199_observed_games_does_not_pass_even_if_pct_100():
    d = cohort()
    d["samples"].pop(0)
    r = run(d)
    assert r["observed_distinct_games"] == 199
    assert r["numeric_b_bar_met_UNVERIFIED"] is False


def test_three_seasons_cannot_fake_four_season_requirement():
    d = cohort()
    for i in range(50):
        d["samples"][i]["season"] = "2023-24"
    r = run(d)
    assert r["seasons_count"] == 3
    assert not r["cohort_numeric_requirement_met_unverified"]


@pytest.mark.parametrize("book", [None, "unknown", "fanduel", "", ["draftkings"]])
def test_unidentified_bookmaker_counts_as_failure_not_skip(book):
    d = cohort()
    d["samples"][0]["sbr_bookmaker"] = book
    r = run(d)
    assert r["cohort_comparison_denominator"] == 200
    assert r["sbr_book_identity_missing_or_wrong"] == 1
    assert r["row_results"][0]["reason"] == "B_EXPLICIT_DK_BOOK_IDENTITIES_REQUIRED"
    assert r["numeric_b_bar_met_UNVERIFIED"] is False


@pytest.mark.parametrize("field", ["market_admitted", "owner_approved",
                                     "SBR_independently_verified", "B_passed"])
def test_input_metadata_cannot_confer_admission(field):
    d = cohort()
    d[field] = True
    with pytest.raises(SBRCheckBRefusal, match="UNPINNED_B_DRYRUN_SCHEMA_ONLY"):
        run(d)


def test_duplicate_game_cannot_swell_denominator():
    d = cohort()
    d["samples"].append(deepcopy(d["samples"][0]))
    with pytest.raises(SBRCheckBRefusal,
                       match="B_DUPLICATE_GAME_WOULD_DOUBLE_COUNT"):
        run(d)


def test_no_unpinned_final_week_arbitrary_empty_roster():
    d = cohort()
    d["cohort"]["final_week_game_ids"] = []
    with pytest.raises(SBRCheckBRefusal,
                       match="FINAL_WEEK_SCHEDULE_REQUIRED"):
        run(d)


def test_final_week_game_wrong_season_or_outside_window_refused():
    d = cohort()
    d["samples"][196]["season"] = "2024-25"
    with pytest.raises(SBRCheckBRefusal,match="B_FINAL_WEEK_FIXTURE_SEASON_WINDOW_MISMATCH"):
        run(d)
    d = cohort()
    d["samples"][196]["game_start_utc"] = "2026-04-06T20:00:00Z"
    with pytest.raises(SBRCheckBRefusal,match="B_FINAL_WEEK_FIXTURE_SEASON_WINDOW_MISMATCH"):
        run(d)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "invalid", True, []])
def test_unsafe_spread_line_shapes_refused(bad):
    d = cohort("TOTAL")
    d["samples"][0]["sbr_close"]["line"] = bad
    with pytest.raises(SBRCheckBRefusal):
        run(d)


def test_malformed_season_syntax_refused():
    d = cohort()
    d["samples"][0]["season"] = "2022-25"
    with pytest.raises(SBRCheckBRefusal,match="NBA_SEASON_ID_INVALID"):
        run(d)


def test_sha_shaped_sources_cannot_certify_archive_or_schedule():
    d = cohort()
    r = run(d)
    assert r["official_schedule_snapshot_sha256_shape_only"] == "c"*64
    assert r["archive_manifest_sha256_shape_only"] == "d"*64
    assert r["official_schedule_independently_authenticated"] is False
    assert r["SBR_archive_independently_authenticated"] is False
    assert r["OddsPapi_quote_independently_authenticated"] is False
    assert not r["true_close_proven"]


def test_no_input_mutation_and_deterministic_arithmetic():
    d = cohort()
    original = deepcopy(d)
    assert run(d) == run(d)
    assert d == original
