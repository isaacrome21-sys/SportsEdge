"""Offline contracts for the strict paired historical evaluation surface.

Synthetic fixtures test evidence checking, not sports forecasting skill.
"""
from datetime import datetime, timedelta, timezone

from sportsedge.backtest.strict_paired_oos import evaluate


START = datetime(2024, 4, 8, 23, tzinfo=timezone.utc)


def row(i=0, *, winner=1, **overrides):
    kick = START + timedelta(days=i)
    payload = {
        "fixture_id": "mlb:2024-04-%02d:Away:Home" % (8 + i),
        "series_id": "series_%03d" % i,
        "market": "TOTAL", "selection": "OVER", "opposite_selection": "UNDER",
        "line": 6.5,
        "kickoff_utc": kick.isoformat(),
        "as_of_utc": (kick - timedelta(hours=2)).isoformat(),
        "feature_max_available_at_utc": (kick - timedelta(hours=3)).isoformat(),
        "train_last_final_at_utc": (kick - timedelta(days=1)).isoformat(),
        "model_source_sha": "a" * 40, "market_blind": True,
        "candidate_p": 0.80 if winner else 0.20,
        "existing_p": 0.60 if winner else 0.40,
        "outcome": winner,
        "market_book": "draftkings", "opposite_book": "draftkings",
        "market_yes_american": -110, "market_no_american": -110,
        "market_yes_captured_at_utc": (kick - timedelta(minutes=5)).isoformat(),
        "market_no_captured_at_utc": (kick - timedelta(minutes=5)).isoformat(),
    }
    payload.update(overrides)
    return payload


def readout(payload):
    return evaluate(payload, min_games=20, min_series=20, bootstrap_reps=120)


def test_empty_archive_cannot_create_edges():
    result = readout([])
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert "NO_HISTORICAL_RECORDS" in result["reasons"]


def test_untimestamped_historical_market_rows_fail_closed():
    result = readout([row(market_yes_captured_at_utc=None)])
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["reject_reasons"]["MISSING_PIT_EVIDENCE"] == 1


def test_legacy_report_cannot_be_mistaken_for_pit_evidence():
    legacy = {"fixture_id": "old", "candidate_p": .65,
              "existing_p": .50, "outcome": 1}
    result = readout([legacy])
    assert result["status"] == "BLOCKED_EVIDENCE"
    assert result["n_verified"] == 0


def test_both_outcomes_and_all_three_probabilities_share_identical_rows():
    inputs = [row(i, winner=i % 2) for i in range(30)]
    a = readout(inputs)
    b = readout(inputs)
    assert a == b
    assert a["status"] == "FORECAST_IMPROVEMENT_RESEARCH_ONLY"
    assert a["n_games"] == 30
    assert a["n_series"] == 30
    assert a["validated_profitability"] is False
    for quantity in a["paired_comparisons"].values():
        assert quantity["delta_candidate_minus_baseline"] < 0
        assert quantity["series_block_ci_95"][1] < 0


def test_losing_candidate_never_passes():
    inputs = [row(i, winner=i % 2,
                  candidate_p=.2 if i % 2 else .8) for i in range(30)]
    result = readout(inputs)
    assert result["status"] == "NO_DEMONSTRATED_FORECAST_IMPROVEMENT"


def test_partial_evidence_not_dropped_to_flatter_model():
    inputs = [row(i, winner=i % 2) for i in range(30)]
    del inputs[-1]["market_book"]
    r = readout(inputs)
    assert r["n_verified"] == 29
    assert r["n_rejected"] == 1
    assert r["status"] == "BLOCKED_EVIDENCE"


def test_started_or_asof_future_or_training_leakage_blocks():
    kick = START.isoformat()
    for bad in (
        {"as_of_utc": kick},
        {"feature_max_available_at_utc": kick},
        {"train_last_final_at_utc": kick},
    ):
        result = readout([row(**bad)])
        assert result["status"] == "BLOCKED_EVIDENCE"
        assert result["reject_reasons"]["PIT_TRAIN_OR_FEATURE_LEAKAGE"] == 1


def test_post_first_pitch_market_quotes_and_cross_book_pairs_block():
    started = readout([row(market_yes_captured_at_utc=START.isoformat())])
    assert started["reject_reasons"]["MARKET_QUOTE_NOT_PREGAME"] == 1
    cross_book = readout([row(opposite_book="Pinnacle")])
    assert cross_book["reject_reasons"]["BOOK_PAIR_MISMATCH"] == 1


def test_paired_quote_time_skew_is_rejected():
    out = readout([row(market_no_captured_at_utc=(
        START - timedelta(minutes=10)).isoformat())])
    assert out["reject_reasons"]["MARKET_PAIR_ASYNCHRONOUS"] == 1


def test_nontimestamped_result_and_push_are_not_binary_events():
    assert readout([row(outcome=.5)])["reject_reasons"]["BINARY_OUTCOME_REQUIRED_NO_PUSH"] == 1


def test_duplicate_game_and_model_revision_drift_block():
    base = row()
    dup = readout([base, dict(base)])
    assert dup["reject_reasons"]["DUPLICATE_GAME_MARKET_SELECTION_LINE"] == 1
    drift = readout([row(0), row(1, model_source_sha="b"*40)])
    assert drift["reasons"] == ["MODEL_SHA_NOT_FROZEN"]


def test_different_markets_must_be_separate_hypotheses():
    r = readout([row(0), row(1, market="ML", line="ML", selection="HOME",
                    opposite_selection="AWAY")])
    assert r["reasons"] == ["MARKET_MUST_BE_EVALUATED_SEPARATELY"]


def test_small_test_sample_stays_insufficient_even_with_all_wins():
    r = readout([row(i) for i in range(19)])
    assert r["status"] == "INSUFFICIENT_OOS"


def test_mathematical_ev_is_never_declared_validated_profit():
    r = readout([row(i, winner=i % 2) for i in range(30)])
    assert r["research_only"] and not r["validated_profitability"]
    assert r["authority"] == "NONE"
    assert not r["holdout_accessed"]
