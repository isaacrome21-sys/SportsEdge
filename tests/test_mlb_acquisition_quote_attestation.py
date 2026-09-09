from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from sportsedge.game_odds_source import parse_game_event_odds
from sportsedge.mlb_quote_attestation import QuoteAttestationError, validate_acquisition_quote
from sportsedge.mlb_source import GameSnapshot
from sportsedge.quote_bridge import validate_canonical_quote


def _game() -> GameSnapshot:
    return GameSnapshot(
        game_pk=777001,
        game_date="2026-09-08T23:10:00Z",
        status="Scheduled",
        away_id=111,
        away_name="Chicago Cubs",
        home_id=222,
        home_name="St. Louis Cardinals",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="Away Pitcher",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="Home Pitcher",
        retrieved_at="2026-09-08T20:00:00+00:00",
        game_number=2,
    )


def _provider_payload() -> dict:
    # Provider-shaped HTTP payload used to exercise the normalization boundary.
    # This is intentionally not claimed as an authentic retained provider capture.
    return {
        "id": "odds-provider-event-abc123",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-09-08T23:10:00Z",
        "home_team": "St. Louis Cardinals",
        "away_team": "Chicago Cubs",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-09-08T22:55:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2026-09-08T22:55:00Z",
                        "outcomes": [
                            {"name": "Chicago Cubs", "price": 120},
                            {"name": "St. Louis Cardinals", "price": -130},
                        ],
                    }
                ],
            }
        ],
    }


def test_provider_event_identity_is_not_rewritten_to_mlb_game_pk() -> None:
    game = _game()
    snapshot = parse_game_event_odds(_provider_payload(), game=game)
    assert not snapshot.failures
    assert len(snapshot.quotes) == 2
    quote = snapshot.quotes[0]
    assert quote["source_event_id"] == "odds-provider-event-abc123"
    assert quote["source_event_id"] != str(game.game_pk)
    assert quote["canonical_game_id"] == str(game.game_pk)
    assert quote["canonical_game_number"] == 2
    assert quote["canonical_home_team_id"] == "222"
    assert quote["canonical_away_team_id"] == "111"
    assert len(quote["acquisition_quote_sha256"]) == 64


def test_quote_bridge_preserves_attestation_without_inference() -> None:
    game = _game()
    quote = parse_game_event_odds(_provider_payload(), game=game).quotes[0]
    normalized = validate_canonical_quote(quote)
    for field in (
        "source_provider",
        "source_event_id",
        "source_home_team_name",
        "source_away_team_name",
        "source_identity_version",
        "canonical_game_id",
        "canonical_game_number",
        "canonical_home_team_id",
        "canonical_away_team_id",
        "quote_hash_algorithm",
        "quote_hash_schema_version",
        "acquisition_quote_sha256",
    ):
        assert normalized[field] == quote[field]
    validate_acquisition_quote(normalized, game=game)


def test_mutating_price_after_acquisition_fails_hash_closed() -> None:
    game = _game()
    quote = dict(parse_game_event_odds(_provider_payload(), game=game).quotes[0])
    quote["american_odds"] = 125
    with pytest.raises(QuoteAttestationError, match="ACQUISITION_QUOTE_HASH_MISMATCH"):
        validate_acquisition_quote(quote, game=game)


def test_mutating_provider_event_identity_after_acquisition_fails_hash_closed() -> None:
    game = _game()
    quote = dict(parse_game_event_odds(_provider_payload(), game=game).quotes[0])
    quote["source_event_id"] = "different-provider-event"
    with pytest.raises(QuoteAttestationError, match="ACQUISITION_QUOTE_HASH_MISMATCH"):
        validate_acquisition_quote(quote, game=game)


def test_provider_team_binding_is_checked_before_attestation() -> None:
    payload = deepcopy(_provider_payload())
    payload["home_team"] = "Wrong Team"
    snapshot = parse_game_event_odds(payload, game=_game())
    assert not snapshot.quotes
    assert snapshot.failures
    assert all("ACQUISITION_PROVIDER_TEAM_BINDING_MISMATCH" in row["reason"] for row in snapshot.failures)
