from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sportsedge.football_prop_extended_run_machine import (
    _ou_offers,
    _raw_price_economics,
    _scorer_offers,
)
from sportsedge.run_it_control import _card_state


def test_run_it_treats_model_output_with_official_blocks_as_partial(tmp_path: Path) -> None:
    path = tmp_path / "card.json"
    path.write_text(json.dumps({"report": {"results": [
        {"model_p": 0.58, "bet_status": "BLOCKED"},
    ]}}), encoding="utf-8")
    status, blocker, models, official = _card_state(path, None)
    assert status == "PARTIAL"
    assert blocker == "MODEL_OUTPUT_PRESENT_OFFICIAL_GATES_BLOCKED"
    assert models == 1
    assert official == 0


def test_run_it_keeps_true_no_model_blocked(tmp_path: Path) -> None:
    path = tmp_path / "card.json"
    path.write_text(json.dumps({"report": {"results": [
        {"model_p": None, "bet_status": "BLOCKED"},
    ]}}), encoding="utf-8")
    status, blocker, models, official = _card_state(path, None)
    assert status == "BLOCKED"
    assert blocker == "ALL_MARKETS_BLOCKED"
    assert models == 0
    assert official == 0


def test_one_sided_raw_price_economics() -> None:
    break_even, ev, kelly = _raw_price_economics(
        model_p=0.64, push_p=0.0, american_odds=-150,
    )
    assert break_even == pytest.approx(0.60)
    assert ev == pytest.approx(0.0666666667)
    assert kelly > 0


def test_one_sided_ou_offer_is_preserved_without_inventing_opposite() -> None:
    now = datetime(2026, 9, 10, 15, 1, tzinfo=timezone.utc)
    start = datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc)
    event = {"bookmakers": [{"key": "draftkings", "markets": [{
        "key": "player_rush_yds",
        "last_update": "2026-09-10T15:00:00Z",
        "outcomes": [{
            "name": "Over", "description": "CMC", "point": 67.5, "price": -115,
        }],
    }]}]}
    offers = _ou_offers(
        event=event,
        book_key="draftkings",
        game_start=start,
        current=now,
        quote_ttl_seconds=180,
        name_maps={"OFFENSE": {"cmc": "p1"}, "KICKER": {}, "DEFENSE": {}},
    )
    assert len(offers) == 1
    assert offers[0]["side"] == "OVER"
    assert offers[0]["paired"] is False
    assert offers[0]["opposite_price"] is None


def test_two_plus_td_stays_blocked_from_scorer_surface() -> None:
    now = datetime(2026, 9, 10, 15, 1, tzinfo=timezone.utc)
    start = datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc)
    event = {"bookmakers": [{"key": "draftkings", "markets": [{
        "key": "player_tds_over",
        "last_update": "2026-09-10T15:00:00Z",
        "outcomes": [{
            "name": "Over", "description": "CMC", "point": 1.5, "price": 220,
        }],
    }]}]}
    offers = _scorer_offers(
        event=event,
        book_key="draftkings",
        game_start=start,
        current=now,
        quote_ttl_seconds=180,
        offensive_names={"cmc": "p1"},
    )
    assert offers == []


def test_catalog_truth_matches_implemented_prop_engines() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "config/football_market_surface.json").read_text())
    by_name = {row["market"]: row for row in payload["markets"]}
    for name in (
        "passing_yards", "receiving_yards", "rushing_yards", "receptions",
        "anytime_td", "fg_made", "kicking_points", "player_sacks",
        "tackles_assists", "player_interceptions",
    ):
        assert by_name[name]["engine_state_by_sport"] == {
            "NFL": "IMPLEMENTED", "CFB": "IMPLEMENTED"
        }
    for name in ("targets", "first_td", "two_plus_td"):
        assert by_name[name]["engine_state_by_sport"] == {
            "NFL": "NO_ENGINE", "CFB": "NO_ENGINE"
        }
