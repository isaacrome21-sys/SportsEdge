"""t197 (#2319/#2354): CFB registry-blocked game rows keep
FAMILY_REGISTRY_NOT_VALIDATED but carry the real unvalidated engine score as
a RESEARCH_ONLY annex (eligible=false). Illinois stays excluded.

RED before the fix: all 18 CFB ML/spread/total sides had no estimate.
"""
import pytest

from artifacts import run_it_full
from sportsedge.phone_display import build_phone_card
from sportsedge.research_estimate import valid_research_estimate


def cfb(market="ML", side="AWAY", away="East Carolina", home="UAB", line=None, odds=-198):
    row = {"sport": "CFB", "away": away, "home": home,
           "kickoff": "2026-10-15T18:30:00-05:00", "book": "draftkings",
           "market": market, "side": side, "odds": odds,
           "quote_source": "OWNER_DK_SCREENSHOT", "book_quote_receipt_verified": False}
    if line is not None:
        row["line"] = line
    return row


@pytest.fixture
def stub_engine(monkeypatch):
    calls = []
    behaviour = {"status": "RESEARCH_POSITIVE_EV_UNVALIDATED", "raise": False, "lane": "INDEPENDENT"}

    def fake_run(payload, **kwargs):
        calls.append((payload["lines"], kwargs))
        if behaviour["raise"]:
            raise RuntimeError("engine down")
        rows = [{"status": behaviour["status"], "estimate_p": 0.66, "push_p": 0.0,
                 "fair_american": -194, "ev_per_dollar": 0.31,
                 "pricing_provenance": {"lane": behaviour["lane"]},
                 "sport": "CFB", "market": l["market"]} for l in payload["lines"]]
        return {"evaluated_rows": rows, "edges": rows, "summary": {"rows": len(rows)}}

    monkeypatch.setattr(run_it_full.engine, "run", fake_run)
    return calls, behaviour


def _run(lines):
    return run_it_full.run_full({"lines": lines}, auto_context=False,
                                getter=lambda url: None)


def test_registry_row_keeps_blocker_and_gains_research_estimate(stub_engine):
    calls, _ = stub_engine
    card = _run([cfb()])
    row = card["evaluated_rows"][0]
    assert row["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")
    assert row["status"] == "NO_MODEL_OR_MARKET"
    est = valid_research_estimate(row)
    assert est is not None and est["probability"] == 0.66
    assert est["eligible"] is False and est["counts_as_validation"] is False
    assert "ev_per_dollar" not in row
    assert card["edges"] == []  # the side card's "edges" never leak
    assert calls and calls[0][1]["lane"] == "A"
    sel = build_phone_card(card)["selections"][0]
    assert sel["status"] == "RESEARCH ONLY" and sel["estimated_ev"] is None
    assert "FAMILY_REGISTRY_NOT_VALIDATED" in sel["reason"]


def test_illinois_fixture_never_scored(stub_engine):
    calls, _ = stub_engine
    for name in ("Illinois", "Northern Illinois"):
        card = _run([cfb(home=name)])
        row = card["evaluated_rows"][0]
        assert "research_estimate" not in row
        assert all(name not in (l["home"], l["away"]) for lines, _ in calls for l in lines)


def test_engine_refusal_failure_or_anchor_leaves_plain_blocker(stub_engine):
    _, behaviour = stub_engine
    for setting in ({"status": "BLOCKED_IL_COLLEGE"}, {"status": "NO_MODEL_OR_MARKET"},
                    {"raise": True}, {"lane": "MARKET_ANCHORED"}):
        behaviour.update({"status": "RESEARCH_POSITIVE_EV_UNVALIDATED", "raise": False,
                          "lane": "INDEPENDENT", **setting})
        row = _run([cfb()])["evaluated_rows"][0]
        assert "research_estimate" not in row, setting
        assert row["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")


def test_cfb_props_are_not_scored(stub_engine):
    calls, _ = stub_engine
    row = _run([dict(cfb(market="PLAYER_PASSING_YARDS", side="OVER", line=250.5),
                     player_name="Somebody")])["evaluated_rows"][0]
    assert "research_estimate" not in row
    assert calls == []


def test_prepricing_refusal_is_named_and_blocks_research_score(stub_engine, monkeypatch):
    calls, _ = stub_engine

    def blocked_stage(games, **kwargs):
        return [{"blocked": True, "block_reason": "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED",
                 "block_detail": "AWAY_QB_IDENTITY_UNVERIFIABLE", "factors": [],
                 "game_label": "East Carolina @ UAB"} for _ in games]
    monkeypatch.setattr(run_it_full, "stage_games", blocked_stage)
    row = _run([cfb()])["evaluated_rows"][0]
    assert row["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")
    assert "prepricing: BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED" in row["reason"]
    assert row["upstream_blocker"] == "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED"
    assert "research_estimate" not in row and calls == []
