from sportsedge.decision_ledger import build_decision_ledger


def payload():
    return {
        "slate_date_ct": "2026-08-12",
        "generated_at_utc": "2026-08-12T15:00:00+00:00",
        "run_status": "PASS",
        "provider_status": [{"provider": "ODDS_API_NATIVE", "status": "PASS"}],
        "results": [
            {"source_index": 0, "game_id": "123", "market": "MONEYLINE", "entity_id": "", "line": None, "side": "HOME", "book_key": "draftkings", "american_odds": 110, "model_p": 0.57, "bet_status": "OFFICIAL_BET", "reason": "TRUTH_GATE_PASS"},
            {"source_index": 1, "game_id": "123", "market": "TOTALS", "entity_id": "", "line": 8.5, "side": "OVER", "book_key": "draftkings", "american_odds": -110, "model_p": 0.51, "bet_status": "PASS", "reason": "PRICE_OR_EDGE_GATE_NOT_MET"},
        ],
    }


def test_ledger_preserves_every_decision_and_verdict():
    ledger = build_decision_ledger(payload(), run_id="run-1")
    assert ledger["schema_version"] == "sportsedge_decision_ledger_v2"
    assert ledger["decision_count"] == 2
    assert [x["bet_status"] for x in ledger["decisions"]] == ["OFFICIAL_BET", "PASS"]
    assert ledger["decisions"][0]["execution_ready"] is True
    assert ledger["decisions"][1]["execution_ready"] is False


def test_decision_ids_are_deterministic_but_offer_specific():
    a = build_decision_ledger(payload(), run_id="run-1")
    b = build_decision_ledger(payload(), run_id="run-1")
    assert [x["decision_id"] for x in a["decisions"]] == [x["decision_id"] for x in b["decisions"]]
    assert a["decisions"][0]["decision_id"] != a["decisions"][1]["decision_id"]


def test_new_run_gets_new_decision_but_same_wager_key_even_if_price_moves():
    a = build_decision_ledger(payload(), run_id="run-1")
    moved = payload(); moved["results"][0]["american_odds"] = 105
    b = build_decision_ledger(moved, run_id="run-2")
    assert a["decisions"][0]["decision_id"] != b["decisions"][0]["decision_id"]
    assert a["decisions"][0]["wager_key"] == b["decisions"][0]["wager_key"]


def test_book_change_is_distinct_wager_key():
    a = build_decision_ledger(payload(), run_id="run-1")
    other = payload(); other["results"][0]["book_key"] = "fanduel"
    b = build_decision_ledger(other, run_id="run-2")
    assert a["decisions"][0]["wager_key"] != b["decisions"][0]["wager_key"]


def test_official_without_exact_book_is_not_execution_ready():
    p = payload(); del p["results"][0]["book_key"]
    ledger = build_decision_ledger(p, run_id="run-1")
    assert ledger["decisions"][0]["wager_key"] is None
    assert ledger["decisions"][0]["execution_ready"] is False
