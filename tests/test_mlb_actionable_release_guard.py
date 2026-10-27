"""Regression for #2685: estimated MLB EV cannot grant betting authority."""

import json
import sys
from pathlib import Path

import pytest

from scripts import render_mlb_myspari_card as renderer
from scripts.print_mlb_fast_game_markets import actionable_game_rows


def _candidate(*, status="ACTIONABLE", engine_status="MODEL_CANDIDATE"):
    return {
        "game_id": "991", "market": "TEAM_TOTALS", "entity_id": "139",
        "entity_name": "Tampa Bay Rays", "side": "OVER", "line": 3.5,
        "american_odds": -105, "model_p": 0.60,
        "model_p_raw": 0.60, "edge": 0.10, "ev_per_dollar": 0.17,
        "confidence_score": 94, "star_rating": 5,
        "status": status, "scored_status": status,
        "engine_status": engine_status, "engine_reason": "DEPLOYMENT_NOT_ELIGIBLE",
        "presentation_reason_codes": (),
    }


def test_release_guard_demotes_candidate_preserving_model_and_price():
    raw = _candidate()
    result = renderer.withhold_unverified_actionable([raw])[0]
    assert result["scored_status"] == result["status"] == "LEAN"
    assert result["star_rating"] == 0
    assert renderer.NO_RELEASE_AUTHORITY_REASON in result["presentation_reason_codes"]
    for unchanged in ("model_p", "model_p_raw", "edge", "ev_per_dollar", "american_odds", "confidence_score", "engine_status"):
        assert result[unchanged] == raw[unchanged]
    assert raw["scored_status"] == "ACTIONABLE"  # no mutation of audit input


def test_release_guard_cannot_be_bypassed_by_engine_bet_claim_or_prior_refusal():
    mixed = _candidate(status="ACTIONABLE")
    mixed["scored_status"] = "NEEDS_CONFIRM"
    rows = [_candidate(engine_status="OFFICIAL_BET"), _candidate(status="BET"),
            _candidate(status="VERIFIED"), mixed, _candidate(status="PASS"),
            _candidate(status="NO_MODEL")]
    safe = renderer.withhold_unverified_actionable(rows)
    assert [r["scored_status"] for r in safe] == ["LEAN", "LEAN", "LEAN", "NEEDS_CONFIRM", "PASS", "NO_MODEL"]
    assert renderer.withhold_unverified_actionable(safe) == safe  # repeat-safe


@pytest.mark.parametrize("claim", [
    "ACTIONABLE ", " ACTIONABLE", "  BET  ", " PLAY", "VERIFIED\t",
    "\nOFFICIAL_BET ", " actionable ",
])
@pytest.mark.parametrize("field", ["scored_status", "status"])
def test_whitespace_or_case_cannot_bypass_unverified_bet_guard(claim, field):
    candidate = _candidate(status="NO_MODEL")
    candidate[field] = claim
    safe = renderer.withhold_unverified_actionable([candidate])[0]
    assert safe["scored_status"] == safe["status"] == "NO_MODEL"
    assert safe["star_rating"] == 0
    assert renderer.NO_RELEASE_AUTHORITY_REASON in safe["presentation_reason_codes"]
    assert actionable_game_rows({"rows": [safe]}) == []


def test_existing_whitespace_refusal_and_scalar_reason_are_preserved():
    candidate = _candidate(status=" ACTIONABLE ")
    candidate["scored_status"] = " NEEDS_CONFIRM "
    candidate["presentation_reason_codes"] = "QUOTE_MOVE_NEEDS_CONFIRM"
    safe = renderer.withhold_unverified_actionable([candidate])[0]
    assert safe["status"] == safe["scored_status"] == "NEEDS_CONFIRM"
    assert safe["presentation_reason_codes"] == (
        "QUOTE_MOVE_NEEDS_CONFIRM", renderer.NO_RELEASE_AUTHORITY_REASON)
    assert renderer.withhold_unverified_actionable([safe])[0] == safe


@pytest.mark.parametrize("claim", ["ACTIONABLE", " PLAY "])
def test_issue_card_and_json_and_fast_bets_are_all_research_only(tmp_path: Path, monkeypatch, claim):
    engine = tmp_path / "engine.json"
    engine.write_text(json.dumps({"observed_at_utc": "2026-10-26T22:19:00+00:00", "results": []}))
    out = tmp_path / "out"
    monkeypatch.setattr(renderer, "myspari_rows", lambda *args, **kwargs: [_candidate(status=claim)])
    monkeypatch.setattr(renderer, "both_side_board_section", lambda payload: "")
    monkeypatch.setattr(sys, "argv", ["render_mlb_myspari_card.py", "--engine-output", str(engine),
                                    "--out-dir", str(out), "--as-of", "2026-10-26T22:19:30+00:00"])
    assert renderer.main() == 0
    posted = (out / "card.md").read_text()
    artifact = json.loads((out / "card.json").read_text())
    assert "RESEARCH ONLY" in posted
    assert "| LEAN |" in posted
    assert "| ACTIONABLE |" not in posted
    assert "## Core plays" not in posted
    assert [r["scored_status"] for r in artifact["rows"]] == ["LEAN"]
    assert actionable_game_rows(artifact) == []
