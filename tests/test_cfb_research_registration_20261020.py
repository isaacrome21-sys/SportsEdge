"""Owner ruling 2026-10-20 (CFB registry gate decision packet, Option B).

CFB moneyline / spread / total register REGISTERED_RESEARCH_ONLY /
NOT_VALIDATED (eligible False, promotable False), mirroring the NFL
prop registration (#2371). A priced row in one of those families keeps
its pricing keys through the registry gate ONLY when the row carries
satisfied Form 2 identity evidence for both teams of its fixture;
unresolved or stale identity blocks per-fixture exactly as before.
CFB player props and team totals stay BLOCKED; NBA/CBB unchanged; the
Illinois exclusion still fires first. Registration is research
pricing, not validation and not evaluation.
"""
from __future__ import annotations

import pytest

from sportsedge import registry_gate as rg
from sportsedge.family_market_registry import family_market_decision
from sportsedge.prepricing.qb_identity_evidence import STATUS_SATISFIED

SATISFIED = "QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE"


def _verdict(status=SATISFIED, ok=True):
    return {"team_id": "194", "ok": ok, "status": status,
            "detail": "resolved", "resolved_athlete_id": "12345",
            "resolved_athlete_name": "Starting Quarterback",
            "availability_status": "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT",
            "injury_points": 0.0, "event_id": "401234567",
            "opponent_espn_id": "130"}


def _both_sides(**kwargs):
    return {"HOME": _verdict(**kwargs), "AWAY": _verdict(**kwargs)}


def _row(market="SPREAD", **extra):
    row = {"sport": "CFB", "market": market, "home": "Ohio State",
           "away": "Michigan", "side": "HOME", "line": -3.5,
           "model_p": 0.61, "ev_per_dollar": 0.05, "fair_american": -150}
    row.update(extra)
    return row


# ---------------------------------------------------------------- registry

@pytest.mark.parametrize("market,family", [
    ("ML", "moneyline"), ("MONEYLINE", "moneyline"), ("h2h", "moneyline"),
    ("SPREAD", "spread"), ("spreads", "spread"), ("point_spread", "spread"),
    ("TOTAL", "total"), ("totals", "total"), ("over_under", "total"),
])
def test_game_families_registered_research_only(market, family):
    d = family_market_decision("CFB", market)
    assert d["market"] == family
    assert d["state"] == "REGISTERED_RESEARCH_ONLY"
    assert d["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert d["validation_status"] == "NOT_VALIDATED"
    assert d["eligible"] is False and d["promotable"] is False
    assert d["research_only"] is True
    assert not (d["official_authority"] or d["model_p_authority"]
                or d["staking_authority"])
    # Registration is not evaluation: scope and the HOLD are untouched.
    assert d["evaluation_scope"] == "HISTORICAL"
    assert d["pricing_condition"] == "FORM2_IDENTITY_SATISFIED_BOTH_TEAMS"


@pytest.mark.parametrize("market", ["TEAM_TOTAL", "PLAYER_PASSING_YARDS",
                                    "PLAYER_RUSHING_YARDS", "ANYTIME_TD"])
def test_other_cfb_families_stay_blocked(market):
    d = family_market_decision("CFB", market)
    assert d["state"] == "BLOCKED"
    assert d["validation_status"] == "UNVALIDATED"


@pytest.mark.parametrize("sport", ["NBA", "CBB"])
@pytest.mark.parametrize("market", ["ML", "SPREAD", "TOTAL"])
def test_nba_cbb_decisions_unchanged(sport, market):
    d = family_market_decision(sport, market)
    assert d["state"] == "BLOCKED"
    assert d["blocker"] == "NO_VALIDATION"
    assert d["validation_status"] == "UNVALIDATED"


def test_form2_status_constant_matches_evidence_module():
    assert rg.FORM2_IDENTITY_SATISFIED_STATUS == STATUS_SATISFIED == SATISFIED


# ------------------------------------------------------------- gate_payload

def test_satisfied_verdict_map_row_keeps_pricing_keys():
    row = _row(qb_form2_identities=_both_sides())
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    out = gated["rows"][0]
    assert out["model_p"] == 0.61 and out["ev_per_dollar"] == 0.05
    assert out["fair_american"] == -150
    assert out["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert out["validation_status"] == "NOT_VALIDATED"
    assert out["eligible"] is False and out["promotable"] is False
    assert out["research_only"] is True
    assert out["registry_disposition"] == (
        "RESEARCH_PRICING_ALLOWED_FORM2_IDENTITY_SATISFIED")
    assert out["family_decision"]["state"] == "REGISTERED_RESEARCH_ONLY"
    assert stats["research_priced"] == 1 and stats["blocked"] == 0


def test_satisfied_identity_status_field_row_keeps_pricing_keys():
    row = _row("ML", identity_status=SATISFIED)
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    out = gated["rows"][0]
    assert out["model_p"] == 0.61
    assert stats["research_priced"] == 1 and stats["blocked"] == 0


def test_no_identity_evidence_row_still_blocked():
    gated, stats = rg.gate_payload({"rows": [_row()]}, "CFB")
    out = gated["rows"][0]
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == "NO_VALIDATION"
    assert not (set(out) & rg.PRICING_KEYS)
    assert stats["blocked"] == 1


def test_stale_identity_row_still_blocked():
    row = _row(qb_form2_identities=_both_sides(
        status="QB_DEPTH_EVIDENCE_STALE", ok=False))
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    out = gated["rows"][0]
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert not (set(out) & rg.PRICING_KEYS)
    assert stats["blocked"] == 1


def test_unresolved_identity_row_still_blocked():
    row = _row(qb_form2_identities=_both_sides(
        status="QB_DEPTH_QB1_RESOLUTION_AMBIGUOUS", ok=False))
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    assert gated["rows"][0]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["blocked"] == 1


def test_one_sided_verdict_map_row_still_blocked():
    row = _row(qb_form2_identities={"HOME": _verdict()})
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    assert gated["rows"][0]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["blocked"] == 1


def test_availability_label_alone_is_not_identity_evidence():
    row = _row(availability_status="AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT")
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    assert gated["rows"][0]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["blocked"] == 1


def test_team_total_row_blocked_even_with_satisfied_identity():
    row = _row("TEAM_TOTAL", qb_form2_identities=_both_sides())
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    assert gated["rows"][0]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["blocked"] == 1 and stats.get("research_priced", 0) == 0


def test_player_prop_row_blocked_even_with_satisfied_identity():
    row = _row("PLAYER_PASSING_YARDS", identity_status=SATISFIED)
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    assert gated["rows"][0]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["blocked"] == 1


def test_nba_row_blocked_even_with_identity_marker():
    row = _row("TOTAL", identity_status=SATISFIED)
    row["sport"] = "NBA"
    gated, stats = rg.gate_payload({"rows": [row]}, "NBA")
    assert gated["rows"][0]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["blocked"] == 1


def test_illinois_exclusion_still_fires_with_satisfied_identity():
    row = _row("ML", home="Illinois Fighting Illini", away="Iowa",
               qb_form2_identities=_both_sides())
    gated, stats = rg.gate_payload({"rows": [row]}, "CFB")
    out = gated["rows"][0]
    assert out["blocker"] == "ILLINOIS_COLLEGE_EXCLUDED"
    assert not (set(out) & rg.PRICING_KEYS)
    assert stats["illinois_excluded"] == 1


def test_mixed_payload_counts_each_disposition():
    rows = [_row(qb_form2_identities=_both_sides()), _row("TOTAL")]
    gated, stats = rg.gate_payload({"sport": "CFB", "rows": rows}, "CFB")
    assert gated["rows"][0]["model_p"] == 0.61
    assert gated["rows"][1]["status"] == "NO_MODEL_OR_MARKET"
    assert stats["research_priced"] == 1 and stats["blocked"] == 1


# ------------------------------------------------------- rows and stamping

def test_family_gate_row_names_registered_state_without_identity():
    out = rg.family_gate_row("CFB", "ML", {"home": "Ohio State",
                                           "away": "Michigan"})
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == "NO_VALIDATION"
    assert out["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")
    assert "REGISTERED_RESEARCH_ONLY" in out["reason"]
    assert out["family_decision"]["state"] == "REGISTERED_RESEARCH_ONLY"
    assert not (set(out) & rg.PRICING_KEYS)


def test_gate_and_stamp_family_state_reflects_research_pricing():
    plain = rg.gate_and_stamp({"sport": "CFB", "rows": [_row()]}, "CFB", "t")
    assert plain["registry_gate"]["family_state"] == "BLOCKED"
    research = rg.gate_and_stamp(
        {"sport": "CFB", "rows": [_row(identity_status=SATISFIED)]},
        "CFB", "t")
    assert research["registry_gate"]["family_state"] == (
        "BLOCKED_WITH_CFB_RESEARCH_PRICING")
    assert research["registry_gate"]["research_priced"] == 1
