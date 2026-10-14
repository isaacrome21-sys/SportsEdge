"""Extended DraftKings milestone adapters: parser coverage, never activation."""
import pytest

from sportsedge.milestone_ladder_intake import expand_milestone_ladder_rows

CAPTURE = "2026-10-14T20:44:00Z"
MLB = {"sport": "MLB", "away": "Milwaukee Brewers",
       "home": "Los Angeles Dodgers", "book": "draftkings",
       "kickoff": "2026-10-15T00:00:00Z", "quote_captured_at": CAPTURE}
NFL = {"sport": "NFL", "away": "Seattle Seahawks",
       "home": "Denver Broncos", "book": "draftkings",
       "kickoff": "2026-10-16T00:15:00Z", "quote_captured_at": CAPTURE}
CFB = {"sport": "CFB", "away": "Kansas State",
       "home": "Texas Tech", "book": "draftkings",
       "kickoff": "2026-10-17T18:00:00Z", "quote_captured_at": CAPTURE}


def ladder(base, market, threshold=4, odds=-110, form="X_PLUS"):
    return {**base, "market": market, "player_name": "A Player",
            "milestone_ladder": {"form": form,
                "rungs": [{"threshold": threshold, "odds": odds}]}}


@pytest.mark.parametrize("market", [
    "BATTER_HOME_RUNS", "BATTER_HRS", "BATTER_K", "BATTER_STRIKEOUTS",
    "BATTER_TRIPLES", "BATTER_EXTRA_BASE_HITS", "PITCHER_PITCHES",
    "BATTER_HITS", "BATTER_TOTAL_BASES", "PITCHER_OUTS",
])
def test_mlb_offered_count_ladder_admitted_to_downstream_gate_not_priced(market):
    out = expand_milestone_ladder_rows([ladder(MLB, market, 2, 125)])
    assert len(out) == 1
    assert out[0]["market"] == market
    assert out[0]["line"] == 1.5
    assert out[0]["odds"] == 125
    assert out[0]["source_quote_form"] == "MILESTONE_X_PLUS"
    assert "milestone_ladder_refusal" not in out[0]
    assert "dk_no_vig_p" not in out[0]
    assert "fair_price" not in out[0]


@pytest.mark.parametrize("market", [
    "PLAYER_PASSING_YARDS", "PLAYER_PASS_TDS", "PLAYER_PASS_ATTEMPTS",
    "PLAYER_COMPLETIONS", "PLAYER_INTERCEPTIONS",
    "PLAYER_RUSHING_YARDS", "PLAYER_RUSH_ATTEMPTS",
    "PLAYER_RECEIVING_YARDS", "PLAYER_RECEPTIONS",
    "PLAYER_RUSH_PLUS_REC_YARDS", "PLAYER_PASS_PLUS_RUSH_YARDS",
])
def test_nfl_ladder_admitted_research_only(market):
    out = expand_milestone_ladder_rows([ladder(NFL, market, 151, 120)])
    assert len(out) == 1
    assert out[0]["line"] == 150.5
    assert out[0]["source_quote_form"] == "MILESTONE_X_PLUS"
    assert "no_vig_p" not in out[0]
    assert "model_p" not in out[0]


@pytest.mark.parametrize("market", [
    "PLAYER_PASSING_YARDS", "PLAYER_PASS_TDS",
    "PLAYER_RUSHING_YARDS", "PLAYER_RECEPTIONS",
])
def test_cfb_ladder_syntax_admitted_without_registry_activation(market):
    out = expand_milestone_ladder_rows([ladder(CFB, market, 200, 105)])
    assert len(out) == 1
    assert out[0]["line"] == 199.5
    assert "milestone_ladder_refusal" not in out[0]
    assert "model_p" not in out[0]


def test_mirror_ladder_does_not_invent_over_side():
    out = expand_milestone_ladder_rows([
        ladder(NFL, "PLAYER_RECEPTIONS", 3, -125, "OR_FEWER")])
    assert len(out) == 1
    assert out[0]["side"] == "UNDER"
    assert out[0]["line"] == 3.5
    assert out[0]["odds"] == -125
    assert "opposite_odds" not in out[0]


@pytest.mark.parametrize("sport,market", [
    (MLB, "PITCHER_RECORD_WIN"),
    (MLB, "BATTER_FIRST_PA_RESULT"),
    (NFL, "ANYTIME_TD"),
    (NFL, "TD_SCORER_EXACTA"),
    (CFB, "ANYTIME_TD"),
])
def test_non_count_yes_only_exotics_do_not_get_milestone_conversion(sport, market):
    out = expand_milestone_ladder_rows([ladder(sport, market, 1, 115)])
    assert len(out) == 1
    assert out[0]["milestone_ladder_refusal"] == "MILESTONE_LADDER_MARKET_UNSUPPORTED"


def test_no_price_or_staking_authority_from_parser_only_unmodeled_pitcher_pitches():
    out = expand_milestone_ladder_rows([
        ladder(MLB, "PITCHER_PITCHES", 90, -105)])[0]
    assert out["line"] == 89.5
    for key in ("estimate_p", "model_p", "ev_per_dollar",
                "official_authority", "staking_authority"):
        assert key not in out


def test_malformed_families_remain_fail_closed():
    row = ladder(MLB, "BATTER_HOME_RUNS", 2, -120)
    row["milestone_ladder"]["rungs"].append(
        {"threshold": 2, "odds": 1000})
    out = expand_milestone_ladder_rows([row])
    assert len(out) == 1
    assert out[0]["milestone_ladder_refusal"] == "MILESTONE_LADDER_DUPLICATE_RUNG"
