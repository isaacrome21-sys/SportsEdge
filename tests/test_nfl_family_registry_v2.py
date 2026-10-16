"""NFL family registry v2 (#2265): the NFL player-prop families get a
versioned registration that names their governed research-only state
(NOT_VALIDATED, eligible=false, non-promotable) without mutating the
frozen governance surface, the Phase 1 coverage matrix, or any family's
BLOCKED disposition on the canonical path.
"""
import hashlib
import json
from pathlib import Path

import pytest

from sportsedge.canonical_coverage import (
    MARKET_RESOLUTIONS, blocked_row_for, coverage_summary, resolve_market,
)
from sportsedge.nfl_family_registry_v2 import (
    GOVERNANCE_SURFACE_SHA256,
    REGISTRY_V2,
    coverage_registration_v2,
    load_registry_v2,
    registered_family,
    settle_nfl_prop_stat,
)

ROOT = Path(__file__).resolve().parents[1]

REGISTERED = [
    "passing_yards", "completions", "attempts", "passing_tds",
    "interceptions", "longest_completion", "pass_plus_rush_yards",
    "rushing_yards", "rush_yards", "rush_attempts", "longest_rush",
    "rush_plus_rec_yards", "receiving_yards", "receptions",
    "longest_reception", "targets", "anytime_td", "first_td",
    "two_plus_td", "fg_made", "kicking_points", "xp_made",
    "player_sacks", "tackles_assists", "player_interceptions",
]


def test_governance_surface_bytes_frozen():
    raw = (ROOT / "config/football_prop_engine_surface.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == GOVERNANCE_SURFACE_SHA256
    surface = json.loads(raw)
    assert surface["sports"]["NFL"]["engine_state"] == "NO_ENGINE"


def test_registry_file_matches_module():
    on_disk = json.loads(
        (ROOT / "config/nfl_family_registry_v2.json").read_text())
    assert on_disk == REGISTRY_V2
    assert on_disk["extends"]["catalog_mutated"] is False


def test_every_family_registered_research_only_non_promotable():
    fams = load_registry_v2()["families"]
    assert sorted(fams) == sorted(REGISTERED)
    for name, fam in fams.items():
        assert fam["status"] == "RESEARCH_ONLY", name
        assert fam["registration_state"] == "REGISTERED_RESEARCH_ONLY", name
        assert fam["promotable"] is False, name
        assert fam["eligible"] is False, name
        assert fam["validation_status"] == "NOT_VALIDATED", name
        assert fam["one_sided_no_vig"] == "UNAVAILABLE", name
        assert fam["settlement_field"], name
        assert fam["settlement_source"], name
        assert fam["evidence_group"] == "NFL_PROP_%s_V2" % name.upper(), name


@pytest.mark.parametrize("market", REGISTERED)
def test_family_resolves_with_registration_and_stays_blocked(market):
    resolution = resolve_market("NFL", market)
    assert resolution is not None
    assert resolution["state"] == "BLOCKED"
    assert resolution["blocker"] in ("NO_ENGINE", "NO_DATA")
    assert resolution["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert resolution["registry_schema"] == "NFL_FAMILY_REGISTRY_V2"
    assert resolution["validation_status"] == "NOT_VALIDATED"
    assert resolution["research_only"] is True
    assert resolution["promotable"] is False
    assert resolution["eligible"] is False
    assert resolution["evidence_group"] == "NFL_PROP_%s_V2" % market.upper()


def test_intake_alias_carries_registration():
    resolution = resolve_market("NFL", "PLAYER_PASS_YARDS")
    assert resolution["market"] == "passing_yards"
    assert resolution["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    resolution = resolve_market("NFL", "DEFENSIVE_PLAYER_INTERCEPTIONS")
    assert resolution["market"] == "player_interceptions"
    assert resolution["registration_state"] == "REGISTERED_RESEARCH_ONLY"


def test_registration_never_prices_and_rows_stay_blocked():
    # No registered family may resolve to a priced path or lose its
    # fail-closed blocked card row.
    for market in REGISTERED:
        assert resolve_market("NFL", market)["state"] != "PRICED_PATH"
        row = blocked_row_for("NFL", market, {"market": market})
        assert row is not None, market
        assert row["status"] == "NO_MODEL_OR_MARKET"
        assert row["research_only"] is True
        assert row["official_authority"] is False
        assert row["staking_authority"] is False


def test_unregistered_and_unknown_markets_unchanged():
    # NFL game markets carry no registration layer.
    for market in ("moneyline", "spread", "total", "team_total"):
        resolution = resolve_market("NFL", market)
        assert "registration_state" not in resolution
    # A market outside the matrix and the registry still resolves to
    # None (fail-closed pass-through is unchanged).
    assert resolve_market("NFL", "punting_yards") is None
    assert coverage_registration_v2("NFL", "punting_yards") is None
    assert coverage_registration_v2("MLB", "passing_yards") is None
    assert registered_family("punting_yards") is None


def test_matrix_census_unmutated():
    assert coverage_summary()["markets_total"] == 89
    raw = MARKET_RESOLUTIONS[("NFL", "passing_yards")]
    assert "registration_state" not in raw
    # Callers cannot poison the authoritative record through a returned
    # dict: the registration merge happens on a copy.
    resolution = resolve_market("NFL", "passing_yards")
    resolution["validation_status"] = "VALIDATED"
    resolution["state"] = "PRICED_PATH"
    again = resolve_market("NFL", "passing_yards")
    assert again["validation_status"] == "NOT_VALIDATED"
    assert again["state"] == "BLOCKED"


def test_loader_refuses_promotable_or_eligible(tmp_path, monkeypatch):
    import sportsedge.nfl_family_registry_v2 as mod
    bad = json.loads(json.dumps(REGISTRY_V2))
    bad["families"]["passing_yards"]["promotable"] = True
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    monkeypatch.setattr(mod, "_PATH", p)
    with pytest.raises(ValueError, match="PROMOTABLE_FORBIDDEN"):
        mod.load_registry_v2()
    bad["families"]["passing_yards"]["promotable"] = False
    bad["families"]["passing_yards"]["eligible"] = True
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="ELIGIBLE_FORBIDDEN"):
        mod.load_registry_v2()


def test_loader_refuses_surface_pin_drift(tmp_path, monkeypatch):
    import sportsedge.nfl_family_registry_v2 as mod
    bad = json.loads(json.dumps(REGISTRY_V2))
    bad["extends"]["catalog_sha256"] = "0" * 64
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    monkeypatch.setattr(mod, "_PATH", p)
    with pytest.raises(ValueError, match="SURFACE_PIN_MISMATCH"):
        mod.load_registry_v2()


@pytest.mark.parametrize("market,stat,line,side,expect", [
    ("passing_yards", {"passing_yards": 287}, 262.5, "OVER", "WIN"),
    ("passing_yards", {"passing_yards": 200}, 262.5, "OVER", "LOSS"),
    ("passing_yards", {"passing_yards": 262}, 262.0, "UNDER", "PUSH"),
    ("anytime_td", {"touchdowns_scored": 1}, 0.5, "OVER", "WIN"),
    ("anytime_td", {"touchdowns_scored": 0}, 0.5, "OVER", "LOSS"),
    ("fg_made", {"field_goals_made": 2}, 1.5, "OVER", "WIN"),
    ("player_sacks", {"sacks": 1}, 0.5, "UNDER", "LOSS"),
])
def test_settlement_from_official_stat(market, stat, line, side, expect):
    assert settle_nfl_prop_stat(market, stat, line, side) == expect


@pytest.mark.parametrize("stat", [{}, {"passing_yards": None},
                                  {"passing_yards": True},
                                  {"passing_yards": 287.5},
                                  {"passing_yards": -1},
                                  {"passYards": 287}])
def test_settlement_refuses_missing_or_bad_stat(stat):
    with pytest.raises(ValueError, match="OFFICIAL_STAT_MISSING"):
        settle_nfl_prop_stat("passing_yards", stat, 262.5, "OVER")


def test_settlement_refuses_bad_side_line_and_family():
    with pytest.raises(ValueError, match="SIDE_INVALID"):
        settle_nfl_prop_stat("passing_yards", {"passing_yards": 10},
                             262.5, "YES")
    with pytest.raises(ValueError, match="LINE_INVALID"):
        settle_nfl_prop_stat("passing_yards", {"passing_yards": 10},
                             float("nan"), "OVER")
    with pytest.raises(ValueError, match="LINE_INVALID"):
        settle_nfl_prop_stat("passing_yards", {"passing_yards": 10},
                             -0.5, "OVER")
    with pytest.raises(ValueError, match="UNREGISTERED_FAMILY"):
        settle_nfl_prop_stat("punting_yards", {"punting_yards": 10},
                             0.5, "OVER")
