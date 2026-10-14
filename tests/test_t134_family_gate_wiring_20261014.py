"""t134 (#2219): behavioural checks for the CFB/NBA/CBB family gate wiring."""
import json
import pytest

from artifacts import run_it_full
from sportsedge import registry_gate
from sportsedge.canonical_coverage import resolve_market, coverage_summary

PRICE_KEYS = registry_gate.PRICING_KEYS


@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
@pytest.mark.parametrize("market", ["ML", "SPREAD", "TOTAL", "PLAYER_POINTS"])
def test_run_it_registry_gate_blocks_family_rows(sport, market):
    line = {"sport": sport, "market": market, "home": "Team A", "away": "Team B"}
    row = run_it_full._registry_blocked_row(sport, [market], line)
    assert row is not None and row["registry_enforced"] is True
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["blocker"] in {"NO_VALIDATION", "NO_ENGINE"}
    assert not any(row.get(k) is not None for k in PRICE_KEYS)
    assert row["staking_authority"] is False


@pytest.mark.parametrize("team", ["Illinois Fighting Illini", "Northwestern Wildcats", "Northwestern"])
def test_illinois_exclusion_runs_first_and_reason_is_preserved(team):
    for key in ("home", "away_team"):
        line = {"sport": "CFB", "market": "ML", key: team}
        row = run_it_full._registry_blocked_row("CFB", ["ML"], line)
        assert row["blocker"] == "ILLINOIS_COLLEGE_EXCLUDED"
        assert row["reason"].startswith("ILLINOIS_COLLEGE_EXCLUDED")


def test_non_illinois_cfb_row_gets_family_reason():
    row = registry_gate.family_gate_row("CFB", "ML", {"home": "Ohio State", "away": "Michigan"})
    assert "ILLINOIS" not in row["reason"]
    assert row["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")


def test_mlb_nfl_untouched_by_family_gate():
    assert registry_gate.family_gate_row("MLB", "MONEYLINE", {}) is None
    assert registry_gate.family_gate_row("NFL", "ML", {}) is None
    assert resolve_market("MLB", "MONEYLINE")["state"] == "PRICED_PATH"
    assert coverage_summary()["markets_total"] == 89


def test_gate_payload_strips_prices_from_nested_family_rows():
    card = {"sport": "CFB", "results": [
        {"market": "SPREAD", "model_p": 0.61, "ev": 0.04, "home": "Ohio State", "away": "Michigan"},
        {"market": "ML", "model_p": 0.55, "home": "Illinois", "away": "Iowa"},
        {"market": "TOTAL", "model_p": None, "note": "unpriced row kept"}]}
    gated = registry_gate.gate_and_stamp(card, "CFB", "test")
    r = gated["results"]
    assert r[0]["model_p"] is None if "model_p" in r[0] else True
    assert all(r[i].get(k) is None for i in (0, 1) for k in PRICE_KEYS)
    assert r[0]["blocker"] == "NO_VALIDATION"
    assert r[1]["blocker"] == "ILLINOIS_COLLEGE_EXCLUDED"
    assert r[2] == card["results"][2]
    assert gated["registry_gate"]["blocked"] == 1
    assert gated["registry_gate"]["illinois_excluded"] == 1
    json.dumps(gated)


def test_gate_payload_leaves_mlb_card_unchanged():
    card = {"sport": "MLB", "results": [{"market": "MONEYLINE", "model_p": 0.5}]}
    gated, stats = registry_gate.gate_payload(card, "MLB")
    assert gated == card and stats["checked"] == 0


def test_nba_text_card_is_replaced_by_blocked_notice():
    out = registry_gate.gate_text("Celtics -3.5 fair -150 EV +4%", "NBA", "scripts/run_nba_lines_issue.py")
    assert "REGISTRY BLOCKED" in out and "-150" not in out and "EV" not in out.replace("EV are", "")
    assert registry_gate.gate_text("x", "NFL", "r") == "x"
