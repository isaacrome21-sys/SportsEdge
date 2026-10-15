"""Canonical CFB Collins-card registration proof, entirely synthetic.

This is a no-price gate test, NOT a real fixture, sportsbook line,
starter-status receipt, or evaluation attempt.
"""
from datetime import datetime, timezone

from artifacts.run_it_full import run_full
from sportsedge.registry_gate import PRICING_KEYS


def test_only_three_registered_collins_prop_rows_change_refusal_reason():
    def forbid_fetch(_url):
        raise AssertionError("blocked CFB player props must not fetch an engine")

    fixture = {
        "sport": "CFB",
        "lines": [
            {"market": "PLAYER_PASSING_YARDS", "player_name": "Rickie Collins",
             "line": 215.5, "side": "OVER"},
            {"market": "PLAYER_PASS_TDS", "player_name": "Rickie Collins",
             "line": 1.5, "side": "UNDER"},
            {"market": "PLAYER_PASS_INTERCEPTIONS", "player_name": "Rickie Collins",
             "line": 0.5, "side": "OVER"},
            # This offered-status-neutral placeholder is purposely engineless.
            {"market": "ANYTIME_TD", "player_name": "Other Synthetic Player",
             "line": 0.5, "side": "OVER"},
        ],
    }
    for row in fixture["lines"]:
        row.update({"home": "Kennesaw State", "away": "Missouri State",
                    "kickoff": "2026-10-17T23:00:00Z"})
    card = run_full(
        fixture, now=datetime(2026, 10, 14, 20, tzinfo=timezone.utc),
        auto_context=False, getter=forbid_fetch)
    rows = card["evaluated_rows"]
    assert len(rows) == 4
    assert [r["input_index"] for r in rows] == list(range(4))
    for row in rows[:3]:
        assert row["status"] == "NO_MODEL_OR_MARKET"
        assert row["blocker"] == "NO_VALIDATION"
        assert row["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")
        assert row["family_decision"]["evaluation_scope"] == "FORWARD_ONLY"
        assert row["registry_enforced"] is True
    assert rows[3]["status"] == "NO_MODEL_OR_MARKET"
    assert rows[3]["reason"].startswith("FAMILY_MARKET_UNREGISTERED")
    assert rows[3]["blocker"] == "NO_ENGINE"
    assert rows[3]["family_decision"]["evaluation_scope"] == "UNREGISTERED"
    assert all(not (PRICING_KEYS & r.keys()) for r in rows)
    assert all(r["staking_authority"] is False for r in rows)
    assert len(card["prop_unpriced"]) == 4
    assert card["prop_candidates"] == []
    assert card["prop_watchlist"] == []
