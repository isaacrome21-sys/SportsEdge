"""Derived F5 read-out tests (matrix M14/M15). Offline fixtures only.

Proves sportsedge.f5_derived_readouts: the read-outs the backtest
matrix recorded as missing now exist over the shared F5 joint --
the Both-Teams-to-Score ladder (YES/NO per rung, monotone in the
rung, sides partitioning the posterior), Winning Margin bands and
Correct Score cells (Jeffreys-stabilized over the quoted partition,
cells summing to one) -- with the selection grammars shared by the
settlement code in sportsedge.mlb_additional_pit_joiner, whose
outcomes are proven against facts["f5"] here.
"""
from __future__ import annotations

import pytest

from sportsedge.f5_derived_readouts import (
    F5DerivedReadoutError,
    margin_band_selection,
    margin_bands_partition,
    parse_btts_rung,
    parse_correct_score_selection,
    parse_margin_band,
    read_f5_btts_probability,
    read_f5_correct_score_probability,
    read_f5_winning_margin_probability,
)
from sportsedge.f5_distribution import build_f5_distribution


def _features(n=16):
    return {
        "away_f5_runs_for": [(i % 5) for i in range(n)],
        "away_f5_runs_against": [(i + 1) % 4 for i in range(n)],
        "home_f5_runs_for": [(i + 2) % 5 for i in range(n)],
        "home_f5_runs_against": [i % 4 for i in range(n)],
        "league_f5_pmf": {"0": 0.28, "1": 0.24, "2": 0.18, "3": 0.12,
                          "4": 0.08, "5": 0.05, "6": 0.03, "7": 0.02},
        "league_prior_halves": 4000,
        "league_prior_strength": 30,
    }


def _dist():
    return build_f5_distribution(_features(), league_prior_strength=30)


MARGIN_PARTITION = ["AWAY_BY_3_PLUS", "AWAY_BY_2", "AWAY_BY_1", "TIE",
                    "HOME_BY_1", "HOME_BY_2", "HOME_BY_3_PLUS"]


# ------------------------------------------------------------- BTTS (M14)

def test_btts_yes_no_partition_and_monotone_rungs():
    dist = _dist()
    previous = 1.0
    for rung in (1, 2, 3):
        yes = read_f5_btts_probability(dist, line=rung, side="YES")
        no = read_f5_btts_probability(dist, line=rung, side="NO")
        assert yes.probability + no.probability == pytest.approx(1.0, abs=1e-9)
        assert yes.push_probability == 0.0
        assert yes.probability < previous  # stricter rung, smaller mass
        previous = yes.probability
    assert previous > 0.0


def test_btts_rung_grammar():
    assert parse_btts_rung(1) == 1
    assert parse_btts_rung(7.0) == 7
    for bad in (0, 8, 2.5, "x", None, True):
        with pytest.raises(F5DerivedReadoutError):
            parse_btts_rung(bad)
    with pytest.raises(F5DerivedReadoutError):
        read_f5_btts_probability(_dist(), line=1, side="OVER")


# ------------------------------------------------------- margin (M15)

def test_margin_grammar_round_trips():
    for text in MARGIN_PARTITION:
        assert margin_band_selection(parse_margin_band(text)) == text
    assert parse_margin_band("TIED").team is None
    with pytest.raises(F5DerivedReadoutError):
        parse_margin_band("HOME_BY_0")  # a zero margin is TIE
    with pytest.raises(F5DerivedReadoutError):
        parse_margin_band("HOME_BY_2_MINUS")
    with pytest.raises(F5DerivedReadoutError):
        parse_margin_band("AWAY")


def test_margin_partition_verification():
    bands = [parse_margin_band(s) for s in MARGIN_PARTITION]
    assert margin_bands_partition(bands)
    # Missing the +infinity tail.
    assert not margin_bands_partition(bands[:-1])
    # Missing the -infinity tail.
    assert not margin_bands_partition(bands[1:])
    # A gap at zero (no TIE).
    assert not margin_bands_partition(
        [b for b in bands if b.team is not None])
    # An overlap (AWAY_BY_1_PLUS already covers the AWAY_BY_1 cell).
    overlap = [parse_margin_band(s) for s in (
        "AWAY_BY_1_PLUS", "AWAY_BY_1", "TIE",
        "HOME_BY_1", "HOME_BY_2", "HOME_BY_3_PLUS")]
    assert not margin_bands_partition(overlap)
    # A coarser but complete partition also verifies.
    coarse = [parse_margin_band(s) for s in (
        "AWAY_BY_1_PLUS", "TIE", "HOME_BY_1_PLUS")]
    assert margin_bands_partition(coarse)


def test_margin_readouts_sum_to_one_over_partition():
    dist = _dist()
    total = sum(
        read_f5_winning_margin_probability(
            dist, partition=MARGIN_PARTITION, selection=s).probability
        for s in MARGIN_PARTITION)
    assert total == pytest.approx(1.0, abs=1e-9)
    tie = read_f5_winning_margin_probability(
        dist, partition=MARGIN_PARTITION, selection="TIE")
    assert 0.0 < tie.probability < 1.0
    assert tie.push_probability == 0.0
    with pytest.raises(F5DerivedReadoutError):
        read_f5_winning_margin_probability(
            dist, partition=MARGIN_PARTITION[:-1], selection="TIE")
    with pytest.raises(F5DerivedReadoutError):
        read_f5_winning_margin_probability(
            dist, partition=MARGIN_PARTITION, selection="HOME_BY_9")


# -------------------------------------------------- correct score (M15)

def test_correct_score_grammar():
    assert parse_correct_score_selection("AWAY_3_HOME_2") == ("CELL", 3, 2)
    assert parse_correct_score_selection("OTHER") == ("ANY_OTHER",)
    with pytest.raises(F5DerivedReadoutError):
        parse_correct_score_selection("3-2")
    with pytest.raises(F5DerivedReadoutError):
        parse_correct_score_selection("HOME_2_AWAY_3")


def test_correct_score_readouts_sum_to_one_with_catch_all():
    dist = _dist()
    partition = ["AWAY_0_HOME_0", "AWAY_1_HOME_1", "AWAY_2_HOME_2", "ANY_OTHER"]
    total = sum(
        read_f5_correct_score_probability(
            dist, partition=partition, selection=s).probability
        for s in partition)
    assert total == pytest.approx(1.0, abs=1e-9)
    # The catch-all carries every unlisted cell: the bulk of the mass.
    other = read_f5_correct_score_probability(
        dist, partition=partition, selection="ANY_OTHER")
    assert other.probability > 0.5
    with pytest.raises(F5DerivedReadoutError):
        read_f5_correct_score_probability(
            dist, partition=partition[:-1], selection="AWAY_0_HOME_0")


# ------------------------------------------------------------- session

def test_derived_session_matches_f5_distribution_identity():
    from sportsedge.shared_f5_derived_engine import (
        SharedF5DerivedEngineError, build_shared_f5_derived_engine_session)
    from sportsedge.shared_f5_engine import build_shared_f5_engine_session
    features = _features()
    derived = build_shared_f5_derived_engine_session()
    out = derived({
        "game_id": "777002", "market": "F5_BOTH_TEAMS_TO_SCORE",
        "entity_id": "777002", "line": 2, "side": "YES",
        "features": features, "feature_source_hash": "abc123",
    })
    assert 0.0 < out["model_p"] < 1.0
    assert out["push_p"] == 0.0
    assert len(out["readout_sha256"]) == 64
    # The derived session reads the SAME joint state as the F5
    # session: identical distribution identity for identical features.
    f5_out = build_shared_f5_engine_session()({
        "game_id": "777002", "market": "F5_TOTALS",
        "entity_id": "777002", "line": 4.5, "side": "OVER",
        "features": features, "feature_source_hash": "abc123",
    })
    assert out["distribution_sha256"] == f5_out["distribution_sha256"]
    margin = derived({
        "game_id": "777002", "market": "F5_WINNING_MARGIN",
        "entity_id": "777002", "line": None, "side": "TIE",
        "partition": MARGIN_PARTITION,
        "features": features, "feature_source_hash": "abc123",
    })
    assert margin["distribution_sha256"] == out["distribution_sha256"]
    with pytest.raises(SharedF5DerivedEngineError):
        derived({
            "game_id": "777002", "market": "F5_TOTALS",
            "entity_id": "777002", "line": 4.5, "side": "OVER",
            "features": features, "feature_source_hash": "abc123",
        })


# ------------------------------------------------------------ settlement

def test_joiner_settles_derived_f5_markets_from_facts():
    from sportsedge.mlb_additional_pit_joiner import (
        MLBPITJoinError, _derive_outcome)
    facts = {"f5": {"away_runs": 3, "home_runs": 1}}
    assert _derive_outcome(facts, "F5_BOTH_TEAMS_TO_SCORE", "777002",
                           1, "YES") == "WIN"
    assert _derive_outcome(facts, "F5_BOTH_TEAMS_TO_SCORE", "777002",
                           2, "YES") == "LOSS"
    assert _derive_outcome(facts, "F5_BOTH_TEAMS_TO_SCORE", "777002",
                           2, "NO") == "WIN"
    assert _derive_outcome(facts, "F5_WINNING_MARGIN", "777002",
                           None, "AWAY_BY_2") == "WIN"
    assert _derive_outcome(facts, "F5_WINNING_MARGIN", "777002",
                           None, "HOME_BY_1") == "LOSS"
    assert _derive_outcome(facts, "F5_WINNING_MARGIN", "777002",
                           None, "TIE") == "LOSS"
    assert _derive_outcome(facts, "F5_CORRECT_SCORE", "777002",
                           None, "AWAY_3_HOME_1") == "WIN"
    assert _derive_outcome(facts, "F5_CORRECT_SCORE", "777002",
                           None, "AWAY_1_HOME_3") == "LOSS"
    # ANY_OTHER cannot settle from a single row: it is the complement
    # of a selection set the row does not carry. Fail closed by name.
    with pytest.raises(MLBPITJoinError, match="ANY_OTHER_REQUIRES_SELECTION_SET"):
        _derive_outcome(facts, "F5_CORRECT_SCORE", "777002",
                        None, "ANY_OTHER")
    # Missing F5 facts fail closed in the settlement code itself.
    with pytest.raises(MLBPITJoinError, match="F5_FACTS_MISSING"):
        _derive_outcome({}, "F5_BOTH_TEAMS_TO_SCORE", "777002", 1, "YES")
    # A garbage margin selection refuses by name, never guesses.
    with pytest.raises(MLBPITJoinError, match="SELECTION_INVALID"):
        _derive_outcome(facts, "F5_WINNING_MARGIN", "777002",
                        None, "HOME_BY_LOTS")
