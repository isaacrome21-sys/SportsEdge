"""Tests for the M50 game-exotics named gates (wiring queue).

DraftKings offers a game-props exotic slate (CATALOG_MLB.md GAME
PROPS / 1ST OF GAME tabs; five of the names are census keys, group
"exotic"): Race to X Runs, Both Teams to Score X+ Runs ladder,
Grand Slam, Extra Innings, Correct Score, team to bat in the
bottom of the 9th, Inning of First/Last Run, Team with Highest
Scoring Inning, Team to Win Most Innings, Team Total Runs
Odd/Even, First Scoring Play -- Number of Runs. They are not among
the 89 matrix markets and have no engine; intake rows for them
used to fall through the canonical card to the generic
NO_VERIFIED_MODEL_FOR_THIS_MARKET fallback. They now refuse at
truthful named gates carried by sportsedge.mlb_exotics_gates (the
mlb_total_hits pattern -- the 89-market canonical_coverage table
is the matrix contract and is NOT extended), split by the missing
construction:

* SCORE_PATH_UNBUILT -- race / first-last run inning / highest
  scoring inning / most innings won / bottom-of-9th / first
  scoring play: settle on the order and timing of scoring; no
  score-path construction exists on the canonical path.
* PLAY_EVENT_POOL_UNBUILT -- grand slam: a bases-loaded HR play
  event; no PIT play-event pool with bases state exists.
* FULL_GAME_DERIVED_READOUT_UNBUILT -- BTTS ladder / correct
  score / extra innings / team-total odd-even: derivable in
  principle from a full-game joint; no full-game readout or
  binding exists (F5 analogues are deployment-gated readouts).

WINNING_MARGIN is NOT claimed here: the Phase-7 coverage layer
owns the bare name (normalized to the football MARGIN_BAND
construction) and an MLB row already terminates at its named
refusal COVERAGE_MARKET_NOT_OFFERED_FOR_MLB:MARGIN_BAND -- pinned
below so the disposition stays explicit.

Label refinements ONLY: pricing stays refused on every path, no
probability or EV may appear, and no registry/deployment/
validation state changes.
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)

SCORE_PATH_GATE = "SCORE_PATH_UNBUILT"
PLAY_EVENT_GATE = "PLAY_EVENT_POOL_UNBUILT"
READOUT_GATE = "FULL_GAME_DERIVED_READOUT_UNBUILT"

SCORE_PATH_MARKETS = [
    "RACE_TO_RUNS", "INNING_OF_FIRST_RUN", "INNING_OF_LAST_RUN",
    "TEAM_WITH_HIGHEST_SCORING_INNING", "TEAM_TO_WIN_MOST_INNINGS",
    "BAT_IN_BOTTOM_9TH", "FIRST_SCORING_PLAY_RUNS",
]
READOUT_MARKETS = [
    "BOTH_TEAMS_TO_SCORE_RUNS", "CORRECT_SCORE", "EXTRA_INNINGS",
    "TEAM_TOTAL_ODD_EVEN",
]


def _row(market, **kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00",
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z",
            "market": market, "side": "HOME", "line": None,
            "odds": 150}
    base.update(kw)
    return base


def _run(row):
    from artifacts.run_it_full import run_full
    card = run_full({"lines": [row], "sport": "MLB"}, now=NOW,
                    auto_context=False)
    return card["evaluated_rows"][0]


def _assert_named_refusal(result, market, gate):
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(f"NO_ENGINE: {gate}")
    assert result["exotic_gate"] == gate
    assert result["coverage_market"] == market
    assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


@pytest.mark.parametrize("market", SCORE_PATH_MARKETS)
def test_score_path_markets_refuse_at_the_named_gate(market):
    _assert_named_refusal(_run(_row(market)), market, SCORE_PATH_GATE)


@pytest.mark.parametrize("market", READOUT_MARKETS)
def test_readout_markets_refuse_at_the_named_gate(market):
    _assert_named_refusal(_run(_row(market)), market, READOUT_GATE)


def test_grand_slam_refuses_at_the_play_event_gate():
    _assert_named_refusal(_run(_row("GRAND_SLAM")), "GRAND_SLAM",
                          PLAY_EVENT_GATE)


@pytest.mark.parametrize("alias,canonical", [
    ("RACE_TO_5_RUNS", "RACE_TO_RUNS"),
    ("RACE_TO_3_RUNS", "RACE_TO_RUNS"),
    ("FIRST_RUN_INNING", "INNING_OF_FIRST_RUN"),
    ("LAST_RUN_INNING", "INNING_OF_LAST_RUN"),
    ("TEAM_HIGHEST_SCORING_INNING", "TEAM_WITH_HIGHEST_SCORING_INNING"),
    ("MOST_INNINGS_WON", "TEAM_TO_WIN_MOST_INNINGS"),
    ("TEAM_TO_BAT_IN_BOTTOM_9TH", "BAT_IN_BOTTOM_9TH"),
    ("FIRST_SCORING_PLAY", "FIRST_SCORING_PLAY_RUNS"),
    ("BTTS", "BOTH_TEAMS_TO_SCORE_RUNS"),
    ("GAME_CORRECT_SCORE", "CORRECT_SCORE"),
    ("GOES_TO_EXTRA_INNINGS", "EXTRA_INNINGS"),
    ("TEAM_TOTAL_RUNS_ODD_EVEN", "TEAM_TOTAL_ODD_EVEN"),
])
def test_aliases_resolve_to_the_canonical_gate(alias, canonical):
    result = _run(_row(alias))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["coverage_market"] == canonical


def test_winning_margin_stays_with_the_coverage_layer():
    from sportsedge.mlb_exotics_gates import canonical_exotic_market
    assert canonical_exotic_market("WINNING_MARGIN") is None
    result = _run(_row("WINNING_MARGIN"))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["reason"].startswith(
        "COVERAGE_MARKET_NOT_OFFERED_FOR_MLB")


def test_neighbouring_names_are_not_claimed():
    from sportsedge.mlb_exotics_gates import canonical_exotic_market
    for name in ("WINNING_MARGIN", "GAME_TOTAL_3_WAY",
                 "F5_BOTH_TEAMS_TO_SCORE", "F5_WINNING_MARGIN",
                 "F5_CORRECT_SCORE", "INNING_1_RUNS",
                 "TEAM_TOTAL_RUNS", "MONEYLINE", "ML_3WAY",
                 "GAME_TOTAL_RUNS_ODD_EVEN"):
        assert canonical_exotic_market(name) is None, name


def test_exotic_markets_stay_outside_the_matrix_table():
    from sportsedge.canonical_coverage import resolve_market
    from sportsedge.mlb_exotics_gates import (
        EXOTIC_GATES, canonical_exotic_market)
    assert len(EXOTIC_GATES) == 12
    for market, (gate, _detail) in EXOTIC_GATES.items():
        assert resolve_market("MLB", market) is None, market
        assert canonical_exotic_market(market) == market
        assert gate in (SCORE_PATH_GATE, PLAY_EVENT_GATE, READOUT_GATE)


def test_claimed_census_exotic_keys():
    import json
    from pathlib import Path

    from sportsedge.mlb_exotics_gates import canonical_exotic_market
    census = json.loads(Path(
        "config/dk_inspected_menu_census_v1.json").read_text())
    exotic_keys = {m["market_key"]
                   for m in census["sports"]["MLB"]["markets"]
                   if m.get("group") == "exotic"}
    assert exotic_keys == {
        "RACE_TO_RUNS", "BOTH_TEAMS_TO_SCORE_RUNS", "GRAND_SLAM",
        "EXTRA_INNINGS", "WINNING_MARGIN", "CORRECT_SCORE"}
    for key in exotic_keys - {"WINNING_MARGIN"}:
        assert canonical_exotic_market(key) == key, key
    # The sixth census exotic is the coverage layer's, per above.
    assert canonical_exotic_market("WINNING_MARGIN") is None
