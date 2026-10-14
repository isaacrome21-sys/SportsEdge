"""t146: every CFB market path is registered-and-blocked or unregistered-and-blocked; none priced.

Ruling 2026-10-14: unvalidated CFB game lines cannot become PLAY; CFB team totals FORWARD_ONLY.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sportsedge import registry_gate as rg
from sportsedge.family_market_registry import (CFB_EVALUATION_SCOPE, cfb_evaluation_admissible,
                                               family_market_decision)

ROOT = Path(__file__).resolve().parents[1]
SURFACE = json.loads((ROOT / "config/cfb_research_market_surface_v1.json").read_text())
FOOTBALL = json.loads((ROOT / "config/football_market_surface.json").read_text())

GAME_FAMILIES = {"MONEYLINE": "moneyline", "SPREAD": "spread", "TOTAL": "total",
                 "TEAM_TOTAL": "team_total"}
FEED_ALIASES = {  # odds-feed spelling -> canonical family
    "h2h": "moneyline", "H2H": "moneyline", "ml": "moneyline", "money_line": "moneyline",
    "moneyline": "moneyline", "spreads": "spread", "spread": "spread", "point_spread": "spread",
    "point-spread": "spread", "POINT SPREAD": "spread", "pointspread": "spread",
    "totals": "total", "total": "total", "over_under": "total", "ou": "total",
    "game_total": "total", "team_totals": "team_total", "team_total": "team_total",
    "team-total": "team_total", "Team Totals": "team_total",
}
FEED_LITERAL = re.compile(r"""["'](h2h|spreads|totals|team_totals?|point_spread|moneyline)["']""")


def _cfb_paths_from_code() -> set[str]:
    keys: set[str] = set()
    files = [*ROOT.glob("scripts/*cfb*.py"), *ROOT.glob("sportsedge/*cfb*.py"),
             *ROOT.glob("sportsedge/sports/cfb/*.py")]
    for f in files:
        keys |= set(FEED_LITERAL.findall(f.read_text(encoding="utf-8", errors="replace")))
    return keys


def _football_cfb_markets() -> dict[str, str]:
    return {m["market"]: m["engine_state_by_sport"]["CFB"] for m in FOOTBALL["markets"]
            if "CFB" in m.get("engine_state_by_sport", {})}


ALL_KEYS = sorted(set(SURFACE["game_markets"]) | set(SURFACE["player_prop_candidate_markets"])
                  | set(SURFACE["unsupported_or_not_promoted"]) | set(_football_cfb_markets())
                  | set(FEED_ALIASES) | _cfb_paths_from_code())


def test_inventory_is_nonempty_and_includes_feed_literals():
    assert {"h2h", "spreads", "totals"} <= _cfb_paths_from_code()
    assert len(ALL_KEYS) > 60


@pytest.mark.parametrize("key,family", sorted(GAME_FAMILIES.items()))
def test_every_surface_game_market_registered_with_declared_scope(key, family):
    assert key in SURFACE["game_markets"]
    d = family_market_decision("CFB", key)
    assert d["market"] == family and d["reason"] == "FAMILY_REGISTRY_NOT_VALIDATED"
    assert d["evaluation_scope"] == ("FORWARD_ONLY" if family == "team_total" else "HISTORICAL")


def test_scope_table_exactly_the_four_cfb_game_families():
    assert CFB_EVALUATION_SCOPE == {"moneyline": "HISTORICAL", "spread": "HISTORICAL",
                                    "total": "HISTORICAL", "team_total": "FORWARD_ONLY"}


@pytest.mark.parametrize("alias,family", sorted(FEED_ALIASES.items()))
def test_odds_feed_aliases_map_to_canonical_family(alias, family):
    assert family_market_decision("CFB", alias)["market"] == family


def test_every_feed_literal_in_cfb_code_is_registered():
    for lit in _cfb_paths_from_code():
        assert family_market_decision("CFB", lit)["evaluation_scope"] != "UNREGISTERED", lit


@pytest.mark.parametrize("key", [m for m, s in _football_cfb_markets().items() if s == "NO_ENGINE"]
                         + list(SURFACE["unsupported_or_not_promoted"])
                         + list(SURFACE["player_prop_candidate_markets"]))
def test_no_engine_and_prop_markets_stay_unregistered(key):
    d = family_market_decision("CFB", key)
    assert d["evaluation_scope"] == "UNREGISTERED" and d["blocker"] == "NO_ENGINE", key


@pytest.mark.parametrize("key", ["alternate_spread", "alternate_total", "first_half_spread",
                                 "first_half_total", "quarter_total", "team_total_first_half",
                                 "alternate_team_total", "spreads_h1", "totals_q1"])
def test_derived_markets_do_not_inherit_full_game_family(key):
    assert family_market_decision("CFB", key)["evaluation_scope"] == "UNREGISTERED"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_cfb_path_blocked_never_play_never_priced(key):
    d = family_market_decision("CFB", key)
    assert d["state"] == "BLOCKED" and d["validation_status"] == "UNVALIDATED"
    assert not (d["official_authority"] or d["model_p_authority"] or d["staking_authority"])
    row = {"sport": "CFB", "market": key, "home": "Ohio State", "away": "Michigan",
           "model_p": 0.61, "ev": 0.04, "fair_american": -150, "stake": 1.0, "status": "PLAY",
           "edge_pp": 3.1}
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    out = gated["rows"][0]
    assert stats["blocked"] == 1
    assert out["status"] == "NO_MODEL_OR_MARKET" and out["status"] != "PLAY"
    assert not (set(out) & rg.PRICING_KEYS), set(out) & rg.PRICING_KEYS


def test_illinois_exclusion_still_first():
    from artifacts.free_models import IL_COLLEGE_NAMES
    name = sorted(IL_COLLEGE_NAMES)[0]
    out = rg.family_gate_row("CFB", "h2h", {"home": name, "away": "Purdue"})
    assert out["blocker"] == "ILLINOIS_COLLEGE_EXCLUDED"
    assert out["family_decision"]["market"] == "moneyline"


# ---- scope enforcement (fail closed) ----

@pytest.mark.parametrize("market", ["moneyline", "h2h", "spreads", "totals"])
def test_historical_game_lines_admissible_for_evaluation_only(market):
    ok, why = cfb_evaluation_admissible(market, "HISTORICAL")
    assert ok and why.startswith("ADMISSIBLE")
    assert cfb_evaluation_admissible(market, "FORWARD_ONLY")[0] is False
    assert family_market_decision("CFB", market)["state"] == "BLOCKED"   # still no PLAY


@pytest.mark.parametrize("market", ["TEAM_TOTAL", "team_totals", "Team Totals"])
def test_team_total_forward_only(market):
    assert cfb_evaluation_admissible(market, "HISTORICAL") == (False, "SCOPE_MISMATCH:team_total:FORWARD_ONLY")
    assert cfb_evaluation_admissible(market, "FORWARD_ONLY")[0] is True


@pytest.mark.parametrize("market,scope,reason", [
    ("moneyline", None, "EVALUATION_SCOPE_INVALID"), ("moneyline", "historical", "EVALUATION_SCOPE_INVALID"),
    ("moneyline", "BOTH", "EVALUATION_SCOPE_INVALID"), ("moneyline", 1, "EVALUATION_SCOPE_INVALID"),
    ("alternate_spread", "HISTORICAL", "FAMILY_MARKET_UNREGISTERED"),
    ("player_pass_yds", "FORWARD_ONLY", "FAMILY_MARKET_UNREGISTERED"),
    (None, "HISTORICAL", "FAMILY_MARKET_UNREGISTERED"), ("", "HISTORICAL", "FAMILY_MARKET_UNREGISTERED")])
def test_scope_check_fails_closed(market, scope, reason):
    assert cfb_evaluation_admissible(market, scope) == (False, reason)


def test_nba_cbb_unchanged_and_unscoped():
    for sport in ("NBA", "CBB"):
        d = family_market_decision(sport, "TEAM_TOTAL")
        assert d["reason"] == "FAMILY_MARKET_UNREGISTERED" and d["evaluation_scope"] == "UNSPECIFIED"
        assert family_market_decision(sport, "h2h")["market"] == "moneyline"
