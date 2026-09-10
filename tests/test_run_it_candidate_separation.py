import json

from sportsedge.run_it_control import _card_state


def _write_card(tmp_path, rows, *, run_status="SUCCESS"):
    path = tmp_path / "card.json"
    path.write_text(
        json.dumps({"report": {"run_status": run_status, "results": rows}}),
        encoding="utf-8",
    )
    return path


def test_candidate_only_card_is_success_not_all_markets_blocked(tmp_path):
    path = _write_card(
        tmp_path,
        [{
            "bet_status": "MODEL_CANDIDATE",
            "model_p": 0.584,
            "official_gate_status": "BLOCKED",
            "official_gate_reason": "PROP_EVIDENCE_REQUIRED",
        }],
    )

    status, blocker, model_rows, official_bets = _card_state(path, None)

    assert status == "SUCCESS"
    assert blocker is None
    assert model_rows == 1
    assert official_bets == 0


def test_true_blocked_rows_without_candidate_stay_blocked(tmp_path):
    path = _write_card(
        tmp_path,
        [{"bet_status": "BLOCKED", "reason": "NO_ENGINE"}],
    )

    status, blocker, model_rows, official_bets = _card_state(path, None)

    assert status == "BLOCKED"
    assert blocker == "ALL_MARKETS_BLOCKED"
    assert model_rows == 0
    assert official_bets == 0


def test_candidate_plus_true_blocker_is_partial(tmp_path):
    path = _write_card(
        tmp_path,
        [
            {"bet_status": "MODEL_CANDIDATE", "model_p": 0.58},
            {"bet_status": "BLOCKED", "reason": "NO_ENGINE"},
        ],
    )

    status, blocker, model_rows, official_bets = _card_state(path, None)

    assert status == "PARTIAL"
    assert blocker == "SOME_MARKETS_BLOCKED_OR_DEGRADED"
    assert model_rows == 1
    assert official_bets == 0


def test_official_bet_remains_counted(tmp_path):
    path = _write_card(
        tmp_path,
        [{"bet_status": "OFFICIAL_BET", "model_p": 0.61}],
    )

    status, blocker, model_rows, official_bets = _card_state(path, None)

    assert status == "SUCCESS"
    assert blocker is None
    assert model_rows == 1
    assert official_bets == 1
