"""Canonical-coverage registry surfacing (2026-10-20 truth-in-labeling fix).

resolve_market used to hardcode state BLOCKED for every CFB/NBA/CBB
family, so surfaces consulting the canonical coverage authority
refused outright even for families the family registry of record
(sportsedge.family_market_registry) had registered research-only,
while the phone lane priced the same families as labeled research
through sportsedge.registry_gate. These tests pin the surfaced truth:

* CFB moneyline/spread/total (#2416, Option B) and NBA
  points/rebounds/assists/PRA (#2419) resolve to their recorded
  REGISTERED_RESEARCH_ONLY / NOT_VALIDATED state;
* NBA team totals and period totals resolve to exactly what PR #2422
  recorded -- an engine exists, NO registration change, no market
  test -- still BLOCKED;
* NBA game lines resolve to their recorded FAILED_VALIDATION verdict
  (accuracy gap vs the close), not a bare registry refusal;
* still-blocked families resolve BLOCKED with unchanged reasons;
* no resolution anywhere carries eligible/promotable True or any
  PLAY/staking authority.
"""
import pytest

from sportsedge import registry_gate
from sportsedge.canonical_coverage import (
    BLOCKED, MARKET_RESOLUTIONS, PRICED_PATH, blocked_row_for,
    resolve_market)

AUTHORITY_KEYS = ("official_authority", "model_p_authority",
                  "staking_authority")


def _assert_no_authority(res):
    assert res.get("eligible") is not True
    assert res.get("promotable") is not True
    for key in AUTHORITY_KEYS:
        assert res.get(key) is not True
    assert res.get("research_only", True) is True


# ----------------------------------------------------- (a) registered

@pytest.mark.parametrize("market", ["ML", "MONEYLINE", "SPREAD", "TOTAL",
                                    "moneyline", "spread", "total"])
def test_cfb_game_families_resolve_registered_research_only(market):
    res = resolve_market("CFB", market)
    assert res["state"] == "REGISTERED_RESEARCH_ONLY"
    assert res["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert res["validation_status"] == "NOT_VALIDATED"
    assert res["blocker"] == "NO_VALIDATION"
    assert res["eligible"] is False and res["promotable"] is False
    assert res["pricing_condition"] == "FORM2_IDENTITY_SATISFIED_BOTH_TEAMS"
    assert res["detail"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")
    assert res["family_registry"] is True
    _assert_no_authority(res)


@pytest.mark.parametrize("market,family", [
    ("PLAYER_POINTS", "player_points"), ("PTS", "player_points"),
    ("PLAYER_REBOUNDS", "player_rebounds"), ("REB", "player_rebounds"),
    ("PLAYER_ASSISTS", "player_assists"), ("AST", "player_assists"),
    ("PLAYER_PRA", "player_pra"), ("PRA", "player_pra"),
    ("PTS_REB_AST", "player_pra"),
])
def test_nba_prop_families_resolve_registered_research_only(market, family):
    res = resolve_market("NBA", market)
    assert res["state"] == "REGISTERED_RESEARCH_ONLY"
    assert res["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert res["validation_status"] == "NOT_VALIDATED"
    assert res["market"] == family
    assert res["blocker"] == "NO_VALIDATION"
    assert res["eligible"] is False and res["promotable"] is False
    assert res["pricing_condition"] == "ENGINE_SUFFICIENCY_MET"
    assert "NBA_PROP_EMPIRICAL_V1" in res["engine"]
    _assert_no_authority(res)


@pytest.mark.parametrize("market", ["TEAM_TOTAL", "TEAM_TOTALS",
                                    "team_quarter_total",
                                    "GAME_HALF_TOTAL", "first_half_total"])
def test_nba_team_period_totals_surface_2422_record_exactly(market):
    """PR #2422 built the engine and recorded NO registration change:
    engined, unregistered, no market test -- still BLOCKED."""
    res = resolve_market("NBA", market)
    assert res["state"] == BLOCKED
    assert res["blocker"] == "NO_VALIDATION"
    assert res["validation_status"] == "NOT_VALIDATED"
    assert res["registration_state"] == "UNREGISTERED"
    assert res["eligible"] is False and res["promotable"] is False
    assert "NBA_TEAM_PERIOD_RATINGS_V1" in res["engine"]
    assert "NO registration" in res["detail"]
    assert "NO_MARKET_TEST" in res["detail"]
    _assert_no_authority(res)


def test_nfl_registered_props_keep_their_layered_registration():
    res = resolve_market("NFL", "passing_yards")
    assert res["state"] == BLOCKED  # registration never changes state
    assert res["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert res["validation_status"] == "NOT_VALIDATED"
    assert res["eligible"] is False and res["promotable"] is False


# --------------------------------------- (b) NBA game lines: the verdict

@pytest.mark.parametrize("market,metric", [
    ("ML", "+0.0117"), ("MONEYLINE", "+0.0117"),
    ("SPREAD", "13.83"), ("TOTAL", "21.46"), ("total", "21.46"),
])
def test_nba_game_lines_resolve_failed_validation(market, metric):
    res = resolve_market("NBA", market)
    assert res["state"] == "FAILED_VALIDATION"
    assert res["validation_status"] == "FAILED_VALIDATION"
    assert res["blocker"] == "NO_VALIDATION"
    assert res["detail"].startswith("FAILED_VALIDATION: accuracy gap")
    assert metric in res["detail"]
    assert res["eligible"] is False and res["promotable"] is False
    assert res["registration_state"] == "UNREGISTERED"
    _assert_no_authority(res)


def test_cbb_game_lines_do_not_inherit_the_nba_verdict():
    """The FAILED_VALIDATION verdict is NBA's, on NBA evidence only."""
    res = resolve_market("CBB", "ML")
    assert res["state"] == BLOCKED
    assert res["validation_status"] == "UNVALIDATED"
    assert res["detail"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")


# ------------------------------------- (c) still-blocked stays blocked

@pytest.mark.parametrize("sport,market,blocker,reason", [
    ("CFB", "TEAM_TOTAL", "NO_VALIDATION", "FAMILY_REGISTRY_NOT_VALIDATED"),
    ("CFB", "PLAYER_PASSING_YARDS", "NO_VALIDATION",
     "FAMILY_REGISTRY_NOT_VALIDATED"),
    ("NBA", "PLAYER_THREES", "NO_ENGINE", "FAMILY_MARKET_UNREGISTERED"),
    ("CBB", "SPREAD", "NO_VALIDATION", "FAMILY_REGISTRY_NOT_VALIDATED"),
    ("CBB", "PLAYER_POINTS", "NO_ENGINE", "FAMILY_MARKET_UNREGISTERED"),
])
def test_still_blocked_families_resolve_unchanged(sport, market, blocker,
                                                  reason):
    res = resolve_market(sport, market)
    assert res["state"] == BLOCKED
    assert res["blocker"] == blocker
    assert res["detail"].startswith(reason)
    _assert_no_authority(res)


# ------------------------------- (d) no authority leaks anywhere, ever

FAMILY_PROBES = (
    [("CFB", m) for m in ("ML", "SPREAD", "TOTAL", "TEAM_TOTAL",
                         "PLAYER_PASSING_YARDS", "PLAYER_RUSHING_YARDS")]
    + [("NBA", m) for m in ("ML", "SPREAD", "TOTAL", "PLAYER_POINTS",
                            "PLAYER_REBOUNDS", "PLAYER_ASSISTS",
                            "PLAYER_PRA", "TEAM_TOTALS",
                            "TEAM_QUARTER_TOTAL", "GAME_HALF_TOTAL",
                            "PLAYER_THREES", "PLAYER_STEALS")]
    + [("CBB", m) for m in ("ML", "SPREAD", "TOTAL", "TEAM_TOTAL")]
)


def test_no_resolution_anywhere_grants_eligibility_or_authority():
    resolutions = [resolve_market(s, m) for (s, m) in MARKET_RESOLUTIONS]
    resolutions += [resolve_market(s, m) for s, m in FAMILY_PROBES]
    assert all(r is not None for r in resolutions)
    for res in resolutions:
        _assert_no_authority(res)
        assert res["state"] != "VALIDATED"


def test_family_resolutions_never_claim_a_priced_path():
    for sport, market in FAMILY_PROBES:
        assert resolve_market(sport, market)["state"] != PRICED_PATH


def test_blocked_row_for_still_defers_family_rows_to_registry_gate():
    """Family card rows are built by registry_gate.family_gate_row
    (Illinois exclusion first); the coverage helper must not shadow it,
    whatever state the family surfaces."""
    for sport, market in FAMILY_PROBES:
        assert blocked_row_for(sport, market, {"market": market}) is None


def test_phone_lane_governance_unchanged_by_surfacing():
    """The coverage lookup grants no pricing: the registry gate still
    refuses NBA game lines outright and still requires the per-family
    pricing conditions for the registered families."""
    assert registry_gate.research_pricing_allowed(
        "NBA", "ML", {"nba_prop_engine": {"engine_id": "NBA_PROP_EMPIRICAL_V1",
                                          "sufficiency_met": True,
                                          "n_prior": 20}}) is False
    assert registry_gate.research_pricing_allowed(
        "NBA", "PLAYER_POINTS", {}) is False
    assert registry_gate.research_pricing_allowed(
        "CFB", "ML", {}) is False
    row = registry_gate.family_gate_row("NBA", "ML", {})
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["blocker"] == "NO_VALIDATION"
