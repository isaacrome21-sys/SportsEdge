import pytest

from sportsedge.mlb_bet_ledger import MLBBetLedgerError, summarize_ledger, validate_ledger_row


def _row(**overrides):
    row = {
        "game_id": "123",
        "market": "NRFI",
        "entity": "123",
        "side": "YES",
        "line": 0.5,
        "american_odds": -120,
        "sportsbook": "DraftKings",
        "observed_at_utc": "2026-08-20T20:00:00+00:00",
        "first_pitch_at_utc": "2026-08-20T22:00:00+00:00",
        "model_probability": .57,
        "fair_market_probability": .53,
        "raw_edge": .04,
        "confidence_multiplier": .75,
        "research_adjusted_edge": .03,
        "model_sha": "abc",
        "feature_contract_sha": "def",
        "lineup_state": "confirmed",
        "weather_state": "fresh",
        "umpire_state": "known",
        "conflict_flags": ["MODEL_DISAGREEMENT"],
    }
    row.update(overrides)
    return row


def test_ledger_row_requires_pregame_quote():
    with pytest.raises(MLBBetLedgerError, match="pregame"):
        validate_ledger_row(_row(observed_at_utc="2026-08-20T22:00:00+00:00"))


def test_ledger_row_reconciles_edges():
    parsed = validate_ledger_row(_row())
    assert parsed.raw_edge == pytest.approx(.04)
    assert parsed.research_adjusted_edge == pytest.approx(.03)
    assert parsed.selection_key


def test_ledger_row_rejects_invented_adjusted_edge():
    with pytest.raises(MLBBetLedgerError, match="research_adjusted_edge"):
        validate_ledger_row(_row(research_adjusted_edge=.07))


def test_summary_is_market_segmented():
    rows = [
        _row(result="WIN", outcome=1),
        _row(game_id="124", result="LOSS", outcome=0),
        _row(game_id="125", market="PITCHER_OUTS", entity="pitcher-1", side="UNDER",
             line=16.5, result="PUSH", outcome=.5),
    ]
    summary = summarize_ledger(rows)
    assert summary["settled"] == 3
    assert summary["by_market"]["NRFI"]["WIN"] == 1
    assert summary["by_market"]["NRFI"]["LOSS"] == 1
    assert summary["by_market"]["PITCHER_OUTS"]["PUSH"] == 1
