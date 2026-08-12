from sportsedge.auto_runner import _blocked, _convert
from sportsedge.decision_ledger import build_decision_ledger, reconciliation_status
from sportsedge.unified_card import UnifiedCardResult


def test_valid_final_card_preserves_exact_book_key():
    raw = UnifiedCardResult(
        game_id="123",
        market="MONEYLINE",
        entity_id="",
        line=None,
        side="HOME",
        american_odds=110,
        model_p=0.57,
        bet_status="OFFICIAL_BET",
        reason="TRUTH_GATE_PASS",
    )
    result = _convert(0, raw, book_key="draftkings")
    assert result.book_key == "draftkings"


def test_blocked_malformed_quote_gets_non_executable_missing_book_sentinel():
    result = _blocked(0, {"game_id": "123", "market": "MONEYLINE"}, "QUOTE_IDENTITY_INCOMPLETE")
    assert result.book_key == "MISSING"


def test_missing_or_sentinel_book_never_becomes_execution_ready():
    base = {
        "slate_date_ct": "2026-08-12",
        "generated_at_utc": "2026-08-12T15:00:00+00:00",
        "run_status": "PASS",
        "results": [{
            "source_index": 0,
            "game_id": "123",
            "market": "MONEYLINE",
            "entity_id": "",
            "line": None,
            "side": "HOME",
            "american_odds": 110,
            "model_p": 0.57,
            "bet_status": "OFFICIAL_BET",
            "reason": "TRUTH_GATE_PASS",
            "book_key": "MISSING",
        }],
    }
    row = build_decision_ledger(base, run_id="run-1")["decisions"][0]
    assert row["execution_ready"] is False
    assert row["wager_key"] is None
    assert row["reconciliation_status"] == "LEGACY_BOOK_UNKNOWN"
    assert row["book_key"] == "LEGACY_BOOK_UNKNOWN"


def test_pre_v2_rows_are_explicitly_irreconcilable_for_clv_and_execution():
    old_row = {
        "game_id": "123",
        "market": "TOTALS",
        "entity_id": "",
        "line": 8.5,
        "side": "OVER",
        "american_odds": -110,
    }
    assert reconciliation_status(old_row, schema_version="sportsedge_decision_ledger_v1") == "LEGACY_BOOK_UNKNOWN"
