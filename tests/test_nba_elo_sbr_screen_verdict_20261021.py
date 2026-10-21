"""A negative Elo sides research screen must never look like promotion."""
from scripts.research_nba_elo_sbr_dateonly_screen import _indicative_side_verdict


def test_historical_spread_and_moneyline_references_were_better():
    # Reproduced against pinned, date-only SBR blob. Values are indicative
    # and cannot establish an admitted market or PIT quote-vintage test.
    assert _indicative_side_verdict(13.452158989671467, 12.75111490119087) == (
        "FAILED_INDICATIVE_REFERENCE_NOT_A_CARD_SOURCE")
    assert _indicative_side_verdict(0.21755364573693664, 0.20669855671907594) == (
        "FAILED_INDICATIVE_REFERENCE_NOT_A_CARD_SOURCE")


def test_ties_are_not_evidence_of_outperformance():
    assert _indicative_side_verdict(0.2, 0.2).startswith("FAILED_")


def test_better_unadmitted_indicative_metric_remains_unadmitted():
    assert _indicative_side_verdict(0.19, 0.20) == (
        "BETTER_INDICATIVE_ONLY_SOURCE_NOT_ADMITTED")


def test_absent_reference_has_no_comparison():
    assert _indicative_side_verdict(None, 0.2) == "REFERENCE_UNMEASURED"
    assert _indicative_side_verdict(0.2, None) == "REFERENCE_UNMEASURED"
