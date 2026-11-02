"""t115: runtime registry enforcement in artifacts/run_it_full.py.

Every market the canonical registry marks BLOCKED must fail closed on the
card with its named blocker, under every intake alias and every routing
lane, and no pricer may be invoked for it. Offline: auto_context=False.
"""
from datetime import datetime, timezone

import pytest

from artifacts import run_it_full as R
from sportsedge.canonical_coverage import (
    BLOCKED, INTAKE_ALIASES, MARKET_RESOLUTIONS, resolve_market)

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
PRICE_KEYS = {"model_p", "probability", "fair_odds", "ev_per_dollar",
              "fair_price", "model_probability", "edge"}

# Owner ruling (Nov 1 2026, sportsedge.nfl_prop_research_admission): these
# NFL empirical-pricer markets now reach the NFL research lane and are
# re-judged there; see test_nfl_admitted_props_fail_closed_without_sufficiency.
NFL_ADMITTED_PROPS = ["PLAYER_PASSING_YARDS", "PASS_YARDS", "PLAYER_RUSHING_YARDS",
                      "RUSH_YARDS", "PLAYER_RECEIVING_YARDS", "REC_YARDS",
                      "PLAYER_RECEPTIONS", "RECEPTIONS", "PLAYER_COMPLETIONS",
                      "COMPLETIONS", "PLAYER_PASS_ATTEMPTS", "PLAYER_PASS_TDS",
                      "PASSING_TDS", "PLAYER_INTERCEPTIONS", "INTERCEPTIONS",
                      "PLAYER_RUSH_ATTEMPTS"]
NFL_PROPS = ["ANYTIME_TD", "ANYTIME_TOUCHDOWN",
             "ANYTIME_TD_SCORER", "FIRST_TD", "FIRST_TD_SCORER", "TARGETS",
             "PLAYER_SACKS", "TACKLES_ASSISTS", "FG_MADE", "KICKING_POINTS",
             "XP_MADE", "TWO_PLUS_TD"]
MLB_TARGETS = ["STOLEN_BASES", "BATTER_STOLEN_BASES", "stolen_bases",
               "PITCHER_HITS_WALKS_ER", "F5_MONEYLINE", "F5_ML",
               "F5_RUN_LINE", "F5_SPREAD", "F5_TOTALS", "F5_TOTAL",
               "F5_TEAM_TOTALS", "FIRST_FIVE_TOTAL", "FIRST_FIVE_TEAM_TOTAL",
               "HITS_STOLEN_BASES", "HITS_RUNS_STOLEN_BASES",
               "HITS_WALKS_STOLEN_BASES", " f5_moneyline "]
NFL_GAME_DERIV = ["TEAM_TOTAL", "TEAM_TOTALS", "TEAM_TOTAL_OVER_UNDER",
                  "FIRST_HALF_TOTAL", "1H_TOTAL", "HALF_TOTAL",
                  "FIRST_HALF_SPREAD", "1H_SPREAD", "FIRST_HALF_MONEYLINE",
                  "QUARTER_TOTAL", "ALT_SPREAD", "ALTERNATE_TOTAL",
                  "SECOND_HALF_TOTAL"]


def _row(sport, market):
    return {"sport": sport, "market": market, "away": "AAA", "home": "BBB",
            "side": "OVER", "selection": "OVER", "line": 1.5, "price": -110,
            "odds": -110, "player_name": "Test Player",
            "book": "DK", "captured_at": NOW.isoformat(),
            "model_p": 0.99, "probability": 0.99}  # untrusted, must vanish


@pytest.fixture
def no_pricers(monkeypatch):
    """Every pricer/engine explodes if called with any row."""
    def boom(name):
        def f(rows, *a, **k):
            if rows:
                raise AssertionError(f"pricer {name} reached with {rows}")
            return [], []
        return f
    for n in ["phone_pitcher_rows", "phone_batter_rows",
              "phone_first_inning_rows", "phone_nfl_player_rows",
              "phone_cfb_player_rows", "price_team_half_rows",
              "phone_coverage_rows", "phone_f5_binding_rows"]:
        monkeypatch.setattr(R, n, boom(n))
    def eng(payload, *a, **k):
        if payload.get("lines"):
            raise AssertionError("game engine reached")
        return {"evaluated_rows": []}
    monkeypatch.setattr(R.engine, "run", eng)


def _assert_blocked(row, sport, market):
    assert row["status"] == "NO_MODEL_OR_MARKET", (sport, market, row)
    assert row.get("blocker"), (sport, market, row)
    assert row.get("registry_enforced") is True
    assert row["reason"].startswith(row["blocker"])
    for k in PRICE_KEYS:
        assert row.get(k) in (None, False), (sport, market, k, row)


@pytest.mark.parametrize("market", NFL_PROPS + NFL_GAME_DERIV)
def test_nfl_blocked_markets_never_reach_pricer(no_pricers, market):
    card = R.run_full({"lines": [_row("NFL", market)]}, now=NOW,
                      auto_context=False)
    _assert_blocked(card["evaluated_rows"][0], "NFL", market)
    assert card["prop_candidates"] == [] and card["prop_watchlist"] == []


@pytest.mark.parametrize("market", NFL_ADMITTED_PROPS)
def test_nfl_admitted_props_fail_closed_without_sufficiency(no_pricers, monkeypatch, market):
    """Admitted markets reach ONLY the NFL empirical lane; untrusted intake
    probabilities never survive, and a pricer row without the engine's
    sufficiency stamp is replaced by the original NO_ENGINE blocker."""
    seen = []

    def lane(rows, *a, **k):
        seen.extend(rows)
        return [{"status": "NO_MODEL_OR_MARKET", "reason": "TEST_NO_HISTORY",
                 "sport": "NFL", "market": r["market"]} for r in rows], []
    monkeypatch.setattr(R, "phone_nfl_player_rows", lane)
    card = R.run_full({"lines": [_row("NFL", market)]}, now=NOW,
                      auto_context=False)
    assert len(seen) == 1
    row = card["evaluated_rows"][0]
    _assert_blocked(row, "NFL", market)
    assert row["blocker"] == "NO_ENGINE"
    assert row["nfl_prop_engine_reason"] == "TEST_NO_HISTORY"
    assert card["prop_candidates"] == [] and card["prop_watchlist"] == []


@pytest.mark.parametrize("market", MLB_TARGETS)
def test_mlb_blocked_markets_never_reach_pricer(no_pricers, market):
    card = R.run_full({"lines": [_row("MLB", market)]}, now=NOW,
                      auto_context=False)
    _assert_blocked(card["evaluated_rows"][0], "MLB", market)


@pytest.mark.parametrize("sport,market", [
    ("CFB", "PLAYER_PASSING_YARDS"), ("CFB", "TEAM_TOTAL"),
    ("NBA", "ML"), ("NBA", "TOTAL"), ("CBB", "SPREAD"),
])
def test_unvalidated_family_rows_never_reach_pricers(no_pricers, sport, market):
    card = R.run_full({"lines": [_row(sport, market)]},
                      now=NOW, auto_context=False)
    row = card["evaluated_rows"][0]
    assert row["status"] == "NO_MODEL_OR_MARKET", (sport, market, row)
    assert row["registry_enforced"] is True
    assert row["blocker"] in {"NO_VALIDATION", "NO_ENGINE"}
    for key in PRICE_KEYS:
        assert row.get(key) in (None, False), (sport, market, key, row)
    assert card["edges"] == [] and card["prop_candidates"] == []


def test_default_sport_payload_cannot_dodge(no_pricers):
    card = R.run_full({"sport": "mlb", "lines": [
        {k: v for k, v in _row("", "STOLEN_BASES").items() if k != "sport"}]},
        now=NOW, auto_context=False)
    _assert_blocked(card["evaluated_rows"][0], "MLB", "STOLEN_BASES")


def test_every_blocked_registry_key_and_alias_fails_closed(no_pricers, monkeypatch):
    # NFL empirical-pricer markets reach the admitted research lane (owner
    # ruling Nov 1 2026); with no sufficiency stamp they must still land on
    # their registry blocker.
    monkeypatch.setattr(R, "phone_nfl_player_rows", lambda rows, *a, **k: ([
        {"status": "NO_MODEL_OR_MARKET", "reason": "TEST_NO_HISTORY",
         "sport": "NFL", "market": r["market"]} for r in rows], []))
    names = [(s, m) for (s, m), r in MARKET_RESOLUTIONS.items()
             if r["state"] == BLOCKED]
    names += [(s, a) for s, al in INTAKE_ALIASES.items()
              for a, m in al.items()
              if MARKET_RESOLUTIONS[(s, m)]["state"] == BLOCKED]
    lines = [_row(s, m) for s, m in names]
    card = R.run_full({"lines": lines}, now=NOW, auto_context=False)
    assert len(card["evaluated_rows"]) == len(names)
    for (s, m), row in zip(names, card["evaluated_rows"]):
        _assert_blocked(row, s, m)
        assert row["blocker"] == resolve_market(s, m)["blocker"]


def test_post_assembly_gate_catches_a_leaking_lane(monkeypatch):
    """Defense in depth: if a lane somehow priced a blocked market (here a
    pitcher pricer emitting PITCHER_HITS_WALKS_ER for a priced intake), the
    final gate replaces it before any surface is built."""
    monkeypatch.setattr(R, "_registry_blocked_row",
                        _only_after_first_call(R._registry_blocked_row))
    def leaky(rows, *a, **k):
        return [{"status": "RESEARCH_CANDIDATE_NOT_VALIDATED",
                 "market": "PITCHER_HITS_WALKS_ER", "model_p": 0.7,
                 "ev_per_dollar": 0.3, "sport": "MLB"} for _ in rows], []
    monkeypatch.setattr(R, "phone_pitcher_rows", leaky)
    card = R.run_full({"lines": [_row("MLB", "PITCHER_HITS_WALKS_ER")]},
                      now=NOW, auto_context=False)
    row = card["evaluated_rows"][0]
    _assert_blocked(row, "MLB", "PITCHER_HITS_WALKS_ER")
    assert card["prop_candidates"] == []


def _only_after_first_call(real):
    state = {"n": 0}
    def f(*a, **k):
        state["n"] += 1
        return None if state["n"] == 1 else real(*a, **k)
    return f


def test_priced_markets_still_route(monkeypatch):
    seen = []
    def rec(rows, *a, **k):
        seen.extend(r["market"] for r in rows)
        return [{"status": "NO_MODEL_OR_MARKET", "market": r["market"]}
                for r in rows], []
    monkeypatch.setattr(R, "phone_pitcher_rows", rec)
    monkeypatch.setattr(R, "phone_batter_rows", rec)
    card = R.run_full({"lines": [_row("MLB", "PITCHER_STRIKEOUTS"),
                                 _row("MLB", "BATTER_HITS")]},
                      now=NOW, auto_context=False)
    assert seen == ["PITCHER_STRIKEOUTS", "BATTER_HITS"]
    assert not any(r.get("registry_enforced") for r in card["evaluated_rows"])
