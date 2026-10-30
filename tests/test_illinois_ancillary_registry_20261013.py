"""Ancillary-script Illinois exclusion vs the frozen registry (issue #2151).

The canonical card path enforces the frozen 13-school ESPN-ID registry
(artifacts/free_models.py IL_COLLEGE_ESPN_IDS, PR #2148). The five
ancillary research scripts inventoried for #2151 each carried their own
hand-maintained name list, and every one of them missed Chicago State
(ESPN id 2130) -- a football school with an 11-game FCS schedule.

These tests prove, per script, through the script's own exclusion logic:

  * every one of the 13 registry schools is excluded, in its attested
    name forms (the canonical IL_COLLEGE_NAMES forms plus the registry
    display labels);
  * Chicago State is excluded in all three canonical name forms
    ("Chicago State", "Chicago State Cougars", "Chicago St") -- the
    bare abbreviation "CHST" is covered canonically only where an ESPN
    ID / directory binding exists; none of these five scripts receives
    team IDs, so it is out of scope for their name matching;
  * non-Illinois fixtures are unaffected, including the Northwestern
    State (Louisiana) name trap, which the canonical standard requires
    NOT to be excluded.

scripts/run_cfb_crossbook_arb.py is included as the re-check control:
the #2151 inventory could not verify it on main; its list already
covers all 13 schools, so it is asserted here without modification.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artifacts.free_models import IL_COLLEGE_ESPN_IDS

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)

# Attested name forms per registry school (canonical IL_COLLEGE_NAMES
# forms + registry display labels + attested mascot forms).
SCHOOL_FORMS = {
    "Illinois": ["Illinois", "Illinois Fighting Illini",
                 "University of Illinois"],
    "Northwestern": ["Northwestern", "Northwestern Wildcats"],
    "DePaul": ["DePaul", "DePaul Blue Demons"],
    "Loyola Chicago": ["Loyola Chicago", "Loyola Chicago Ramblers"],
    "UIC": ["UIC", "UIC Flames", "Illinois Chicago"],
    "Bradley": ["Bradley", "Bradley Braves"],
    "Illinois State": ["Illinois State", "Illinois State Redbirds",
                       "Illinois St"],
    "Southern Illinois": ["Southern Illinois", "Southern Illinois Salukis"],
    "SIU Edwardsville": ["SIU Edwardsville", "SIU Edwardsville Cougars",
                         "Southern Illinois Edwardsville"],
    "Eastern Illinois": ["Eastern Illinois", "Eastern Illinois Panthers"],
    "Western Illinois": ["Western Illinois",
                         "Western Illinois Leathernecks"],
    "Northern Illinois": ["Northern Illinois",
                          "Northern Illinois Huskies"],
    "Chicago State": ["Chicago State", "Chicago State Cougars",
                      "Chicago St"],
}
CHICAGO_STATE_FORMS = SCHOOL_FORMS["Chicago State"]
ALL_FORMS = [(school, form) for school, forms in SCHOOL_FORMS.items()
             for form in forms]
NON_ILLINOIS = ["Iowa", "Iowa Hawkeyes", "Alabama", "Georgia",
                "Delaware", "Middle Tennessee", "Purdue Boilermakers"]
NORTHWESTERN_STATE_FORMS = ["Northwestern State",
                            "Northwestern State Demons"]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_forms_table_covers_exactly_the_frozen_registry():
    assert set(SCHOOL_FORMS) == set(IL_COLLEGE_ESPN_IDS.values())
    assert len(SCHOOL_FORMS) == 13
    assert IL_COLLEGE_ESPN_IDS["2130"] == "Chicago State"


# ------------------------------------------------------- consensus (script 1)

def _consensus_card(matchup):
    return {"schema": "CFB_SDV_CARD_V2",
            "scored_at_utc": "2026-10-10T02:00:00Z",
            "results": [{"game_id": "g1", "matchup": matchup,
                         "market": "SPREAD", "side": "HOME",
                         "line": -3.5, "american_odds": 110,
                         "start_ts": "2026-10-10T16:00:00Z",
                         "model_p": 0.91, "bet_status": "LEAN"}]}


def _consensus_refs():
    return {"books": [
        {"book": b, "captured_at_utc": "2026-10-10T01:59:00Z", "quotes": [
            {"game_id": "g1", "market": "SPREAD", "side": "AWAY",
             "line": 3.5, "american_odds": -110},
            {"game_id": "g1", "market": "SPREAD", "side": "HOME",
             "line": -3.5, "american_odds": -110},
        ]} for b in ("Pinnacle", "Circa")]}


@pytest.mark.parametrize("school,form", ALL_FORMS,
                         ids=[f"{s}:{f}" for s, f in ALL_FORMS])
def test_consensus_excludes_every_registry_school(school, form):
    from scripts.research_cfb_independent_consensus import evaluate
    for matchup in (f"{form} @ Iowa", f"Iowa @ {form}"):
        r = evaluate(_consensus_card(matchup), _consensus_refs())
        assert r["results"][0]["status"] == "ILLINOIS_COLLEGE_EXCLUDED", matchup


def test_consensus_non_illinois_and_trap_unaffected():
    from scripts.research_cfb_independent_consensus import evaluate
    r = evaluate(_consensus_card("Iowa @ Purdue"), _consensus_refs())
    assert r["results"][0]["status"] == "SHADOW_PRICE_DISLOCATION"
    for form in NORTHWESTERN_STATE_FORMS:
        r = evaluate(_consensus_card(f"{form} @ Iowa"), _consensus_refs())
        assert r["results"][0]["status"] != "ILLINOIS_COLLEGE_EXCLUDED"


# ------------------------------------------------------- grade (script 3)

def _grade_game(matchup):
    def q(side, line, p):
        return {"market": "SPREAD", "side": side, "line": line,
                "american_odds": -110, "model_p": p, "market_p": 0.5,
                "expected_roi_unvalidated": round(p * (1 + 100 / 110) - 1, 6),
                "devig": "PAIRED_PROPORTIONAL",
                "quote_evidence": "UNATTESTED_MANUAL_BOARD",
                "original_status": "LEAN"}
    return {"matchup": matchup,
            "quoted_selections": [q("HOME", -3.5, 0.57), q("AWAY", 3.5, 0.43)]}


@pytest.mark.parametrize("school,form", ALL_FORMS,
                         ids=[f"{s}:{f}" for s, f in ALL_FORMS])
def test_grade_excludes_every_registry_school(school, form):
    from scripts.grade_cfb_sdv_forward_value import _select_pre_result
    assert _select_pre_result(_grade_game(f"{form} @ Home")) == []
    assert _select_pre_result(_grade_game(f"Away @ {form}")) == []


def test_grade_non_illinois_and_trap_unaffected():
    from scripts.grade_cfb_sdv_forward_value import _select_pre_result
    assert len(_select_pre_result(_grade_game("Iowa @ Home"))) == 1
    for form in NORTHWESTERN_STATE_FORMS:
        assert len(_select_pre_result(_grade_game(f"{form} @ Home"))) == 1


# ------------------------------------------------------- paper market (script 4)

def _paper_event(home="Alabama", away="Georgia",
                 updated="2026-10-10T02:59:00Z"):
    def book(key, away_odds, home_odds):
        return {"key": key, "last_update": updated, "markets": [
            {"key": "h2h", "last_update": updated,
             "outcomes": [{"name": away, "price": away_odds},
                          {"name": home, "price": home_odds}]}]}
    return {"id": "game", "home_team": home, "away_team": away,
            "commence_time": "2026-10-10T23:30:00Z",
            "bookmakers": [book("draftkings", 150, -170),
                           book("fanduel", -110, -110),
                           book("betmgm", -110, -110)]}


@pytest.mark.parametrize("school,form", ALL_FORMS,
                         ids=[f"{s}:{f}" for s, f in ALL_FORMS])
def test_paper_market_excludes_every_registry_school(school, form):
    from scripts.run_cfb_paper_market import build_payload
    for ev in (_paper_event(home=form), _paper_event(away=form)):
        out = build_payload([ev], .02, NOW, "ODDS_PROVIDER", "READY")
        assert out["coverage"]["illinois_games_excluded"] == 1
        assert out["candidates"] == []


def test_paper_market_non_illinois_and_trap_unaffected():
    from scripts.run_cfb_paper_market import build_payload
    out = build_payload([_paper_event()], .02, NOW, "ODDS_PROVIDER", "READY")
    assert out["coverage"].get("illinois_games_excluded", 0) == 0
    assert len(out["candidates"]) == 1
    for form in NORTHWESTERN_STATE_FORMS:
        out = build_payload([_paper_event(home=form)], .02, NOW,
                            "ODDS_PROVIDER", "READY")
        assert out["coverage"].get("illinois_games_excluded", 0) == 0


# ------------------------------------------------------- four sports (script 5)

auto = _load("dkauto_il", "scripts/collect_auto_dk_four_sports.py")
AUTO_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _auto_event(away, home):
    started = (AUTO_NOW + timedelta(hours=3)).isoformat()
    markets = [
        {"key": "h2h", "outcomes": [{"name": away, "price": 150},
                                    {"name": home, "price": -170}]},
        {"key": "spreads", "outcomes": [{"name": away, "point": 3.5,
                                         "price": -110},
                                        {"name": home, "point": -3.5,
                                         "price": -110}]},
        {"key": "totals", "outcomes": [{"name": "Over", "point": 45.5,
                                         "price": -110},
                                        {"name": "Under", "point": 45.5,
                                         "price": -110}]},
    ]
    return {"id": "e1", "sport_key": auto.SPORTS["CFB"],
            "commence_time": started, "away_team": away, "home_team": home,
            "bookmakers": [{"key": "draftkings",
                            "last_update": AUTO_NOW.isoformat(),
                            "markets": markets}]}


@pytest.mark.parametrize("school,form", ALL_FORMS,
                         ids=[f"{s}:{f}" for s, f in ALL_FORMS])
def test_four_sports_excludes_every_registry_school(school, form):
    assert auto.events_to_board("CFB", [_auto_event(form, "Iowa")],
                                AUTO_NOW) == []
    assert auto.events_to_board("CFB", [_auto_event("Iowa", form)],
                                AUTO_NOW) == []


def test_four_sports_non_illinois_and_trap_unaffected():
    assert len(auto.events_to_board(
        "CFB", [_auto_event("Iowa", "Purdue")], AUTO_NOW)) == 1
    for form in NORTHWESTERN_STATE_FORMS:
        assert len(auto.events_to_board(
            "CFB", [_auto_event(form, "Iowa")], AUTO_NOW)) == 1


# ------------------------------------------------------- full slate (script 2)

slate = pytest.importorskip("bs4") and _load(
    "fullslate_il", "scripts/fetch_cfb_dk_public_full_slate.py")

SLATE_PAGE = """
<html><body><h1>DraftKings Sportsbook Betting Splits</h1>
<h4>Indiana @ Nebraska</h4><div>10/10, 12:00PM</div>
<h5>Spread</h5><div>Indiana -7.5</div><a>-115</a>
<div>Nebraska +7.5</div><a>-105</a>
<h5>Total</h5><div>Over 47.5</div><a>-118</a>
<div>Under 47.5</div><a>-102</a></body></html>
"""


@pytest.mark.parametrize("school,form", ALL_FORMS,
                         ids=[f"{s}:{f}" for s, f in ALL_FORMS])
def test_full_slate_predicate_covers_every_registry_school(school, form):
    assert slate._is_illinois_team(form) is True, form


def test_full_slate_predicate_controls():
    for name in NON_ILLINOIS + NORTHWESTERN_STATE_FORMS:
        assert slate._is_illinois_team(name) is False, name


def test_full_slate_no_pair_keyed_list_remains():
    assert not hasattr(slate, "ILLINOIS_MATCHUPS")


def test_full_slate_compile_parity_and_computed_count():
    result = slate.compile_full_slate(
        {1: SLATE_PAGE}, captured_at_utc="2026-10-10T02:00:00Z",
        min_eligible_paired=1)
    by_pair = {(x["away"], x["home"]): x["status"]
               for x in result["inventory"]}
    for pair in (("Ball State", "Northwestern"),
                 ("Illinois", "Michigan State"),
                 ("Air Force", "Northern Illinois")):
        assert by_pair[pair] == "ILLINOIS_COLLEGE_EXCLUDED", pair
    assert result["illinois_exclusions"] == 3
    assert by_pair[("Indiana", "Nebraska")] != "ILLINOIS_COLLEGE_EXCLUDED"
    assert len(result["board"]) == 1


# ------------------------------------------------------- crossbook (re-check control)

@pytest.mark.parametrize("school,form", ALL_FORMS,
                         ids=[f"{s}:{f}" for s, f in ALL_FORMS])
def test_crossbook_recheck_already_covers_registry(school, form):
    from scripts.run_cfb_crossbook_arb import excluded_illinois
    assert excluded_illinois(form, "Iowa") is True, form
    assert excluded_illinois("Iowa", form) is True, form


def test_crossbook_recheck_trap_unaffected():
    from scripts.run_cfb_crossbook_arb import excluded_illinois
    for form in NORTHWESTERN_STATE_FORMS:
        assert excluded_illinois(form, "Iowa") is False
