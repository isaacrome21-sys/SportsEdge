import json
from pathlib import Path


SURFACE = Path("config/football_market_surface.json")

REQUIRED_MARKETS = {
    "moneyline", "spread", "total", "team_total",
    "first_half_moneyline", "first_half_spread", "first_half_total",
    "second_half_moneyline", "second_half_spread", "second_half_total",
    "quarter_moneyline", "quarter_spread", "quarter_total",
    "alternate_spread", "alternate_total", "race_to_n_points",
    "first_score", "largest_lead", "winning_margin_band",
    "both_teams_to_score_n", "total_touchdowns", "longest_fg_made",
    "defensive_special_teams_td", "safety",
    "passing_yards", "completions", "attempts", "passing_tds",
    "interceptions", "rush_yards", "longest_completion",
    "pass_plus_rush_yards", "rushing_yards", "receiving_yards",
    "receptions", "rush_attempts", "targets", "rush_plus_rec_yards",
    "longest_reception", "longest_rush", "anytime_td", "first_td",
    "two_plus_td", "fg_made", "kicking_points", "xp_made",
    "player_sacks", "tackles_assists", "player_interceptions",
    "team_sacks", "team_turnovers",
}


def _load():
    return json.loads(SURFACE.read_text())


def test_declared_surface_accounts_for_every_required_market_family():
    data = _load()
    markets = [row["market"] for row in data["markets"]]
    assert set(markets) == REQUIRED_MARKETS
    assert len(markets) == len(set(markets))


def test_surface_declares_both_football_sports():
    assert set(_load()["sports"]) == {"NFL", "CFB"}


def test_state_layers_are_independent_and_no_pass_run_state_exists():
    states = _load()["state_layers"]
    assert states["run"] == ["READY", "DEGRADED", "BLOCKED"]
    assert "PASS" not in states["run"]
    assert states["engine"] == ["PRICED", "NO_ENGINE", "INPUT_MISSING", "ENGINE_BLOCKED"]
    assert states["decision"] == ["BET", "PASS"]
    assert states["card_status"] == ["BETS_FOUND", "NO_BETS"]


def test_every_market_declares_valid_engine_dependencies():
    for row in _load()["markets"]:
        assert row["engines"]
        assert set(row["engines"]).issubset({"A", "B", "C"})
        assert "A" in row["engines"]


def test_player_markets_require_engine_b():
    data = _load()
    for row in data["markets"]:
        if row["family"] in {"qb", "skill"}:
            assert "B" in row["engines"]


def test_registry_engine_capability_is_explicit_per_sport():
    data = _load()
    assert data["schema_version"] == 2
    assert data["capability_contract"] == "DECLARATION_DOES_NOT_IMPLY_ENGINE_CAPABILITY_V1"
    implemented = {"moneyline", "spread", "total"}
    for row in data["markets"]:
        states = row["engine_state_by_sport"]
        assert set(states) == {"NFL", "CFB"}
        expected = "IMPLEMENTED" if row["market"] in implemented else "NO_ENGINE"
        assert states["NFL"] == expected
        assert states["CFB"] == expected


def test_declared_no_engine_market_cannot_be_interpreted_as_implemented():
    data = _load()
    row = next(row for row in data["markets"] if row["market"] == "first_half_total")
    assert row["engines"] == ["A"]
    assert row["engine_state_by_sport"]["CFB"] == "NO_ENGINE"
    assert row["engine_state_by_sport"]["NFL"] == "NO_ENGINE"
