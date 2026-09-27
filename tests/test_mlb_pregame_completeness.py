"""A partial public feed must not look like complete scored-card input."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import sys

import pytest

from sportsedge import mlb_run_it_pregame as pregame
from sportsedge.mlb_input_readiness import scored_input_readiness
from sportsedge.mlb_pregame_feature_adapter import attach_pregame_context
from sportsedge.source_lineage import canonical_json_sha256


@pytest.fixture
def acquire(monkeypatch):
    # This suite exercises bundle assembly; individual source lanes have their
    # own injected-network contract tests. No live acquisition is needed here.
    for name in (
        "acquire_injuries_and_scratches", "acquire_umpire_context",
        "acquire_statcast_preview", "acquire_park_venue_context",
        "acquire_weather_roof_context", "acquire_dk_hybrid_quotes",
    ):
        monkeypatch.setattr(pregame, name, lambda **kw: {"model_p_eligible": False})

    def run(live):
        return pregame.acquire_mlb_run_it_pregame(
            game_pk=999005, as_of=datetime(2026, 9, 27, tzinfo=timezone.utc),
            live_payload=live,
        )
    return run


@pytest.fixture
def live():
    return {
        "gameData": {"probablePitchers": {"away": {"id": 501}, "home": {"id": 502}}},
        "liveData": {"boxscore": {"teams": {
            "away": {"battingOrder": list(range(101, 110))},
            "home": {"battingOrder": list(range(201, 210))},
        }}},
    }


def test_complete_inputs_remain_context_only_and_hash_bound(acquire, live):
    bundle = acquire(live)
    assert bundle["status"] == "AVAILABLE"
    assert bundle["input_readiness"]["ready"] is True
    assert bundle["input_readiness"]["missing_reasons"] == []
    assert bundle["model_p_eligible"] is False
    assert bundle["input_readiness"]["model_p_eligible"] is False
    content = deepcopy(bundle)
    digest = content.pop("payload_sha256")
    assert digest == canonical_json_sha256(content)
    del live["gameData"]["probablePitchers"]["home"]
    assert acquire(live)["payload_sha256"] != digest


@pytest.mark.parametrize("side", ["away", "home"])
@pytest.mark.parametrize("bad_id", [None, 0, -1, True, 501.5, "501.5", "", "abc"])
def test_invalid_or_missing_starter_cannot_admit_card(acquire, live, side, bad_id):
    live["gameData"]["probablePitchers"][side]["id"] = bad_id
    bundle = acquire(live)
    assert bundle["starters"]["status"] == "PARTIAL"
    assert bundle["status"] == "PARTIAL"
    assert bundle["acquisition_status"] == "AVAILABLE"
    assert bundle["input_readiness"]["ready"] is False
    assert f"{side.upper()}_STARTER_MISSING_OR_INVALID" in bundle["input_readiness"]["missing_reasons"]
    row = attach_pregame_context({"game_pk": 999005, "market": "TOTALS"}, bundle)
    assert scored_input_readiness(row) == (False, ("PREGAME_INPUTS_INCOMPLETE",))


@pytest.mark.parametrize("side", ["away", "home"])
@pytest.mark.parametrize("order", [
    [], list(range(101, 109)), list(range(101, 111)), [101] * 9,
    [0] + list(range(102, 110)), [True] + list(range(102, 110)),
    [101.5] + list(range(102, 110)), ["bad"] + list(range(102, 110)),
    list(range(101, 110)) + ["bad"],
])
def test_missing_partial_duplicate_or_malformed_lineup_blocks(acquire, live, side, order):
    live["liveData"]["boxscore"]["teams"][side]["battingOrder"] = order
    bundle = acquire(live)
    assert bundle["lineups"]["status"] == "PARTIAL"
    assert bundle["input_readiness"]["ready"] is False
    assert f"{side.upper()}_LINEUP_MISSING_OR_INVALID" in bundle["input_readiness"]["missing_reasons"]


def test_no_posted_inputs_is_missing_not_available(acquire):
    bundle = acquire({})
    assert bundle["starters"]["status"] == "MISSING"
    assert bundle["lineups"]["status"] == "MISSING"
    assert len(bundle["input_readiness"]["missing_reasons"]) == 4


@pytest.mark.parametrize("kind", ["starter", "lineup"])
def test_same_player_on_both_teams_is_not_complete(acquire, live, kind):
    if kind == "starter":
        live["gameData"]["probablePitchers"]["home"]["id"] = 501
    else:
        live["liveData"]["boxscore"]["teams"]["home"]["battingOrder"][0] = 101
    assert acquire(live)["input_readiness"]["ready"] is False


def test_numeric_string_ids_are_supported(acquire, live):
    for side in ("away", "home"):
        live["gameData"]["probablePitchers"][side]["id"] = str(live["gameData"]["probablePitchers"][side]["id"])
        team = live["liveData"]["boxscore"]["teams"][side]
        team["battingOrder"] = [str(value) for value in team["battingOrder"]]
    assert acquire(live)["input_readiness"]["ready"] is True


@pytest.mark.parametrize("readiness", [None, {}, {"ready": "true"}, {"ready": False}])
def test_malformed_explicit_readiness_fails_closed(readiness):
    assert scored_input_readiness({"market": "TOTALS", "pregame_input_readiness": readiness})[0] is False


def test_complete_inputs_do_not_override_missing_feature_validation(acquire, live):
    bundle = acquire(live)
    row = attach_pregame_context(
        {"game_pk": 999005, "market": "TOTALS", "feature_family_readiness": {}}, bundle,
    )
    assert row["pregame_input_readiness"]["ready"] is True
    assert scored_input_readiness(row)[0] is False


@pytest.mark.parametrize("ready,exit_code", [(False, 2), (True, 0)])
def test_cli_gate_preserves_diagnostics(monkeypatch, tmp_path, ready, exit_code):
    from scripts import run_it_mlb_pregame as cli
    bundle = {"input_readiness": {"ready": ready}, "model_p_eligible": False}
    monkeypatch.setattr(cli, "acquire_mlb_run_it_pregame", lambda **kw: bundle)
    output = tmp_path / "pregame.json"
    monkeypatch.setattr(sys, "argv", ["run_it_mlb_pregame", "999005", "--require-complete-inputs", "--out", str(output)])
    assert cli.main() == exit_code
    assert json.loads(output.read_text()) == bundle
