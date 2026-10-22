"""Historical SBR totals comparison is descriptive, never market admission."""
from scripts.research_nba_v2_sbr_dateonly_screen import _indicative_reference_verdict


def test_candidate_losing_reference_is_explicit_stop():
    assert _indicative_reference_verdict(18.977001389677067, 18.05123313379557) == (
        "FAILED_INDICATIVE_REFERENCE_NOT_A_CARD_SOURCE"
    )


def test_tie_is_not_outperformance():
    assert _indicative_reference_verdict(19.0, 19.0).startswith("FAILED_")


def test_better_indicative_number_still_no_admission():
    assert _indicative_reference_verdict(18.0, 19.0) == (
        "BETTER_INDICATIVE_ONLY_SOURCE_NOT_ADMITTED"
    )


def test_missing_price_has_no_benchmark_verdict():
    assert _indicative_reference_verdict(18.0, None) == "REFERENCE_UNMEASURED"
    assert _indicative_reference_verdict(None, 18.0) == "REFERENCE_UNMEASURED"
