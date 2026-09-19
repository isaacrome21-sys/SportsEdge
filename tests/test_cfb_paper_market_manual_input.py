import json
from datetime import datetime, timezone

from scripts.run_cfb_paper_market import build_payload, load_events


def _manual_board():
    return [
        {
            "id": "paper-game-1",
            "away_team": "Team A",
            "home_team": "Team B",
            "commence_time": "2099-09-19T18:00:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": 150},
                                {"name": "Team B", "price": -170},
                            ],
                        }
                    ],
                },
                {
                    "key": "fanduel",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": -110},
                                {"name": "Team B", "price": -110},
                            ],
                        }
                    ],
                },
                {
                    "key": "betmgm",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": -105},
                                {"name": "Team B", "price": -115},
                            ],
                        }
                    ],
                },
            ],
        }
    ]


def test_missing_market_input_emits_explicit_zero_authority_blocker():
    events, source, input_status = load_events("", inline_json="")
    payload = build_payload(
        events,
        0.02,
        datetime(2026, 9, 19, tzinfo=timezone.utc),
        source,
        input_status,
    )
    assert payload["status"] == "PAPER_ONLY"
    assert payload["input_status"] == "BLOCKED_NO_MARKET_INPUT"
    assert payload["market_input_source"] == "MARKET_INPUT_UNAVAILABLE"
    assert payload["candidates"] == []
    assert not any(payload["authority"].values())


def test_inline_manual_board_runs_same_consensus_logic_without_api_key():
    events, source, input_status = load_events("", inline_json=json.dumps(_manual_board()))
    payload = build_payload(
        events,
        0.02,
        datetime(2026, 9, 19, tzinfo=timezone.utc),
        source,
        input_status,
    )
    assert payload["input_status"] == "READY"
    assert payload["market_input_source"] == "MANUAL_JSON_INLINE"
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["side"] == "Team A"
    assert candidate["draftkings_odds"] == 150.0
    assert candidate["market_consensus_edge"] > 0.02
    assert candidate["market_consensus_ev_per_dollar"] > 0
    assert candidate["model_p"] is None
    assert candidate["official"] is False
    assert not any(payload["authority"].values())
