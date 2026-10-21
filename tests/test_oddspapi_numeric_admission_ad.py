"""Exact boundary tests for A and D numerical diagnostics, never admission."""
from copy import deepcopy
import pytest

from sportsedge.oddspapi_numeric_admission_ad import (
    VERSION, NumericAdmissionRefusal, evaluate_numeric_admission_dryrun,
)

HASH = "f" * 64


def sample(i=1):
    return {
        "sample_id": f"case_{i}",
        "dk": {
            "canonical_event_id": "MLB:event1",
            "market_id": "mlb_total",
            "bookmaker": "draftkings",
            "side": "OVER",
            "line": "8.5",
            "captured_at_utc": "2026-06-15T19:30:00Z",
            "american_price": -110,
            "source_sha256": "a"*64,
        },
        "oddspapi": {
            "canonical_event_id": "MLB:event1",
            "market_id": "mlb_total",
            "bookmaker": "draftkings",
            "side": "OVER",
            "line": "8.5",
            "captured_at_utc": "2026-06-15T19:00:00Z",
            "decimal_price": "1.9090909090909091",
            "source_sha256": "b"*64,
        },
    }


def close(i=1):
    return {
        "canonical_event_id": "MLB:event1",
        "market_id": "mlb_total",
        "bookmaker": "draftkings",
        "provider_created_at_utc": "2026-06-15T19:59:59Z",
        "candidate_sha256": f"{i:064x}",
        "actual_first_play": {
            "canonical_event_id": "MLB:event1",
            "actual_first_play_utc": "2026-06-15T20:00:00Z",
            "official_source_sha256": "c"*64,
        },
    }


def data(n=1):
    return {
        "version": VERSION,
        "dk_cohort_manifest_sha256": HASH,
        "dk_samples": [sample(i) for i in range(1, n+1)],
        "close_candidates": [close(i) for i in range(1, n+1)],
    }


def run(d):
    return evaluate_numeric_admission_dryrun(d)


def test_exact_a_30_minutes_passes_no_market_admission():
    d = data()
    report = run(d)
    assert report["check_A"]["rows"][0]["status"] == "PASS_NUMERIC_ONLY"
    assert report["check_A"]["rows"][0]["time_gap_seconds"] == 1800
    assert report["check_A"]["rows"][0]["american_price_difference"] == 0
    assert report["check_A"]["numeric_threshold_met_unverified"] is True
    assert report["check_D"]["numeric_threshold_met_unverified"] is True
    assert report["check_B"]["status"].startswith("NOT_EVALUATED")
    assert report["status"] == "NOT_ADMITTED_NUMERIC_DRYRUN"
    assert report["admission"] == "NOT_ADMITTED"
    assert not report["eligible"] and not report["play_authority"]
    assert not report["clock_started"] and not report["certified_close_authority"]
    assert report["source_cohort_independently_authenticated"] is False


def test_a_30_minutes_plus_one_second_fails():
    d = data()
    d["dk_samples"][0]["oddspapi"]["captured_at_utc"] = "2026-06-15T18:59:59Z"
    row = run(d)["check_A"]["rows"][0]
    assert row["reason"] == "A_QUOTE_OUTSIDE_30_MINUTES"


def test_a_price_plus_10_valid_and_plus_11_fails():
    d = data()
    d["dk_samples"][0]["dk"]["american_price"] = -120
    report = run(d)
    assert report["check_A"]["rows"][0]["american_price_difference"] == 10
    assert report["check_A"]["rows"][0]["status"] == "PASS_NUMERIC_ONLY"
    d["dk_samples"][0]["dk"]["american_price"] = -121
    row = run(d)["check_A"]["rows"][0]
    assert row["american_price_difference"] == 11
    assert row["reason"] == "A_AMERICAN_PRICE_DIFFERENCE_GT_10"


def test_a_line_mismatch_fails_even_if_rounded_same_book_price():
    d = data()
    d["dk_samples"][0]["oddspapi"]["line"] = "9.0"
    row = run(d)["check_A"]["rows"][0]
    assert row["reason"] == "A_LINE_NOT_EXACT"
    d["dk_samples"][0]["oddspapi"]["line"] = "8.50"
    row = run(d)["check_A"]["rows"][0]
    assert row["line_exact"] and row["status"] == "PASS_NUMERIC_ONLY"


@pytest.mark.parametrize("key,val", [
    ("canonical_event_id", "MLB:different"),
    ("market_id", "moneyline"),
    ("side", "UNDER"),
    ("bookmaker", "pinnacle"),
])
def test_a_wrong_identity_or_book_never_matches(key,val):
    d = data()
    d["dk_samples"][0]["oddspapi"][key] = val
    if key == "bookmaker":
        with pytest.raises(NumericAdmissionRefusal, match="A_REQUIRES_EXACT_DK_BOOK"):
            run(d)
    else:
        row = run(d)["check_A"]["rows"][0]
        assert row["reason"] == "A_FIXTURE_MARKET_SIDE_BOOK_MISMATCH"


def test_95_of_100_exactly_meets_rate_94_fails_and_denominator_unshrunk():
    d = data(100)
    for i in range(5):
        d["dk_samples"][i]["dk"]["american_price"] = -121
    report = run(d)
    assert report["check_A"]["passed"] == 95
    assert report["check_A"]["failed"] == 5
    assert report["check_A"]["observed_match_rate"] == "0.95"
    assert report["check_A"]["numeric_threshold_met_unverified"]
    assert report["admission"] == "NOT_ADMITTED"
    d["dk_samples"][5]["dk"]["american_price"] = -121
    report = run(d)
    assert report["check_A"]["passed"] == 94
    assert report["check_A"]["observed_match_rate"] == "0.94"
    assert not report["check_A"]["numeric_threshold_met_unverified"]


def test_unpaired_dk_sample_counted_as_failure_not_filtered():
    d = data(20)
    d["dk_samples"][0]["oddspapi"] = None
    out = run(d)
    assert out["check_A"]["sample_count"] == 20
    assert out["check_A"]["passed"] == 19
    assert out["check_A"]["rows"][0]["reason"] == "A_UNPAIRED_SAMPLE"
    assert out["check_A"]["numeric_threshold_met_unverified"]


def test_d_one_second_prestart_passes_at_first_play_fails():
    d = data()
    assert run(d)["check_D"]["numeric_threshold_met_unverified"]
    d["close_candidates"][0]["provider_created_at_utc"] = "2026-06-15T20:00:00Z"
    result = run(d)
    assert result["check_D"]["rows"][0]["reason"] == "D_CLOSE_AT_OR_AFTER_FIRST_PLAY"
    assert result["check_D"]["observed_prestart_rate"] == "0"
    assert not result["check_D"]["numeric_threshold_met_unverified"]


def test_d_actual_start_not_scheduled_start_must_be_used():
    d = data()
    d["close_candidates"][0]["actual_first_play"][
        "actual_first_play_utc"] = "2026-06-15T19:58:00Z"
    assert run(d)["check_D"]["rows"][0]["reason"] == "D_CLOSE_AT_OR_AFTER_FIRST_PLAY"


def test_d_99_of_100_fails_strict_100_percent():
    d = data(100)
    d["close_candidates"][34]["provider_created_at_utc"] = "2026-06-15T20:01:00Z"
    r = run(d)
    assert r["check_D"]["passed"] == 99
    assert r["check_D"]["observed_prestart_rate"] == "0.99"
    assert not r["check_D"]["numeric_threshold_met_unverified"]
    assert r["admission"] == "NOT_ADMITTED"


def test_d_missing_actual_start_never_inferred_from_scheduled():
    d = data()
    d["close_candidates"][0]["actual_first_play"] = None
    assert run(d)["check_D"]["rows"][0]["reason"] == (
        "D_INDEPENDENT_ACTUAL_FIRST_PLAY_NOT_SUPPLIED")


def test_d_cross_fixture_actual_start_fails():
    d = data()
    d["close_candidates"][0]["actual_first_play"][
        "canonical_event_id"] = "MLB:other"
    assert run(d)["check_D"]["rows"][0]["reason"] == (
        "D_ACTUAL_START_EVENT_MISMATCH")


def test_d_duplicate_receipts_refused_without_100_percent_claim():
    d = data(2)
    d["close_candidates"][1]["candidate_sha256"] = (
        d["close_candidates"][0]["candidate_sha256"])
    with pytest.raises(NumericAdmissionRefusal,match="D_DUPLICATE_CLOSE_RECEIPT"):
        run(d)


def test_a_duplicate_samples_refused_not_double_counted():
    d = data(2)
    d["dk_samples"][1]["sample_id"] = d["dk_samples"][0]["sample_id"]
    with pytest.raises(NumericAdmissionRefusal, match="A_DUPLICATE_SAMPLE_ID"):
        run(d)


@pytest.mark.parametrize("flag", [
    "owner_approved", "market_admitted", "B_passed", "verification_complete",
    "independent_source_verified",
])
def test_spoofed_authority_not_accepted(flag):
    d = data()
    d[flag] = True
    with pytest.raises(NumericAdmissionRefusal,match="DRYRUN_FIXED_SCHEMA_REQUIRED"):
        run(d)


@pytest.mark.parametrize("field", ["dk_samples", "close_candidates"])
def test_empty_cohort_cannot_vacuously_pass(field):
    d = data()
    d[field] = []
    with pytest.raises(NumericAdmissionRefusal, match="NONEMPTY"):
        run(d)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "not-a-number", None])
def test_nonfinite_or_missing_price_refuses(bad):
    d = data()
    d["dk_samples"][0]["oddspapi"]["decimal_price"] = bad
    with pytest.raises(NumericAdmissionRefusal):
        run(d)


def test_invalid_bool_price_and_unhashable_side_refuse():
    d = data()
    d["dk_samples"][0]["dk"]["american_price"] = True
    with pytest.raises(NumericAdmissionRefusal,match="DK_AMERICAN_PRICE_INVALID"):
        run(d)
    d = data()
    d["dk_samples"][0]["oddspapi"]["side"] = ["OVER"]
    with pytest.raises(NumericAdmissionRefusal,match="QUOTE_SIDE_UNKNOWN"):
        run(d)


def test_source_hash_shape_is_not_proof_of_independence():
    d = data()
    r = run(d)
    assert r["dk_cohort_manifest_sha256"] == HASH
    assert r["actual_first_play_independently_authenticated"] is False
    assert r["source_cohort_independently_authenticated"] is False
    assert r["SBR_archive_evidence_authenticated"] is False


def test_no_implicit_b_pass_through_a_and_d_green():
    d = data()
    r = run(d)
    assert r["check_A"]["numeric_threshold_met_unverified"] is True
    assert r["check_D"]["numeric_threshold_met_unverified"] is True
    assert r["check_B"]["numeric_threshold_met"] is False
    assert r["check_B"]["owner_frozen_policy_present"] is False
    assert r["admission"] == "NOT_ADMITTED"


def test_multiple_reads_do_not_mutate_payload():
    d = data()
    orig = deepcopy(d)
    assert run(d) == run(d)
    assert d == orig
