import hashlib
import json

import pytest

from sportsedge.research.the_odds_api_historical_adapter import adapt_historical_response


def response():
    return {
        "timestamp": "2021-10-18T11:55:00Z",
        "previous_timestamp": "2021-10-18T11:45:00Z",
        "next_timestamp": "2021-10-18T12:05:00Z",
        "data": [
            {
                "id": "game-1",
                "sport_key": "americanfootball_nfl",
                "commence_time": "2021-10-19T00:15:00Z",
                "home_team": "Tennessee Titans",
                "away_team": "Buffalo Bills",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2021-10-18T11:48:09Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Buffalo Bills", "price": -294},
                                    {"name": "Tennessee Titans", "price": 230},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Buffalo Bills", "price": -110, "point": -5.5},
                                    {"name": "Tennessee Titans", "price": -110, "point": 5.5},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 53.5},
                                    {"name": "Under", "price": -110, "point": 53.5},
                                ],
                            },
                            {"key": "alternate_spreads", "outcomes": []},
                        ],
                    }
                ],
            }
        ],
    }


def test_documented_response_shape_yields_three_paired_rows():
    raw = json.dumps(response(), sort_keys=True).encode()
    req = {
        "sport": "americanfootball_nfl",
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "date": "2021-10-18T12:00:00Z",
    }
    rows = adapt_historical_response(
        response(), raw_bytes=raw, retrieved_at_utc="2026-09-13T14:00:00Z", request_identity=req
    )
    assert [r["market_family"] for r in rows] == ["moneyline", "spread", "game_total"]
    assert all(r["raw_byte_sha256"] == hashlib.sha256(raw).hexdigest() for r in rows)
    assert len({r["source_request_sha256"] for r in rows}) == 1
    assert all(r["sportsbook_inputs_allowed_in_model_fit"] is False for r in rows)


def test_book_update_after_snapshot_fails_closed():
    payload = response()
    payload["data"][0]["bookmakers"][0]["last_update"] = "2021-10-18T11:56:00Z"
    with pytest.raises(ValueError, match="cannot exceed"):
        adapt_historical_response(
            payload,
            raw_bytes=b"x",
            retrieved_at_utc="2026-09-13T14:00:00Z",
            request_identity={"date": "2021-10-18T12:00:00Z"},
        )


def test_empty_raw_bytes_block():
    with pytest.raises(ValueError, match="raw response bytes required"):
        adapt_historical_response(
            response(),
            raw_bytes=b"",
            retrieved_at_utc="2026-09-13T14:00:00Z",
            request_identity={"date": "2021-10-18T12:00:00Z"},
        )
